"""ffmpeg helpers: probing, cutting, frame grids for the AI, posters, timeline strips, webcam detection."""
import base64
import json
import os
import subprocess
import tempfile

import numpy as np


class MediaError(Exception):
    pass


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise MediaError(r.stderr.decode(errors="ignore")[-800:])
    return r.stdout


def probe(path):
    try:
        out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                   "-of", "json", path])
        data = json.loads(out)
        v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        return {"duration": float(data.get("format", {}).get("duration") or 0),
                "width": int(v.get("width") or 1920), "height": int(v.get("height") or 1080),
                "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}
    except Exception:
        return {"duration": 0.0, "width": 1920, "height": 1080, "has_audio": True}


def duration(path):
    return probe(path)["duration"]


def cut_segment(src, start, length, out_path):
    """Horizontal copy of a context window; every later edit/render starts from this small file."""
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, start):.2f}", "-t", f"{length:.2f}", "-i", src,
         "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path])


def frame_jpeg(src, t, width=960, out_path=None):
    """One frame as JPEG bytes (and optionally saved)."""
    data = run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.2f}", "-i", src, "-frames:v", "1",
                "-vf", f"scale={width}:-2", "-q:v", "4", "-f", "image2", "-c:v", "mjpeg", "-"])
    if out_path:
        with open(out_path, "wb") as f:
            f.write(data)
    return data


def grid_jpeg(src, start, length, cols=4, rows=3, tile_w=320):
    """Contact sheet of cols*rows frames evenly spread over [start, start+length]. Returns (jpeg, times)."""
    n = cols * rows
    step = length / n
    times = [round(i * step + step / 2, 1) for i in range(n)]
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for i, t in enumerate(times):
            p = os.path.join(tmp, f"f{i:02d}.jpg")
            try:
                frame_jpeg(src, start + t, tile_w, p)
                paths.append(p)
            except MediaError:
                break
        if not paths:
            raise MediaError("no frames")
        out = os.path.join(tmp, "grid.jpg")
        run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", os.path.join(tmp, "f%02d.jpg"),
             "-vf", f"tile={cols}x{rows}:padding=4:color=black", "-frames:v", "1", "-q:v", "4", out])
        with open(out, "rb") as f:
            return f.read(), times[:len(paths)]


def b64(data):
    return base64.b64encode(data).decode()


def sprite(src, out_path, every=2.0, height=72):
    """Horizontal strip of thumbnails for the editor timeline. Returns number of tiles."""
    dur = duration(src)
    n = max(1, min(90, int(dur / every + 0.999)))
    run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf",
         f"fps={1.0 / every},scale=-2:{height},tile={n}x1", "-frames:v", "1", "-q:v", "5", out_path])
    return n


def wave(src, step=0.25):
    """Loudness per `step` seconds (0..1) for the editor waveform."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(8000 * step)
    n = len(x) // hop
    if n == 0:
        return []
    db = 20 * np.log10(np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-6)
    return [round(float(v), 3) for v in np.clip((db + 60) / 60, 0, 1)]


def solid_jpeg(color="red"):
    return run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=32x32", "-frames:v", "1",
                "-f", "image2", "-c:v", "mjpeg", "-"])


# ----------------------------------------------------------------- webcam detection (optional OpenCV)

def detect_webcam(src, start, length, samples=14):
    """Find a streamer facecam: a face that stays in the same place across many frames.

    Game characters move around; a webcam overlay doesn't. Returns {"box": [x, y, w, h] (0..1),
    "confidence": share of frames with the face} or None. Needs opencv-python; returns None without it.
    """
    try:
        import cv2
    except ImportError:
        return None
    try:
        cascade = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
    except Exception:
        return None
    if cascade.empty():          # face model file missing from this OpenCV install
        return None
    dets, used = [], 0
    for i in range(samples):
        t = start + (i + 0.5) * length / samples
        try:
            data = frame_jpeg(src, t, 640)
        except MediaError:
            continue
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        used += 1
        h, w = img.shape
        for (x, y, fw, fh) in cascade.detectMultiScale(img, 1.1, 6, minSize=(22, 22)):
            dets.append((i, (x + fw / 2) / w, (y + fh / 2) / h, fw / w, fh / h))
    return webcam_from_detections(dets, used)


def webcam_from_detections(dets, frames_used, min_share=0.4):
    """dets: [(frame_idx, cx, cy, w, h)] normalised. Pure function (unit-tested)."""
    if not dets or frames_used < 3:
        return None
    best, best_frames = None, set()
    for _, cx, cy, _, _ in dets:
        near = [d for d in dets if abs(d[1] - cx) < 0.05 and abs(d[2] - cy) < 0.06]
        frames = {d[0] for d in near}
        if len(frames) > len(best_frames):
            best, best_frames = near, frames
    share = len(best_frames) / frames_used
    if share < min_share:
        return None
    cx = float(np.median([d[1] for d in best]))
    cy = float(np.median([d[2] for d in best]))
    fw = float(np.median([d[3] for d in best]))
    if fw > 0.3:                         # huge face = full-screen camera (IRL/just chatting), not an overlay
        return None
    size = min(0.5, max(0.14, fw * 3.2))  # 16:9 cam box in a 16:9 frame: same normalised w and h
    x, y = cx - size / 2, cy - size * 0.45
    x = min(max(x, 0.0), 1 - size)
    y = min(max(y, 0.0), 1 - size)
    snap = 0.05
    if x < snap:
        x = 0.0
    if x + size > 1 - snap:
        x = 1 - size
    if y < snap:
        y = 0.0
    if y + size > 1 - snap:
        y = 1 - size
    return {"box": [round(x, 3), round(y, 3), round(size, 3), round(size, 3)], "confidence": round(share, 2)}
