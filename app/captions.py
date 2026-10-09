import json
import re
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Captions:
    caption: str
    youtube_title: str
    youtube_description: str
    instagram_caption: str
    tiktok_caption: str
    ai_generated: bool = False


def read_captions(video: Path) -> Captions:
    title = re.sub(r"^\d+[ _.-]*", "", video.stem).replace("_", " ").strip() or "Clip"
    data = {}
    if video.with_suffix(".json").exists():
        data = json.loads(video.with_suffix(".json").read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("El sidecar JSON debe ser un objeto")
        for key in ("caption", "youtube_title", "youtube_description", "instagram_caption", "tiktok_caption"):
            if key in data and not isinstance(data[key], str):
                raise ValueError(f"{key} debe ser texto")
        if "ai_generated" in data and not isinstance(data["ai_generated"], bool):
            raise ValueError("ai_generated debe ser booleano")
    elif video.with_suffix(".txt").exists():
        data["caption"] = video.with_suffix(".txt").read_text(encoding="utf-8-sig").strip()
    general = data.get("caption", title)
    return Captions(general, data.get("youtube_title") or title,
                    data.get("youtube_description", general),
                    data.get("instagram_caption", general), data.get("tiktok_caption", general),
                    data.get("ai_generated", False))
