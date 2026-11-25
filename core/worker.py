"""Background work: watch channels, record live, download VODs, run the pipeline, re-render edits."""
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time

from . import chat, config, db, media, pipeline
from .pipeline import Cancelled, hms, set_stage

jobs = queue.Queue()
current_job = {"text": "idle", "since": time.time(), "rec_id": None, "kind": None}
sessions = {}            # source_id -> LiveSession
_sessions_lock = threading.Lock()
_procs = {}              # rec_id -> running download process (for cancel)
rendering = set()        # clip ids queued or rendering right now


# ----------------------------------------------------------------- sources

def parse_source(text):
    """Work out what the user pasted. Returns dict(kind, platform, url, name) or raises ValueError."""
    raw = text.strip().strip('"')
    if os.path.isfile(raw):
        return {"kind": "file", "platform": "local", "url": os.path.abspath(raw), "name": os.path.basename(raw)}
    url = raw if raw.startswith("http") else "https://" + raw
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if m:
        return {"kind": "vod", "platform": "twitch", "url": f"https://www.twitch.tv/videos/{m.group(1)}",
                "name": f"Twitch VOD {m.group(1)}"}
    m = re.search(r"twitch\.tv/([A-Za-z0-9_]{2,25})/?$", url.split("?")[0])
    if m and m.group(1).lower() not in ("videos", "directory", "settings"):
        name = m.group(1).lower()
        return {"kind": "channel", "platform": "twitch", "url": f"https://www.twitch.tv/{name}", "name": name}
    if re.search(r"(youtube\.com/(watch|live/|shorts/)|youtu\.be/)", url):
        return {"kind": "vod", "platform": "youtube", "url": url, "name": "YouTube video"}
    m = re.search(r"youtube\.com/(@[\w.\-]+|channel/[\w\-]+|c/[\w\-]+)", url)
    if m:
        handle = m.group(1)
        return {"kind": "channel", "platform": "youtube", "url": f"https://www.youtube.com/{handle}/live",
                "name": handle.split("/")[-1]}
    raise ValueError("Paste a YouTube/Twitch video or channel link, or drop a video file.")


def add_source(text, profile="", platform=None, display_name=None):
    info = parse_source(text)
    if platform:
        info["platform"] = platform
    if display_name:
        info["name"] = display_name
    if info["kind"] == "channel" and db.one("SELECT id FROM sources WHERE url=?", (info["url"],)):
        raise ValueError("That channel is already being watched.")
    sid = db.execute("INSERT INTO sources (kind, platform, url, name, status, added_at, profile) VALUES (?,?,?,?,?,?,?)",
                     (info["kind"], info["platform"], info["url"], info["name"],
                      "offline" if info["kind"] == "channel" else "queued", time.time(), profile or ""))
    rec_id = None
    if info["kind"] != "channel":
        rec_id = db.execute("INSERT INTO recordings (source_id, name, title, started_at, status, stage, kind, profile)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            (sid, info["name"], info["name"], time.time(), "queued", "queued", info["kind"],
                             profile if profile and profile != "auto" else ""))
        jobs.put(("vod", rec_id))
    db.log(f"Added {info['kind']}: {info['name']}")
    return {"source_id": sid, "recording_id": rec_id, "kind": info["kind"]}


# ----------------------------------------------------------------- VODs / files

def _download(rec_id, url, stamp):
    """yt-dlp with live progress. Returns (path, title, uploader)."""
    out_tpl = os.path.join(config.REC_DIR, f"vod_{rec_id}_{stamp}.%(ext)s")
    cmd = ["yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]/b", "--merge-output-format", "mp4", "--no-playlist",
           "--newline", "--progress", "-o", out_tpl, "--print", "before_dl:TITLE=%(title)s",
           "--print", "before_dl:UPLOADER=%(uploader)s", "--print", "after_move:FILE=%(filepath)s", url]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    _procs[rec_id] = proc
    path = title = uploader = None
    tail = []
    try:
        for line in proc.stdout:
            line = line.strip()
            tail = (tail + [line])[-6:]
            if line.startswith("TITLE="):
                title = line[6:]
                db.update("recordings", rec_id, title=title, name=title[:80])
            elif line.startswith("UPLOADER="):
                uploader = line[9:]
            elif line.startswith("FILE="):
                path = line[5:]
            else:
                m = re.search(r"\[download\]\s+([\d.]+)%", line)
                if m:
                    set_stage(rec_id, "downloading", round(float(m.group(1)) / 100 * 0.15, 3),
                              f"Downloading video {float(m.group(1)):.0f}%")
            if rec_id in pipeline.cancel_flags:
                proc.terminate()
                raise Cancelled()
        proc.wait()
    finally:
        _procs.pop(rec_id, None)
    if proc.returncode != 0 or not path or not os.path.exists(path):
        raise RuntimeError("download failed: " + " | ".join(tail)[-300:])
    return path, title, uploader


