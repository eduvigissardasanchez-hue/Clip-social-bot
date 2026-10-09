from pathlib import Path
import shutil
from .scanner import file_hash
from .scheduler import can_cleanup


def cleanup_clip(db, clip, storage, root):
    if not can_cleanup(db.posts(clip['sha256'])):
        return False
    source = Path(clip['path'])
    destination = root / 'publicados' / clip['filename']
    moves = [(source, destination)] + [(source.with_suffix(suffix), destination.with_suffix(suffix))
                                      for suffix in ('.txt','.json')]
    # Never delete remotely or overwrite locally if the clip has changed under us.
    if source.exists() and file_hash(source) != clip['sha256']:
        raise ValueError('El MP4 local cambió; se conserva el medio remoto para revisión.')
    if not source.exists() and (not destination.exists() or file_hash(destination) != clip['sha256']):
        raise ValueError('No se encuentra el MP4 original ni archivado; se requiere revisión.')
    for src, dst in moves:
        if src.exists() and dst.exists():
            raise ValueError('Colisión en publicados; no se sobrescribirán archivos. Revisa las carpetas.')
    if not clip['remote_deleted'] and clip['remote_key']:
        storage.delete(clip['remote_key'])
        db.update_clip(clip['sha256'], remote_deleted=1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    for src, dst in moves:
        if src.exists():
            shutil.move(str(src), str(dst))
    db.update_clip(clip['sha256'], archived=1, path=str(destination))
    return True
