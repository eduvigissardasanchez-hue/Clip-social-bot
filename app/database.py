import sqlite3
from datetime import datetime, timezone
from .models import PLATFORMS, State

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS clips (
 sha256 TEXT PRIMARY KEY, filename TEXT NOT NULL, path TEXT NOT NULL,
 position INTEGER NOT NULL UNIQUE, discovered_at TEXT NOT NULL,
 public_url TEXT, remote_key TEXT, last_error TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT
);
CREATE TABLE IF NOT EXISTS posts (
 clip_hash TEXT NOT NULL REFERENCES clips(sha256), platform TEXT NOT NULL,
 post_id TEXT UNIQUE, state TEXT NOT NULL DEFAULT 'local', scheduled_at TEXT,
 last_error TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT,
 PRIMARY KEY(clip_hash, platform),
 CHECK(platform IN ('youtube','instagram','tiktok')),
 CHECK(state IN ('local','uploaded','queued','scheduled','sent','error'))
);
"""

class Database:
    def __init__(self, path, readonly=False):
        if readonly:
            self.connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path)
            self.connection.executescript(SCHEMA)
        self.connection.row_factory = sqlite3.Row
        if not readonly:
            self.migrate()

    def close(self):
        self.connection.close()

    def register(self, clips):
        with self.connection:
            position = self.connection.execute("SELECT COALESCE(MAX(position),0) FROM clips").fetchone()[0]
            for clip in clips:
                if self.connection.execute("SELECT 1 FROM clips WHERE sha256=?", (clip.sha256,)).fetchone():
                    continue
                position += 1
                self.connection.execute("INSERT INTO clips(sha256,filename,path,position,discovered_at) VALUES(?,?,?,?,?)",
                    (clip.sha256, clip.filename, clip.path, position, datetime.now(timezone.utc).isoformat()))
                self.connection.executemany("INSERT INTO posts(clip_hash,platform) VALUES(?,?)",
                                            [(clip.sha256, p) for p in PLATFORMS])

    def clips(self):
        return self.connection.execute("SELECT * FROM clips ORDER BY position").fetchall()

    def posts(self, digest):
        return self.connection.execute("SELECT * FROM posts WHERE clip_hash=? ORDER BY platform", (digest,)).fetchall()

    def record_post(self, digest, platform, post_id, state=State.SCHEDULED, scheduled_at=None):
        if platform not in PLATFORMS or not post_id:
            raise ValueError("Plataforma o ID inválido")
        with self.connection:
            existing = self.connection.execute("SELECT post_id FROM posts WHERE clip_hash=? AND platform=?", (digest, platform)).fetchone()
            if not existing:
                raise ValueError("Clip no registrado")
            if existing[0] and existing[0] != post_id:
                raise ValueError("No se puede reemplazar un post existente")
            self.connection.execute("UPDATE posts SET post_id=?,state=?,scheduled_at=?,last_error=NULL WHERE clip_hash=? AND platform=?",
                                    (post_id, state, scheduled_at, digest, platform))

    def migrate(self):
        additions = {
            'clips': {'captions_json': 'TEXT', 'archived': 'INTEGER NOT NULL DEFAULT 0',
                      'remote_deleted': 'INTEGER NOT NULL DEFAULT 0',
                      'preparation_attempts': 'INTEGER NOT NULL DEFAULT 0', 'next_retry_at': 'TEXT'},
            'posts': {'channel_id': 'TEXT', 'intent': "TEXT NOT NULL DEFAULT ''",
                      'retryable': 'INTEGER NOT NULL DEFAULT 0', 'next_retry_at': 'TEXT'},
        }
        with self.connection:
            for table, fields in additions.items():
                known = {r[1] for r in self.connection.execute(f'PRAGMA table_info({table})')}
                for name, definition in fields.items():
                    if name not in known:
                        self.connection.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')

    def update_clip(self, digest, **values):
        allowed = {'public_url','remote_key','last_error','attempts','last_attempt_at',
                   'captions_json','archived','remote_deleted','path','preparation_attempts','next_retry_at'}
        if not values or not set(values) <= allowed:
            raise ValueError('Campos de clip inválidos')
        with self.connection:
            self.connection.execute('UPDATE clips SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE sha256=?',
                                    (*values.values(), digest))

    def update_post(self, digest, platform, **values):
        allowed = {'state','scheduled_at','last_error','attempts','last_attempt_at',
                   'channel_id','intent','retryable','next_retry_at'}
        if not values or not set(values) <= allowed:
            raise ValueError('Campos de post inválidos')
        with self.connection:
            self.connection.execute('UPDATE posts SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE clip_hash=? AND platform=?',
                                    (*values.values(), digest, platform))
