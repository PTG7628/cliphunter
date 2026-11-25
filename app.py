"""ClipHunter: gaming & livestream highlight studio.

Run:  python app.py   (opens http://127.0.0.1:7860)
"""
import os
import shutil
import subprocess
import sys
import sysconfig
import threading
import time
import webbrowser

# pip puts streamlink.exe / yt-dlp.exe in Python's "Scripts" folder, which often isn't on PATH
for _scheme in (None, f"{os.name}_user"):
    try:
        _dir = sysconfig.get_path("scripts", _scheme) if _scheme else sysconfig.get_path("scripts")
    except KeyError:
        continue
    if _dir and os.path.isdir(_dir) and _dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _dir + os.pathsep + os.environ.get("PATH", "")

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

from flask import Flask, abort, jsonify, request, send_file, send_from_directory  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402

from core import ai, config, db, learning, media, pipeline, profiles, render, worker  # noqa: E402

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 ** 3   # uploads up to 40 GB (it's your own PC)
HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, "ui")
PORT = int(os.environ.get("CLIPHUNTER_PORT", "7860"))
CLIP_COLS = ("id, recording_id, source_name, start, length, signal, score, quality, stage1, stage2, category, "
             "profile, ctx_start, ctx_len, clip_in, clip_out, hook, title, caption, reason, status, created_at, "
             "updated_at, view_pct, like_pct, summary, weaknesses, reject_reason, learn_adj, evidence, poster, "
             "edited, breakdown_json, edit_json")


def ok(**kw):
    return jsonify({"ok": True, **kw})


def err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


@app.get("/")
def index():
    return send_from_directory(UI, "index.html")


@app.get("/ui/<path:name>")
def ui_file(name):
    return send_from_directory(UI, name)


# ----------------------------------------------------------------- overview

@app.get("/api/state")
def state():
    counts = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) n FROM clips GROUP BY status")}
    since = time.time() - 86400
    m = db.query("SELECT kind, SUM(ok) ok, COUNT(*) n, SUM(tokens) tokens, SUM(images) images, SUM(secs) secs "
                 "FROM metrics WHERE ts > ? GROUP BY kind", (since,))
    metrics = {r["kind"]: r for r in m}
    ai_calls = sum(metrics.get(k, {}).get("n", 0) or 0 for k in ("analyze", "review", "hooks"))
    ai_fail = sum((metrics.get(k, {}).get("n", 0) or 0) - (metrics.get(k, {}).get("ok", 0) or 0)
                  for k in ("analyze", "review", "hooks"))
    avg_q = db.one("SELECT AVG(quality) q FROM clips WHERE status IN ('ready','review','approved')")
    s = config.load()
    return jsonify({
        "job": worker.current_job["text"], "job_rec": worker.current_job["rec_id"],
        "job_seconds": int(time.time() - worker.current_job["since"]), "queue": worker.jobs.qsize(),
        "live": worker.active_sessions(), "counts": counts,
        "avg_quality": round((avg_q or {}).get("q") or 0),
        "usage": {"ai_calls": ai_calls, "ai_failures": ai_fail,
                  "tokens": sum((metrics.get(k, {}).get("tokens") or 0) for k in ("analyze", "review", "hooks")),
                  "images": sum((metrics.get(k, {}).get("images") or 0) for k in ("analyze", "review")),
                  "stt_calls": metrics.get("stt", {}).get("n", 0) or 0,
                  "renders": metrics.get("render", {}).get("n", 0) or 0},
        "log": db.query("SELECT ts, level, msg FROM log ORDER BY id DESC LIMIT 80"),
        "missing_tools": worker.check_tools(),
        "ai_on": ai.enabled(s), "vision": ai.vision_status(s),
        "thresholds": {"export": s["export_threshold"], "review": s["review_threshold"],
                       "max": s["max_clips_per_video"]},
        "rendering": sorted(worker.rendering),
    })


