from .scanner import scan
from .captions import read_captions
from .database import Database


def inspect_local(root, dry_run=True):
    clips = scan(root / 'pendientes')
    # Validate all sidecars before any write.
    for clip in clips:
        from pathlib import Path
        read_captions(Path(clip.path))
    if not dry_run:
        db = Database(root / 'data' / 'bot.db')
        try:
            db.register(clips)
        finally:
            db.close()
    return clips
