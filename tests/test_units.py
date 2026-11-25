"""Fast unit tests for the rules that decide what gets clipped and how."""
from core import ai, config, db, learning, media, pipeline, profiles, render

S = dict(config.DEFAULTS)


def test_bounds_are_clamped_ordered_and_within_length_limits():
    b = ai.fix_bounds({"setup_start": -5, "key_action": 40, "payoff": 38, "end": 300}, 90, 40, S)
    assert 0 <= b["setup_start"] <= b["key_action"] <= b["payoff"] <= b["end"] <= 90
    assert S["min_clip_sec"] <= b["end"] - b["setup_start"] <= S["max_clip_sec"]
    short = ai.fix_bounds({"setup_start": 40, "key_action": 41, "payoff": 41.5, "end": 42}, 90, 41, S)
    assert short["end"] - short["setup_start"] >= S["min_clip_sec"]
    junk = ai.fix_bounds({"setup_start": "?", "key_action": None}, 90, 50, S)
    assert junk["key_action"] == 50


def test_rubric_scores_are_capped_per_criterion():
    sc = ai._clamp_scores({"significance": 99, "hook": -4, "reaction": "12", "visual": "x"})
    assert sc == {"significance": 25, "hook": 0, "reaction": 12, "retention": 0, "standalone": 0, "visual": 0}
    assert sum(ai.RUBRIC.values()) == 100


def test_rule_engine_rejects_unverifiable_and_ordinary_moments():
    a = {"category": "clutch", "is_highlight": True, "used_vision": False, "rejection_reasons": [],
         "scores": {"significance": 20, "hook": 15, "reaction": 15, "retention": 12, "standalone": 8, "visual": 5}}
    assert pipeline.rule_check(a, [], [], S) == ["cannot verify (not enough evidence)"]
    assert pipeline.rule_check(a, [[0, 1, "hi"]], [], S) == []
    weak = dict(a, scores=dict(a["scores"], significance=5, hook=3))
    assert {"ordinary gameplay", "weak opening"} <= set(pipeline.rule_check(weak, [[0, 1, "x"]], [], S))


def test_dead_air_only_cuts_quiet_wordless_unprotected_gaps():
    words = [[1, 1.5, "okay"], [1.5, 2, "watch"], [6, 6.5, "NO"], [6.5, 7, "WAY"], [12, 12.5, "bro"]]
    wave = [0.8] * 80
    for i in range(int(2.2 / 0.25), int(5.8 / 0.25)):
        wave[i] = 0.2                                      # quiet stretch between 2 s and 6 s
    keep, cuts = render.dead_air(0.5, 14, words, wave, [], protect=[(9, 13)])
    assert len(cuts) == 1 and 2.0 < cuts[0][0] < cuts[0][1] < 6.0
    keep2, cuts2 = render.dead_air(0.5, 14, words, wave, [], protect=[(4, 8)])
    assert cuts2 == [], "never cut into the build-up before the key action"
    rt = render.retime_words(words, keep)
    assert rt[2][0] < 6 - (cuts[0][1] - cuts[0][0]) + 0.01 and len(rt) == len(words)


def test_webcam_needs_a_face_that_stays_put():
    stable = [(i, 0.88, 0.82, 0.06, 0.1) for i in range(9)] + [(2, 0.4, 0.5, 0.1, 0.1)]
    box = media.webcam_from_detections(stable, 12)
    assert box and box["box"][0] + box["box"][2] <= 1.0 and box["confidence"] >= 0.7
    roaming = [(i, 0.1 * i, 0.5, 0.06, 0.1) for i in range(9)]
    assert media.webcam_from_detections(roaming, 12) is None
    fullscreen = [(i, 0.5, 0.4, 0.4, 0.5) for i in range(9)]
    assert media.webcam_from_detections(fullscreen, 12) is None


def test_profiles_detect_from_title():
    assert profiles.detect("GTA 6 FIRST DAY - Vice City chaos") == "open_world"
    assert profiles.detect("Valorant ranked grind") == "fps"
    assert profiles.detect("Late night podcast IRL") == "just_chatting"
    assert profiles.detect("random stream") == "general"
    assert profiles.resolve("horror", "GTA 6") == "horror"


def test_facecam_geometry_stays_inside_the_frame():
    g = render.geometry({"layout": "facecam", "aspect": "9:16", "cam_box": [0.8, 0.75, 0.2, 0.25], "focus_x": 0.9},
                        1920, 1080)
    assert g["layout"] == "facecam" and 0.26 * 1920 <= g["cam_h"] <= 0.40 * 1920
    assert render.geometry({"layout": "facecam", "aspect": "9:16"}, 1920, 1080)["layout"] == "blur"
    assert render.geometry({"layout": "crop", "aspect": "16:9"}, 1920, 1080)["layout"] == "fit"


def test_captions_highlight_and_emphasise():
    g = render.geometry({"layout": "blur", "aspect": "9:16"}, 1920, 1080)
    ass = render.build_ass([[0, 0.4, "no"], [0.4, 0.8, "way"], [0.8, 1.2, "INSANE"]], "Hook 😂", 3, 2, g,
                           {"caption_style": "bold", "emphasis_words": ["way"]}, S)
    assert "Style: Cap" in ass and "HOOK" in ass and "😂" not in ass
    assert render.STYLES["bold"]["emph"] in ass and render.STYLES["bold"]["hi"] in ass
    off = render.build_ass([[0, 1, "hi"]], "", 3, 2, g, {"captions": False}, S)
    assert "Dialogue: 0" not in off


def test_learning_needs_real_data_and_is_capped(tmp_path):
    db.init()
    assert learning.adjustment("funny fail") == (0, "")
    ids = []
    for i, (cat, views) in enumerate([("funny fail", 40000), ("funny fail", 50000), ("funny fail", 45000),
                                      ("clutch", 2000), ("clutch", 3000), ("clutch", 2500), ("clutch", 1000)]):
        cid = db.execute("INSERT INTO clips (category, status, quality) VALUES (?, 'approved', 80)", (cat,))
        learning.add_result(cid, {"views": views, "platform": "TikTok"})
        ids.append(cid)
    adj, note = learning.adjustment("funny fail")
    assert adj == 5 and "outperform" in note
    assert learning.adjustment("clutch")[0] < 0
    assert "funny fail" in learning.insights_text()
    for cid in ids:
        db.execute("DELETE FROM results WHERE clip_id=?", (cid,))
        db.execute("DELETE FROM clips WHERE id=?", (cid,))


def test_csv_import_accepts_common_column_names():
    db.init()
    cid = db.execute("INSERT INTO clips (category, status, quality) VALUES ('clutch', 'approved', 90)")
    out = learning.import_csv(f"Video title,Views,Average percentage viewed (%),Likes\n"
                              f"88q_ducky_NO_WAY_{cid}.mp4,\"1,200\",55%,80\nno id here,5,5,5\n")
    assert out["added"] == 1 and len(out["skipped"]) == 1
    r = db.one("SELECT * FROM results WHERE clip_id=?", (cid,))
    assert r["views"] == 1200 and r["avg_pct_viewed"] == 55
    db.execute("DELETE FROM results WHERE clip_id=?", (cid,))
    db.execute("DELETE FROM clips WHERE id=?", (cid,))