# ----------------------------------------------------------------- projects

def _project_row(r):
    counts = {x["status"]: x["n"] for x in db.query(
        "SELECT status, COUNT(*) n FROM clips WHERE recording_id=? GROUP BY status", (r["id"],))}
    r["counts"] = counts
    src = db.one("SELECT kind, platform, url FROM sources WHERE id=?", (r["source_id"],)) if r["source_id"] else None
    r["source"] = src or {}
    r["profile_name"] = profiles.get(r["profile"])["name"] if r.get("profile") else ""
    top = db.one("SELECT id, poster FROM clips WHERE recording_id=? AND status IN ('ready','review','approved') "
                 "ORDER BY quality DESC LIMIT 1", (r["id"],))
    r["cover"] = top["id"] if top and top["poster"] else None
    return r


@app.get("/api/projects")
def projects():
    rows = db.query("SELECT id, source_id, name, title, status, stage, progress, detail, summary, duration, profile,"
                    " analyzed_sec, candidates, started_at, ended_at, error, kind, proc_secs FROM recordings "
                    "ORDER BY id DESC LIMIT 100")
    return jsonify([_project_row(r) for r in rows])


@app.get("/api/projects/<int:rid>")
def project(rid):
    r = db.one("SELECT * FROM recordings WHERE id=?", (rid,))
    if not r:
        abort(404)
    r = _project_row(r)
    r["wave"] = pipeline.load_wave(rid)
    r["clips"] = [db.parse_clip(c) for c in db.query(
        f"SELECT {CLIP_COLS}, cues_json FROM clips WHERE recording_id=? ORDER BY start", (rid,))]
    for c in r["clips"]:
        meta = c.pop("cues_json") or {}
        c["peak"] = meta.get("peak") if isinstance(meta, dict) else None
        c["cues"] = meta.get("cues", []) if isinstance(meta, dict) else []
        c["nominated_by"] = meta.get("nominated_by") if isinstance(meta, dict) else ""
    try:
        cam = __import__("json").loads(r.get("cam_box") or "{}")
    except ValueError:
        cam = {}
    r["cam"] = cam
    for k in ("path", "chat_path"):
        r.pop(k, None)
    return jsonify(r)


@app.post("/api/projects/<int:rid>/cancel")
def cancel_project(rid):
    worker.cancel(rid)
    return ok()


@app.post("/api/projects/<int:rid>/retry")
def retry_project(rid):
    worker.retry(rid)
    return ok()


@app.delete("/api/projects/<int:rid>")
def delete_project(rid):
    worker.delete_project(rid)
    return ok()


@app.post("/api/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return err("No file received")
    name = secure_filename(f.filename) or "video.mp4"
    if not name.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".ts", ".flv", ".avi", ".m4v")):
        return err("That doesn't look like a video file")
    path = os.path.join(config.UPLOAD_DIR, f"{int(time.time())}_{name}")
    f.save(path)
    res = worker.add_source(path, request.form.get("profile", ""), platform="upload",
                            display_name=os.path.splitext(f.filename)[0][:80])
    return ok(**res)


@app.post("/api/sources")
def add_source():
    d = request.json or {}
    try:
        return ok(**worker.add_source(d.get("url", ""), d.get("profile", "")))
    except ValueError as e:
        return err(str(e))


@app.get("/api/channels")
def channels():
    return jsonify(db.query("SELECT * FROM sources WHERE kind='channel' ORDER BY id DESC"))


@app.post("/api/channels/<int:sid>/<action>")
def channel_action(sid, action):
    if action == "toggle":
        db.execute("UPDATE sources SET enabled = 1 - enabled, last_checked = 0 WHERE id=?", (sid,))
        src = db.one("SELECT enabled FROM sources WHERE id=?", (sid,))
        if src and not src["enabled"]:
            worker.stop_session(sid)
    elif action == "check":
        db.update("sources", sid, last_checked=0)
    elif action == "stop":
        worker.stop_session(sid)
    elif action == "profile":
        db.update("sources", sid, profile=(request.json or {}).get("profile", ""))
    else:
        return err("unknown action")
    return ok()


