"""SQLite layer: sources, recordings (projects), clips (every candidate, kept or rejected), results, metrics, log."""
import json
import sqlite3
import threading
import time

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,            -- channel / vod / file
    platform TEXT NOT NULL,        -- twitch / youtube / local
    url TEXT NOT NULL,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'idle',
    last_checked REAL NOT NULL DEFAULT 0,
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER,
    name TEXT,
    path TEXT,
    chat_path TEXT,
    chat_mode TEXT DEFAULT 'rel',
    file_start REAL DEFAULT 0,
    started_at REAL,
    ended_at REAL,
    status TEXT DEFAULT 'recording'
);
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id INTEGER,
    source_name TEXT,
    start REAL,
    length REAL,
    signal REAL,
    score INTEGER,
    hook TEXT DEFAULT '',
    title TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    transcript TEXT DEFAULT '',
    words_json TEXT DEFAULT '[]',
    raw_path TEXT,
    path TEXT,
    status TEXT DEFAULT 'review',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id INTEGER,
    platform TEXT,
    posted_at TEXT,
    views INTEGER,
    watch_time_sec REAL,
    avg_pct_viewed REAL,
    completion_rate REAL,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    saves INTEGER,
    notes TEXT,
    added_at REAL
);
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    kind TEXT,                     -- analyze / review / hooks / stt / render / video
    ok INTEGER,
    tokens INTEGER DEFAULT 0,
    images INTEGER DEFAULT 0,
    secs REAL DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    level TEXT,
    msg TEXT
);
"""

# columns added after V1; added automatically to old databases
MIGRATIONS = {
    "sources": {"profile": "TEXT DEFAULT ''", "cam_box": "TEXT DEFAULT ''"},
    "recordings": {
        "title": "TEXT DEFAULT ''", "duration": "REAL DEFAULT 0", "profile": "TEXT DEFAULT ''",
        "stage": "TEXT DEFAULT ''", "progress": "REAL", "detail": "TEXT DEFAULT ''", "summary": "TEXT DEFAULT ''",
        "cam_box": "TEXT DEFAULT ''", "error": "TEXT DEFAULT ''", "analyzed_sec": "REAL DEFAULT 0",
        "candidates": "INTEGER DEFAULT 0", "proc_secs": "REAL DEFAULT 0", "kind": "TEXT DEFAULT ''",
    },
    "clips": {
        "view_pct": "INTEGER DEFAULT 0", "like_pct": "INTEGER DEFAULT 0",
        "quality": "INTEGER DEFAULT 0", "stage1": "INTEGER DEFAULT 0", "stage2": "INTEGER",
        "category": "TEXT DEFAULT ''", "profile": "TEXT DEFAULT ''",
        "ctx_start": "REAL DEFAULT 0", "ctx_len": "REAL DEFAULT 0",
        "clip_in": "REAL DEFAULT 0", "clip_out": "REAL DEFAULT 0",
        "breakdown_json": "TEXT DEFAULT '{}'", "analysis_json": "TEXT DEFAULT '{}'",
        "review_json": "TEXT DEFAULT '{}'", "edit_json": "TEXT DEFAULT '{}'",
        "cues_json": "TEXT DEFAULT '[]'", "wave_json": "TEXT DEFAULT '[]'",
        "summary": "TEXT DEFAULT ''", "weaknesses": "TEXT DEFAULT ''", "reject_reason": "TEXT DEFAULT ''",
        "poster": "TEXT DEFAULT ''", "sprite": "TEXT DEFAULT ''", "edited": "INTEGER DEFAULT 0",
        "learn_adj": "INTEGER DEFAULT 0", "evidence": "TEXT DEFAULT ''", "render_secs": "REAL DEFAULT 0",
        "updated_at": "REAL DEFAULT 0",
    },
}

CLIP_JSON_FIELDS = ("breakdown_json", "analysis_json", "review_json", "edit_json", "cues_json", "wave_json",
                    "words_json")


def _conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    with _lock, _conn() as c:
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        # V1 clips: "pending" means "needs review"; score/10 becomes a rough quality
        c.execute("UPDATE clips SET status='review' WHERE status='pending'")
        c.execute("UPDATE clips SET quality = score * 10 WHERE quality = 0 AND score IS NOT NULL")
        # anything left mid-way from a crash
        c.execute("UPDATE recordings SET status='interrupted', stage='interrupted' "
                  "WHERE status IN ('recording','processing','downloading','queued')")
        c.execute("UPDATE sources SET status='idle' WHERE status NOT IN ('done','error')")
        c.execute("UPDATE clips SET status='review' WHERE status='rendering'")
        c.execute("CREATE INDEX IF NOT EXISTS clips_rec ON clips(recording_id)")
        c.execute("CREATE INDEX IF NOT EXISTS clips_status ON clips(status)")


def query(sql, args=()):
    with _lock, _conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql, args=()):
    with _lock, _conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def update(table, row_id, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    execute(f"UPDATE {table} SET {cols} WHERE id=?", (*vals, row_id))


def clip(clip_id, parse=True):
    row = one("SELECT * FROM clips WHERE id=?", (clip_id,))
    return parse_clip(row) if (row and parse) else row


def parse_clip(row):
    for f in CLIP_JSON_FIELDS:
        try:
            row[f] = json.loads(row.get(f) or ("[]" if f in ("cues_json", "wave_json", "words_json") else "{}"))
        except ValueError:
            row[f] = [] if f in ("cues_json", "wave_json", "words_json") else {}
    return row


def log(msg, level="info"):
    print(time.strftime("%H:%M:%S"), level.upper(), msg, flush=True)
    try:
        execute("INSERT INTO log (ts, level, msg) VALUES (?,?,?)", (time.time(), level, str(msg)[:500]))
        execute("DELETE FROM log WHERE id < (SELECT MAX(id) - 800 FROM log)")
    except Exception:
        pass


def metric(kind, ok=True, tokens=0, images=0, secs=0.0, note=""):
    try:
        execute("INSERT INTO metrics (ts, kind, ok, tokens, images, secs, note) VALUES (?,?,?,?,?,?,?)",
                (time.time(), kind, 1 if ok else 0, int(tokens or 0), int(images or 0), float(secs or 0),
                 str(note)[:200]))
    except Exception:
        pass
