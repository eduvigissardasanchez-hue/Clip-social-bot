from dataclasses import dataclass, field
from pathlib import Path
import os
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

@dataclass(frozen=True)
class Config:
    root: Path = ROOT
    dry_run: bool = True
    capacity: int = 10
    thumbnail_offset_ms: int = 2000
    buffer_api_key: str = field(default="", repr=False)
    r2_account_id: str = ""
    r2_access_key_id: str = field(default="", repr=False)
    r2_secret_access_key: str = field(default="", repr=False)
    r2_bucket: str = ""
    r2_public_base_url: str = ""

    organization_id: str = ""
    channel_ids: dict = field(default_factory=dict)
    max_attempts: int = 5

    @classmethod
    def load(cls, root=ROOT):
        root = Path(root)
        load_dotenv(root / ".env", override=False)
        flag = os.getenv("DRY_RUN", "true").lower()
        if flag not in ("true", "false"):
            raise ValueError("DRY_RUN debe ser true o false")
        capacity = int(os.getenv("BUFFER_CHANNEL_CAPACITY", "10"))
        offset = int(os.getenv("THUMBNAIL_OFFSET_MS", "2000"))
        if not 1 <= int(os.getenv("MAX_ATTEMPTS", "5")) <= 20:
            raise ValueError("MAX_ATTEMPTS debe estar entre 1 y 20")
        if not 1 <= capacity <= 10 or offset < 0:
            raise ValueError("Capacidad inválida (1..10) o thumbnailOffset negativo")
        return cls(root, flag == "true", capacity, offset,
                   os.getenv("BUFFER_API_KEY", ""), os.getenv("R2_ACCOUNT_ID", ""),
                   os.getenv("R2_ACCESS_KEY_ID", ""), os.getenv("R2_SECRET_ACCESS_KEY", ""),
                   os.getenv("R2_BUCKET", ""), os.getenv("R2_PUBLIC_BASE_URL", "").rstrip("/"),
                   os.getenv("BUFFER_ORGANIZATION_ID", ""),
                   {p: os.getenv(f"BUFFER_{p.upper()}_CHANNEL_ID", "") for p in ("youtube", "instagram", "tiktok")},
                   int(os.getenv("MAX_ATTEMPTS", "5")))

    def validate_storage(self):
        names = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL")
        values = (self.r2_account_id, self.r2_access_key_id, self.r2_secret_access_key, self.r2_bucket, self.r2_public_base_url)
        missing = [name for name, value in zip(names, values) if not value]
        if missing:
            raise ValueError("Configura en .env: " + ", ".join(missing))
        url = urlsplit(self.r2_public_base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("R2_PUBLIC_BASE_URL debe ser HTTPS público sin credenciales ni parámetros")