@app.delete("/api/channels/<int:sid>")
def delete_channel(sid):
    worker.stop_session(sid)
    db.execute("DELETE FROM sources WHERE id=?", (sid,))
    return ok()


# ----------------------------------------------------------------- clips

SORTS = {
    "quality": "quality DESC, id DESC",
    "significance": "CAST(json_extract(breakdown_json, '$.scores.significance') AS INT) DESC, quality DESC",
    "entertainment": "(COALESCE(json_extract(breakdown_json, '$.scores.reaction'),0) + "
                     "COALESCE(json_extract(breakdown_json, '$.scores.hook'),0) + "
                     "COALESCE(json_extract(breakdown_json, '$.scores.retention'),0)) DESC, quality DESC",
    "duration": "(clip_out - clip_in) ASC",
    "timeline": "recording_id DESC, start ASC",
    "newest": "id DESC",
}


@app.get("/api/clips")
def clips():
    status = request.args.get("status", "top")
    where, args = [], []
    if status == "top":
        where.append("status='ready'")
    elif status == "all":
        where.append("status IN ('ready','review','approved')")
    else:
        where.append("status=?")
        args.append(status)
    for key, col in (("profile", "profile"), ("category", "category"), ("project", "recording_id")):
        if request.args.get(key):
            where.append(f"{col}=?")
            args.append(request.args[key])
    order = SORTS.get(request.args.get("sort", "quality"), SORTS["quality"])
    rows = db.query(f"SELECT {CLIP_COLS} FROM clips WHERE {' AND '.join(where)} ORDER BY {order} LIMIT 300", args)
    out = []
    for r in rows:
        r = db.parse_clip(r)
        r["rendering"] = r["id"] in worker.rendering
        r["duration"] = round((r["edit_json"] or {}).get("rendered_duration") or (r["clip_out"] - r["clip_in"]), 1)
        out.append(r)
    return jsonify(out)


@app.get("/api/clips/<int:cid>")
def clip_detail(cid):
    c = db.clip(cid)
    if not c:
        abort(404)
    c["rendering"] = cid in worker.rendering
    for k in ("raw_path", "path", "sprite"):
        c["has_" + k] = bool(c.get(k)) and os.path.exists(c[k])
        c.pop(k, None)
    rec = db.one("SELECT name, title, cam_box FROM recordings WHERE id=?", (c["recording_id"],)) or {}
    c["project"] = {"name": rec.get("name"), "title": rec.get("title")}
    c["rubric"] = {"max": ai.RUBRIC, "labels": ai.RUBRIC_LABELS, "order": list(ai.RUBRIC)}
    c["styles"] = {k: v["label"] for k, v in render.STYLES.items()}
    return jsonify(c)


@app.post("/api/clips/<int:cid>/save")
def save_clip(cid):
    try:
        edit = pipeline.save_edit(cid, request.json or {})
    except ValueError as e:
        return err(str(e), 404)
    if (request.json or {}).get("render"):
        worker.queue_render(cid)
    return ok(edit=edit)


@app.post("/api/clips/<int:cid>/render")
def render_clip(cid):
    if request.json:
        pipeline.save_edit(cid, request.json)
    worker.queue_render(cid)
    return ok()


@app.post("/api/clips/<int:cid>/hooks")
def more_hooks(cid):
    if not ai.enabled():
        return err("Turn on an AI provider in Settings first.")
    try:
        return ok(hooks=ai.new_hooks(db.clip(cid)))
    except Exception as e:
        return err(str(e)[:200], 500)


