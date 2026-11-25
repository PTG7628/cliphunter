"""Cheap multimodal signals and candidate *events* (pipeline stages 1-5).

Nothing here decides quality. Signals only nominate moments worth showing to the AI judge, and every
cue is passed on as "automatic hint, may be wrong".
"""
import json
import re
import subprocess

import numpy as np

HOP = 0.5           # seconds per analysis step
SR = 16000
VIS_W, VIS_H = 64, 36

HYPE_RE = re.compile(
    r"(KEKW|OMEGALUL|LUL|LMAO+|LOL+|POG|PogU|Pog|W+\b|NO WAY|NOWAY|WTF|OMG|CLIP|\?\?\?|!!!|💀|😂|🤣|"
    r"HOLY|BRO+|YOOO+|AINTNOWAY|ICANT|monkaS|Aware|EZ|DEAD|HAHA+)",
    re.IGNORECASE,
)
BANDS_HZ = [0, 150, 300, 600, 1000, 1500, 2200, 3400, 5000, 8001]
VOICE_BANDS = slice(2, 7)  # 300-3400 Hz


# ----------------------------------------------------------------- helpers

def smooth(x, seconds):
    """Moving average that stays correct at the edges (no zero padding)."""
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return x
    k = max(1, min(len(x), int(round(seconds / HOP))))
    num = np.convolve(x, np.ones(k), mode="same")
    den = np.convolve(np.ones(len(x)), np.ones(k), mode="same")
    return num / den


def robust_z(x):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return x
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826
    scale = max(mad, np.std(x) * 0.5, 1e-3)
    return (x - med) / scale


def _window_max(x, before, after):
    """y[i] = max(x[i-before : i+after+1]) in steps."""
    n = len(x)
    out = np.empty(n)
    for i in range(n):
        out[i] = x[max(0, i - before):min(n, i + after + 1)].max()
    return out


def _window_mean(x, start_off, end_off):
    """y[i] = mean(x[i+start_off : i+end_off]) (offsets in steps, may be negative)."""
    n = len(x)
    c = np.concatenate([[0.0], np.cumsum(x)])
    out = np.empty(n)
    for i in range(n):
        a, b = max(0, i + start_off), min(n, i + end_off)
        out[i] = (c[b] - c[a]) / (b - a) if b > a else x[i]
    return out


# ----------------------------------------------------------------- chat

def load_chat(recording):
    """List of (seconds_into_video, text) for a recording's chat log."""
    path = recording.get("chat_path")
    if not path:
        return []
    msgs = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if "t" in m:
                    t = float(m["t"])
                elif "ts" in m:
                    t = float(m["ts"]) - float(recording.get("file_start") or 0)
                else:
                    continue
                msgs.append((t, m.get("m", "")))
    except (FileNotFoundError, TypeError):
        return []
    return msgs


