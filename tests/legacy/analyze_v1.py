"""Find hype moments from chat activity + audio loudness."""
import json
import re
import subprocess

import numpy as np

HOP = 0.5          # seconds per analysis step
SAMPLE_RATE = 16000

HYPE_RE = re.compile(
    r"(KEKW|OMEGALUL|LUL|LMAO+|LOL+|POG|PogU|Pog|W+\b|NO WAY|NOWAY|WTF|OMG|CLIP|\?\?\?|!!!|💀|😂|🤣|"
    r"HOLY|BRO+|YOOO+|AINTNOWAY|ICANT|monkaS|Aware|EZ|DEAD|HAHA+)",
    re.IGNORECASE,
)


def audio_db(path, t0, duration):
    """Loudness (dB) every HOP seconds for [t0, t0+duration] of the file."""
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0, t0):.2f}", "-t", f"{duration:.2f}", "-i", path,
           "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(SAMPLE_RATE * HOP)
    n = len(samples) // hop
    if n == 0:
        return np.zeros(0)
    frames = samples[: n * hop].reshape(n, hop)
    return 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1) + 1e-10))


def load_chat(recording):
    """Return list of (seconds_into_video, text) for a recording's chat log."""
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
    except FileNotFoundError:
        return []
    return msgs


def hype_weight(text):
    w = 1.0
    if HYPE_RE.search(text or ""):
        w += 1.0
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        w += 0.5
    return w


def _smooth(x, seconds):
    """Moving average that stays correct at the edges (no zero padding)."""
    k = max(1, min(len(x), int(seconds / HOP)))
    if len(x) == 0:
        return x
    num = np.convolve(x, np.ones(k), mode="same")
    den = np.convolve(np.ones(len(x)), np.ones(k), mode="same")
    return num / den


def _robust_z(x):
    if len(x) == 0:
        return x
    med = np.median(x)
    mad = np.median(np.abs(x - med)) * 1.4826
    scale = max(mad, np.std(x) * 0.5, 1e-3)
    return (x - med) / scale


def chat_curve(msgs, t0, n, delay):
    counts = np.zeros(n)
    for t, text in msgs:
        i = int((t - delay - t0) / HOP)
        if 0 <= i < n:
            counts[i] += hype_weight(text)
    return counts


def find_candidates(path, t0, t1, msgs, settings, blocked, final):
    """Analyse [t0, t1] of the video and return candidate moments.

    blocked: list of (start, end) ranges already clipped.
    Returns list of dicts {start, length, peak, signal, chat_rate}.
    """
    clip_len = float(settings["clip_length"])
    context = 90.0                       # extra seconds before t0 for a stable baseline
    a0 = max(0.0, t0 - context)
    db = audio_db(path, a0, t1 - a0)
    n = len(db)
    if n < int(clip_len / HOP):
        return []

    audio_spike = db - _smooth(db, 60)
    audio_z = _robust_z(_smooth(audio_spike, 3))

    chat = chat_curve(msgs, a0, n, float(settings["chat_delay_sec"]))
    has_chat = chat.sum() >= 15
    if has_chat:
        chat_rate = _smooth(chat, 4)
        chat_z = _robust_z(chat_rate - _smooth(chat_rate, 120) * 0.5)
        score = 0.65 * chat_z + 0.35 * audio_z
    else:
        chat_rate = np.zeros(n)
        score = audio_z

    # only accept peaks inside the new part of the window
    lo = int((t0 - a0) / HOP)
    tail = 0.0 if final else clip_len * 0.35
    hi = int((t1 - tail - a0) / HOP)
    valid = np.full(n, -np.inf)
    if hi > lo:
        valid[lo:hi] = score[lo:hi]

    minutes = (t1 - t0) / 60.0
    max_n = max(1, int(round(settings["max_clips_per_hour"] * minutes / 60.0 + 0.49)))
    picks = []
    steps = int(clip_len / HOP)
    while len(picks) < max_n * 2:      # over-pick; the AI judge throws weak ones away
        i = int(np.argmax(valid))
        if not np.isfinite(valid[i]) or valid[i] < float(settings["min_signal"]):
            break
        peak = a0 + i * HOP
        start = max(0.0, peak - clip_len * 0.65)
        end = start + clip_len
        lo_b, hi_b = max(0, i - steps), min(n, i + steps)
        valid[lo_b:hi_b] = -np.inf
        if any(start < b_end and end > b_start for b_start, b_end in blocked):
            continue
        picks.append({
            "start": round(start, 2), "length": clip_len, "peak": round(peak, 2),
            "signal": round(float(score[i]), 2),
            "chat_rate": round(float(chat_rate[i]) / HOP, 2),
            "chat_normal": round(float(np.median(chat_rate)) / HOP, 2) if has_chat else 0.0,
        })
        blocked.append((start, end))
    return picks


def chat_lines(msgs, start, end, delay, limit=70):
    lines = [text for t, text in msgs if start + delay - 2 <= t <= end + delay]
    if len(lines) > limit:
        step = len(lines) / limit
        lines = [lines[int(i * step)] for i in range(limit)]
    return lines
