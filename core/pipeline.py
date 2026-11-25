"""The V2 highlight pipeline (quality first; zero clips is a valid result).

  1. scan        cheap audio / keyframe / chat signals for a chunk (overlapping chunks for long videos)
  2. find        distinct candidate *events* with a context window each (no fixed-length cutting)
  3. transcribe  only the context windows (word timestamps)
  4. analyze     AI editor: category, setup/action/reaction/payoff/end, 100-pt rubric with justifications
                 (+ frame grid + key frame when the model can see)
  5. rules       strict rejection engine
  6. review      independent AI re-check of the proposed clip (fresh frames, can reject everything)
  7. learn       small +-5 nudge from your real posted results (only with enough data)
  8. dedupe+cap  near-duplicates removed, max N per video (a limit, not a target)
  9. render      only clips that passed; everything else keeps its scores and reasons for transparency
"""
import json
import os
import re
import time
import uuid
from collections import Counter

from . import ai, config, db, learning, media, profiles, render, signals, stt

cancel_flags = set()


class Cancelled(Exception):
    pass


def check_cancel(rec_id):
    if rec_id in cancel_flags:
        raise Cancelled()


def hms(t):
    t = max(0, int(t or 0))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def set_stage(rec_id, stage, progress=None, detail=None):
    fields = {"stage": stage, "progress": progress}
    if detail is not None:
        fields["detail"] = detail
    db.update("recordings", rec_id, **fields)


def transcribe_context(raw_path, settings, source=None, ctx_start=0.0):
    """Word timestamps for a context window (separate function so tests can swap it)."""
    return stt.transcribe(raw_path, settings["whisper_model"], settings["caption_language"], settings)


def recording_profile(rec, settings):
    if rec.get("profile"):
        return rec["profile"]
    src = db.one("SELECT profile FROM sources WHERE id=?", (rec.get("source_id"),)) if rec.get("source_id") else None
    chosen = (src or {}).get("profile") or settings["default_profile"]
    pid = profiles.resolve(chosen, rec.get("title") or rec.get("name"), settings["game_context"])
    db.update("recordings", rec["id"], profile=pid)
    return pid


def _cam_box(rec):
    for raw in (rec.get("cam_box"),
                (db.one("SELECT cam_box FROM sources WHERE id=?", (rec.get("source_id"),)) or {}).get("cam_box")
                if rec.get("source_id") else None):
        if raw:
            try:
                box = json.loads(raw)
                return box.get("box") if isinstance(box, dict) else box
            except ValueError:
                pass
    return None


def maybe_detect_webcam(rec, t0, t1, settings):
    if not settings.get("auto_webcam") or rec.get("cam_box"):
        return
    try:
        found = media.detect_webcam(rec["path"], t0, max(30.0, t1 - t0))
    except Exception:
        found = None
    if found:
        db.update("recordings", rec["id"], cam_box=json.dumps(dict(found, source="auto")))
        db.log(f"[{rec['name']}] Facecam found (confidence {int(found['confidence'] * 100)}%). Check it in the editor.")
    else:
        db.update("recordings", rec["id"], cam_box=json.dumps({"box": None, "source": "auto"}))


# ----------------------------------------------------------------- window

