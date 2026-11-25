"""End-to-end selection tests on synthetic gaming footage (the 8 required cases + safety checks).

The AI is a rule-based stand-in (tests/mock_ai.py) and transcripts are scripted, so these tests prove the
*pipeline* behaves correctly given sensible judgements: candidate discovery, context, boundaries, strict
rejection, second pass, dedupe, chunk overlap, zero-output and rendering. They cannot prove how good a real
AI's taste is on real streams; that needs real footage on your PC.
"""
import json
import os

import pytest

from core import config, db, media, pipeline, worker
from tests import fixtures
from tests.legacy import analyze_v1

RESULTS = {}


def _settings(env, **over):
    base = dict(config.DEFAULTS, ai_provider="custom", ai_base_url=env["ai"]["url"], ai_key="test",
                ai_model="mock-vision", vision_model="", vision_mode="auto", ai_min_gap_sec=0,
                font="DejaVu Sans", learning=False, auto_webcam=True, export_quality="small")
    base.update(over)
    config.save(base)
    return config.load()


def run_fixture(env, name, key=None, **over):
    s = _settings(env, **over)
    path, chat_path = fixtures.make(name, os.path.join(os.path.dirname(__file__), ".media"))
    fx = fixtures.FIXTURES[name]
    res = worker.add_source(path, fx["profile"])
    rid = res["recording_id"]
    worker.jobs.get_nowait()                     # run it here instead of the background thread
    if chat_path:
        db.update("recordings", rid, chat_path=chat_path, chat_mode="rel")
    pipeline.transcribe_context = lambda raw, st, source=None, ctx_start=0.0: fixtures.words_for(
        name, ctx_start, media.duration(raw))
    worker.process_vod(rid)
    rec = db.one("SELECT * FROM recordings WHERE id=?", (rid,))
    clips = [db.parse_clip(c) for c in db.query("SELECT * FROM clips WHERE recording_id=? ORDER BY start", (rid,))]
    kept = [c for c in clips if c["status"] in ("ready", "review", "approved")]
    RESULTS[key or name] = {"rec": rec, "clips": clips, "kept": kept, "settings": s}
    return rec, clips, kept


def test_ordinary_gameplay_gives_zero_clips(env):
    rec, clips, kept = run_fixture(env, "ordinary")
    assert rec["status"] == "done"
    assert kept == []
    assert "zero clips" in rec["summary"] or "Nothing stood out" in rec["summary"]


def test_loud_ordinary_gameplay_gives_zero_clips(env):
    rec, clips, kept = run_fixture(env, "noisy_ordinary")
    assert kept == [], [(c["start"], c["status"], c["reject_reason"]) for c in clips]


def test_high_skill_clutch_is_top_pick_with_setup(env):
    rec, clips, kept = run_fixture(env, "clutch")
    assert len(kept) == 1
    c = kept[0]
    assert c["status"] == "ready" and c["quality"] >= 85
    start_abs = c["ctx_start"] + c["clip_in"]
    assert abs(start_abs - 70) < 1.5, "clip must start at the '1v4' setup, not a fixed window"
    assert 30 <= c["clip_out"] - c["clip_in"] <= 45
    assert c["stage2"] is not None and "2nd review" in c["evidence"] and "frames" in c["evidence"]
    assert all(c["breakdown_json"]["justification"].get(k) is not None for k in ("significance", "hook"))
    info = media.probe(c["path"])
    assert (info["width"], info["height"]) == (1080, 1920)


def test_loud_reaction_to_ordinary_event_is_rejected(env):
    rec, clips, kept = run_fixture(env, "loud_ordinary")
    assert kept == []
    assert any("screaming" in (c["reject_reason"] or "") for c in clips), "the loud moment must be judged, then rejected"


def test_silent_visual_fail_found_without_audio_chat_or_transcript(env):
    rec, clips, kept = run_fixture(env, "silent_fail")
    assert len(kept) == 1, rec["summary"]
    c = kept[0]
    meta = c["cues_json"]
    assert any(k in json.dumps(meta["cues"]) for k in ("colour", "flash")), "nominated by the picture"
    assert abs(c["ctx_start"] + c["analysis_json"]["bounds_final"]["key_action"] - 119.5) < 3


def test_silent_fail_is_not_kept_when_ai_cannot_see(env):
    with_vision = RESULTS.get("silent_fail")
    rec, clips, kept = run_fixture(env, "silent_fail", ai_model="mock-text")
    assert kept == []
    RESULTS["silent_fail_blind"] = RESULTS["silent_fail"]
    if with_vision:
        RESULTS["silent_fail"] = with_vision


def test_long_buildup_keeps_the_setup(env):
    rec, clips, kept = run_fixture(env, "buildup")
    assert len(kept) == 1
    c = kept[0]
    assert abs(c["ctx_start"] + c["clip_in"] - 60) < 1.5
    assert 40 <= c["clip_out"] - c["clip_in"] <= 50


def test_duplicate_moments_collapse_to_one(env):
    rec, clips, kept = run_fixture(env, "duplicates")
    assert len(kept) == 1
    assert any("duplicate" in (c["reject_reason"] or "") for c in clips)


def test_highlight_crossing_chunk_boundary_found_once(env):
    rec, clips, kept = run_fixture(env, "boundary", chunk_minutes=1, chunk_overlap_sec=45)
    assert len(kept) == 1
    c = kept[0]
    assert c["ctx_start"] + c["clip_in"] < 60 < c["ctx_start"] + c["clip_out"]
    peaks = [cl["cues_json"]["peak"] for cl in clips]
    assert sum(1 for p in peaks if abs(p - 60) < 10) == 1, f"judged more than once: {peaks}"


