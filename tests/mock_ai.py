"""A stand-in for an OpenAI-compatible AI, used only by the tests.

It judges like a sensible editor from the evidence in the prompt (it never sees real pixels): a clutch or a
landed stunt in the transcript is a highlight; screaming with nothing else is not; a colour-loss death screen
counts only when frames were attached. It also checks that the app sends what it claims (image count limits).
"""
import json
import re
import threading

from flask import Flask, jsonify, request

calls = []


def _lines(block):
    return [(float(t), txt) for t, txt in re.findall(r"\[(-?[\d.]+)\] (.*)", block)]


def _section(prompt, start, end):
    a = prompt.find(start)
    if a < 0:
        return ""
    b = prompt.find(end, a + len(start))
    return prompt[a:b if b > 0 else None]


def judge_editor(prompt, n_images):
    transcript = _lines(_section(prompt, "TRANSCRIPT", "CHAT"))
    cues = [(float(t), txt) for t, txt in re.findall(r"- t=([\d.]+)s: (.*)", prompt)]
    text = " ".join(t for _, t in transcript).lower()
    cats = re.search(r"one of: (.*?) \| none", prompt).group(1).split(", ")

    def cat(*names):
        return next((c for c in cats if any(n in c for n in names)), cats[0])

    def find(word):
        return next((t for t, x in transcript if word in x.lower()), None)

    if "clutched" in text:
        setup, act = find("versus") or (find("clutched") - 15), find("clutched")
        return dict(is_highlight=True, category=cat("clutch", "skill"), setup_start=setup, key_action=act,
                    reaction=act + 1, payoff=act + 1, end=act + 5,
                    scores=dict(significance=24, hook=18, reaction=18, retention=14, standalone=9, visual=8),
                    hook="1v4 with one HP left", event_summary="Streamer clutches a 1v4 and celebrates.",
                    emphasis_words=["clutched"])
    if "made it" in text:
        setup, act = find("watch this"), find("made it")
        return dict(is_highlight=True, category=cat("stunt"), setup_start=setup, key_action=act - 1,
                    reaction=act + 2, payoff=act, end=act + 4,
                    scores=dict(significance=23, hook=17, reaction=17, retention=13, standalone=9, visual=8),
                    hook="He tried to jump the canyon", event_summary="Long run-up, canyon jump lands, big reaction.")
    colour = next((t for t, c in cues if "colour" in c or "flash" in c), None)
    if n_images and colour is not None and not transcript:
        return dict(is_highlight=True, category=cat("fail"), setup_start=colour - 9, key_action=colour,
                    reaction=None, payoff=colour + 1, end=colour + 5,
                    scores=dict(significance=22, hook=17, reaction=4, retention=13, standalone=9, visual=9),
                    hook="This did not go to plan", event_summary="Car flips off the ramp, Wasted screen.")
    if "aaaa" in text:
        return dict(is_highlight=False, category="none", setup_start=0, key_action=0, payoff=0, end=0,
                    scores=dict(significance=4, hook=8, reaction=9, retention=4, standalone=2, visual=3),
                    rejection_reasons=["random screaming without context"], event_summary="Scream, nothing visible.")
    return dict(is_highlight=False, category="none", setup_start=0, key_action=0, payoff=0, end=0,
                scores=dict(significance=3, hook=4, reaction=2, retention=3, standalone=3, visual=3),
                rejection_reasons=["ordinary gameplay"], event_summary="Ordinary driving and talking.")


def judge_reviewer(prompt, n_images):
    claim = re.search(r"Claimed event: (.*)", prompt).group(1).lower()
    if "clutch" in claim:
        return dict(verified=True, verdict="export", opening_ok=True, payoff_ok=True, standalone_ok=True,
                    scores=dict(significance=24, hook=17, reaction=18, retention=14, standalone=9, visual=8),
                    trim={"start": 0, "end": 0.5}, notes="Clear 1v4, great reaction.")
    if "canyon" in claim:
        return dict(verified=True, verdict="export", opening_ok=True, payoff_ok=True, standalone_ok=True,
                    scores=dict(significance=22, hook=17, reaction=17, retention=13, standalone=9, visual=8))
    if "wasted" in claim:
        if not n_images:
            return dict(verified=False, verdict="reject", scores={}, issues=["cannot see the claimed crash"])
        return dict(verified=True, verdict="review", opening_ok=True, payoff_ok=True, standalone_ok=True,
                    scores=dict(significance=21, hook=16, reaction=4, retention=12, standalone=9, visual=9))
    return dict(verified=False, verdict="reject", scores={}, issues=["nothing happens"])


def make_app():
    app = Flask("mock_ai")

    @app.get("/v1/models")
    def models():
        return jsonify({"data": [{"id": "mock-text"}, {"id": "mock-vision"}]})

    @app.post("/v1/chat/completions")
    def completions():
        body = request.json
        msg = body["messages"][-1]["content"]
        if isinstance(msg, list):
            prompt = " ".join(p.get("text", "") for p in msg if p.get("type") == "text")
            n_images = sum(1 for p in msg if p.get("type") == "image_url")
        else:
            prompt, n_images = msg, 0
        if n_images > 5:
            return jsonify({"error": "too many images"}), 400
        if n_images and body["model"] == "mock-text":
            return jsonify({"error": {"message": "this model does not support image input"}}), 400
        if "TASK: decide if this window" in prompt:
            out = judge_editor(prompt, n_images)
        elif "PROPOSED CLIP" in prompt:
            out = judge_reviewer(prompt, n_images)
        elif "hooks" in prompt:
            out = {"hooks": ["NO WAY HE DID THAT", "1v4 ON ONE HP", "WATCH THE LAST SECOND", "HE ACTUALLY DID IT",
                             "CHAT WENT CRAZY"]}
        else:
            out = {"ok": True}
        calls.append({"kind": "editor" if "TASK" in prompt else "review" if "PROPOSED" in prompt else "other",
                      "images": n_images, "model": body["model"]})
        return jsonify({"choices": [{"message": {"content": json.dumps(out)}}],
                        "usage": {"total_tokens": 1200 + 1000 * n_images}})

    return app


def start(port):
    app = make_app()
    t = threading.Thread(target=lambda: app.run(port=port, use_reloader=False), daemon=True)
    t.start()
    return t