def process_vod(rec_id):
    rec = db.one("SELECT * FROM recordings WHERE id=?", (rec_id,))
    if not rec:
        return
    src = db.one("SELECT * FROM sources WHERE id=?", (rec["source_id"],)) or {}
    started = time.time()
    db.update("recordings", rec_id, status="processing", error="")
    try:
        path, owned = rec.get("path"), False
        if path and os.path.exists(path):
            owned = src.get("kind") != "file" or src.get("platform") == "upload"
        elif src.get("kind") == "file":
            path, owned = src["url"], src.get("platform") == "upload"
        else:
            set_stage(rec_id, "downloading", 0.0, "Starting download")
            path, title, uploader = _download(rec_id, src["url"], time.strftime("%Y%m%d_%H%M%S"))
            owned = True
            name = uploader if uploader and uploader != "NA" else (title or src["name"])
            db.update("sources", src["id"], name=name[:80])
            db.update("recordings", rec_id, name=name[:80], title=title or name)
            set_stage(rec_id, "downloading", 0.15, "Getting chat replay")
            chat_path = os.path.join(config.REC_DIR, f"vod_{rec_id}_chat.jsonl")
            if chat.download_vod_chat(src["url"], chat_path) > 0:
                db.update("recordings", rec_id, chat_path=chat_path, chat_mode="rel")
        info = media.probe(path)
        dur = info["duration"]
        if dur <= 0:
            raise RuntimeError("couldn't read the video (no duration)")
        db.update("recordings", rec_id, path=path, duration=dur, file_start=0)
        rec = db.one("SELECT * FROM recordings WHERE id=?", (rec_id,))
        s = config.load()
        chunk = max(60, int(s["chunk_minutes"]) * 60)
        overlap = max(45, int(s["chunk_overlap_sec"]))
        t = max(0.0, (rec.get("analyzed_sec") or 0) - overlap) if rec.get("analyzed_sec") else 0.0
        while t < dur:
            end = min(dur, t + chunk)
            current_job["text"] = f"{rec['name']}: {hms(t)} / {hms(dur)}"
            pipeline.process_window(rec_id, t, end, final=end >= dur, overall=(t, end, dur))
            t = end - overlap if end < dur else dur
        secs = time.time() - started
        db.update("recordings", rec_id, status="done", stage="done", progress=1.0, detail="Finished",
                  proc_secs=(rec.get("proc_secs") or 0) + secs, ended_at=time.time())
        db.metric("video", True, 0, 0, secs, f"{dur:.0f}s video")
        if src.get("id"):
            db.update("sources", src["id"], status="done")
        pipeline.update_summary(rec_id)
        if owned and not config.get("keep_recordings") and os.path.exists(path):
            os.remove(path)
            db.update("recordings", rec_id, path="")
        db.log(f"[{rec['name']}] done in {hms(secs)}")
    except Cancelled:
        db.update("recordings", rec_id, status="cancelled", stage="cancelled", detail="Cancelled", progress=None)
        db.log(f"Cancelled project #{rec_id}", "warn")
    except Exception as e:
        db.update("recordings", rec_id, status="error", stage="error", error=str(e)[:400], detail="Failed")
        db.metric("video", False, 0, 0, time.time() - started, str(e)[:80])
        db.log(f"Project #{rec_id} failed: {e}", "error")
        if src.get("id"):
            db.update("sources", src["id"], status="error")
    finally:
        pipeline.cancel_flags.discard(rec_id)