def process_window(rec_id, t0, t1, final=False, overall=None):
    """Find, judge and render highlights in [t0, t1] of a recording."""
    rec = db.one("SELECT * FROM recordings WHERE id=?", (rec_id,))
    if not rec or not os.path.exists(rec["path"] or ""):
        return
    s = config.load()
    pid = recording_profile(rec, s)
    prof = profiles.get(pid)
    duration = rec.get("duration") or 0
    if final or not duration:
        duration = media.duration(rec["path"]) or t1
    span = f"{hms(t0)}-{hms(t1)}"

    def prog(frac):
        if not overall:
            return None
        o0, o1, total = overall
        return round(min(1.0, (o0 + frac * (o1 - o0)) / max(total, 1)), 3)

    check_cancel(rec_id)
    set_stage(rec_id, "scanning", prog(0.02), f"Scanning audio, picture and chat {span}")
    a0 = max(0.0, t0 - 90)
    msgs = signals.load_chat(rec)
    sc = signals.scan(rec["path"], a0, t1, msgs, s)
    if sc is None:
        db.log(f"[{rec['name']}] {span}: no audio to analyse", "warn")
        return
    _append_wave(rec_id, sc, t0)
    if t0 < 1:
        maybe_detect_webcam(rec, max(0, t0), t1, s)
        rec = db.one("SELECT * FROM recordings WHERE id=?", (rec_id,))
    tr = signals.tracks(sc)

    check_cancel(rec_id)
    set_stage(rec_id, "finding", prog(0.1), f"Looking for stand-out moments {span}")
    blocked = [c["peak"] for c in _existing_peaks(rec_id)]
    cands = signals.find_candidates(sc, tr, t0, t1, final, blocked, s, prof, duration, pid)
    db.execute("UPDATE recordings SET candidates = COALESCE(candidates, 0) + ?, analyzed_sec = MAX(COALESCE("
               "analyzed_sec, 0), ?) WHERE id=?", (len(cands), t1, rec_id))
    if not cands:
        db.log(f"[{rec['name']}] {span}: nothing stood out")
        update_summary(rec_id)
        return
    db.log(f"[{rec['name']}] {span}: {len(cands)} moment(s) worth a closer look")
    for i, c in enumerate(cands):
        check_cancel(rec_id)
        base = 0.15 + 0.8 * i / len(cands)
        try:
            evaluate_candidate(rec, c, msgs, s, pid, lambda st, f=0, b=base: set_stage(
                rec_id, st, prog(b + f * 0.8 / len(cands)), f"Moment {i + 1}/{len(cands)} at {hms(c['peak'])}"))
        except Cancelled:
            raise
        except Exception as e:
            db.log(f"Moment at {hms(c['peak'])} failed: {e}", "error")
    dedupe_and_cap(rec_id, s)
    update_summary(rec_id)


def _existing_peaks(rec_id):
    out = []
    for r in db.query("SELECT cues_json FROM clips WHERE recording_id=?", (rec_id,)):
        try:
            meta = json.loads(r["cues_json"] or "{}")
            if isinstance(meta, dict) and "peak" in meta:
                out.append(meta)
        except ValueError:
            pass
    return out


def _append_wave(rec_id, sc, t0):
    path = os.path.join(config.CACHE_DIR, f"wave_{rec_id}.json")
    try:
        with open(path, encoding="utf-8") as f:
            pts = {p[0]: p[1] for p in json.load(f)}
    except (OSError, ValueError):
        pts = {}
    for t, v in signals.waveform(sc):
        if t >= t0 - 1:
            pts[t] = v
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted([t, v] for t, v in pts.items()), f)


