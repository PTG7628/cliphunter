"""AI editor (stage 1), independent reviewer (stage 2) and hook writer.

Works with any OpenAI-compatible API (Groq, Gemini, Meta Muse, OpenRouter, Ollama...). Frames are sent as
images when the model can see; otherwise the AI is told plainly that it cannot see the video.
"""
import base64
import json
import re
import threading
import time
import urllib.error
import urllib.request

from . import config, db, profiles

_lock = threading.Lock()
_last_call = 0.0
_vision_broken = {}          # model -> reason (detected at runtime)

RUBRIC = {"significance": 25, "hook": 20, "reaction": 20, "retention": 15, "standalone": 10, "visual": 10}
RUBRIC_LABELS = {
    "significance": "Gameplay significance / comedic payoff",
    "hook": "Hook strength",
    "reaction": "Streamer reaction & emotional impact",
    "retention": "Retention potential",
    "standalone": "Standalone understanding",
    "visual": "Visual clarity & editing potential",
}
REJECT_REASONS = [
    "ordinary gameplay", "routine kill/action", "random screaming without context", "walking/driving/waiting",
    "menus/inventory/loading", "repetitive conversation", "no clear setup or payoff", "weak opening",
    "incomplete joke", "duplicate", "unrelated dialogue", "poor audio/visuals", "would distort the event",
    "story spoiler", "cannot verify (not enough evidence)",
]

SYSTEM_EDITOR = (
    "You are a strict senior highlight editor for gaming livestreams. You pick moments that genuinely work as "
    "standalone YouTube Shorts / TikTok / Reels clips and you decide exactly where they start and end. "
    "Most moments are ordinary and must be rejected. You never invent events, reactions or chat activity: you "
    "only describe what the transcript, chat and images actually show. You answer with one JSON object only."
)
SYSTEM_REVIEWER = (
    "You are an independent, skeptical second reviewer. Another editor proposed a clip. Your job is to verify it "
    "with fresh eyes and reject it if it does not hold up. You did not choose this clip and have no reason to "
    "defend it. You never invent anything that is not in the evidence. You answer with one JSON object only."
)

LANG_RULES = {
    "English": "Write hook, title and caption in casual English.",
    "Roman Urdu": "Write hook, title and caption in Roman Urdu (Urdu in English letters, e.g. 'Bhai ye kya ho "
                  "gaya'), the way Pakistani gamers write on TikTok.",
    "Hinglish": "Write hook, title and caption in Hinglish (Hindi + English in Latin letters).",
}


class VisionUnsupported(Exception):
    pass


# ----------------------------------------------------------------- transport

def enabled(settings=None):
    s = settings or config.load()
    return s["ai_provider"] != "none" and bool(s["ai_base_url"]) and bool(s["ai_model"])


def vision_model(settings):
    return settings.get("vision_model") or settings["ai_model"]


def vision_on(settings):
    return (enabled(settings) and settings.get("vision_mode", "auto") != "off"
            and vision_model(settings) not in _vision_broken)


def vision_status(settings=None):
    s = settings or config.load()
    if not enabled(s):
        return {"on": False, "text": "AI off"}
    if s.get("vision_mode") == "off":
        return {"on": False, "text": "Vision turned off in Settings"}
    m = vision_model(s)
    if m in _vision_broken:
        return {"on": False, "text": f"{m} can't read images: set a vision model in Settings"}
    return {"on": True, "text": f"Sends frames to {m}"}


