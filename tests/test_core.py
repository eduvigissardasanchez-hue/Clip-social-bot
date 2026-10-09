from pathlib import Path
import pytest
from app.scanner import scan
from app.captions import read_captions
from app.database import Database
from app.scheduler import available_capacity, missing_platforms, can_cleanup
from app.models import final_state, State, PLATFORMS


def test_order_hash_duplicates(tmp_path):
    for name, content in [('003.mp4', b'c'), ('001.mp4', b'a'), ('002.mp4', b'b'), ('004.mp4', b'a')]:
        (tmp_path / name).write_bytes(content)
    clips = scan(tmp_path)
    assert [c.filename for c in clips] == ['001.mp4', '002.mp4', '003.mp4']
    assert len({c.sha256 for c in clips}) == 3
    assert len(clips[0].sha256) == 64


def test_caption_fallback_txt_json(tmp_path):
    video = tmp_path / '001_mi_clip.mp4'
    assert read_captions(video).youtube_title == 'mi clip'
    video.with_suffix('.txt').write_text('Texto', encoding='utf-8')
    assert read_captions(video).instagram_caption == 'Texto'
    video.with_suffix('.json').write_text('{"caption":"General","youtube_title":"Título","ai_generated":false}')
    caption = read_captions(video)
    assert caption.caption == 'General'
    assert caption.youtube_title == 'Título'
    assert caption.tiktok_caption == 'General'
    video.with_suffix('.json').write_text('{"ai_generated":"false"}')
    with pytest.raises(ValueError):
        read_captions(video)


def test_capacity():
    assert available_capacity(dict(youtube=3, instagram=8, tiktok=5)) == 2
    assert available_capacity(dict(youtube=11, instagram=0, tiktok=0)) == 0
    with pytest.raises(ValueError):
        available_capacity({'youtube': 1})


def test_idempotence_partial(tmp_path):
    (tmp_path / 'clip.mp4').write_bytes(b'video')
    clips = scan(tmp_path)
    db = Database(tmp_path / 'data' / 'bot.db')
    db.register(clips)
    db.register(clips)
    assert len(db.clips()) == 1
    digest = clips[0].sha256
    db.record_post(digest, 'youtube', 'yt')
    db.record_post(digest, 'tiktok', 'tt')
    posts = [dict(p) for p in db.posts(digest)]
    assert missing_platforms(posts) == ['instagram']
    with pytest.raises(ValueError):
        db.record_post(digest, 'youtube', 'duplicate')
    db.close()


@pytest.mark.parametrize('states,expected', [
    (['sent']*3, State.SENT), (['sent','error','scheduled'], State.ERROR),
    (['sent','scheduled','scheduled'], State.SCHEDULED), (['local']*3, State.LOCAL)])
def test_final_state(states, expected):
    assert final_state(states) == expected


def test_cleanup_gate():
    posts = [dict(platform=p, post_id=p, state='sent') for p in PLATFORMS]
    assert can_cleanup(posts)
    posts[1]['state'] = 'error'
    assert not can_cleanup(posts)
    assert not can_cleanup(posts[:2])


def test_dry_run_no_changes(tmp_path):
    from app.local_workflow import inspect_local
    (tmp_path / 'pendientes').mkdir()
    (tmp_path / 'pendientes' / '001.mp4').write_bytes(b'video')
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert len(inspect_local(tmp_path, dry_run=True)) == 1
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert before == after


def test_shared_description_keeps_each_filename_title(tmp_path):
    import json
    text='🔥 Sígueme\n\n💜 Twitch: @honnoe'
    (tmp_path/'_default.json').write_text(json.dumps({'caption':text,'ai_generated':False},ensure_ascii=False),encoding='utf-8')
    first=read_captions(tmp_path/'001_mi_clip.mp4')
    second=read_captions(tmp_path/'002_otro_clip.mp4')
    assert first.youtube_title=='mi clip'
    assert second.youtube_title=='otro clip'
    for captions in (first,second):
        assert captions.youtube_description==captions.instagram_caption==captions.tiktok_caption==text


def test_specific_sidecars_override_shared_description(tmp_path):
    import json
    video=tmp_path/'clip.mp4'
    (tmp_path/'_default.json').write_text(json.dumps({'caption':'Común'}))
    video.with_suffix('.txt').write_text('Específico TXT')
    assert read_captions(video).caption=='Específico TXT'
    video.with_suffix('.json').write_text(json.dumps({'caption':'Específico JSON','youtube_title':'Título propio'}))
    captions=read_captions(video)
    assert captions.caption=='Específico JSON'
    assert captions.youtube_title=='Título propio'


def test_invalid_shared_json_stops_caption_processing(tmp_path):
    (tmp_path/'_default.json').write_text('{"caption":123}')
    with pytest.raises(ValueError,match='caption'):
        read_captions(tmp_path/'clip.mp4')


def test_filename_title_exact_and_visible_on_all_platforms(tmp_path):
    import json
    (tmp_path/'_default.json').write_text(json.dumps({'caption':'🔥 Redes\n💜 Twitch',
                         'title_from_filename':True,'youtube_title':'Título que se ignora'},ensure_ascii=False),encoding='utf-8')
    captions=read_captions(tmp_path/'001_Mi_Clip.mp4')
    assert captions.youtube_title=='001_Mi_Clip'
    assert captions.youtube_description=='🔥 Redes\n💜 Twitch'
    assert captions.instagram_caption==captions.tiktok_caption=='001_Mi_Clip\n\n🔥 Redes\n💜 Twitch'


def test_filename_title_flag_must_be_boolean(tmp_path):
    (tmp_path/'_default.json').write_text('{"caption":"Texto","title_from_filename":"true"}')
    with pytest.raises(ValueError,match='title_from_filename'):
        read_captions(tmp_path/'clip.mp4')