def cancel(rec_id):
    pipeline.cancel_flags.add(rec_id)
    proc = _procs.get(rec_id)
    if proc and proc.poll() is None:
        proc.terminate()
    rec = db.one("SELECT source_id, status FROM recordings WHERE id=?", (rec_id,))
    if rec and rec["status"] == "recording":
        stop_session(rec["source_id"])
    if rec and rec["status"] == "queued":
        db.update("recordings", rec_id, status="cancelled", stage="cancelled", detail="Cancelled")


def retry(rec_id):
    pipeline.cancel_flags.discard(rec_id)
    db.update("recordings", rec_id, status="queued", stage="queued", detail="Queued again", error="", progress=None)
    jobs.put(("vod", rec_id))


def delete_project(rec_id):
    cancel(rec_id)
    rec = db.one("SELECT * FROM recordings WHERE id=?", (rec_id,))
    for c in db.query("SELECT path, raw_path, poster, sprite FROM clips WHERE recording_id=?", (rec_id,)):
        for p in c.values():
            if p and os.path.exists(p):
                os.remove(p)
    db.execute("DELETE FROM clips WHERE recording_id=?", (rec_id,))
    if rec:
        for p in (rec.get("chat_path"), os.path.join(config.CACHE_DIR, f"wave_{rec_id}.json")):
            if p and os.path.exists(p):
                os.remove(p)
        src = db.one("SELECT * FROM sources WHERE id=?", (rec["source_id"],))
        if rec.get("path") and os.path.exists(rec["path"]) and (not src or src["kind"] != "file"
                                                                 or src["platform"] == "upload"):
            os.remove(rec["path"])
        if src and src["kind"] != "channel":
            db.execute("DELETE FROM sources WHERE id=?", (src["id"],))
    db.execute("DELETE FROM recordings WHERE id=?", (rec_id,))


# ----------------------------------------------------------------- live recording

