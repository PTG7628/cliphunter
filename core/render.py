"""Clip editor backend: trims, layouts (facecam / blur / crop / action), captions, dead-air removal, export."""
import os
import re

import numpy as np

from .media import MediaError, probe, run

SIZES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
CRF = {"high": 18, "balanced": 21, "small": 25}

# ASS colours are &HAABBGGRR
STYLES = {
    "bold": {"label": "Bold", "font": "Arial Black", "size": 92, "primary": "&H00FFFFFF", "outline": "&H00000000",
             "back": "&H64000000", "border": 1, "ow": 7, "shadow": 3, "hi": "&H0000F0FF", "emph": "&H00813DFF",
             "upper": True, "hook_text": "&H0000F0FF", "hook_box": "&H00000000"},
    "clean": {"label": "Clean", "font": "Arial", "size": 76, "primary": "&H00FFFFFF", "outline": "&H50140B0B",
              "back": "&H00000000", "border": 3, "ow": 14, "shadow": 0, "hi": "&H00FFE500", "emph": "&H00813DFF",
              "upper": False, "hook_text": "&H00FFFFFF", "hook_box": "&H00F65C8B"},
    "neon": {"label": "Neon", "font": "Arial Black", "size": 88, "primary": "&H00FFE500", "outline": "&H00F65C8B",
             "back": "&H64000000", "border": 1, "ow": 6, "shadow": 4, "hi": "&H00813DFF", "emph": "&H0000F0FF",
             "upper": True, "hook_text": "&H00FFFFFF", "hook_box": "&H00813DFF"},
    "minimal": {"label": "Minimal", "font": "Arial", "size": 62, "primary": "&H00FFFFFF", "outline": "&H00000000",
                "back": "&H50000000", "border": 1, "ow": 4, "shadow": 1, "hi": None, "emph": None, "upper": False,
                "hook_text": "&H00FFFFFF", "hook_box": "&H96000000"},
}


def _even(v):
    return max(2, int(round(v / 2.0)) * 2)


# ----------------------------------------------------------------- layout geometry

def resolve_layout(edit):
    layout = edit.get("layout") or "auto"
    aspect = edit.get("aspect") or "9:16"
    if aspect == "16:9":
        return "fit"
    if layout == "auto":
        return "facecam" if (edit.get("cam_box") and aspect == "9:16") else "blur"
    if layout == "facecam" and (not edit.get("cam_box") or aspect != "9:16"):
        return "blur"
    return layout