def test_no_webcam_no_chat_still_works(env):
    rec, clips, kept = run_fixture(env, "no_cam_no_chat")
    assert len(kept) == 1
    c = kept[0]
    assert not c["edit_json"].get("cam_box")
    assert c["edit_json"]["resolved_layout"] == "blur"


def test_without_ai_nothing_is_a_top_pick(env):
    rec, clips, kept = run_fixture(env, "clutch", key="clutch_no_ai", ai_provider="none")
    assert all(c["status"] != "ready" for c in clips)
    assert all(c["quality"] <= 75 for c in clips)


def test_editor_changes_rerender(env):
    c = RESULTS["clutch"]["kept"][0] if RESULTS.get("clutch") and RESULTS["clutch"]["kept"] else None
    if c is None:
        pytest.skip("clutch clip missing")
    _settings(env)
    pipeline.save_edit(c["id"], {"edit": {"aspect": "1:1", "caption_style": "neon", "in": c["clip_in"] + 2,
                                          "out": c["clip_in"] + 14, "hook": "NEW HOOK", "dead_air": False},
                                 "title": "edited title"})
    pipeline.render_clip(c["id"])
    c2 = db.clip(c["id"])
    info = media.probe(c2["path"])
    assert (info["width"], info["height"]) == (1080, 1080)
    assert abs(info["duration"] - 12) < 0.6
    assert c2["hook"] == "NEW HOOK" and c2["title"] == "edited title" and c2["edited"] == 1


def test_threshold_change_reclassifies_without_ai(env):
    _settings(env, export_threshold=99, review_threshold=70)
    pipeline.reclassify()
    assert not db.query("SELECT id FROM clips WHERE status='ready'")
    _settings(env, export_threshold=85, review_threshold=70)
    pipeline.reclassify()


def test_api_endpoints(env):
    import app as webapp
    client = webapp.app.test_client()
    st = client.get("/api/state").get_json()
    assert st["usage"]["ai_calls"] > 0 and "vision" in st
    projects = client.get("/api/projects").get_json()
    assert projects and all("summary" in p for p in projects)
    all_clips = client.get("/api/clips?status=all&sort=entertainment").get_json()
    assert all_clips
    cid = all_clips[0]["id"]
    detail = client.get(f"/api/clips/{cid}").get_json()
    assert detail["rubric"]["max"]["significance"] == 25 and detail["has_raw_path"]
    assert client.get(f"/media/{cid}").status_code == 200
    assert client.get(f"/media/sprite/{cid}").status_code == 200
    assert client.get(f"/media/frame/{cid}?t=2").status_code == 200
    hooks = client.post(f"/api/clips/{cid}/hooks").get_json()
    assert hooks["ok"] and len(hooks["hooks"]) == 5
    r = client.post(f"/api/clips/{cid}/approve", json={}).get_json()
    assert r["ok"] and os.path.exists(os.path.join(config.APPROVED_DIR, r["file"]))
    assert client.post("/api/results", json={"clip_id": cid, "platform": "TikTok", "views": "12.5k",
                                             "likes": 900}).get_json()["ok"]
    res = client.get("/api/results").get_json()
    assert res["results"][0]["views"] == 12500
    up = client.post("/api/results/import", json={"csv": f"clip_id,views,likes\n{cid},3000,100\nx,1,1\n"}).get_json()
    assert up["added"] == 1 and up["skipped"]
    proj = client.get(f"/api/projects/{all_clips[0]['recording_id']}").get_json()
    assert proj["wave"] and proj["clips"]


def test_vision_requests_respect_limits(env):
    calls = env["ai"]["calls"]
    assert any(c["images"] == 2 for c in calls if c["kind"] == "editor")
    assert all(c["images"] <= 5 for c in calls)


def test_zz_compare_v1_v2(env):
    """V1 (loudness + fixed 30 s windows, keep if signal score >= 6/10) vs V2 on the same footage."""
    v1_settings = {"clip_length": 30, "max_clips_per_hour": 10, "min_signal": 2.0, "chat_delay_sec": 7}
    rows = []
    for name, fx in fixtures.FIXTURES.items():
        path, chat_path = fixtures.make(name, os.path.join(os.path.dirname(__file__), ".media"))
        msgs = []
        if chat_path:
            with open(chat_path) as f:
                msgs = [(json.loads(l)["t"], json.loads(l)["m"]) for l in f]
        cands = analyze_v1.find_candidates(path, 0, fx["duration"], msgs, v1_settings, [], True)
        v1_kept = sum(1 for c in cands if round(3 + c["signal"]) >= 6)
        r = RESULTS.get(name)
        v2_kept = len(r["kept"]) if r else None
        v2_top = sum(1 for c in r["kept"] if c["status"] == "ready") if r else None
        v2_judged = len(r["clips"]) if r else None
        lengths = ", ".join(f"{c['clip_out'] - c['clip_in']:.0f}s" for c in r["kept"]) if r else ""
        if name == "clutch" and r and r["kept"]:
            lengths = f"{r['kept'][0]['analysis_json']['bounds_final']['end'] - r['kept'][0]['analysis_json']['bounds_final']['setup_start']:.0f}s (before the editor test trimmed it)"
        rows.append((name, fx["expect"], len(cands), v1_kept, v2_judged, v2_kept, v2_top, lengths))
    out = ["| Footage | Expected | V1 moments | V1 clips (fixed 30 s) | V2 moments judged | V2 clips kept | "
           "V2 top picks | V2 clip lengths |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| " + " | ".join("—" if v is None else str(v) for v in r) + " |")
    os.makedirs(os.path.join(os.path.dirname(__file__), "results"), exist_ok=True)
    with open(os.path.join(os.path.dirname(__file__), "results", "comparison.md"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("\n" + "\n".join(out))
