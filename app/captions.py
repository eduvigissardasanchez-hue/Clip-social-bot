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


def _json_data(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("El JSON de descripción debe ser un objeto")
    for key in ("caption", "youtube_title", "youtube_description", "instagram_caption", "tiktok_caption"):
        if key in data and not isinstance(data[key], str):
            raise ValueError(f"{key} debe ser texto")
    for key in ("ai_generated", "title_from_filename"):
        if key in data and not isinstance(data[key], bool):
            raise ValueError(f"{key} debe ser booleano")
    return data


def read_captions(video: Path) -> Captions:
    title = re.sub(r"^\d+[ _.-]*", "", video.stem).replace("_", " ").strip() or "Clip"
    data = {}
    if video.with_suffix(".json").exists():
        data = _json_data(video.with_suffix(".json"))
    elif video.with_suffix(".txt").exists():
        data["caption"] = video.with_suffix(".txt").read_text(encoding="utf-8-sig").strip()
    elif (video.parent / "_default.json").exists():
        data = _json_data(video.parent / "_default.json")
    from_filename = data.get("title_from_filename", False)
    if from_filename:
        title = video.stem
    general = data.get("caption", title)
    instagram = data.get("instagram_caption", general)
    tiktok = data.get("tiktok_caption", general)
    if from_filename:
        # Buffer has no separate video-title metadata for Instagram/TikTok.
        instagram = f"{title}\n\n{instagram}" if instagram else title
        tiktok = f"{title}\n\n{tiktok}" if tiktok else title
    return Captions(general, title if from_filename else data.get("youtube_title") or title,
                    data.get("youtube_description", general), instagram, tiktok,
                    data.get("ai_generated", False))