def load_wave(rec_id):
    try:
        with open(os.path.join(config.CACHE_DIR, f"wave_{rec_id}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


# ----------------------------------------------------------------- one candidate

def heuristic_analysis(cand, words, chat_rows, ctx_len, peak_rel, s):
    """No AI configured: signals only, never trusted enough to auto-export."""
    start, end = max(0.0, peak_rel - 14), min(ctx_len, peak_rel + 10)
    for ws, we, _ in words:                     # extend to the surrounding sentence boundaries
        if start - 4 <= ws < start:
            start = ws
        if end < we <= end + 4:
            end = we
    total = int(max(0, min(75, 40 + 6 * cand["signal"])))
    cues = "; ".join(c["text"] for c in cand.get("cues", [])[:3]) or "signal spike"
    return {
        "is_highlight": total >= int(s["review_threshold"]), "category": "unverified",
        "event_summary": f"Unverified: {cues}.",
        "bounds": ai.fix_bounds({"setup_start": start, "key_action": peak_rel, "payoff": peak_rel + 2, "end": end},
                                ctx_len, peak_rel, s),
        "scores": {}, "total": total,
        "justification": {"significance": "No AI configured: picked from audio/chat/visual signals only. "
                                          "Nothing was verified, so this can never be a top pick."},
        "weaknesses": ["not verified by AI"], "rejection_reasons": [], "emphasis_words": [],
        "hook": "", "title": "", "caption": "", "views_potential": 0, "likes_potential": 0, "used_vision": False,
    }


def rule_check(a, words, chat_rows, s):
    """Strict, deterministic rejection rules applied on top of the AI's own judgement."""
    reasons = []
    if a["category"] == "unverified":
        return reasons
    sc = a["scores"]
    if not words and not chat_rows and not a["used_vision"]:
        reasons.append("cannot verify (not enough evidence)")
    if sc.get("significance", 0) < 8:
        reasons.append("ordinary gameplay")
    if sc.get("hook", 0) < 6:
        reasons.append("weak opening")
    if sc.get("standalone", 0) < 3:
        reasons.append("no clear setup or payoff")
    if not a["is_highlight"]:
        reasons.extend(a["rejection_reasons"] or ["not a highlight (AI)"])
    return list(dict.fromkeys(reasons))


def evaluate_candidate(rec, cand, msgs, s, pid, stage):
    uid = uuid.uuid4().hex[:10]
    raw = os.path.join(config.RAW_DIR, f"raw_{uid}.mp4")
    media.cut_segment(rec["path"], cand["ctx_start"], cand["ctx_len"], raw)
    ctx_len = media.duration(raw) or cand["ctx_len"]
    peak_rel = cand["peak"] - cand["ctx_start"]
    export_thr, review_thr = int(s["export_threshold"]), int(s["review_threshold"])

    stage("transcribing", 0.1)
    words = transcribe_context(raw, s, source=rec["path"], ctx_start=cand["ctx_start"]) or []
    chat_rows = signals.chat_window(msgs, cand["ctx_start"], cand["ctx_start"] + ctx_len, float(s["chat_delay_sec"]))
    use_ai = ai.enabled(s)

    a = None
    if use_ai:
        stage("analyzing", 0.3)
        images, grid_times = [], []
        if ai.vision_on(s):
            try:
                grid, grid_times = media.grid_jpeg(raw, 0, ctx_len, 4, 3, 320)
                images = [media.b64(grid), media.b64(media.frame_jpeg(raw, peak_rel, 768))]
            except media.MediaError:
                images = []
        ev = {"source_name": rec["name"], "title": rec.get("title") or rec["name"], "profile_id": pid,
              "ctx_len": ctx_len, "peak_rel": peak_rel, "cues": cand["cues"], "words": words, "chat": chat_rows,
              "images": images, "grid_times": grid_times, "peak_frame_time": peak_rel,
              "stream_kind": "live stream recording" if rec.get("kind") == "live" else "video",
              "insights": learning.insights_text() if s["learning"] else ""}
        try:
            a = ai.analyze_moment(ev, s)
        except Exception as e:
            db.log(f"AI editor failed at {hms(cand['peak'])} ({str(e)[:120]}); signals only", "warn")
    if a is None:
        a = heuristic_analysis(cand, words, chat_rows, ctx_len, peak_rel, s)
    reasons = rule_check(a, words, chat_rows, s)
    b = dict(a["bounds"])
    quality, review = a["total"], None

    if use_ai and a["category"] != "unverified" and not reasons and quality >= review_thr and s["second_pass"]:
        stage("reviewing", 0.6)
        review = _second_pass(rec, raw, a, b, words, msgs, cand, ctx_len, s, pid)
        if review:
            b = review.pop("_bounds", b)
            quality = round(0.4 * a["total"] + 0.6 * review["total"])
            if not review["verified"]:
                quality = min(quality, 60)
                reasons.append("cannot verify (not enough evidence)")
            if review["verdict"] == "reject":
                quality = min(quality, review_thr - 1)
                reasons.extend(review["issues"][:2] or ["rejected by second reviewer"])
            elif review["verdict"] == "review":
                quality = min(quality, export_thr - 1)
        else:
            quality = min(quality, export_thr - 1)   # unreviewed clips never auto-export
    elif a["category"] == "unverified":
        quality = min(quality, export_thr - 1)
    if reasons:
        quality = min(quality, review_thr - 1)

    adj, adj_note = (0, "")
    if s["learning"] and not reasons and a["category"] != "unverified":
        adj, adj_note = learning.adjustment(a["category"])
        quality += adj
    quality = max(0, min(100, int(quality)))
    status = "ready" if quality >= export_thr else ("review" if quality >= review_thr else "rejected")
    if status == "rejected" and not reasons:
        reasons = ["below the quality threshold"]

    clip_in, clip_out = b["setup_start"], b["end"]
    a["bounds_final"] = b
    meta = {k: cand[k] for k in ("peak", "signal", "modalities", "nominated_by", "cues", "motion_track")}
    summary = a["event_summary"]
    clip_id = db.execute(
        "INSERT INTO clips (recording_id, source_name, start, length, signal, score, quality, stage1, stage2, "
        "category, profile, ctx_start, ctx_len, clip_in, clip_out, hook, title, caption, reason, transcript, "
        "words_json, raw_path, path, status, created_at, updated_at, view_pct, like_pct, breakdown_json, "
        "analysis_json, review_json, cues_json, summary, weaknesses, reject_reason, learn_adj, evidence) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rec["id"], rec["name"], cand["ctx_start"] + clip_in, clip_out - clip_in, cand["signal"],
         round(quality / 10), quality, a["total"], review["total"] if review else None, a["category"], pid,
         cand["ctx_start"], ctx_len, clip_in, clip_out, a["hook"], a["title"], a["caption"],
         "; ".join(reasons) if reasons else (adj_note or ""),
         " ".join(w[2] for w in words if clip_in - 1 <= w[0] <= clip_out), json.dumps(words), raw, "",
         "rendering" if status != "rejected" else "rejected", time.time(), time.time(),
         a["views_potential"], a["likes_potential"],
         json.dumps({"scores": a["scores"], "justification": a["justification"],
                     "review_scores": (review or {}).get("scores")}),
         json.dumps(a), json.dumps(review or {}), json.dumps(meta), summary, "; ".join(a["weaknesses"]),
         "; ".join(reasons), adj, _evidence(words, chat_rows, a, review)))
    label = f"{hms(cand['peak'])}: {quality}/100 {a['category']}"
    if status == "rejected":
        if not s["keep_rejected_media"] and os.path.exists(raw):
            os.remove(raw)
            db.update("clips", clip_id, raw_path="")
        db.log(f"  {label} -> rejected ({'; '.join(reasons)[:110]})")
        return clip_id
    stage("rendering", 0.85)
    try:
        _prepare_clip(clip_id, rec, a, b, s)
        render_clip(clip_id)
    except Exception as e:
        db.update("clips", clip_id, status="rejected", reject_reason=f"render failed: {str(e)[:120]}")
        raise
    db.update("clips", clip_id, status=status)
    db.log(f"  {label} -> {'TOP PICK' if status == 'ready' else 'review'}: \"{a['hook']}\"")
    return clip_id


def _evidence(words, chat_rows, a, review):
    parts = []
    parts.append("transcript" if words else "no transcript")
    parts.append("chat" if chat_rows else "no chat")
    parts.append("frames" if a.get("used_vision") or (review or {}).get("used_vision") else "no frames")
    parts.append("2nd review" if review else "single pass")
    return ", ".join(parts)


def _second_pass(rec, raw, a, b, words, msgs, cand, ctx_len, s, pid):
    t_in, t_out = b["setup_start"], b["end"]
    clip_len = t_out - t_in
    images, grid_times = [], []
    if ai.vision_on(s):
        try:
            grid, grid_times = media.grid_jpeg(raw, t_in, clip_len, 3, 3, 320)
            images = [media.b64(grid), media.b64(media.frame_jpeg(raw, t_in + 0.2, 768))]
        except media.MediaError:
            images = []
    rel_words = [[round(ws - t_in, 2), round(we - t_in, 2), w] for ws, we, w in words if t_in - 8 <= ws <= t_out + 8]
    chat_rows = signals.chat_window(msgs, cand["ctx_start"] + t_in - 5, cand["ctx_start"] + t_out + 5,
                                    float(s["chat_delay_sec"]))
    chat_rows = [(round(t - 5, 1), m) for t, m in chat_rows]
    ev = {"profile_id": pid, "clip_len": clip_len, "words": rel_words, "chat": chat_rows, "images": images,
          "grid_times": grid_times}
    try:
        r = ai.review_moment(ev, {"category": a["category"], "event_summary": a["event_summary"]}, s)
    except Exception as e:
        db.log(f"Second review failed ({str(e)[:100]}); clip stays in review", "warn")
        return None
    nb = dict(b)
    nb["setup_start"] = max(0.0, min(b["key_action"], b["setup_start"] + r["trim"]["start"]))
    nb["end"] = min(ctx_len, max(b["payoff"], b["end"] + r["trim"]["end"]))
    fixed = ai.fix_bounds(nb, ctx_len, b["key_action"], s)
    r["_bounds"] = fixed
    return r


# ----------------------------------------------------------------- editing + rendering

def _prepare_clip(clip_id, rec, a, b, s):
    clip = db.clip(clip_id)
    raw = clip["raw_path"]
    motion = (clip["cues_json"] or {}).get("motion_track", []) if isinstance(clip["cues_json"], dict) else []
    sprite_path = os.path.join(config.THUMB_DIR, f"sprite_{clip_id}.jpg")
    try:
        tiles = media.sprite(raw, sprite_path, 2.0, 72)
    except media.MediaError:
        sprite_path, tiles = "", 0
    edit = {
        "in": b["setup_start"], "out": b["end"], "aspect": s["aspect"], "layout": s["layout"],
        "cam_box": _cam_box(rec), "zoom": s["zoom"], "focus_x": signals.focus_x(motion, b["setup_start"], b["end"]),
        "caption_style": s["caption_style"], "caption_pos": s["caption_pos"], "captions": bool(s["captions"]),
        "hook": a["hook"], "hook_secs": 3.5, "gain_db": 0, "normalize": True, "dead_air": bool(s["dead_air"]),
        "quality": s["export_quality"], "emphasis_words": a.get("emphasis_words", []), "sprite_tiles": tiles,
        "sprite_every": 2.0,
    }
    db.update("clips", clip_id, edit_json=edit, wave_json=media.wave(raw, 0.25), sprite=sprite_path)


def render_clip(clip_id):
    clip = db.clip(clip_id)
    if not clip or not os.path.exists(clip["raw_path"] or ""):
        raise media.MediaError("the original moment is missing, can't render")
    s = config.load()
    edit = dict(clip["edit_json"])
    words = clip["words_json"] or []
    a = clip["analysis_json"] or {}
    b = a.get("bounds_final") or a.get("bounds") or {}
    meta = clip["cues_json"] if isinstance(clip["cues_json"], dict) else {}
    protect = []
    if b:
        protect.append((b.get("key_action", 0) - 3, b.get("payoff", 0) + 2.5))
        if b.get("reaction") is not None:
            protect.append((b["reaction"] - 1.5, b["reaction"] + 2.5))
    cuts = []
    segments = [(edit["in"], edit["out"])]
    if edit.get("dead_air"):
        segments, cuts = render.dead_air(edit["in"], edit["out"], words, clip["wave_json"],
                                         meta.get("motion_track", []), protect)
    started = time.time()
    out = os.path.join(config.CLIP_DIR, f"clip_{clip_id}_{uuid.uuid4().hex[:6]}.mp4")
    result = render.render(clip["raw_path"], out, words, dict(edit, segments=segments), s)
    poster = os.path.join(config.THUMB_DIR, f"poster_{clip_id}_{uuid.uuid4().hex[:6]}.jpg")
    try:
        media.frame_jpeg(out, min(1.0, result["duration"] / 3), 360, poster)
    except media.MediaError:
        poster = ""
    edit.update(cuts=cuts, rendered_duration=result["duration"], resolved_layout=result["layout"])
    secs = time.time() - started
    old = (clip["path"], clip["poster"])
    db.update("clips", clip_id, path=out, poster=poster, edit_json=edit, render_secs=round(secs, 1),
              updated_at=time.time(), clip_in=edit["in"], clip_out=edit["out"],
              start=clip["ctx_start"] + edit["in"], length=edit["out"] - edit["in"],
              transcript=" ".join(w[2] for w in words if edit["in"] - 1 <= w[0] <= edit["out"]))
    db.metric("render", True, 0, 0, secs)
    for p in old:
        if p and p not in (out, poster) and os.path.exists(p):
            os.remove(p)
    return result


def save_edit(clip_id, changes):
    """Apply editor changes (edit fields, words, texts). Returns the new edit dict."""
    clip = db.clip(clip_id)
    if not clip:
        raise ValueError("clip not found")
    edit = dict(clip["edit_json"] or {})
    allowed = {"in", "out", "aspect", "layout", "cam_box", "zoom", "focus_x", "caption_style", "caption_pos",
               "captions", "hook", "hook_secs", "gain_db", "normalize", "dead_air", "quality", "emphasis_words"}
    for k, v in (changes.get("edit") or {}).items():
        if k in allowed:
            edit[k] = v
    ctx_len = clip["ctx_len"] or media.duration(clip["raw_path"] or "")
    edit["in"] = max(0.0, min(float(edit.get("in", 0)), ctx_len - 1))
    edit["out"] = max(edit["in"] + 1, min(float(edit.get("out", ctx_len)), ctx_len))
    fields = {"edit_json": edit, "edited": 1, "updated_at": time.time()}
    if "hook" in (changes.get("edit") or {}):
        fields["hook"] = str(edit["hook"])[:120]
    for k in ("title", "caption"):
        if k in changes:
            fields[k] = str(changes[k])[:500]
    if isinstance(changes.get("words"), list):
        words = []
        for w in changes["words"]:
            try:
                words.append([float(w[0]), float(w[1]), str(w[2])[:40]])
            except (TypeError, ValueError, IndexError):
                continue
        fields["words_json"] = words
    db.update("clips", clip_id, **fields)
    return edit


# ----------------------------------------------------------------- dedupe, cap, summaries

def _toks(text):
    return set(re.findall(r"[a-z0-9']{3,}", (text or "").lower()))


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def dedupe_and_cap(rec_id, s):
    rows = [db.parse_clip(r) for r in db.query(
        "SELECT * FROM clips WHERE recording_id=? AND status IN ('ready','review','approved') "
        "ORDER BY quality DESC, id ASC", (rec_id,))]
    keep = []
    for c in rows:
        lo, hi = c["ctx_start"] + c["clip_in"], c["ctx_start"] + c["clip_out"]
        act = c["ctx_start"] + ((c["analysis_json"] or {}).get("bounds_final") or {}).get("key_action", c["clip_in"])
        toks = _toks(c["transcript"])
        dup = None
        for k in keep:
            inter = max(0.0, min(hi, k["_hi"]) - max(lo, k["_lo"]))
            iou = inter / max(1e-6, max(hi, k["_hi"]) - min(lo, k["_lo"]))
            sim = _jaccard(toks, k["_toks"])
            near = c["category"] == k["category"] and abs(act - k["_act"]) < 60
            if iou > 0.3 or (near and sim > 0.45) or (sim > 0.7 and len(toks) >= 8):
                dup = k
                break
        if dup and c["status"] != "approved" and not c["edited"]:
            _reject(c, f"duplicate of clip #{dup['id']}")
            continue
        c.update(_lo=lo, _hi=hi, _act=act, _toks=toks)
        keep.append(c)
    limit = int(s["max_clips_per_video"])
    if len(keep) > limit:
        removable = [c for c in sorted(keep, key=lambda c: c["quality"])
                     if c["status"] != "approved" and not c["edited"]]
        for c in removable[:len(keep) - limit]:
            _reject(c, f"over the {limit}-clip limit (lower score than the kept clips)")


def _reject(c, reason):
    for p in (c.get("path"), c.get("poster")):
        if p and os.path.exists(p):
            os.remove(p)
    if c.get("raw_path") and os.path.exists(c["raw_path"]) and not config.get("keep_rejected_media"):
        os.remove(c["raw_path"])
    db.update("clips", c["id"], status="rejected", reject_reason=reason, reason=reason, path="", poster="")
    db.log(f"  clip #{c['id']} removed: {reason}")


def reclassify(rec_id=None):
    """Re-apply thresholds to existing scores (no AI calls). Rejected clips without media stay rejected."""
    s = config.load()
    ex, rv = int(s["export_threshold"]), int(s["review_threshold"])
    where = "WHERE status IN ('ready','review')" + (" AND recording_id=?" if rec_id else "")
    changed = 0
    for c in db.query(f"SELECT id, quality, status FROM clips {where}", (rec_id,) if rec_id else ()):
        new = "ready" if c["quality"] >= ex else ("review" if c["quality"] >= rv else "rejected")
        if new != c["status"]:
            fields = {"status": new}
            if new == "rejected":
                fields["reject_reason"] = "below the quality threshold"
            db.update("clips", c["id"], **fields)
            changed += 1
    return changed


def _reason_key(r):
    r = (r or "").split(";")[0].strip().lower()
    if r.startswith("duplicate"):
        return "duplicate"
    if r.startswith("over the"):
        return "over the clip limit"
    for k in ai.REJECT_REASONS:
        if k.split(" (")[0] in r:
            return k
    return r[:40] or "below the quality threshold"


def update_summary(rec_id):
    rec = db.one("SELECT * FROM recordings WHERE id=?", (rec_id,))
    if not rec:
        return
    rows = db.query("SELECT status, reject_reason FROM clips WHERE recording_id=?", (rec_id,))
    counts = Counter(r["status"] for r in rows)
    kept = counts["ready"] + counts["review"] + counts["approved"]
    analysed = hms(rec.get("analyzed_sec") or 0)
    reasons = Counter(_reason_key(r["reject_reason"]) for r in rows if r["status"] == "rejected")
    why = ", ".join(f"{n} {k}" for k, n in reasons.most_common(4))
    if not rows:
        text = (f"Analysed {analysed}. Nothing stood out in the audio, chat or picture, so no moment was worth "
                f"sending to the AI.")
    elif kept == 0:
        text = (f"Analysed {analysed}. Checked {len(rows)} possible moment(s); none passed the quality bar "
                f"({why}). For ordinary footage, zero clips is the right result.")
    else:
        text = (f"Analysed {analysed}. Checked {len(rows)} moment(s): {counts['ready']} top pick(s), "
                f"{counts['review']} to review, {counts['approved']} approved, {counts['rejected']} rejected"
                + (f" ({why})." if why else "."))
    db.update("recordings", rec_id, summary=text)
    return text