def _nice_name(clip):
    slug = "".join(ch if ch.isalnum() else "_" for ch in (clip["hook"] or clip["category"] or "clip"))[:40].strip("_")
    src = "".join(ch if ch.isalnum() else "_" for ch in (clip["source_name"] or ""))[:30]
    return f"{clip['quality']}q_{src}_{slug}_{clip['id']}"


@app.post("/api/clips/<int:cid>/approve")
def approve(cid):
    if request.json:
        pipeline.save_edit(cid, request.json)
    c = db.clip(cid)
    if not c or not os.path.exists(c["path"] or ""):
        return err("This clip has no rendered video yet", 404)
    name = _nice_name(c)
    shutil.copy2(c["path"], os.path.join(config.APPROVED_DIR, name + ".mp4"))
    bd = c["breakdown_json"] or {}
    with open(os.path.join(config.APPROVED_DIR, name + ".txt"), "w", encoding="utf-8") as f:
        f.write(f"QUALITY: {c['quality']}/100   CATEGORY: {c['category']}\n"
                f"SCORES: {bd.get('scores')}\n\nTITLE:\n{c['title']}\n\nCAPTION:\n{c['caption']}\n\n"
                f"HOOK:\n{c['hook']}\n\nWHY: {c['summary']}\nCLIP ID (for results import): {c['id']}\n")
    db.update("clips", cid, status="approved")
    return ok(file=name + ".mp4")


@app.post("/api/clips/<int:cid>/reject")
def reject(cid):
    c = db.clip(cid, parse=False)
    if c:
        for p in (c["path"], c["raw_path"], c["poster"], c["sprite"]):
            if p and os.path.exists(p):
                os.remove(p)
        db.update("clips", cid, status="rejected", reject_reason="rejected by you", path="", raw_path="", poster="",
                  sprite="")
    return ok()


@app.post("/api/clips/<int:cid>/restore")
def restore(cid):
    c = db.clip(cid, parse=False)
    if not c or not c["path"] or not os.path.exists(c["path"]):
        return err("This clip's video was deleted, it can't be restored")
    db.update("clips", cid, status="review")
    return ok()


@app.post("/api/clips/<int:cid>/webcam")
def set_webcam(cid):
    d = request.json or {}
    box = d.get("box")
    if box is not None and (len(box) != 4 or not all(0 <= float(v) <= 1 for v in box)):
        return err("bad box")
    c = db.clip(cid)
    edit = dict(c["edit_json"] or {}, cam_box=box)
    if box and edit.get("layout") in ("auto", "blur"):
        edit["layout"] = "facecam"
    db.update("clips", cid, edit_json=edit, edited=1)
    if d.get("apply_to") == "channel":
        rec = db.one("SELECT source_id FROM recordings WHERE id=?", (c["recording_id"],))
        payload = __import__("json").dumps({"box": box, "source": "manual"})
        db.update("recordings", c["recording_id"], cam_box=payload)
        if rec and rec["source_id"]:
            db.update("sources", rec["source_id"], cam_box=payload)
        for other in db.query("SELECT id, edit_json FROM clips WHERE recording_id=? AND id != ? AND status IN "
                              "('ready','review')", (c["recording_id"], cid)):
            e2 = __import__("json").loads(other["edit_json"] or "{}")
            e2["cam_box"] = box
            db.update("clips", other["id"], edit_json=e2)
    return ok(edit=edit)


def _file(cid, field, mimetype):
    c = db.one(f"SELECT {field} FROM clips WHERE id=?", (cid,))
    if not c or not c[field] or not os.path.exists(c[field]):
        abort(404)
    return send_file(c[field], mimetype=mimetype, conditional=True, max_age=0)


@app.get("/media/<int:cid>")
def media_clip(cid):
    return _file(cid, "path", "video/mp4")


@app.get("/media/raw/<int:cid>")
def media_raw(cid):
    return _file(cid, "raw_path", "video/mp4")


@app.get("/media/poster/<int:cid>")
def media_poster(cid):
    return _file(cid, "poster", "image/jpeg")


