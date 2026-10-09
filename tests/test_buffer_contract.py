from pathlib import Path
from unittest.mock import Mock
import pytest
import requests
from graphql import build_schema, parse, validate, coerce_input_value
from app.buffer_client import BufferClient, BufferError, ACCOUNT, CHANNELS, POSTS, CREATE, EDIT
from app.post_inputs import post_input
from app.captions import Captions

SCHEMA=build_schema((Path(__file__).parents[1]/'docs'/'buffer-reference-derived.graphql').read_text())


@pytest.mark.parametrize('document',[ACCOUNT,CHANNELS,POSTS,CREATE,EDIT])
def test_operations_valid_against_official_reference(document):
    assert validate(SCHEMA,parse(document))==[]


@pytest.mark.parametrize('platform',['youtube','instagram','tiktok'])
def test_metadata_input_valid_against_official_schema(platform):
    captions=Captions('Texto','Título','Descripción','Instagram','TikTok',False)
    payload=post_input(platform,'channel',captions,'https://media.example.org/clip.mp4')
    errors=[]
    coerce_input_value(payload,SCHEMA.get_type('CreatePostInput'),on_error=lambda *args:errors.append(args))
    assert errors==[]
    assert payload['schedulingType']=='automatic'
    assert payload['mode']=='addToQueue'
    assert 'privacy' not in payload['metadata'].get('tiktok',{})
    video=payload['assets'][0]['video']
    assert ('metadata' in video)==(platform!='youtube')


def response(body,status=200):
    r=Mock(status_code=status,headers={})
    r.json.return_value=body
    return r


def test_http_401_not_retried_or_logged():
    session=Mock();session.post.return_value=response({},401)
    with pytest.raises(BufferError,match='401'):
        BufferClient('hidden',session,sleep=Mock()).account()
    assert session.post.call_count==1


def test_read_backoff_bounded():
    session=Mock()
    session.post.side_effect=[requests.Timeout(),requests.Timeout(),response({'data':{'account':{'id':'ok'}}})]
    sleep=Mock()
    assert BufferClient('key',session,sleep).account()['id']=='ok'
    assert [call.args[0] for call in sleep.call_args_list]==[1,2]


def test_mutation_timeout_not_retried():
    session=Mock();session.post.side_effect=requests.Timeout()
    with pytest.raises(BufferError) as error:
        BufferClient('key',session,sleep=Mock()).create_post({})
    assert error.value.uncertain
    assert session.post.call_count==1


def test_mutation_union_invalid_input_permanent():
    session=Mock();session.post.return_value=response({'data':{'createPost':{'__typename':'InvalidInputError','message':'hidden'}}})
    with pytest.raises(BufferError) as error:
        BufferClient('key',session).create_post({})
    assert not error.value.retryable
    assert not error.value.uncertain
    assert 'hidden' not in str(error.value)


def test_pagination_reads_all_and_stops():
    session=Mock()
    session.post.side_effect=[response({'data':{'posts':{'edges':[{'node':{'id':'1'}}],
         'pageInfo':{'hasNextPage':True,'endCursor':'cursor'}}}}),
         response({'data':{'posts':{'edges':[{'node':{'id':'2'}}],
         'pageInfo':{'hasNextPage':False,'endCursor':'last'}}}})]
    assert [p['id'] for p in BufferClient('key',session).posts('org',['channel'])]==['1','2']
    assert session.post.call_args.kwargs['json']['variables']['after']=='cursor'


def test_incomplete_pagination_never_gives_partial_capacity():
    session=Mock();session.post.return_value=response({'data':{'posts':{'edges':[],
         'pageInfo':{'hasNextPage':True,'endCursor':None}}}})
    with pytest.raises(BufferError,match='Paginación'):
        BufferClient('key',session).posts('org',['channel'])


def test_post_batch_uses_30_aliases_valid_schema():
    session=Mock()
    session.post.side_effect=[response({'data':{f'p{i}':{'id':str(i)} for i in range(30)}}),
                             response({'data':{'p0':{'id':'30'}}})]
    assert len(BufferClient('key',session).posts_by_ids([str(i) for i in range(31)]))==31
    for call in session.post.call_args_list:
        assert validate(SCHEMA,parse(call.kwargs['json']['query']))==[]


def test_title_and_caption_limits():
    with pytest.raises(ValueError):
        post_input('youtube','channel',Captions('','x'*101,'','',''),'https://media.example.org/a.mp4')
    with pytest.raises(ValueError):
        post_input('tiktok','channel',Captions('','title','','','😀'*1101),'https://media.example.org/a.mp4')
