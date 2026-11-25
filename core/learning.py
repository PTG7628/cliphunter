"""Performance learning: your real posted-clip results -> stats, AI context, and a small ranking nudge.

Nothing is invented: with no results there are no insights and no adjustment.
"""
import csv
import io
import math
import re
import statistics
import time

from . import db

FIELDS = ["platform", "posted_at", "views", "watch_time_sec", "avg_pct_viewed", "completion_rate", "likes",
          "comments", "shares", "saves", "notes"]
NUMERIC = {"views", "watch_time_sec", "avg_pct_viewed", "completion_rate", "likes", "comments", "shares", "saves"}
MIN_TOTAL, MIN_GROUP = 6, 3


def _num(v):
    if v in (None, ""):
        return None
    try:
        s = str(v).strip().replace(",", "").replace("%", "")
        mult = 1
        if s[-1:].lower() == "k":
            s, mult = s[:-1], 1000
        elif s[-1:].lower() == "m":
            s, mult = s[:-1], 1_000_000
        return float(s) * mult
    except (TypeError, ValueError):
        return None


def add_result(clip_id, data):
    row = {k: (_num(data.get(k)) if k in NUMERIC else str(data.get(k) or "")[:200]) for k in FIELDS}
    if row["views"] is None:
        raise ValueError("views is required")
    if not db.one("SELECT id FROM clips WHERE id=?", (clip_id,)):
        raise ValueError(f"clip #{clip_id} not found")
    cols = ", ".join(["clip_id", *FIELDS, "added_at"])
    db.execute(f"INSERT INTO results ({cols}) VALUES ({', '.join('?' * (len(FIELDS) + 2))})",
               (clip_id, *[row[k] for k in FIELDS], time.time()))


ALIASES = {
    "clip_id": ["clip_id", "clip", "id", "clip id"],
    "file": ["file", "filename", "video", "title", "video title"],
    "platform": ["platform", "network"],
    "posted_at": ["posted_at", "date", "publish date", "published", "posted"],
    "views": ["views", "video views", "plays"],
    "watch_time_sec": ["watch_time_sec", "watch time", "total watch time (sec)", "watch time (seconds)"],
    "avg_pct_viewed": ["avg_pct_viewed", "average percentage viewed", "average percentage viewed (%)",
                       "avg % viewed", "avg viewed %"],
    "completion_rate": ["completion_rate", "completion rate", "watched full video", "full video watched %"],
    "likes": ["likes"], "comments": ["comments"], "shares": ["shares"], "saves": ["saves", "favorites"],
    "notes": ["notes"],
}


def import_csv(text):
    """Import a CSV. Rows match clips by clip_id, or by an approved file name ending in _<id>."""
    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
    col = {k: next((headers[a] for a in names if a in headers), None) for k, names in ALIASES.items()}
    added, skipped = 0, []
    for n, r in enumerate(reader, start=2):
        cid = _num(r.get(col["clip_id"])) if col["clip_id"] else None
        if cid is None and col["file"]:
            m = re.search(r"_(\d+)(?:\.mp4)?\s*$", r.get(col["file"]) or "")
            cid = float(m.group(1)) if m else None
        if cid is None:
            skipped.append(f"line {n}: no clip id")
            continue
        try:
            add_result(int(cid), {k: r.get(col[k]) for k in FIELDS if col.get(k)})
            added += 1
        except ValueError as e:
            skipped.append(f"line {n}: {e}")
    return {"added": added, "skipped": skipped[:20]}


def _rows():
    return db.query("""SELECT r.*, c.category, c.profile, c.quality, c.clip_out - c.clip_in AS length,
                              c.edit_json FROM results r JOIN clips c ON c.id = r.clip_id""")


def _bucket(length):
    if length is None:
        return "unknown"
    return "under 20s" if length < 20 else ("20-35s" if length < 35 else "35-60s")


def _group(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(key(r) or "unknown", []).append(r)
    out = []
    for name, items in groups.items():
        views = [r["views"] for r in items if r["views"] is not None]
        pct = [r["avg_pct_viewed"] for r in items if r["avg_pct_viewed"] is not None]
        likes = [r["likes"] / r["views"] for r in items if r["likes"] is not None and r["views"]]
        out.append({"name": name, "n": len(items), "median_views": statistics.median(views) if views else 0,
                    "avg_pct_viewed": round(statistics.mean(pct), 1) if pct else None,
                    "like_rate": round(100 * statistics.mean(likes), 2) if likes else None})
    return sorted(out, key=lambda g: g["median_views"], reverse=True)


def stats():
    rows = _rows()
    views = [r["views"] for r in rows if r["views"] is not None]
    import json

    def layout(r):
        try:
            return json.loads(r["edit_json"] or "{}").get("layout", "auto")
        except ValueError:
            return "auto"
    return {
        "total": len(rows),
        "median_views": statistics.median(views) if views else 0,
        "by_category": _group(rows, lambda r: r["category"]),
        "by_profile": _group(rows, lambda r: r["profile"]),
        "by_length": _group(rows, lambda r: _bucket(r["length"])),
        "by_platform": _group(rows, lambda r: r["platform"]),
        "by_layout": _group(rows, layout),
        "enough_data": len(rows) >= MIN_TOTAL,
    }


def insights_text():
    st = stats()
    if not st["enough_data"]:
        return ""
    lines = [f"Across {st['total']} posted clips the median is {int(st['median_views'])} views."]
    for g in st["by_category"]:
        if g["n"] >= MIN_GROUP and g["name"] != "unknown":
            pct = f", {g['avg_pct_viewed']}% avg viewed" if g["avg_pct_viewed"] is not None else ""
            lines.append(f"- '{g['name']}' clips: median {int(g['median_views'])} views (n={g['n']}{pct})")
    for g in st["by_length"]:
        if g["n"] >= MIN_GROUP:
            lines.append(f"- {g['name']} clips: median {int(g['median_views'])} views (n={g['n']})")
    lines.append("Use this only as a light hint; judge the moment on its own merits.")
    return "\n".join(lines)


def adjustment(category):
    """+-5 quality points at most, only with enough real results for this category."""
    st = stats()
    if not st["enough_data"] or not st["median_views"]:
        return 0, ""
    g = next((g for g in st["by_category"] if g["name"] == category), None)
    if not g or g["n"] < MIN_GROUP or not g["median_views"]:
        return 0, ""
    ratio = g["median_views"] / st["median_views"]
    adj = max(-5, min(5, int(round(5 * math.log2(ratio)))))
    if adj == 0:
        return 0, ""
    word = "outperform" if adj > 0 else "underperform"
    return adj, f"{'+' if adj > 0 else ''}{adj}: your '{category}' clips {word} your median ({g['n']} posted)"
