from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import pytest
from app.config import Config
from app.database import Database
from app.scanner import scan
from app.buffer_client import BufferError
from app.channels import check_schedules, check_queues, discover
from app.models import PLATFORMS
from app.workflow import Workflow

DATE = '2099-01-01T10:00:00Z'


def fixtures(tmp_path, count=1, dry=False):
    (tmp_path/'pendientes').mkdir(exist_ok=True)
    for i in range(count):
        (tmp_path/'pendientes'/f'{i:03}_clip.mp4').write_bytes(f'video-{i}'.encode())
    config = Config(root=tmp_path, dry_run=dry)
    channels = {p: dict(id=p, service=p, name=p, displayName=p, timezone='Europe/Madrid',
                       isDisconnected=False, isLocked=False, isQueuePaused=False,
                       metadata={'defaultToReminders':False}, postingSchedule=[
                           dict(day=d, paused=False,times=['10:00','22:00'])
                           for d in ['mon','tue','wed','thu','fri','sat','sun']]) for p in PLATFORMS}
    buffer = Mock()
    buffer.account.return_value={'organizations':[{'id':'org','name':'Cuenta'}]}
    buffer.channels.return_value=list(channels.values())
    buffer.posts.return_value=[]
    buffer.posts_by_ids.return_value=[]
    serial=[0]
    def create(payload):
        serial[0]+=1
        return dict(id=f'p{serial[0]}',channelId=payload['channelId'],status='scheduled',
                    dueAt=payload.get('dueAt',DATE),schedulingType='automatic',
                    assets=[{'source':payload['assets'][0]['video']['url']}])
    buffer.create_post.side_effect=create
    storage=Mock()
    storage.base_url='https://media.example.org'
    storage.key.side_effect=lambda path:'clips/'+__import__('app.scanner',fromlist=['file_hash']).file_hash(path)+'.mp4'
    storage.upload.side_effect=lambda path:storage.base_url+'/'+storage.key(path)
    storage.diagnose.return_value='R2 accesible'
    workflow=Workflow(config,buffer,storage,emit=lambda text:None)
    return workflow,buffer,storage,channels


def test_full_run_idempotent(tmp_path):
    w,b,s,channels=fixtures(tmp_path,3)
    w.run()
    assert b.create_post.call_count==9
    assert s.upload.call_count==3
    db=Database(tmp_path/'data'/'bot.db')
    remote=[dict(id=p['post_id'],channelId=p['platform'],status='scheduled',dueAt=DATE,schedulingType='automatic')
            for c in db.clips() for p in db.posts(c['sha256'])]
    db.close()
    b.posts.return_value=remote
    w.run()
    assert b.create_post.call_count==9
    assert s.upload.call_count==3


def test_free_capacity_40_keeps_30_local(tmp_path):
    w,b,s,_=fixtures(tmp_path,40)
    w.run()
    assert b.create_post.call_count==30
    db=Database(tmp_path/'data'/'bot.db')
    assert len(db.clips())==40
    assert sum(all(p['post_id'] for p in db.posts(c['sha256'])) for c in db.clips())==10
    db.close()


