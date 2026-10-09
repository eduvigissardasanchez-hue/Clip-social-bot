from unittest.mock import Mock
from dataclasses import replace
import pytest
from botocore.exceptions import ClientError
from app.config import Config
from app.storage import R2Storage, StorageError
from app.buffer_client import BufferClient, BufferError


def storage():
    config = Config(r2_account_id='account', r2_access_key_id='key', r2_secret_access_key='secret',
                    r2_bucket='bucket', r2_public_base_url='https://media.example.org')
    client = Mock()
    client.list_objects_v2.return_value={'Contents':[], 'IsTruncated':False}
    client.list_multipart_uploads.return_value={'Uploads':[], 'IsTruncated':False}
    http = Mock()
    response = Mock(status_code=200, headers={'Content-Type':'video/mp4'}, content=b'Clips Social Bot storage probe')
    response.iter_content.return_value = iter([b'video'])
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    http.get.return_value = response
    return R2Storage(config, client, http), client, response


def test_r2_upload_once(tmp_path):
    s, client, response = storage()
    video = tmp_path / 'clip.mp4'
    video.write_bytes(b'video')
    client.head_object.side_effect = ClientError({'Error': {'Code':'404'}}, 'HeadObject')
    url = s.upload(video)
    assert url.endswith('.mp4')
    client.put_object.assert_called_once()
    client.head_object.side_effect = None
    response.iter_content.return_value = iter([b'video'])
    assert s.upload(video) == url
    client.put_object.assert_called_once()


def test_public_url_requires_success():
    s, client, response = storage()
    response.status_code = 403
    with pytest.raises(StorageError):
        s.verify_public_url('https://media.example.org/clips/a.mp4')


def test_storage_dry_run_no_writes():
    s, client, response = storage()
    s.diagnose(True)
    client.put_object.assert_not_called()
    client.delete_object.assert_not_called()


def test_storage_probe_deletes_on_failure():
    s, client, response = storage()
    response.status_code = 403
    with pytest.raises(StorageError):
        s.diagnose(False)
    client.put_object.assert_called_once()
    client.delete_object.assert_called_once()


def test_storage_probe_complete():
    s, client, response = storage()
    client.head_object.side_effect = ClientError({'Error': {'Code':'404'}}, 'HeadObject')
    assert 'borrado' in s.diagnose(False)
    client.delete_object.assert_called_once()


@pytest.mark.parametrize('body', [
    {'errors':[{'message':'secret'}]},
    {'data': {'createPost': {'__typename':'MutationError', 'message':'secret'}}},
    {'data': None},
])
def test_graphql_errors_even_http_200(body):
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = body
    with pytest.raises(BufferError) as exc:
        BufferClient('sensitive', session).execute('query { __typename }')
    assert 'sensitive' not in str(exc.value)
    assert 'secret' not in str(exc.value)