def hype_weight(text):
    w = 1.0
    if HYPE_RE.search(text or ""):
        w += 1.0
    letters = [c for c in (text or "") if c.isalpha()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        w += 0.5
    return w


def chat_curve(msgs, a0, n, delay):
    counts = np.zeros(n)
    for t, text in msgs:
        i = int((t - delay - a0) / HOP)
        if 0 <= i < n:
            counts[i] += hype_weight(text)
    return counts


def chat_window(msgs, start, end, delay, limit=60):
    """Chat in [start, end] of the video, times shifted by the chat delay and made relative to start."""
    rows = [(round(t - delay - start, 1), text) for t, text in msgs if start <= t - delay <= end]
    if len(rows) > limit:
        step = len(rows) / limit
        rows = [rows[int(i * step)] for i in range(limit)]
    return rows


# ----------------------------------------------------------------- audio

def audio_features(path, t0, duration):
    """Per-HOP audio features for [t0, t0+duration]: loudness, streamer-voice-band intensity, onsets."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0, t0):.2f}", "-t", f"{duration:.2f}", "-i", path,
           "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(SR * HOP)
    n = len(samples) // hop
    if n == 0:
        return None
    frames = samples[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-6)

    freqs = np.fft.rfftfreq(hop, 1.0 / SR)
    edges = np.searchsorted(freqs, BANDS_HZ)
    bands = np.zeros((n, len(BANDS_HZ) - 1))
    for b0 in range(0, n, 256):
        block = frames[b0:b0 + 256]
        power = np.abs(np.fft.rfft(block, axis=1)) ** 2
        for k in range(len(BANDS_HZ) - 1):
            bands[b0:b0 + len(block), k] = power[:, edges[k]:edges[k + 1]].sum(axis=1)
    total = bands.sum(axis=1) + 1e-9
    voice = bands[:, VOICE_BANDS].sum(axis=1)
    log_bands = np.log10(bands + 1e-9)
    flux = np.concatenate([[0.0], np.maximum(0, np.diff(log_bands, axis=0)).sum(axis=1)])
    return {"db": db, "voice_db": 10 * np.log10(voice + 1e-9), "voice_ratio": voice / total, "flux": flux}


# ----------------------------------------------------------------- video (keyframes only: cheap)

def _scan_frames(path, t0, duration, keyframes_only):
    vf = f"scale={VIS_W}:{VIS_H},showinfo" if keyframes_only else f"fps=1,scale={VIS_W}:{VIS_H},showinfo"
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-threads", "0"]
    if keyframes_only:
        cmd += ["-skip_frame", "nokey"]
    else:  # full decode: skip deblocking for speed, we only need 64x36 thumbnails
        cmd += ["-skip_loop_filter", "all", "-flags2", "+fast"]
    cmd += ["-ss", f"{max(0, t0):.2f}", "-t", f"{duration:.2f}", "-i", path, "-an", "-vf", vf,
            "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    times = [float(x) for x in re.findall(rb"pts_time:\s*([-\d.]+)", r.stderr)]
    size = VIS_W * VIS_H * 3
    count = min(len(times), len(r.stdout) // size)
    frames = np.frombuffer(r.stdout[: count * size], dtype=np.uint8).reshape(count, VIS_H, VIS_W, 3)
    return np.array(times[:count]), frames


def visual_features(path, t0, duration):
    """Keyframe scan: motion / scene change, flashes, colour loss, where on screen things move."""
    times, frames = _scan_frames(path, t0, duration, keyframes_only=True)
    if len(times) < max(3, duration / 12):  # too few keyframes: decode 1 frame/s instead (slower)
        times, frames = _scan_frames(path, t0, duration, keyframes_only=False)
    if len(times) < 2:
        return None
    f = frames.astype(np.float32) / 255.0
    gray = f.mean(axis=3)
    bright = gray.mean(axis=(1, 2))
    mx, mn = f.max(axis=3), f.min(axis=3)
    sat = ((mx - mn) / (mx + 1e-3)).mean(axis=(1, 2))
    diff = np.abs(np.diff(gray, axis=0))
    motion = np.concatenate([[0.0], diff.mean(axis=(1, 2))])
    cols = diff.mean(axis=1)                      # (n-1, W)
    xs = (np.arange(VIS_W) + 0.5) / VIS_W
    cx = np.concatenate([[0.5], (cols * xs).sum(axis=1) / (cols.sum(axis=1) + 1e-6)])
    desat = np.concatenate([[0.0], np.maximum(0, sat[:-1] - sat[1:])])
    flash = np.concatenate([[0.0], np.abs(np.diff(bright))])
    return {"times": t0 + times, "motion": motion, "bright": bright, "sat": sat, "desat": desat,
            "flash": flash, "cx": cx}


def _to_grid(times, values, a0, n):
    """Spread per-keyframe changes over the grid: each step gets the change measured at the next keyframe
    (the change happened somewhere in between). Avoids a sparse, spiky grid that would fake z-scores."""
    grid = np.zeros(n)
    times = np.asarray(times)
    if len(times) == 0:
        return grid
    t_grid = a0 + np.arange(n) * HOP
    idx = np.searchsorted(times, t_grid, side="left")
    ok = idx < len(times)
    grid[ok] = np.asarray(values)[idx[ok]]
    return grid


# ----------------------------------------------------------------- combine

class Scan:
    """All signals for [a0, a0 + n*HOP] of one video."""

    def __init__(self, a0, audio, visual, chat, has_chat):
        self.a0, self.audio, self.visual, self.chat, self.has_chat = a0, audio, visual, chat, has_chat
        self.n = len(audio["db"])

    def t(self, i):
        return self.a0 + i * HOP


def scan(path, a0, t1, msgs, settings):
    audio = audio_features(path, a0, t1 - a0)
    if audio is None:
        return None
    n = len(audio["db"])
    try:
        visual = visual_features(path, a0, t1 - a0)
    except Exception:
        visual = None
    chat = chat_curve(msgs, a0, n, float(settings["chat_delay_sec"]))
    return Scan(a0, audio, visual, chat, chat.sum() >= 15)


def tracks(sc):
    """z-scored evidence tracks on the HOP grid. Missing modalities are simply absent."""
    a = sc.audio
    out = {}
    out["voice"] = robust_z(smooth(a["voice_db"] - smooth(a["voice_db"], 60), 2))
    pre = _window_mean(a["db"], -int(6 / HOP), -int(1 / HOP))
    post = _window_max(a["db"], 0, int(2 / HOP))
    out["contrast"] = robust_z(smooth(post - pre, 1.5))
    out["onset"] = robust_z(smooth(a["flux"], 1.5))
    if sc.has_chat:
        rate = smooth(sc.chat, 4)
        out["chat"] = robust_z(rate - 0.5 * smooth(rate, 120))
        out["_chat_rate"] = rate / HOP
    v = sc.visual
    if v is not None:
        for key in ("motion", "flash", "desat"):
            g = _to_grid(v["times"], v[key], sc.a0, sc.n)
            out[key] = robust_z(smooth(g, 1.0)) if g.any() else np.zeros(sc.n)
    return out


def combined(tr, weights):
    keys = [k for k in weights if k in tr]
    num = sum(weights[k] * np.clip(tr[k], -1.5, 8) for k in keys)
    den = np.sqrt(sum(weights[k] ** 2 for k in keys)) or 1.0
    return num / den


CUE_TEXT = {
    "chat": "chat burst ({ratio}x normal speed)",
    "voice": "streamer's voice gets much louder / more intense",
    "contrast": "quiet moment followed by a sudden loud burst",
    "onset": "sudden sharp sound (impact, gunshot, crash?)",
    "motion": "big visual change on screen (fast action or a scene cut)",
    "flash": "bright flash or sudden fade (explosion? transition?)",
    "desat": "screen suddenly loses its colour",
}


def describe_cues(sc, tr, i, ctx_start, profile_id):
    """Readable hints near step i, times relative to ctx_start."""
    cues = []
    lo, hi = max(0, i - int(10 / HOP)), min(sc.n, i + int(10 / HOP) + 1)
    for key, text in CUE_TEXT.items():
        if key not in tr:
            continue
        seg = tr[key][lo:hi]
        j = int(np.argmax(seg))
        z = float(seg[j])
        if z < 2.0:
            continue
        t_rel = round(sc.t(lo + j) - ctx_start, 1)
        msg = text
        if key == "chat":
            rate = tr["_chat_rate"]
            ratio = rate[lo + j] / max(np.median(rate), 0.05)
            msg = text.format(ratio=f"{min(ratio, 99):.1f}")
        if key == "desat" and profile_id == "open_world":
            msg += " (in GTA often a 'Wasted'/'Busted' death screen)"
        cues.append({"t": t_rel, "kind": key, "z": round(z, 1), "text": msg})
    return sorted(cues, key=lambda c: c["t"])


def find_candidates(sc, tr, t0, t1, final, blocked_peaks, settings, profile, duration, profile_id="general"):
    """Pick distinct moments worth sending to the AI, each with a context window around it.

    No fixed-length cutting happens here: the AI decides where each clip really starts and ends.
    """
    weights = profile["weights"]
    score = combined(tr, weights)
    before, after = settings.get("context_before") or profile["context"][0], \
        settings.get("context_after") or profile["context"][1]
    valid_hi = t1 if final else t1 - after
    budget = max(2, int(round(settings["candidates_per_hour"] * (t1 - t0) / 3600.0 + 0.49)))
    spacing = int(40 / HOP)
    min_signal = float(settings["min_signal"])
    modal_keys = [k for k in weights if k in tr]

    avail = score.copy()
    for i in range(sc.n):
        t = sc.t(i)
        if t < t0 or t > valid_hi:
            avail[i] = -np.inf
    picks = []

    def take(i, reason):
        peak = sc.t(i)
        if any(abs(peak - b) < 35 for b in blocked_peaks):
            return False
        ctx_start = max(0.0, peak - before)
        ctx_end = min(duration if duration > 0 else t1, peak + after)
        modal = {k: round(float(tr[k][i]), 2) for k in modal_keys}
        picks.append({
            "peak": round(peak, 2), "ctx_start": round(ctx_start, 2), "ctx_len": round(ctx_end - ctx_start, 2),
            "signal": round(float(score[i]), 2), "modalities": modal, "nominated_by": reason,
            "cues": describe_cues(sc, tr, i, ctx_start, profile_id),
            "motion_track": _motion_track(sc, ctx_start, ctx_end),
        })
        blocked_peaks.append(peak)
        return True

    while len(picks) < budget:
        i = int(np.argmax(avail))
        if not np.isfinite(avail[i]) or avail[i] < min_signal:
            break
        strongest = max((tr[k][i] for k in modal_keys), default=0)
        lo, hi = max(0, i - spacing), min(sc.n, i + spacing)
        if strongest >= 2.2:
            take(i, "combined")
        avail[lo:hi] = -np.inf

    # diversity: one very strong single-signal moment (e.g. a silent visual fail) the mix may have missed
    for key in ("desat", "motion", "flash", "chat"):
        if key not in tr:
            continue
        z = tr[key].copy()
        for i in range(sc.n):
            if sc.t(i) < t0 or sc.t(i) > valid_hi:
                z[i] = -np.inf
        i = int(np.argmax(z))
        if np.isfinite(z[i]) and z[i] >= 4.0 and not any(abs(sc.t(i) - p["peak"]) < 40 for p in picks):
            if take(i, f"strong {key}"):
                break
    return sorted(picks, key=lambda p: p["peak"])


def _motion_track(sc, start, end):
    """[(t_rel, cx, motion)] inside [start, end] for action-focused cropping later."""
    v = sc.visual
    if v is None:
        return []
    out = []
    for t, cx, m in zip(v["times"], v["cx"], v["motion"]):
        if start <= t <= end:
            out.append([round(float(t - start), 2), round(float(cx), 3), round(float(m), 4)])
    return out


def focus_x(motion_track, t_in, t_out):
    """Average horizontal position of on-screen action between t_in and t_out (0..1)."""
    pts = [(cx, m) for t, cx, m in motion_track if t_in <= t <= t_out and m > 0]
    if not pts:
        return 0.5
    w = np.array([m for _, m in pts])
    x = np.array([cx for cx, _ in pts])
    val = float((x * w).sum() / (w.sum() + 1e-9))
    return float(np.clip(0.5 + (val - 0.5) * 0.8, 0.15, 0.85))  # damped: never hug the edge


def waveform(sc, step_sec=2.0):
    """Downsampled loudness for the project timeline: [[t, db], ...]."""
    k = max(1, int(step_sec / HOP))
    db = sc.audio["db"]
    return [[round(sc.t(i), 1), round(float(db[i:i + k].max()), 1)] for i in range(0, sc.n, k)]