def geometry(edit, src_w, src_h):
    """Return the video filter (from {vin} to [pre]) and where captions/hook go."""
    aspect = edit.get("aspect") or "9:16"
    W, H = SIZES.get(aspect, SIZES["9:16"])
    layout = resolve_layout(edit)
    scale = {"9:16": 1.0, "1:1": 0.85, "16:9": 0.62}[aspect if aspect in SIZES else "9:16"]
    g = {"W": W, "H": H, "layout": layout, "font_scale": scale}
    fx = float(edit.get("focus_x", 0.5) or 0.5)

    if layout == "fit":
        g["vf"] = (f"{{vin}}scale={W}:{H}:force_original_aspect_ratio=decrease,"
                   f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black[pre]")
        g.update(cap=(2, 70), hook=(8, 50))
    elif layout in ("crop", "action"):
        if layout == "crop":
            fx = 0.5
        sw = _even(src_w * H / src_h)
        if sw >= W:
            x = int(min(max(fx * sw - W / 2, 0), sw - W))
            g["vf"] = f"{{vin}}scale={sw}:{H},crop={W}:{H}:{x}:0[pre]"
        else:
            sh = _even(src_h * W / src_w)
            g["vf"] = f"{{vin}}scale={W}:{sh},crop={W}:{H}:0:{(sh - H) // 2}[pre]"
        g.update(cap=(2, int(H * 0.30)), hook=(8, int(H * 0.12)))
    elif layout == "facecam":
        bx, by, bw, bh = [float(v) for v in edit["cam_box"]]
        cw, ch = bw * src_w, bh * src_h
        cam_h = min(max(W * ch / max(cw, 1), H * 0.26), H * 0.40)
        target = W / cam_h                          # width/height the cam crop must have
        if cw / ch > target:                        # too wide: narrow it around its centre
            ncw, nch = ch * target, ch
        else:                                       # too tall: shorten it
            ncw, nch = cw, cw / target
        cx0 = bx * src_w + (cw - ncw) / 2
        cy0 = by * src_h + (ch - nch) / 2
        ncw, nch = _even(ncw), _even(nch)
        cx0 = int(min(max(cx0, 0), src_w - ncw))
        cy0 = int(min(max(cy0, 0), src_h - nch))
        cam_h = _even(cam_h)
        game_h = H - cam_h
        gw = _even(min(src_w, src_h * W / game_h))
        gh = _even(min(src_h, gw * game_h / W))
        gx = int(min(max(fx * src_w - gw / 2, 0), src_w - gw))
        gy = int((src_h - gh) / 2)
        g["vf"] = (f"{{vin}}split=2[c][g];[c]crop={ncw}:{nch}:{cx0}:{cy0},scale={W}:{cam_h}[cam];"
                   f"[g]crop={gw}:{gh}:{gx}:{gy},scale={W}:{game_h}[game];[cam][game]vstack[pre]")
        g.update(cap=(2, int(game_h * 0.22)), hook=(8, cam_h + 30), cam_h=cam_h)
    else:  # blur
        zoom = float(edit.get("zoom") or 1.35)
        fg_w = _even(W * zoom)
        fg_h = _even(fg_w * src_h / src_w)
        if fg_h > H * 0.8:
            fg_h = _even(H * 0.8)
            fg_w = _even(fg_h * src_w / src_h)
        band_top = (H - fg_h) / 2
        band_bottom = band_top + fg_h
        g["vf"] = (f"{{vin}}split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                   f"boxblur=25:3,eq=brightness=-0.08[bg];[b]scale={fg_w}:{fg_h}[fg0];"
                   f"[fg0]crop='min(iw,{W})':ih[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[pre]")
        if H - band_bottom >= 220:
            g["cap"] = (8, int(band_bottom + 40))
        else:
            g["cap"] = (2, int(H - band_bottom + 30))
        g["hook"] = (2, int(H - band_top + 24)) if band_top >= 150 else (8, 40)
    pos = edit.get("caption_pos") or "auto"
    if pos == "top":
        g["cap"] = (8, int(H * 0.14))
    elif pos == "middle":
        g["cap"] = (5, 0)
    elif pos == "bottom":
        g["cap"] = (2, int(H * 0.20))
    return g


# ----------------------------------------------------------------- captions

def _ass_time(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def clean(text):
    text = re.sub(r"[\U00010000-\U0010FFFF]", "", text or "")  # emojis don't render in burned captions
    return text.replace("\\", "").replace("{", "(").replace("}", ")").strip()


def build_ass(words, hook, hook_secs, length, geom, edit, settings):
    style_id = edit.get("caption_style") or settings.get("caption_style") or "bold"
    st = STYLES.get(style_id, STYLES["bold"])
    lang = settings.get("caption_language", "auto")
    rtl = lang in ("ur", "ar", "fa")
    font = st["font"]
    if rtl or settings.get("font") not in (None, "", "Arial Black"):
        font = "Arial" if rtl else settings["font"]
    sc = geom["font_scale"]
    cap_align, cap_mv = geom["cap"]
    hook_align, hook_mv = geom["hook"]
    out = [f"""[Script Info]
ScriptType: v4.00+
PlayResX: {geom['W']}
PlayResY: {geom['H']}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{int(st['size'] * sc)},{st['primary']},{st['primary']},{st['outline']},{st['back']},-1,0,0,0,100,100,0,0,{st['border']},{st['ow']},{st['shadow']},{cap_align},70,70,{cap_mv},1
Style: Hook,{font},{int(74 * sc)},{st['hook_text']},{st['hook_text']},{st['hook_box']},&H96000000,-1,0,0,0,100,100,0,0,3,16,0,{hook_align},80,80,{hook_mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""]
    hook = clean(hook)
    if hook:
        out.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(min(hook_secs, length))},Hook,,0,0,0,,{hook.upper()}")
    if not edit.get("captions", True) or style_id == "off":
        return "\n".join(out) + "\n"
    emph = {w.lower().strip(".,!?") for w in (edit.get("emphasis_words") or []) if w}
    per = max(1, int(settings.get("words_per_caption", 3)))
    for i in range(0, len(words), per):
        chunk = words[i:i + per]
        chunk_end = words[i + per][0] if i + per < len(words) else chunk[-1][1] + 0.3
        for j, (ws, _, _) in enumerate(chunk):
            end = chunk[j + 1][0] if j + 1 < len(chunk) else chunk_end
            parts = []
            for k, (_, _, wt) in enumerate(chunk):
                txt = clean(wt) if (rtl or not st["upper"]) else clean(wt).upper()
                key = clean(wt).lower().strip(".,!?")
                if k == j and st["hi"]:
                    parts.append("{\\c" + st["hi"] + "&}" + txt + "{\\c" + st["primary"] + "&}")
                elif st["emph"] and (key in emph or (len(key) > 2 and clean(wt).isupper())):
                    parts.append("{\\c" + st["emph"] + "&}" + txt + "{\\c" + st["primary"] + "&}")
                else:
                    parts.append(txt)
            pop = "{\\fscx110\\fscy110\\t(0,90,\\fscx100\\fscy100)}" if st["hi"] else ""
            out.append(f"Dialogue: 0,{_ass_time(ws)},{_ass_time(max(end, ws + 0.05))},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    return "\n".join(out) + "\n"


def _filter_path(path):
    p = os.path.abspath(path).replace("\\", "/")
    return p.replace(":", "\\:").replace("'", "\\'")


# ----------------------------------------------------------------- dead air

def dead_air(t_in, t_out, words, wave, motion_track, protect, wave_step=0.25, min_gap=1.6, pad=0.35,
             max_ratio=0.35):
    """Find quiet, still, wordless stretches inside the clip. Returns (keep_segments, cuts).

    Only gaps *between* spoken words are considered (never the opening or the ending), never inside
    `protect` ranges (build-up before the key action, the payoff, the reaction), and the audio must be
    quieter than the clip's typical level. Motion, when known, must be low too.
    """
    inside = sorted((w[0], w[1]) for w in words if t_in <= w[0] <= t_out)
    if len(inside) < 2:
        return [(t_in, t_out)], []
    wv = np.asarray(wave or [], dtype=float)

    def level(a, b):
        if not len(wv):
            return None
        seg = wv[int(a / wave_step):max(int(a / wave_step) + 1, int(b / wave_step))]
        return float(seg.mean()) if len(seg) else None

    clip_level = level(t_in, t_out)
    motions = [m for t, _, m in (motion_track or []) if t_in <= t <= t_out]
    med_motion = float(np.median(motions)) if motions else None
    gaps = []
    for (_, e1), (s2, _) in zip(inside, inside[1:]):
        a, b = e1, s2
        if b - a < min_gap:
            continue
        if any(a < p1 and b > p0 for p0, p1 in protect):
            continue
        lv = level(a, b)
        if lv is not None and clip_level is not None and lv > clip_level - 0.04:
            continue
        if med_motion is not None:
            gm = [m for t, _, m in motion_track if a <= t <= b]
            if gm and float(np.mean(gm)) > med_motion * 0.9:
                continue
        gaps.append((a + pad, b - pad))
    budget = (t_out - t_in) * max_ratio
    cuts = []
    for a, b in sorted(gaps, key=lambda g: g[1] - g[0], reverse=True):
        if b - a <= 0.2 or (b - a) > budget:
            continue
        cuts.append((round(a, 2), round(b, 2)))
        budget -= b - a
    cuts.sort()
    keep, cur = [], t_in
    for a, b in cuts:
        keep.append((round(cur, 2), a))
        cur = b
    keep.append((round(cur, 2), round(t_out, 2)))
    return keep, cuts


def retime_words(words, segments):
    """Move word timestamps from raw-file time to time inside the edited clip; drop cut words."""
    out, offset = [], 0.0
    for a, b in segments:
        for ws, we, w in words:
            if a <= ws < b:
                out.append([round(ws - a + offset, 2), round(min(we, b) - a + offset, 2), w])
        offset += b - a
    return out


# ----------------------------------------------------------------- render

def render(raw_path, out_path, words, edit, settings):
    """Render the edited clip. `words` are in raw-file time. Returns dict(duration, segments, cuts, layout)."""
    info = probe(raw_path)
    t_in = max(0.0, float(edit.get("in", 0)))
    t_out = min(float(edit.get("out", info["duration"])), info["duration"] or float(edit.get("out", 0)))
    if t_out - t_in < 1:
        raise MediaError("clip is shorter than 1 second")
    segments = edit.get("segments") or [(t_in, t_out)]
    segments = [(max(t_in, a), min(t_out, b)) for a, b in segments if min(t_out, b) - max(t_in, a) > 0.2]
    length = sum(b - a for a, b in segments)
    geom = geometry(edit, info["width"], info["height"])
    clip_words = retime_words(words, segments)

    cmd = ["ffmpeg", "-v", "error", "-y"]
    fc = []
    if len(segments) == 1:
        a, b = segments[0]
        cmd += ["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", raw_path]
        vin, ain = "[0:v]", "[0:a]"
    else:
        cmd += ["-i", raw_path]
        parts = []
        for i, (a, b) in enumerate(segments):
            fc.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
            if info["has_audio"]:
                fc.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
                parts.append(f"[v{i}][a{i}]")
            else:
                parts.append(f"[v{i}]")
        fc.append("".join(parts) + f"concat=n={len(segments)}:v=1:a={1 if info['has_audio'] else 0}"
                  + ("[vc][ac]" if info["has_audio"] else "[vc]"))
        vin, ain = "[vc]", "[ac]"
    fc.append(geom["vf"].format(vin=vin))

    ass_path = out_path + ".ass"
    hook = edit.get("hook", "")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(build_ass(clip_words, hook, float(edit.get("hook_secs", 3.5)), length, geom, edit, settings))
    fc.append(f"[pre]subtitles='{_filter_path(ass_path)}'[v]")
    maps = ["-map", "[v]"]
    if info["has_audio"]:
        gain = float(edit.get("gain_db", 0) or 0)
        norm = ",loudnorm=I=-14:TP=-1.5:LRA=11" if edit.get("normalize", True) else ""
        fc.append(f"{ain}volume={gain}dB{norm}[aout]")
        maps += ["-map", "[aout]"]
    crf = CRF.get(edit.get("quality") or settings.get("export_quality", "high"), 18)
    cmd += ["-filter_complex", ";".join(fc), *maps, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-r", "30", "-pix_fmt", "yuv420p"]
    if info["has_audio"]:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    cmd += ["-movflags", "+faststart", out_path]
    try:
        run(cmd)
    finally:
        if os.path.exists(ass_path):
            os.remove(ass_path)
    return {"duration": round(length, 2), "segments": segments, "layout": geom["layout"],
            "size": [geom["W"], geom["H"]]}
