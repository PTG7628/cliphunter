"""Settings (saved to data/settings.json) and folder locations."""
import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("CLIPHUNTER_DATA") or os.path.join(BASE_DIR, "data")
REC_DIR = os.path.join(DATA_DIR, "recordings")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
RAW_DIR = os.path.join(DATA_DIR, "raw_segments")
CLIP_DIR = os.path.join(DATA_DIR, "clips")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
APPROVED_DIR = os.environ.get("CLIPHUNTER_APPROVED") or os.path.join(BASE_DIR, "APPROVED_CLIPS")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
DB_PATH = os.path.join(DATA_DIR, "cliphunter.db")

for _d in (DATA_DIR, REC_DIR, UPLOAD_DIR, RAW_DIR, CLIP_DIR, THUMB_DIR, CACHE_DIR, APPROVED_DIR):
    os.makedirs(_d, exist_ok=True)

# Free / open-source AI providers. All speak the OpenAI "chat completions" format.
PROVIDERS = {
    "none": {"label": "No AI (signals only, clips stay unverified)", "base_url": "", "model": "",
             "vision_model": "", "needs_key": False},
    "meta": {"label": "Meta Muse (Meta Model API key)", "base_url": "https://api.meta.ai/v1",
             "model": "muse-spark-1.1", "vision_model": "", "needs_key": True, "signup": "https://dev.meta.ai"},
    "groq": {"label": "Groq (free key, very fast)", "base_url": "https://api.groq.com/openai/v1",
             "model": "openai/gpt-oss-120b", "vision_model": "meta-models/muse-spark-open", "needs_key": True,
             "signup": "https://console.groq.com/keys"},
    "gemini": {"label": "Google Gemini (free key, sees images)",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "model": "gemini-2.5-flash", "vision_model": "", "needs_key": True,
               "signup": "https://aistudio.google.com/apikey"},
    "openrouter": {"label": "OpenRouter free models", "base_url": "https://openrouter.ai/api/v1",
                   "model": "openai/gpt-oss-120b:free", "vision_model": "", "needs_key": True,
                   "signup": "https://openrouter.ai/keys"},
    "ollama": {"label": "Ollama (open-source AI on your own PC, no key)", "base_url": "http://localhost:11434/v1",
               "model": "qwen2.5:3b", "vision_model": "", "needs_key": False, "signup": "https://ollama.com/download"},
    "custom": {"label": "Custom (any OpenAI-compatible API)", "base_url": "", "model": "", "vision_model": "",
               "needs_key": True},
}

DEFAULTS = {
    # AI
    "ai_provider": "none",
    "ai_base_url": "",
    "ai_key": "",
    "ai_model": "",
    "vision_mode": "auto",        # auto = send frames when the model can see; off = text only
    "vision_model": "",           # optional separate image-capable model on the same provider
    "ai_min_gap_sec": 3,          # pause between AI calls (free tiers have per-minute limits)
    "hook_language": "English",   # English / Roman Urdu / Hinglish
    "game_context": "GTA 6 (Grand Theft Auto VI)",
    "default_profile": "auto",    # game profile id, or auto (guess from the video title)
    # Quality gate (V2)
    "export_threshold": 85,       # >= this: "Top pick", rendered and ready to post
    "review_threshold": 70,       # >= this: rendered for manual review; below: rejected
    "max_clips_per_video": 5,     # a limit, not a target
    "second_pass": True,          # independent AI re-check of every clip that passes stage 1
    "keep_rejected_media": False,
    "learning": True,             # use your posted-clip results to nudge rankings (max +-5)
    # Candidate discovery
    "candidates_per_hour": 14,    # how many moments per hour of video are sent to the AI at most
    "min_signal": 1.6,            # how unusual a moment must be to be looked at (lower = more)
    "chat_delay_sec": 7,
    "chunk_minutes": 20,          # long videos are analysed in overlapping chunks
    "chunk_overlap_sec": 90,
    "context_before": 0,          # seconds of context the AI sees before a flagged moment (0 = game profile)
    "context_after": 0,
    "min_clip_sec": 10,
    "max_clip_sec": 60,
    # Live watching
    "check_interval_sec": 120,
    "process_every_min": 10,
    "max_live_recordings": 2,
    "record_quality": "720p60,720p,best",
    "keep_recordings": False,
    # Editing defaults
    "aspect": "9:16",             # 9:16 / 1:1 / 16:9
    "layout": "auto",             # auto / facecam / blur / crop / action
    "zoom": 1.35,
    "auto_webcam": True,
    "captions": True,
    "caption_style": "bold",      # bold / clean / neon / minimal
    "caption_pos": "auto",        # auto / top / middle / bottom
    "caption_language": "auto",
    "words_per_caption": 3,
    "font": "Arial Black",
    "dead_air": True,
    "export_quality": "high",     # high / balanced / small
    # Transcription
    "whisper_model": "small",
    "transcription": "auto",      # auto (PC, then Groq cloud if PC fails) / local / groq
    "stt_key": "",
}

_lock = threading.Lock()
_cache = None


def load():
    global _cache
    with _lock:
        if _cache is None:
            data = dict(DEFAULTS)
            if os.path.exists(SETTINGS_PATH):
                try:
                    with open(SETTINGS_PATH, encoding="utf-8") as f:
                        saved = json.load(f)
                    data.update({k: v for k, v in saved.items() if k in DEFAULTS})
                except Exception:
                    pass
            _cache = data
        return dict(_cache)


def save(updates):
    global _cache
    current = load()
    for key, value in updates.items():
        if key not in DEFAULTS:
            continue
        default = DEFAULTS[key]
        try:
            if isinstance(default, bool):
                value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "on", "yes")
            elif isinstance(default, int):
                value = int(float(value))
            elif isinstance(default, float):
                value = float(value)
            else:
                value = str(value).strip()
        except (TypeError, ValueError):
            continue
        current[key] = value
    if current["review_threshold"] > current["export_threshold"]:
        current["review_threshold"] = current["export_threshold"]
    with _lock:
        _cache = current
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    return dict(current)


def reset_cache():
    global _cache
    with _lock:
        _cache = None


def get(key):
    return load().get(key, DEFAULTS.get(key))
