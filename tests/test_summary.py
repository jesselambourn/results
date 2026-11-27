import pytest

from vicresults import summary
from vicresults.client import AnalysisClient, is_sample

from factory import analysis, booth, cand, district, region


@pytest.fixture
def data():
    a = cand(1, "SMITH, A", "labor", 500)
    b = cand(2, "JONES, B", "greens", 300)
    s = cand(3, "RED, C", "socialists", 200)
    d1 = district(10, "Footscray District", [a, b, s],
                  tcp=[dict(a, votes=550), dict(b, votes=450)],
                  booths=[booth(77, "Footscray Town Hall", [a, b, s])])
    d2 = district(20, "Empty District", [cand(4, "X, Y", None, 0)])
    r1 = region(30, "Western Metropolitan Region",
                [("Victorian Socialists", "socialists", 300), ("Labor", "labor", 700)],
                quota=167, ungrouped=[cand(5, "LONE, R", None, 0)])
    return analysis([d1, d2], [r1])


def test_districts(data):
    rows = {r["district"]: r for r in summary.lower_house_districts(data)}
    f = rows["Footscray District"]
    assert f["formal"] == 1000 and f["leader_party"] == "labor" and f["leader_pct"] == 50.0
    assert f["socialists_pct"] == 20.0 and f["socialists_rank"] == 3
    assert f["tcp_leader_party"] == "labor" and f["tcp_leader_pct"] == 55.0 and f["tcp_runner_up_party"] == "greens"
    e = rows["Empty District"]
    assert e["leader"] is None and e["socialists_pct"] is None and e["tcp_leader"] is None


def test_candidates_and_booths(data):
    c = summary.lower_house_candidates(data)
    assert {r["candidate"] for r in c} >= {"SMITH, A", "RED, C"}
    smith = next(r for r in c if r["candidate"] == "SMITH, A")
    assert smith["ordinary"] == 500 and smith["evcEarly"] is None and smith["tcp_votes"] == 550
    b = summary.lower_house_booths(data)
    assert len(b) == 3 and b[0]["booth"] == "Footscray Town Hall" and b[0]["pct"] == 50.0


def test_upper_and_party_totals(data):
    g = {r["party"]: r for r in summary.upper_house_groups(data) if r["party"]}
    assert g["socialists"]["pct"] == 30.0 and g["socialists"]["quotas"] == round(300 / 167, 3)
    lower = {r["party"]: r for r in summary.party_totals(data, "lower")}
    assert lower["socialists"]["votes"] == 200 and lower["other"]["votes"] == 0
    upper = {r["party"]: r for r in summary.party_totals(data, "upper")}
    assert upper["labor"]["pct"] == 70.0


def test_changed_and_sample(data):
    import copy
    later = copy.deepcopy(data)
    later["lowerHouse"]["mediaFeed"]["election"]["house"]["contests"]["contest"][1]["firstPreferences"]["total"]["votes"] = 99
    assert summary.changed_districts(data, later) == ["Empty District"]
    assert summary.changed_districts(None, data) == []
    assert is_sample(data)


def test_client_guards(monkeypatch):
    monkeypatch.delenv("ANALYSIS_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        AnalysisClient()
    with pytest.raises(ValueError):
        AnalysisClient(token="t", base_url="https://example.vercel.app")
    c = AnalysisClient(token="secret-value", timeout=5)
    assert c.timeout == 30.0 and "secret-value" not in repr(c)
    with pytest.raises(ValueError):
        c.analysis("9pm")


def test_droop_quota_when_vec_leaves_it_empty():
    d = analysis([], [region(30, "R", [("A", "socialists", 600)], quota=None)])
    r = summary.upper_house_groups(d)[0]
    assert r["quota"] == 101 and r["quota_source"] == "droop" and r["quotas"] == round(600 / 101, 3)