@app.get("/media/sprite/<int:cid>")
def media_sprite(cid):
    return _file(cid, "sprite", "image/jpeg")


@app.get("/media/frame/<int:cid>")
def media_frame(cid):
    c = db.one("SELECT raw_path FROM clips WHERE id=?", (cid,))
    if not c or not c["raw_path"] or not os.path.exists(c["raw_path"]):
        abort(404)
    t = float(request.args.get("t", 1))
    data = media.frame_jpeg(c["raw_path"], t, 960)
    return app.response_class(data, mimetype="image/jpeg")


@app.get("/download/<int:cid>")
def download(cid):
    c = db.clip(cid, parse=False)
    if not c or not os.path.exists(c["path"] or ""):
        abort(404)
    return send_file(c["path"], as_attachment=True, download_name=_nice_name(c) + ".mp4")


@app.post("/api/open-approved")
def open_approved():
    folder = config.APPROVED_DIR
    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass
    return ok(folder=folder)


@app.post("/api/reclassify")
def reclassify():
    return ok(changed=pipeline.reclassify())


# ----------------------------------------------------------------- results / learning

@app.get("/api/results")
def results():
    rows = db.query("SELECT r.*, c.hook, c.category, c.source_name, c.quality FROM results r "
                    "JOIN clips c ON c.id = r.clip_id ORDER BY r.id DESC LIMIT 300")
    approved = db.query("SELECT id, hook, title, category, source_name, quality, poster FROM clips "
                        "WHERE status='approved' ORDER BY id DESC LIMIT 200")
    return jsonify({"results": rows, "approved": approved, "stats": learning.stats(),
                    "insights": learning.insights_text()})


@app.post("/api/results")
def add_result():
    d = request.json or {}
    try:
        learning.add_result(int(d.get("clip_id", 0)), d)
    except (ValueError, TypeError) as e:
        return err(str(e))
    return ok()


@app.delete("/api/results/<int:rid>")
def delete_result(rid):
    db.execute("DELETE FROM results WHERE id=?", (rid,))
    return ok()


@app.post("/api/results/import")
def import_results():
    f = request.files.get("file")
    text = f.read().decode("utf-8-sig", errors="replace") if f else (request.json or {}).get("csv", "")
    return ok(**learning.import_csv(text))


@app.get("/api/results/template.csv")
def results_template():
    body = ("clip_id,platform,posted_at,views,avg_pct_viewed,completion_rate,watch_time_sec,likes,comments,shares,"
            "saves,notes\n12,TikTok,2026-11-20,15400,61,38,9200,1200,45,80,150,posted at 8pm\n")
    return app.response_class(body, mimetype="text/csv",
                              headers={"Content-Disposition": "attachment; filename=results_template.csv"})


# ----------------------------------------------------------------- settings

@app.get("/api/settings")
def get_settings():
    return jsonify({"settings": config.load(), "providers": config.PROVIDERS, "profiles": profiles.public_list(),
                    "styles": {k: v["label"] for k, v in render.STYLES.items()}})


@app.post("/api/settings")
def set_settings():
    before = config.load()
    after = config.save(request.json or {})
    changed = 0
    if (before["export_threshold"], before["review_threshold"]) != (after["export_threshold"],
                                                                    after["review_threshold"]):
        changed = pipeline.reclassify()
    return ok(settings=after, reclassified=changed)


@app.post("/api/ai/test")
def test_ai():
    d = request.json or {}
    return jsonify(ai.test(d.get("base_url", ""), d.get("key", ""), d.get("model", ""), d.get("vision_model", "")))


@app.get("/api/profiles")
def get_profiles():
    return jsonify(profiles.public_list())


def main():
    worker.start()
    missing = worker.check_tools()
    if missing:
        db.log("Missing tools: " + ", ".join(missing) + ". Run INSTALL.bat again.", "error")
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  ClipHunter is running: {url}\n  Keep this window open. Close it to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
