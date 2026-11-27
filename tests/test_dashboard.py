"""Results pages model: matching by name across elections, and the two swings."""

import json

from factory import analysis, booth, cand, district, region

from vicresults.dashboard import build_model, empty_model, norm
from vicresults.serve import build_site, page_html


def _base():
    a = [cand(1, "RED, Ann", "labor", 600), cand(2, "BLUE, Bob", "liberal", 400)]
    b1 = booth(10, "Town Hall", [cand(1, "RED, Ann", "labor", 300), cand(2, "BLUE, Bob", "liberal", 100)])
    b2 = booth(11, "Primary School", [cand(1, "RED, Ann", "labor", 300), cand(2, "BLUE, Bob", "liberal", 300)])
    d = district(100, "Alpha District", a, tcp=a, booths=[b1, b2])
    r = region(0, "North Region", [("Labor", "labor", 500), ("Other Party", None, 500)])
    return analysis([d], [r])


def _cur():
    # New ids everywhere, a new party, one booth back so far, one brand-new booth.
    a = [cand(901, "RED, Zed", "labor", 150), cand(902, "BLUE, Yan", "liberal", 150), cand(903, "PINK, Xi", "socialists", 100)]
    b1 = booth(910, "TOWN  HALL", [cand(901, "RED, Zed", "labor", 100), cand(902, "BLUE, Yan", "liberal", 50), cand(903, "PINK, Xi", "socialists", 50)])
    b3 = booth(912, "New Estate", [cand(901, "RED, Zed", "labor", 50), cand(902, "BLUE, Yan", "liberal", 100), cand(903, "PINK, Xi", "socialists", 50)])
    d = district(500, "Alpha District", a, tcp=a[:2], booths=[b1, b3])
    d["pollingDistrictIdentifier"]["regionId"] = 801
    r = region(800, "North Region", [("Labor", "labor", 300), ("Other Party", None, 700)])
    out = analysis([d], [r], lh_file="State2026mediafilelitepplh.zip")
    out["pollingLocations"] = {"pollingDistrictList": {"pollingDistrict": [{
        "pollingDistrictIdentifier": {"id": 501, "name": "Alpha District"},
        "pollingPlaces": {"pollingPlace": [{"pollingPlaceIdentifier": {"id": i, "name": n}} for i, n in
                                           [(910, "Town Hall"), (911, "Primary School"), (912, "New Estate")]]}}]}}
    return out


def test_norm():
    assert norm("Albert Park District") == norm("albert  park") == "albertpark"
    assert norm("North-Eastern Metropolitan Region") == "northeasternmetropolitan"
    assert norm("South Melbourne Park (HJVC)") == norm("South Melbourne Park")


def test_matching_and_swings():
    m = build_model(_cur(), _base())
    assert m["meta"]["match"]["districtsUnmatched"] == []
    assert m["meta"]["match"]["booths"] == 2 and m["meta"]["match"]["boothsMatched"] == 1
    assert m["meta"]["sample"] is False
    d = m["districts"][0]
    assert d["region"] == m["regions"][0]["id"] == "north"
    by = {c["k"]: c for c in d["cands"]}
    # raw: 150/400 = 37.5% now against 60% at the 2022 final
    assert by["labor"]["raw"] == -22.5
    # like-for-like: only Town Hall matches. 100/200 = 50% now, 300/400 = 75% then
    assert by["labor"]["sw"] == -25.0
    assert by["liberal"]["sw"] == 0.0
    assert by["socialists"]["new"] is True and by["socialists"]["sw"] == 25.0
    assert d["matched"] == 50.0
    names = [b["n"] for b in d["booths"]]
    assert names == ["New Estate", "TOWN  HALL", "Primary School"]
    waiting = d["booths"][2]
    assert waiting["w"] == 1 and waiting["bf"] == 600
    assert "bv" not in d["booths"][0]  # new booth: no baseline
    assert d["tcp"]["same"] is True and d["lead"] in ("labor", "liberal") and d["held"] == "labor"
    low = {r["k"]: r for r in m["state"]["lower"]["rows"]}
    assert low["labor"]["sw"] == -25.0 and low["labor"]["held"] == 1


def test_upper_house_swing_and_quota():
    m = build_model(_cur(), _base())
    u = m["regions"][0]["upper"]
    rows = {r["k"]: r for r in u["rows"]}
    assert rows["labor"]["p"] == 30.0 and rows["labor"]["raw"] == -20.0
    assert u["quota"] == 1000 // 6 + 1
    assert rows["labor"]["q"] == round(300 / u["quota"], 3)


def test_different_tcp_pair_gives_no_tcp_swing():
    cur = _cur()
    d = cur["lowerHouse"]["mediaFeed"]["election"]["house"]["contests"]["contest"][0]
    d["twoCandidatePreferred"]["candidate"] = [d["firstPreferences"]["candidate"][0], d["firstPreferences"]["candidate"][2]]
    t = build_model(cur, _base())["districts"][0]["tcp"]
    assert t["same"] is False and all(c["sw"] is None for c in t["c"])


def test_no_baseline_and_empty_feed_still_build():
    m = build_model(_cur(), None)
    assert m["districts"][0]["cands"][0]["sw"] is None
    cur = _cur()
    for c in cur["lowerHouse"]["mediaFeed"]["election"]["house"]["contests"]["contest"]:
        c["pollingPlaces"] = None  # as in the 6 pm file
        c.pop("twoCandidatePreferred", None)
    json.dumps(build_model(cur, _base()))
    assert empty_model("x")["meta"]["waiting"] is True


def test_build_site(tmp_path):
    build_site(_cur(), _base(), tmp_path)
    assert json.loads((tmp_path / "data.json").read_text())["districts"][0]["name"] == "Alpha"
    assert "<title>" in page_html()
