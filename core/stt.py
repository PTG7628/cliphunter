"""Speech-to-text: faster-whisper on the PC, or Groq's free cloud Whisper (word timestamps)."""
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import db
from .media import run

_whisper = None
_whisper_name = None
_whisper_lock = threading.Lock()
_whisper_failed_at = 0.0


# ----------------------------------------------------------------- transcription

def _model(name):
    global _whisper, _whisper_name, _whisper_failed_at
    if _whisper is not None and _whisper_name == name:
        return _whisper
    if time.time() - _whisper_failed_at < 600:
        raise RuntimeError("speech model unavailable (will retry in a few minutes)")
    from faster_whisper import WhisperModel  # imported lazily: big library
    db.log(f"Loading speech model '{name}' (first time downloads it)...")
    try:
        _whisper = WhisperModel(name, device="auto", compute_type="int8")
    except Exception:
        _whisper_failed_at = time.time()
        raise
    _whisper_name = name
    return _whisper


GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_cloud_note_logged = False


def _groq_key(settings):
    if settings.get("stt_key"):
        return settings["stt_key"].strip()
    if settings.get("ai_provider") == "groq" or "api.groq.com" in settings.get("ai_base_url", ""):
        return settings.get("ai_key", "").strip()
    return ""


def _groq_transcribe(audio_path, lang, key):
    """Groq's free cloud Whisper (large-v3-turbo) with word timestamps."""
    boundary = uuid.uuid4().hex
    fields = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json",
              "timestamp_granularities[]": "word", "temperature": "0"}
    if lang not in ("", "auto"):
        fields["language"] = lang
    body = b""
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    with open(audio_path, "rb") as f:
        audio = f.read()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.mp3"\r\n'
             f"Content-Type: audio/mpeg\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}",
               "User-Agent": "ClipHunter/1.0"}
    for attempt in range(3):
        try:
            req = urllib.request.Request(GROQ_STT_URL, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                db.log("Groq transcription rate limit, waiting 20s...", "warn")
                time.sleep(20)
                continue
            raise RuntimeError(f"Groq transcription error {e.code}: {e.read().decode(errors='ignore')[:200]}")
    words = data.get("words") or []
    if not words:  # some responses only have segments: spread words evenly inside each segment
        for seg in data.get("segments") or []:
            parts = seg.get("text", "").split()
            if not parts:
                continue
            step = (seg["end"] - seg["start"]) / len(parts)
            for i, w in enumerate(parts):
                words.append({"word": w, "start": seg["start"] + i * step, "end": seg["start"] + (i + 1) * step})
    return [[round(float(w["start"]), 2), round(float(w["end"]), 2), str(w["word"]).strip()]
            for w in words if str(w.get("word", "")).strip()]


def transcribe(path, model_name, lang, settings=None):
    """Return list of [start, end, word]. Uses the PC (faster-whisper) or Groq cloud, per settings."""
    from . import config
    s = settings or config.load()
    mode = s.get("transcription", "auto")
    key = _groq_key(s)
    global _cloud_note_logged

    if mode == "groq" or (mode == "auto" and key and _local_broken()):
        if not key:
            db.log("Cloud transcription needs a Groq key (Settings > Captions)", "warn")
            return []
        return _cloud(path, lang, key)

    words = _local_transcribe(path, model_name, lang)
    if words is None and mode == "auto" and key:
        if not _cloud_note_logged:
            db.log("Speech model doesn't work on this PC; using Groq cloud transcription instead")
            _cloud_note_logged = True
        return _cloud(path, lang, key)
    if words is None and mode == "auto" and not key and not _cloud_note_logged:
        db.log("No transcript: add a free Groq key in Settings > Captions to transcribe in the cloud", "warn")
        _cloud_note_logged = True
    return words or []


def _local_broken():
    return _whisper is None and time.time() - _whisper_failed_at < 600


def _cloud(path, lang, key):
    audio = path + ".mp3"
    try:
        run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", audio])
        t = time.time()
        words = _groq_transcribe(audio, lang, key)
        db.metric("stt", True, 0, 0, time.time() - t)
        return words
    except Exception as e:
        db.metric("stt", False, 0, 0, 0, str(e)[:80])
        db.log(f"Cloud transcription failed: {e}", "warn")
        return []
    finally:
        if os.path.exists(audio):
            os.remove(audio)


def _local_transcribe(path, model_name, lang):
    """faster-whisper on the PC. Returns None if it can't run here."""
    global _whisper_failed_at
    wav = path + ".wav"
    try:
        run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", wav])
        with _whisper_lock:
            model = _model(model_name)
            segments, _ = model.transcribe(wav, language=None if lang in ("", "auto") else lang,
                                           word_timestamps=True, vad_filter=True)
            words = []
            for seg in segments:
                for w in seg.words or []:
                    if w.word.strip():
                        words.append([round(w.start, 2), round(w.end, 2), w.word.strip()])
        return words
    except ImportError:
        _whisper_failed_at = time.time()
        return None
    except Exception as e:
        if "unavailable" not in str(e):
            db.log(f"PC speech model failed: {str(e)[:200]}", "warn")
        _whisper_failed_at = max(_whisper_failed_at, time.time())
        return None
    finally:
        if os.path.exists(wav):
            os.remove(wav)


