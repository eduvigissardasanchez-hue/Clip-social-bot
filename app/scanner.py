import hashlib
from pathlib import Path
from .models import Clip


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan(folder: Path) -> list[Clip]:
    if not folder.exists():
        return []
    paths = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"),
                   key=lambda p: (p.name.casefold(), p.name))
    seen = set()
    result = []
    for path in paths:
        digest = file_hash(path)
        if digest not in seen:
            result.append(Clip(digest, path.name, str(path), len(result) + 1))
            seen.add(digest)
    return result