class LiveSession(threading.Thread):
    def __init__(self, source, title=""):
        super().__init__(daemon=True)
        self.source, self.title = source, title
        self.stop_event = threading.Event()
        self.proc = None
        self.chat = None
        self.started = time.time()
        self.file_start = None
        self.rec_id = None

    def stop(self):
        self.stop_event.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def info(self):
        elapsed = time.time() - (self.file_start or self.started)
        return {"source_id": self.source["id"], "recording_id": self.rec_id, "name": self.source["name"],
                "title": self.title, "elapsed": hms(elapsed), "chat": self.chat.count if self.chat else 0}

    def run(self):
        src, s = self.source, config.load()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.join(config.REC_DIR, f"{re.sub(r'[^A-Za-z0-9_@-]', '', src['name'])}_{stamp}")
        path, chat_path = base + ".ts", base + "_chat.jsonl"
        db.update("sources", src["id"], status="recording")
        db.log(f"LIVE: {src['name']} went live. Recording...")
        cam = src.get("cam_box") or ""
        self.rec_id = db.execute(
            "INSERT INTO recordings (source_id, name, title, path, chat_path, chat_mode, started_at, status, stage,"
            " detail, kind, cam_box) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (src["id"], src["name"], self.title or src["name"], path, chat_path, "epoch", time.time(), "recording",
             "recording", "Recording live stream", "live", cam))
        self.chat = chat.LiveChatLogger(src["platform"], src["url"], src["name"], chat_path)
        self.chat.start()
        self.proc = subprocess.Popen(["streamlink", "--loglevel", "warning", "--force", "-o", path, src["url"],
                                      s["record_quality"]], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        while self.proc.poll() is None and not self.stop_event.is_set():
            if os.path.exists(path) and os.path.getsize(path) > 0:
                break
            time.sleep(0.5)
        self.file_start = time.time()
        db.update("recordings", self.rec_id, file_start=self.file_start)

        next_start = 0.0
        overlap = max(45, int(config.get("chunk_overlap_sec")))
        while self.proc.poll() is None and not self.stop_event.is_set():
            self.stop_event.wait(10)
            elapsed = time.time() - self.file_start - 15          # stay a bit behind the live edge
            every = max(3, int(config.get("process_every_min"))) * 60
            if elapsed - next_start >= every:
                jobs.put(("window", self.rec_id, next_start, elapsed, False))
                next_start = elapsed - overlap

        if self.proc.poll() is None:
            self.proc.terminate()
        err = self.proc.stderr.read().decode(errors="ignore")[-300:] if self.proc.stderr else ""
        self.chat.stop()
        end = media.duration(path) if os.path.exists(path) else 0
        db.update("recordings", self.rec_id, ended_at=time.time(), status="processing", duration=end)
        if end > 20:
            db.log(f"{src['name']} stream ended ({hms(end)} recorded). Checking the rest...")
            jobs.put(("window", self.rec_id, next_start, end, True))
        elif err:
            db.log(f"Recording {src['name']} failed: {err}", "error")
        jobs.put(("cleanup", self.rec_id))
        with _sessions_lock:
            sessions.pop(src["id"], None)
        db.update("sources", src["id"], status="offline", last_checked=time.time())


def is_live(url):
    try:
        r = subprocess.run(["streamlink", "--json", url], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=60, text=True)
        data = json.loads(r.stdout or "{}")
        title = ((data.get("metadata") or {}).get("title") or "") if isinstance(data, dict) else ""
        return bool(data.get("streams")), title
    except Exception:
        return False, ""


def stop_session(source_id):
    with _sessions_lock:
        sess = sessions.get(source_id)
    if sess:
        sess.stop()


def watcher_loop():
    while True:
        try:
            s = config.load()
            for src in db.query("SELECT * FROM sources WHERE kind='channel' AND enabled=1"):
                with _sessions_lock:
                    if src["id"] in sessions or len(sessions) >= int(s["max_live_recordings"]):
                        continue
                if time.time() - src["last_checked"] < int(s["check_interval_sec"]):
                    continue
                db.update("sources", src["id"], status="checking", last_checked=time.time())
                live, title = is_live(src["url"])
                if live:
                    sess = LiveSession(src, title)
                    with _sessions_lock:
                        sessions[src["id"]] = sess
                    sess.start()
                else:
                    db.update("sources", src["id"], status="offline")
        except Exception as e:
            db.log(f"Watcher error: {e}", "error")
        time.sleep(15)


# ----------------------------------------------------------------- job loop

def _finish_live(rec_id):
    rec = db.one("SELECT * FROM recordings WHERE id=?", (rec_id,))
    if not rec:
        return
    db.update("recordings", rec_id, status="done", stage="done", progress=1.0, detail="Finished")
    pipeline.update_summary(rec_id)
    if not config.get("keep_recordings") and rec["path"] and os.path.exists(rec["path"]):
        os.remove(rec["path"])
        db.update("recordings", rec_id, path="")
        db.log(f"[{rec['name']}] finished. Deleted the full recording to save space (clips are kept).")


def job_loop():
    while True:
        job = jobs.get()
        kind = job[0]
        current_job.update(kind=kind, since=time.time(), rec_id=None)
        try:
            if kind == "window":
                _, rec_id, t0, t1, final = job
                rec = db.one("SELECT name FROM recordings WHERE id=?", (rec_id,))
                current_job.update(text=f"{rec['name'] if rec else ''}: {hms(t0)}-{hms(t1)}", rec_id=rec_id)
                pipeline.process_window(rec_id, t0, t1, final)
                if not final:
                    set_stage(rec_id, "recording", None, "Recording live stream")
            elif kind == "cleanup":
                _finish_live(job[1])
            elif kind == "vod":
                current_job.update(text="Processing video", rec_id=job[1])
                process_vod(job[1])
            elif kind == "render":
                current_job.update(text=f"Rendering clip #{job[1]}")
                try:
                    pipeline.render_clip(job[1])
                    db.log(f"Rendered clip #{job[1]}")
                finally:
                    rendering.discard(job[1])
        except Cancelled:
            db.log("Job cancelled", "warn")
        except Exception as e:
            db.log(f"Job {kind} failed: {e}", "error")
        finally:
            current_job.update(text="idle", since=time.time(), rec_id=None, kind=None)
            jobs.task_done()


def start():
    db.init()
    for target in (job_loop, watcher_loop):
        threading.Thread(target=target, daemon=True).start()
    for rec in db.query("SELECT id FROM recordings WHERE status IN ('queued','interrupted') AND kind IN ('vod','file')"):
        retry(rec["id"])


def active_sessions():
    with _sessions_lock:
        return [s.info() for s in sessions.values()]


def queue_render(clip_id):
    rendering.add(clip_id)
    jobs.put(("render", clip_id))


def check_tools():
    return [t for t in ("ffmpeg", "ffprobe", "streamlink", "yt-dlp") if not shutil.which(t)]
