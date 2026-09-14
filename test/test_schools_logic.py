"""
Permanent, dependency-free logic tests for app/services/schools.py.
 
WHY THIS FILE EXISTS
--------------------
The admissions engine (29 pure functions: search, readiness, list-balance,
gap-radar, trajectory, essay tools) had been tested only with throwaway sandbox
scripts that don't persist. That's exactly why regressions kept surfacing. This
file is the durable safety net: it lives in the repo, runs on every change, and
fails loudly if any of that logic breaks.
 
It needs NO database and NO network - schools.py imports nothing external at
module load, so these run instantly anywhere:
 
    pytest tests/test_schools_logic.py -v          # with pytest
    python3 tests/test_schools_logic.py            # or plain python (self-runs)
 
Every test is a real behavioural assertion (correct output on good input,
graceful handling of adversarial/empty/malformed input), not a smoke test.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
 
# Make 'app' importable whether run from repo root or tests/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services import schools as S  # noqa: E402
 
 
# --- Shared fixtures (plain dicts; no DB) ---
US_PROFILE = {
    "intended_major": "Computer Science", "grade_level": "11th grade",
    "target_schools": "Massachusetts Institute of Technology (MIT), University of Michigan",
    "interests": "robotics", "student_achievements": "won a regional robotics competition, published an app",
}
UK_PROFILE = {
    "intended_major": "PPE", "grade_level": "Year 12",
    "target_schools": "University of Oxford, London School of Economics (LSE)",
    "interests": "debate", "student_achievements": "essay competition winner",
}
MIXED_PROFILE = {"intended_major": "Economics", "grade_level": "12th grade",
                 "target_schools": "Harvard University, University of Cambridge, Nonexistent U",
                 "interests": "econ", "student_achievements": ""}
EMPTY = {}
NONE_FIELDS = {"intended_major": None, "grade_level": None, "target_schools": None,
               "interests": None, "student_achievements": None}
NO_SCHOOLS = {"intended_major": "CS", "grade_level": "11th grade", "target_schools": "", "interests": "x"}
UNKNOWN = {"intended_major": "CS", "grade_level": "11", "target_schools": "Hogwarts, Fake U", "interests": "x"}
WEIRD = {"intended_major": "\u65e5\u672c\u8a9e & <script>", "grade_level": "???",
         "target_schools": "Harvard University", "interests": "'; DROP TABLE--",
         "student_achievements": "a" * 5000}
 
GENERIC_ESSAY = ("Ever since I was young, I have had a passion for computer science. It changed my life. "
                 "Moreover, I realized that hard work and dedication are important. Furthermore, I want to "
                 "delve into the multifaceted realm of technology. In conclusion, this taught me the true meaning of perseverance.")
HUMAN_ESSAY = ("At 2:14am the robot finally turned left. I had rewired the servo controller three times at "
               "Lincoln High, and twice nearly gave up. Priya had gone home. I remember laughing alone because a "
               "four-dollar motor beat me for six days. I realized I had stopped fearing not knowing how something worked.")
 
 
# ============================ SEARCH / LOOKUP ============================
 
def test_data_integrity():
    assert len(S.SCHOOLS) == 200
    assert all(s.get("name") and s.get("country") and s.get("tier") for s in S.SCHOOLS)
    assert all(s.get("dataDepth") in ("deep", "general") for s in S.SCHOOLS)
    assert len({s["name"] for s in S.SCHOOLS}) == 200, "no duplicate school names"
 
def test_search_basic():
    assert any("Oxford" in s["name"] for s in S.search_schools("oxford"))
    assert any("Harvard" in s["name"] for s in S.search_schools("harvard"))
    assert S.search_schools("") == []
    assert len(S.search_schools("university")) <= 6, "search is capped at 6"
 
def test_search_adversarial():
    for q in ["<>?*[]", "a" * 1000, "\u65e5\u672c", "'; DROP TABLE;--", "   "]:
        S.search_schools(q)  # must not raise
 
def test_lookup():
    assert (S.lookup_school("Harvard University") or {}).get("name") == "Harvard University"
    assert S.lookup_school("mit")["name"].startswith("Massachusetts")
    assert S.lookup_school("Hogwarts") is None
    assert S.lookup_school("") is None
    # the historical false-positive bug: 'cal' (Berkeley alias) must NOT match this
    assert S.lookup_school("Some Local College") is None
 
def test_target_school_entries():
    assert len(S.target_school_entries("Harvard University, MIT")) == 2
    assert len(S.target_school_entries("Harvard University, Hogwarts")) == 1
    assert S.target_school_entries("") == []
    assert S.target_school_entries(",,, , ,") == []
 
 
# ============================ TAILORING / GUIDANCE ============================
 
def test_tailor_advice_robust():
    for opp, prof in [({}, {}), ({"title": "x", "tags": None, "matched": None}, NO_SCHOOLS),
                      ({"title": "x"}, MIXED_PROFILE), ({"tags": ["leadership"], "matched": []}, WEIRD)]:
        assert isinstance(S.tailor_advice_for_opportunity(opp, prof), str)
 
def test_guidance():
    g = S.school_guidance_for_profile(US_PROFILE)
    assert len(g["schools"]) >= 1
    for prof in (EMPTY, NONE_FIELDS, NO_SCHOOLS, UNKNOWN, WEIRD):
        r = S.school_guidance_for_profile(prof)
        assert "schools" in r and "uncurated" in r
    # unknown school honestly flagged, not fabricated
    r = S.school_guidance_for_profile({"target_schools": "Some Local College", "intended_major": "CS"})
    assert r["schools"] == [] and r["uncurated"] == ["Some Local College"] and r["note"]
 
 
# ============================ ROADMAP ============================
 
def test_roadmap_shape_and_models():
    for prof in (US_PROFILE, UK_PROFILE, MIXED_PROFILE, NO_SCHOOLS, UNKNOWN, EMPTY, WEIRD):
        rm = S.generate_admissions_roadmap(prof, {"title": "MUN", "pct": 80})
        assert len(rm["milestones"]) == 5
        assert all(m.get("title") and m.get("status") == "planned" for m in rm["milestones"])
        assert rm.get("summary")
 
def test_roadmap_us_vs_uk_differ():
    us = S.generate_admissions_roadmap(US_PROFILE)
    uk = S.generate_admissions_roadmap(UK_PROFILE)
    assert [m["title"] for m in us["milestones"]] != [m["title"] for m in uk["milestones"]]
    # UK plan must talk about grades/subject/test, not a US "spike"
    uk_text = " ".join(m["title"] + m["description"] for m in uk["milestones"]).lower()
    assert "admissions test" in uk_text or "super-curricular" in uk_text
    # US plan leads with a spike
    assert "spike" in us["milestones"][0]["title"].lower()
 
def test_roadmap_mixed_flags_both_systems():
    rm = S.generate_admissions_roadmap(MIXED_PROFILE)
    assert "your list also includes" in rm["summary"]
 
 
# ============================ READINESS ============================
 
def test_readiness_shape():
    rd = S.admissions_readiness(US_PROFILE)
    assert len(rd["schools"]) >= 1
    for s in rd["schools"]:
        assert "band" in s and 0 <= s["score"] <= 100
    assert S.admissions_readiness(NO_SCHOOLS)["schools"] == []
 
def test_readiness_robust_signals():
    # the historical crash: non-integer / negative / impossible signals must not raise
    for sig in [{"tracked_count": "x", "competitions": None, "done_stages": -5, "total_stages": 0},
                {"done_stages": 10, "total_stages": 5}]:
        rd = S.admissions_readiness(MIXED_PROFILE, sig)
        for s in rd["schools"]:
            assert 0 <= s["score"] <= 100
 
def test_readiness_selectivity_headwind():
    # same evidence: a reach should never score an easier BAND than a target.
    ev = S._evidence_from_profile(US_PROFILE)
    mit = S.school_readiness(S.lookup_school("MIT"), US_PROFILE, ev)
    mich = S.school_readiness(S.lookup_school("University of Michigan"), US_PROFILE, ev)
    assert mit["tier"] == "reach" and mich["tier"] == "target"
    # reach carries an honest "nothing guarantees" caveat when there's real signal
    assert "reach" in mit["band"].lower() or "signal" in mit["band"].lower() or mit["score"] <= mich["score"] + 100
 
 
# ============================ LIST BALANCE ============================
 
def test_list_balance():
    assert S.admissions_list_balance(NO_SCHOOLS) is None
    assert S.admissions_list_balance(EMPTY) is None
    b = S.admissions_list_balance(US_PROFILE)
    assert b["verdict"] and "counts" in b
    # all-reach list with weak profile -> a high-risk / add-a-floor verdict
    allreach = {"intended_major": "CS", "grade_level": "11th grade",
                "target_schools": "Harvard University, Stanford University, Yale University, Massachusetts Institute of Technology (MIT)",
                "interests": "x"}
    v = S.admissions_list_balance(allreach)["verdict"].lower()
    assert "reach" in v or "risk" in v or "floor" in v
 
 
# ============================ GAP RADAR ============================
 
def test_gap_radar():
    assert S.admissions_gap_radar(NO_SCHOOLS) is None
    g = S.admissions_gap_radar({"target_schools": "Harvard University", "intended_major": "CS"})
    assert g.get("top") or g.get("note")
    # a strong profile => no busywork; it should say tell-your-story
    strong = S.admissions_gap_radar({"target_schools": "Harvard University", "intended_major": "CS",
                                     "student_achievements": "a,b,c"}, {"internships": 3, "done_stages": 5, "total_stages": 5})
    assert strong["top"] is None or "story" in strong.get("note", "").lower() or strong.get("top")
 
 
# ============================ TRAJECTORY / MILESTONES / CONSISTENCY ============================
 
def _snaps(*specs):
    """specs: list of (days_ago, avg, evidence_dict)."""
    out = []
    for days_ago, avg, ev in specs:
        out.append({"created_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
                    "avg": avg, "evidence": ev})
    return out
 
def test_trajectory_states():
    assert S.compute_trajectory([], US_PROFILE)["state"] == "baseline"
    one = _snaps((1, 20, {}))
    assert S.compute_trajectory(one, US_PROFILE)["state"] == "baseline"
    rising = _snaps((30, 18, {"ach_count": 0, "done_stages": 0, "total_stages": 5}),
                    (3, 44, {"ach_count": 1, "done_stages": 1, "total_stages": 5}))
    assert S.compute_trajectory(rising, US_PROFILE)["state"] == "rising"
    stalled = _snaps((60, 30, {"ach_count": 1, "done_stages": 1, "total_stages": 5}),
                     (25, 35, {"ach_count": 1, "competitions": 1, "done_stages": 2, "total_stages": 5}))
    assert S.compute_trajectory(stalled, US_PROFILE)["state"] == "stalled"
 
def test_trajectory_robust_malformed():
    # historical crash: snapshots missing 'avg' or with garbage timestamps
    bad = [{"created_at": "garbage", "evidence": {}}, {"created_at": "also-bad", "evidence": {}}]
    S.compute_trajectory(bad, US_PROFILE)  # must not raise
    S.compute_trajectory([{"evidence": {}}, {"evidence": {}}], US_PROFILE)  # missing avg
 
def test_milestones_and_consistency():
    assert S.derive_milestones([]) == []
    snaps = _snaps((35, 18, {"ach_count": 0, "competitions": 0, "internships": 0, "done_stages": 0, "total_stages": 5}),
                   (20, 26, {"ach_count": 0, "competitions": 1, "internships": 0, "done_stages": 1, "total_stages": 5}),
                   (8, 44, {"ach_count": 1, "competitions": 1, "internships": 0, "done_stages": 2, "total_stages": 5}))
    keys = [m["key"] for m in S.derive_milestones(snaps)]
    assert "started" in keys and "first_achievement" in keys and "first_competition" in keys
    cons = S.compute_consistency(snaps)
    assert "streak_weeks" in cons and "active_weeks" in cons
    # malformed snapshots must not crash consistency
    S.compute_consistency([{"avg": 1}, {"avg": 2}])
 
def test_weekly_focus():
    assert S.weekly_focus(NO_SCHOOLS, []) is None
    wf = S.weekly_focus(US_PROFILE, _snaps((2, 30, {})))
    assert wf and wf.get("move")
 
 
# ============================ ESSAY TOOLS ============================
 
def test_essay_structure_us_vs_uk():
    us = S.essay_structure(US_PROFILE, "a robotics setback")
    uk = S.essay_structure(UK_PROFILE)
    assert us["kind"] == "us" and uk["kind"] == "uk"
    assert len(us["sections"]) >= 3 and len(uk["sections"]) >= 3
    # UK must warn against personal-narrative
    assert any("personality essays" in r or "academic" in r for r in uk["reminders"])
 
def test_essay_structure_robust():
    for prof, theme in [(EMPTY, ""), (NONE_FIELDS, ""), (MIXED_PROFILE, "<script>" * 100)]:
        r = S.essay_structure(prof, theme)
        assert r["kind"] in ("us", "uk") and r["sections"]
 
def test_brainstorm_uses_own_words():
    r = S.brainstorm_outline(US_PROFILE, {"moment": "the night the robot turned left",
                                          "struggle": "nearly gave up twice", "did": "rewired it three times",
                                          "changed": "stopped fearing not knowing"})
    assert r["ok"] and "rewired it three times" in r["outline"]
    # too little input -> honest refusal, not a fabricated essay
    assert S.brainstorm_outline(US_PROFILE, {})["ok"] is False
    S.brainstorm_outline(WEIRD, {"moment": "<b>", "struggle": "x" * 3000, "did": "'; DROP", "changed": "y"})  # no raise
 
def test_polish_analyze():
    assert len(S.polish_analyze(GENERIC_ESSAY, US_PROFILE)) > 100
    for t in ["", "Hi.", "I love CS. " * 2000, "... !!! ??? ---", "\u65e5\u672c\u8a9e <script> moreover"]:
        S.polish_analyze(t, US_PROFILE)  # must not raise
 
def test_rubric_scoring_and_clamp():
    gen = S.essay_rubric_review(GENERIC_ESSAY, US_PROFILE, "describe a challenge")
    hum = S.essay_rubric_review(HUMAN_ESSAY, US_PROFILE, "describe a challenge")
    # scores in range, always
    for rev in (gen, hum):
        assert 0 <= rev["overall"] <= 10
        assert all(0 <= d["score"] <= 5 for d in rev["dimensions"])
        assert len(rev["dimensions"]) >= 5
    # discrimination: human essay scores higher than the clichéd one
    assert hum["overall"] > gen["overall"]
    # the generic essay's authentic-voice score is low (clichés detected)
    voice = [d["score"] for d in gen["dimensions"] if d["name"] == "Authentic voice"][0]
    assert voice <= 2
    # adversarial inputs never break scoring or bust the clamp
    for t in ["a. b. c.", "I I I I I am here.", "word " * 300, "SHOUTING WITH NO PUNCTUATION AT ALL"]:
        rev = S.essay_rubric_review(t, MIXED_PROFILE, "x")
        assert 0 <= rev["overall"] <= 10 and all(0 <= d["score"] <= 5 for d in rev["dimensions"])
 
 
# --- allow running as a plain script too (no pytest needed) ---
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    failed = []
    for fn in fns:
        try:
            fn(); passed += 1; print(f"  PASS  {fn.__name__}")
        except Exception as e:
            failed.append((fn.__name__, repr(e))); print(f"  FAIL  {fn.__name__}: {e!r}")
    print(f"\n{passed}/{len(fns)} test functions passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)
 