def test_partial_retry_only_missing(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    create=b.create_post.side_effect
    def partial(payload):
        if payload['channelId']=='instagram':
            raise BufferError('rate limit',retryable=True)
        return create(payload)
    b.create_post.side_effect=partial
    w.run()
    db=Database(tmp_path/'data'/'bot.db')
    digest=db.clips()[0]['sha256']
    ids={p['platform']:p['post_id'] for p in db.posts(digest)}
    assert ids['youtube'] and ids['tiktok'] and not ids['instagram']
    db.update_post(digest,'instagram',next_retry_at=None)
    b.posts.return_value=[dict(id=id,channelId=p,status='scheduled',dueAt=DATE,schedulingType='automatic')
                         for p,id in ids.items() if id]
    db.close()
    b.create_post.side_effect=create
    b.create_post.reset_mock()
    w.run()
    assert b.create_post.call_count==1
    assert b.create_post.call_args[0][0]['channelId']=='instagram'
    assert b.create_post.call_args[0][0]['mode']=='customScheduled'
    assert s.upload.call_count==1


def test_uncertain_creation_no_blind_retry(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    b.create_post.side_effect=BufferError('timeout',retryable=True,uncertain=True)
    w.run()
    assert b.create_post.call_count==1
    w.run()
    assert b.create_post.call_count==1
    s.delete.assert_not_called()


def test_uncertain_recovers_from_assets(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    b.create_post.side_effect=BufferError('timeout',uncertain=True)
    w.run()
    db=Database(tmp_path/'data'/'bot.db')
    clip=dict(db.clips()[0]);db.close()
    recovered=dict(id='found',channelId='youtube',status='scheduled',dueAt=DATE,
                   schedulingType='automatic',assets=[{'source':clip['public_url']}])
    b.posts.return_value=[recovered]
    b.create_post.side_effect=lambda payload:dict(id=payload['channelId'],channelId=payload['channelId'],
                      status='scheduled',dueAt=DATE,schedulingType='automatic')
    b.create_post.reset_mock()
    w.run()
    assert b.create_post.call_count==2
    assert {c.args[0]['channelId'] for c in b.create_post.call_args_list}=={'instagram','tiktok'}


def test_dry_run_entire_workflow_no_changes(tmp_path):
    w,b,s,_=fixtures(tmp_path,dry=True)
    before={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    w.run()
    assert before=={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    b.create_post.assert_not_called();s.upload.assert_not_called();s.delete.assert_not_called()


def test_dry_run_discovers_new_files_with_existing_database(tmp_path):
    w,b,s,_=fixtures(tmp_path,dry=True)
    db=Database(tmp_path/'data'/'bot.db');db.close()
    assert len(w.preview())==1


def test_validation_error_not_retried(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    b.create_post.side_effect=BufferError('InvalidInputError')
    w.run(); count=b.create_post.call_count
    w.run()
    assert b.create_post.call_count==count


def test_cleanup_only_three_sent(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    sidecar=tmp_path/'pendientes'/'000_clip.txt';sidecar.write_text('texto')
    w.run()
    db=Database(tmp_path/'data'/'bot.db')
    clip=dict(db.clips()[0]);posts=[dict(p) for p in db.posts(clip['sha256'])];db.close()
    remote=[dict(id=p['post_id'],channelId=p['platform'],status='sent',dueAt=DATE,schedulingType='automatic') for p in posts]
    b.posts.return_value=[]
    b.posts_by_ids.return_value=remote[:-1]+[dict(remote[-1],status='error')]
    w.run();s.delete.assert_not_called()
    b.posts_by_ids.return_value=remote
    w.run()
    s.delete.assert_called_once()
    assert (tmp_path/'publicados'/'000_clip.mp4').exists()
    assert (tmp_path/'publicados'/'000_clip.txt').exists()
    assert not (tmp_path/'pendientes'/'000_clip.mp4').exists()


def test_maintenance_refills_two_slots(tmp_path):
    w,b,s,_=fixtures(tmp_path,12)
    w.run()
    db=Database(tmp_path/'data'/'bot.db')
    clips=db.clips()
    remote=[];sent=[]
    for index,c in enumerate(clips[:10]):
        for p in db.posts(c['sha256']):
            post=dict(id=p['post_id'],channelId=p['platform'],status='sent' if index<2 else 'scheduled',
                      dueAt=DATE,schedulingType='automatic')
            (sent if index<2 else remote).append(post)
    db.close()
    b.posts.return_value=remote;b.posts_by_ids.return_value=sent
    b.create_post.reset_mock()
    w.run()
    assert b.create_post.call_count==6
    assert s.delete.call_count==2


def test_queue_mismatch_blocks_before_upload(tmp_path):
    w,b,s,channels=fixtures(tmp_path)
    b.posts.return_value=[dict(id='manual',channelId='youtube',status='scheduled',dueAt=DATE)]
    with pytest.raises(BufferError):w.run()
    s.upload.assert_not_called();b.create_post.assert_not_called()


def test_notification_tiktok_clear_error(tmp_path):
    w,b,s,channels=fixtures(tmp_path)
    channels['tiktok']['metadata']['defaultToReminders']=True
    with pytest.raises(BufferError, match='notification'):
        w.run()
    b.create_post.assert_not_called()


def test_ambiguous_channels_require_env(tmp_path):
    w,b,s,channels=fixtures(tmp_path)
    b.channels.return_value=list(channels.values())+[dict(channels['tiktok'],id='tiktok2')]
    with pytest.raises(BufferError,match='BUFFER_TIKTOK_CHANNEL_ID'):
        w.run()


def test_queue_schedules_must_match(tmp_path):
    w,b,s,channels=fixtures(tmp_path)
    channels['instagram']['timezone']='Europe/London'
    with pytest.raises(BufferError):check_schedules(channels)


def test_creation_alignment_uses_existing_date(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    create=b.create_post.side_effect
    def shifted(payload):
        post=create(payload)
        if payload['channelId']=='instagram':post['dueAt']='2099-01-01T22:00:00Z'
        return post
    b.create_post.side_effect=shifted
    b.reschedule.return_value=dict(id='p2',channelId='instagram',status='scheduled',dueAt=DATE,schedulingType='automatic')
    w.run()
    assert b.reschedule.call_args.args[0]=='p2'
    assert b.reschedule.call_count==1


def test_recoverable_publish_failure_retries_same_post_id(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    w.run()
    db=Database(tmp_path/'data'/'bot.db');clip=db.clips()[0]
    saved=[dict(p) for p in db.posts(clip['sha256'])];db.close()
    active=[dict(id=p['post_id'],channelId=p['platform'],status='scheduled',dueAt=DATE,schedulingType='automatic')
            for p in saved if p['platform']!='instagram']
    failed=next(p for p in saved if p['platform']=='instagram')
    b.posts.return_value=active
    b.posts_by_ids.return_value=[dict(id=failed['post_id'],channelId='instagram',status='error',dueAt=DATE,
                                 schedulingType='automatic',error={'message':'Service temporarily unavailable'})]
    b.retry_post.return_value=dict(id=failed['post_id'],channelId='instagram',status='scheduled',dueAt=DATE,schedulingType='automatic')
    b.create_post.reset_mock()
    w.run()
    b.retry_post.assert_called_once_with(failed['post_id'])
    b.create_post.assert_not_called()


def test_publication_requires_unchanged_preview(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    plan=w.preview(only_one=True)[0]
    (tmp_path/'pendientes'/'000_clip.txt').write_text('changed')
    w.run(only_hash=plan['sha256'],limit=1,expected_plan=plan)
    s.upload.assert_not_called();b.create_post.assert_not_called()


def test_invalid_sidecar_blocks_automatic_retries(tmp_path):
    w,b,s,_=fixtures(tmp_path)
    (tmp_path/'pendientes'/'000_clip.json').write_text('{invalid')
    w.run()
    db=Database(tmp_path/'data'/'bot.db');clip=db.clips()[0]
    assert all(p['state']=='error' and not p['retryable'] for p in db.posts(clip['sha256']))
    db.close()
    w.run()
    s.upload.assert_not_called();b.create_post.assert_not_called()


def test_transient_storage_failure_can_resume_after_backoff(tmp_path):
    from app.storage import StorageError
    w,b,s,_=fixtures(tmp_path)
    upload=s.upload.side_effect
    s.upload.side_effect=StorageError('temporary',retryable=True)
    w.run()
    db=Database(tmp_path/'data'/'bot.db');clip=db.clips()[0]
    assert all(p['retryable'] for p in db.posts(clip['sha256']))
    db.update_clip(clip['sha256'],next_retry_at=None);db.close()
    s.upload.side_effect=upload
    w.run()
    assert b.create_post.call_count==3


def test_single_publication_does_not_cleanup_other_clips(tmp_path):
    w,b,s,_=fixtures(tmp_path,2)
    w.run(limit=1)
    db=Database(tmp_path/'data'/'bot.db');clips=db.clips()
    first=clips[0];second=clips[1]
    remote=[dict(id=p['post_id'],channelId=p['platform'],status='sent',dueAt=DATE,schedulingType='automatic')
            for p in db.posts(first['sha256'])]
    db.close()
    b.posts.return_value=[];b.posts_by_ids.return_value=remote
    plan=w.preview(only_one=True)[0]
    assert plan['sha256']==second['sha256']
    w.run(only_hash=second['sha256'],limit=1,expected_plan=plan)
    s.delete.assert_not_called()


def test_remote_file_conserved_when_local_changed(tmp_path):
    from app.cleanup import cleanup_clip
    w,b,s,_=fixtures(tmp_path)
    w.run()
    db=Database(tmp_path/'data'/'bot.db');clip=dict(db.clips()[0])
    for p in PLATFORMS:db.update_post(clip['sha256'],p,state='sent')
    Path(clip['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):cleanup_clip(db,clip,s,tmp_path)
    s.delete.assert_not_called();db.close()