def _request(base_url, key, path, payload=None, timeout=120):
    url = base_url.rstrip("/") + path
    headers = {"Content-Type": "application/json", "User-Agent": "ClipHunter/2.0"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if "openrouter.ai" in base_url:
        headers["HTTP-Referer"] = "http://localhost"
        headers["X-Title"] = "ClipHunter"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def chat(messages, settings=None, max_tokens=900, kind="chat", model=None, json_mode=False):
    """One chat completion. Returns the reply text. Tracks usage in the metrics table."""
    s = settings or config.load()
    global _last_call
    images = sum(1 for m in messages if isinstance(m.get("content"), list)
                 for part in m["content"] if part.get("type") == "image_url")
    started = time.time()
    with _lock:  # one AI call at a time, spaced out for free-tier limits
        wait = float(s["ai_min_gap_sec"]) - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        payload = {"model": model or s["ai_model"], "messages": messages, "temperature": 0.3,
                   "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        for attempt in range(5):
            try:
                resp = _request(s["ai_base_url"], s["ai_key"], "/chat/completions", payload)
                _last_call = time.time()
                usage = resp.get("usage") or {}
                text = resp["choices"][0]["message"].get("content") or ""
                db.metric(kind, True, usage.get("total_tokens", 0), images, time.time() - started)
                return text
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="ignore")[:400]
                low = body.lower()
                if e.code == 429 and attempt < 4:
                    retry = e.headers.get("retry-after")
                    pause = min(60.0, float(retry)) if retry and retry.replace(".", "").isdigit() else 20.0
                    db.log(f"AI rate limit hit, waiting {pause:.0f}s...", "warn")
                    time.sleep(pause)
                    continue
                if e.code in (400, 422) and "response_format" in payload and (
                        "response_format" in low or "json" in low):
                    payload.pop("response_format")
                    continue
                if e.code in (400, 422) and "max_tokens" in low and "max_tokens" in payload:
                    payload.pop("max_tokens")
                    continue
                if images and e.code in (400, 404, 415, 422) and any(
                        w in low for w in ("image", "vision", "multimodal", "content type", "image_url",
                                           "does not support", "unsupported")):
                    db.metric(kind, False, 0, images, time.time() - started, "vision unsupported")
                    raise VisionUnsupported(body)
                db.metric(kind, False, 0, images, time.time() - started, f"HTTP {e.code}")
                raise RuntimeError(f"AI error {e.code}: {body[:250]}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 2:
                    time.sleep(5)
                    continue
                db.metric(kind, False, 0, images, time.time() - started, "network")
                raise RuntimeError(f"AI not reachable: {e}")
        db.metric(kind, False, 0, images, time.time() - started, "gave up")
        raise RuntimeError("AI kept rate-limiting")


def _parse_json(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON in AI reply")
    return json.loads(text[start:end + 1])


def _content(prompt, images):
    if not images:
        return prompt
    parts = [{"type": "text", "text": prompt}]
    for img in images:
        b64 = img if isinstance(img, str) else base64.b64encode(img).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return parts


def _ask(system, prompt, images, s, kind, max_tokens=2500):
    """Ask with images if possible; if the model can't see, retry text-only and remember that."""
    model = vision_model(s) if images else s["ai_model"]
    try:
        reply = chat([{"role": "system", "content": system}, {"role": "user", "content": _content(prompt, images)}],
                     s, max_tokens=max_tokens, kind=kind, model=model, json_mode=True)
        return _parse_json(reply), bool(images)
    except VisionUnsupported:
        _vision_broken[model] = "no image input"
        db.log(f"Model '{model}' can't read images. Judging without frames. Set a vision model in Settings.",
               "warn")
        prompt = prompt.replace("[[IMAGES]]", "")
        reply = chat([{"role": "system", "content": system}, {"role": "user", "content": prompt + NO_IMAGES_NOTE}],
                     s, max_tokens=max_tokens, kind=kind, json_mode=True)
        return _parse_json(reply), False
    except ValueError:  # bad JSON: one retry, stricter
        reply = chat([{"role": "system", "content": system},
                      {"role": "user", "content": _content(prompt + "\nReturn ONLY the JSON object.", images)}],
                     s, max_tokens=max_tokens, kind=kind, model=model, json_mode=False)
        return _parse_json(reply), bool(images)


NO_IMAGES_NOTE = ("\nIMPORTANT: you were NOT given any images, so you cannot see the video. Do not claim visual "
                  "events; score 'visual' 5 or less and lower your confidence.")


# ----------------------------------------------------------------- formatting evidence

def transcript_lines(words, start=0.0, end=None, max_chars=3000):
    """[(t, text)] lines from word timestamps, relative to `start`."""
    lines, cur, cur_t, last_end = [], [], None, None
    for ws, we, w in words:
        if ws < start or (end is not None and ws > end):
            continue
        if cur and (ws - last_end > 0.8 or len(cur) >= 12):
            lines.append((cur_t, " ".join(cur)))
            cur = []
        if not cur:
            cur_t = round(ws - start, 1)
        cur.append(w)
        last_end = we
    if cur:
        lines.append((cur_t, " ".join(cur)))
    out, size = [], 0
    for t, text in lines:
        size += len(text) + 8
        if size > max_chars:
            out.append((t, "..."))
            break
        out.append((t, text))
    return out


def _fmt_lines(rows, empty):
    return "\n".join(f"[{t:.1f}] {text}" for t, text in rows) if rows else empty


def _clamp_scores(raw):
    out = {}
    for k, mx in RUBRIC.items():
        try:
            out[k] = max(0, min(mx, int(round(float((raw or {}).get(k, 0))))))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def _num(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fix_bounds(d, ctx_len, peak_rel, s):
    """Make the AI's timestamps sane: inside the window, ordered, between min and max clip length."""
    mn, mx = float(s["min_clip_sec"]), float(s["max_clip_sec"])
    action = min(max(_num(d.get("key_action"), peak_rel), 0), ctx_len)
    start = min(max(_num(d.get("setup_start"), action - 12), 0), action)
    payoff = min(max(_num(d.get("payoff"), action + 3), action), ctx_len)
    end = min(max(_num(d.get("end"), payoff + 3), payoff), ctx_len)
    reaction = d.get("reaction")
    reaction = None if reaction in (None, "", "null") else min(max(_num(reaction, payoff), 0), ctx_len)
    if end - start > mx:                 # too long: keep the payoff, drop the earliest setup
        start = max(start, end - mx)
        if action < start:
            end = min(ctx_len, action + mx * 0.5)
            start = max(0, end - mx)
    if end - start < mn:                 # too short: grow around the action
        need = mn - (end - start)
        start = max(0.0, start - need * 0.6)
        end = min(ctx_len, end + need * 0.4)
        if end - start < mn:
            start = max(0.0, end - mn)
            end = min(ctx_len, start + mn)
    return {"setup_start": round(start, 2), "key_action": round(action, 2),
            "reaction": None if reaction is None else round(reaction, 2), "payoff": round(payoff, 2),
            "end": round(end, 2)}


def _pct(v):
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _strs(v, limit=6, size=160):
    if isinstance(v, str):
        v = [v]
    return [str(x).strip()[:size] for x in (v or []) if str(x).strip()][:limit]


# ----------------------------------------------------------------- stage 1: editor

def analyze_moment(ev, settings=None):
    """ev: dict(source_name, title, profile_id, ctx_len, peak_rel, cues, words, chat, images, grid_times,
    peak_frame_time, stream_kind, insights). Returns a validated analysis dict."""
    s = settings or config.load()
    prof = profiles.get(ev["profile_id"])
    cats = prof["categories"]
    words = ev.get("words") or []
    chat_rows = ev.get("chat") or []
    images = ev.get("images") or []
    has_visual = bool(images)

    cue_txt = "\n".join(f"- t={c['t']:.1f}s: {c['text']}" for c in ev.get("cues", [])) or "- (none)"
    img_txt = ""
    if has_visual:
        times = ", ".join(f"{t:.0f}" for t in ev.get("grid_times", []))
        img_txt = (f"[[IMAGES]]IMAGES: Image 1 is a grid of frames read left-to-right, top-to-bottom, taken at t = "
                   f"{times} s. Image 2 is a larger frame at t = {ev.get('peak_frame_time', ev['peak_rel']):.1f} s.")
    prompt = f"""GAME PROFILE: {prof['name']} ({s['game_context']})
What makes a highlight here: {prof['focus']}
Usually reject: {prof['reject']}
Highlight categories: {"; ".join(f"{k} = {v}" for k, v in cats.items())}
CHANNEL: {ev.get('source_name', '')}   VIDEO TITLE: {ev.get('title') or 'unknown'}   TYPE: {ev.get('stream_kind', 'stream')}

This is a {ev['ctx_len']:.0f}-second window. All times are seconds from the start of this window (0 to {ev['ctx_len']:.0f}).
An automatic detector flagged something around t={ev['peak_rel']:.0f}s. That flag is only a hint (audio, chat or
screen change) and is NOT proof that anything interesting happened.

AUTOMATIC SIGNAL HINTS (may be wrong):
{cue_txt}

TRANSCRIPT (streamer mic, auto-transcribed, may contain errors):
{_fmt_lines(transcript_lines(words), "(no speech was transcribed)")}

CHAT (viewer messages, times already shifted to line up with the video):
{_fmt_lines(chat_rows, "(no chat data)")}

{img_txt if has_visual else "NO IMAGES: you cannot see the video."}
{("YOUR PAST RESULTS (real views of clips you posted):" + chr(10) + ev['insights']) if ev.get('insights') else ""}

TASK: decide if this window contains a genuinely entertaining, standalone short-form highlight, and if so
exactly where the clip should start and end.

RULES
- Quality over quantity. Rejecting is normal and expected; most windows are ordinary.
- A highlight must be impressive, surprising, funny, emotional, or tell a short story with setup and payoff.
- Reject: {", ".join(REJECT_REASONS[:13])}.
- Never invent events, reactions or chat. Use only the transcript, chat and images. Loud audio or chat spam
  alone is not proof. A laugh is not automatically funny to an outsider.
- Boundaries (seconds in this window): setup_start = where a new viewer must start to understand;
  key_action = the main event; reaction = the streamer's reaction (null if none); payoff = punchline/result;
  end = just after the payoff/reaction. Do not cut the reaction off and do not add dead time.
  Clip length {s['min_clip_sec']}-{s['max_clip_sec']} s. Sudden funny reactions: short. Clutches and stories: keep the needed setup.
- Score strictly with this rubric (most clips should land below 70):
  significance 0-25 (gameplay significance or comedic payoff), hook 0-20 (first 2 seconds from setup_start),
  reaction 0-20 (observable streamer reaction; 0-5 if none is observable), retention 0-15 (will people watch to
  the end), standalone 0-10 (understandable without the stream), visual 0-10 (clarity / editing potential).
  Each justification must cite specific observed moments with their times, or say what could not be observed.
- hook: max 7 words, creates curiosity, no emojis, not misleading; don't reveal the payoff if suspense matters.
- {LANG_RULES.get(s['hook_language'], LANG_RULES['English'])}

Return ONLY this JSON:
{{"is_highlight": true, "category": "<one of: {", ".join(cats)} | none>",
 "event_summary": "what actually happens, only what is observed",
 "setup_start": 0, "key_action": 0, "reaction": null, "payoff": 0, "end": 0,
 "scores": {{"significance": 0, "hook": 0, "reaction": 0, "retention": 0, "standalone": 0, "visual": 0}},
 "justification": {{"significance": "", "hook": "", "reaction": "", "retention": "", "standalone": "", "visual": ""}},
 "weaknesses": [""], "rejection_reasons": [""], "emphasis_words": [""],
 "hook": "", "title": "", "caption": "", "views_potential": 0, "likes_potential": 0}}"""

    data, used_vision = _ask(SYSTEM_EDITOR, prompt.replace("[[IMAGES]]", ""), images, s, "analyze")
    scores = _clamp_scores(data.get("scores"))
    if not used_vision:
        scores["visual"] = min(scores["visual"], 5)
    if not words and not chat_rows and not used_vision:
        # nothing to verify against: never let this through as a confident pick
        for k in scores:
            scores[k] = min(scores[k], int(RUBRIC[k] * 0.4))
    category = str(data.get("category") or "none").strip().lower()
    if category not in cats:
        category = next((c for c in cats if c in category), "none")
    just = data.get("justification") or {}
    return {
        "is_highlight": bool(data.get("is_highlight")) and category != "none",
        "category": category,
        "event_summary": str(data.get("event_summary", ""))[:400],
        "bounds": fix_bounds(data, ev["ctx_len"], ev["peak_rel"], s),
        "scores": scores,
        "total": sum(scores.values()),
        "justification": {k: str(just.get(k, ""))[:300] for k in RUBRIC},
        "weaknesses": _strs(data.get("weaknesses")),
        "rejection_reasons": _strs(data.get("rejection_reasons")),
        "emphasis_words": _strs(data.get("emphasis_words"), 8, 30),
        "hook": str(data.get("hook", "")).strip()[:80],
        "title": str(data.get("title", "")).strip()[:120],
        "caption": str(data.get("caption", "")).strip()[:400],
        "views_potential": _pct(data.get("views_potential")),
        "likes_potential": _pct(data.get("likes_potential")),
        "used_vision": used_vision,
    }


# ----------------------------------------------------------------- stage 2: independent reviewer

def review_moment(ev, claim, settings=None):
    """ev: dict(profile_id, clip_len, words (relative to clip start), chat, images, grid_times).
    claim: stage-1 category + event summary. Returns verdict dict."""
    s = settings or config.load()
    prof = profiles.get(ev["profile_id"])
    images = ev.get("images") or []
    img_txt = ""
    if images:
        times = ", ".join(f"{t:.0f}" for t in ev.get("grid_times", []))
        img_txt = (f"IMAGES: Image 1 is a grid of frames across the clip (left-to-right, top-to-bottom) at t = {times} s. "
                   f"Image 2 is the very first frame (the opening viewers see).")
    prompt = f"""GAME PROFILE: {prof['name']} ({s['game_context']}). Usually not clip-worthy: {prof['reject']}.

PROPOSED CLIP ({ev['clip_len']:.0f} s long, times are seconds from the clip's first frame)
Claimed category: {claim.get('category')}
Claimed event: {claim.get('event_summary')}

TRANSCRIPT inside the clip:
{_fmt_lines(transcript_lines(ev.get('words') or []), "(no speech)")}

CHAT inside the clip:
{_fmt_lines(ev.get('chat') or [], "(no chat data)")}

{img_txt or "NO IMAGES: you cannot see the video."}

Check, with fresh eyes:
1. Is the claimed event actually visible or audible in this evidence? (If you can't verify it, say so.)
2. Does the opening create interest within ~2 seconds?
3. Does the clip end on the payoff/reaction (not cut off, no long tail)?
4. Would someone who never saw the stream understand and enjoy it?
5. Is it genuinely impressive/funny/surprising, or just ordinary gameplay, noise or chat spam?
Re-score with the rubric: significance 0-25, hook 0-20, reaction 0-20, retention 0-15, standalone 0-10, visual 0-10.
You may suggest small boundary fixes in seconds (negative start = start earlier; positive end = end later), max 6 s.
verdict: "export" only for clips you'd confidently post; "review" if borderline; "reject" if it fails.

Return ONLY JSON:
{{"verified": true, "evidence": "what you can actually observe", "opening_ok": true, "payoff_ok": true,
 "standalone_ok": true, "scores": {{"significance": 0, "hook": 0, "reaction": 0, "retention": 0, "standalone": 0, "visual": 0}},
 "verdict": "export|review|reject", "issues": [""], "notes": "", "trim": {{"start": 0, "end": 0}}}}"""
    data, used_vision = _ask(SYSTEM_REVIEWER, prompt, images, s, "review")
    scores = _clamp_scores(data.get("scores"))
    if not used_vision:
        scores["visual"] = min(scores["visual"], 5)
    trim = data.get("trim") or {}
    verdict = str(data.get("verdict", "review")).lower()
    if verdict not in ("export", "review", "reject"):
        verdict = "review"
    return {
        "verified": bool(data.get("verified")),
        "evidence": str(data.get("evidence", ""))[:300],
        "opening_ok": bool(data.get("opening_ok")),
        "payoff_ok": bool(data.get("payoff_ok")),
        "standalone_ok": bool(data.get("standalone_ok")),
        "scores": scores,
        "total": sum(scores.values()),
        "verdict": verdict,
        "issues": _strs(data.get("issues")),
        "notes": str(data.get("notes", ""))[:300],
        "trim": {"start": max(-6.0, min(6.0, _num(trim.get("start"), 0))),
                 "end": max(-6.0, min(6.0, _num(trim.get("end"), 0)))},
        "used_vision": used_vision,
    }


# ----------------------------------------------------------------- hooks + tests

def new_hooks(clip, settings=None):
    s = settings or config.load()
    lang_rule = LANG_RULES.get(s["hook_language"], LANG_RULES["English"])
    summary = (clip.get("analysis_json") or {}).get("event_summary", "") if isinstance(clip.get("analysis_json"),
                                                                                        dict) else ""
    prompt = (f"Game: {s['game_context']}. Streamer: {clip['source_name']}.\n"
              f"What happens: {summary}\nClip transcript: \"\"\"{(clip.get('transcript') or '')[:2000]}\"\"\"\n"
              f"Current hook: {clip.get('hook')}\n\n"
              f"Write 5 different scroll-stopping on-screen hooks (max 7 words each, no emojis, no spoilers, not "
              f"misleading). {lang_rule}\nAnswer ONLY with JSON: {{\"hooks\": [\"...\"]}}")
    data = _parse_json(chat([{"role": "system", "content": SYSTEM_EDITOR}, {"role": "user", "content": prompt}], s,
                            kind="hooks", json_mode=True))
    return [str(h).strip() for h in data.get("hooks", []) if str(h).strip()][:5]


def test(base_url, key, model, vision_model_id=""):
    """Check a provider: list models, send a tiny request, and check image input."""
    result = {"ok": False, "models": [], "message": "", "vision": None}
    try:
        data = _request(base_url, key, "/models", timeout=20)
        result["models"] = sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))[:300]
    except Exception as e:
        result["message"] = f"Couldn't list models ({e}). "
    if not model:
        result["message"] += "Pick a model and test again."
        return result
    s = dict(config.load(), ai_base_url=base_url, ai_key=key, ai_model=model, ai_min_gap_sec=0)
    try:
        reply = chat([{"role": "user", "content": 'Reply with JSON {"ok": true}'}], s, max_tokens=60, kind="test")
        result["ok"] = True
        result["message"] += f"Text model working ({reply.strip()[:40]}). "
    except Exception as e:
        result["message"] += f"Text test failed: {e}. "
        return result
    vm = vision_model_id or model
    try:
        from .media import b64, solid_jpeg
        reply = chat([{"role": "user", "content": _content("What colour is this image? One word.",
                                                           [b64(solid_jpeg("red"))])}],
                     s, max_tokens=60, kind="test", model=vm)
        result["vision"] = True
        _vision_broken.pop(vm, None)
        result["message"] += f"Vision working with {vm} (saw: {reply.strip()[:20]})."
    except VisionUnsupported:
        result["vision"] = False
        result["message"] += f"{vm} can't read images. Clips will be judged without frames; pick a vision model."
    except Exception as e:
        result["vision"] = False
        result["message"] += f"Vision test failed: {str(e)[:120]}"
    return result
