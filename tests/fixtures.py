"""Synthetic gaming footage for the test suite (ffmpeg lavfi; no real game footage needed).

Each fixture: a busy moving picture (like gameplay), game-like background noise, optional events
(voice spikes in the speech band, loud game SFX, white flashes, colour-loss 'death screen'), an optional chat
log and a scripted transcript [(time, text)]. 640x360 with keyframes every 2 s, like a stream.
"""
import json
import os
import subprocess

FIXTURES = {
    "ordinary": {
        "duration": 180, "profile": "open_world",
        "transcript": [(20, "okay going to the car shop"), (64, "nice car"), (120, "where is the mission"),
                       (150, "driving to the beach")],
        "events": [], "chat": "steady",
        "expect": "zero clips: ordinary gameplay",
    },
    "noisy_ordinary": {
        "duration": 240, "profile": "open_world",
        "transcript": [(15, "okay let's go"), (70, "shooting these guys"), (130, "driving again"),
                       (200, "back to the safehouse")],
        "events": [("sfx", t, 1.6) for t in range(20, 230, 24)] + [("flash", t + 0.3, 0.3) for t in range(44, 230, 48)],
        "chat": "steady",
        "expect": "zero clips: loud gunfire/explosions in ordinary play (the real-world V1 failure)",
    },
    "clutch": {
        "duration": 180, "profile": "fps",
        "transcript": [(70, "okay it's one versus four"), (88, "he's one shot"), (100, "I CLUTCHED IT"),
                       (103, "LETS GO")],
        "events": [("voice", 99.5, 4.0), ("flash", 100.5, 0.4)], "chat": [(101, 8, "NO WAY CLUTCH")],
        "expect": "one top pick that starts at the 1v4 setup",
    },
    "loud_ordinary": {
        "duration": 180, "profile": "open_world",
        "transcript": [(30, "just driving around"), (90, "AAAAAAH"), (140, "anyway")],
        "events": [("voice", 89.5, 3.0), ("sfx", 89.5, 2.0)], "chat": "steady",
        "expect": "nominated by the loud audio, then rejected: screaming without context",
    },
    "silent_fail": {
        "duration": 180, "profile": "open_world",
        "transcript": [],
        "events": [("flash", 119.0, 0.4), ("desat", 119.5, 7.0)], "chat": None,
        "expect": "found from the picture alone (no audio, chat or transcript) and kept when the AI can see",
    },
    "buildup": {
        "duration": 200, "profile": "open_world",
        "transcript": [(60, "watch this I'm gonna jump the canyon"), (75, "here we go full speed"),
                       (100, "I MADE IT"), (102, "no way bro")],
        "events": [("voice", 99.5, 4.0), ("sfx", 99.0, 1.5)], "chat": [(101, 6, "NO WAY")],
        "expect": "one clip ~40-48 s long starting at 'watch this'",
    },
    "duplicates": {
        "duration": 200, "profile": "fps",
        "transcript": [(70, "okay it's one versus four"), (80, "I CLUTCHED IT"), (83, "LETS GO"),
                       (115, "okay it's one versus four"), (125, "I CLUTCHED IT"), (128, "LETS GO")],
        "events": [("voice", 79.5, 3.0), ("voice", 124.5, 3.0)], "chat": [(81, 6, "CLUTCH"), (126, 6, "CLUTCH")],
        "expect": "two near-identical moments -> only one kept",
    },
    "boundary": {
        "duration": 150, "profile": "fps",
        "transcript": [(40, "okay it's one versus four"), (60, "I CLUTCHED IT"), (62, "LETS GO")],
        "events": [("voice", 59.5, 3.5), ("flash", 60.0, 0.4)], "chat": [(61, 6, "NO WAY")],
        "expect": "event at 60 s crossing a chunk boundary is found exactly once",
    },
    "no_cam_no_chat": {
        "duration": 160, "profile": "fps",
        "transcript": [(55, "okay it's one versus four"), (80, "I CLUTCHED IT")],
        "events": [("voice", 79.5, 3.0)], "chat": None,
        "expect": "works without webcam or chat; layout falls back to full gameplay",
    },
}


def _video_filter(events):
    vf = ["testsrc2=s=640x360:r=30"]
    for kind, t, d in events:
        if kind == "flash":
            vf.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=white@1:t=fill:enable='between(t,{t},{t + d})'")
        if kind == "desat":
            vf.append(f"hue=s=0:enable='between(t,{t},{t + d})'")
    return ",".join(vf)


def make(name, out_dir):
    fx = FIXTURES[name]
    d = fx["duration"]
    path = os.path.join(out_dir, f"{name}.mp4")
    if not os.path.exists(path):
        voice = "+".join(f"between(t,{t},{t + dd})" for k, t, dd in fx["events"] if k == "voice") or "0"
        sfx = "+".join(f"between(t,{t},{t + dd})" for k, t, dd in fx["events"] if k == "sfx") or "0"
        fc = (f"[1:a]volume=1.0[n];"
              f"[2:a]volume='0.7*({voice})':eval=frame[v];"
              f"[3:a]volume='0.9*({sfx})':eval=frame[s];"
              f"[n][v][s]amix=inputs=3:normalize=0[a]")
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", str(d), "-i", _video_filter(fx["events"]),
               "-f", "lavfi", "-t", str(d), "-i", "anoisesrc=c=pink:a=0.05:r=16000",
               "-f", "lavfi", "-t", str(d), "-i", "sine=f=420:r=16000",
               "-f", "lavfi", "-t", str(d), "-i", "anoisesrc=c=brown:a=0.9:r=16000",
               "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
               "-g", "60", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
        subprocess.run(cmd, check=True)
    chat_path = None
    if fx["chat"]:
        chat_path = os.path.join(out_dir, f"{name}_chat.jsonl")
        with open(chat_path, "w", encoding="utf-8") as f:
            for t in range(0, d, 2):                          # background chatter: 1 msg / 2 s
                f.write(json.dumps({"t": t + 0.3, "u": "v", "m": "hello chat"}) + "\n")
            if isinstance(fx["chat"], list):
                for t, secs, msg in fx["chat"]:
                    for i in range(secs * 6):                 # burst: ~6 msgs / s
                        f.write(json.dumps({"t": t + i / 6.0, "u": "b", "m": msg}) + "\n")
    return path, chat_path


def words_for(name, ctx_start, ctx_len):
    """Scripted transcript for a context window, as word timestamps relative to ctx_start."""
    out = []
    for t, text in FIXTURES[name]["transcript"]:
        if ctx_start <= t <= ctx_start + ctx_len:
            for i, w in enumerate(text.split()):
                ws = t - ctx_start + i * 0.35
                out.append([round(ws, 2), round(ws + 0.3, 2), w])
    return out
