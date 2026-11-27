import gzip
import json

from vicresults import poll
from vicresults.client import AuthError, NotReadyError, SchemaMismatchError

from factory import analysis, cand, district, region


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def analysis(self, sample=None):
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def test_poll_sequence(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(poll.time, "sleep", lambda s: sleeps.append(s))
    d = analysis([district(1, "A District", [cand(1, "X", "labor", 5)])], [region(2, "R", [("G", None, 1)])])
    d2 = json.loads(json.dumps(d))
    d2["files"]["lowerHouse"] = "State2026mediafilelitepplh_new.zip"
    fake = FakeClient([
        NotReadyError(404, "no files"),
        d, d,
        SchemaMismatchError(500, "mismatch", {"error": "mismatch", "issues": [{"path": "a", "message": "b"}]}),
        d2,
        AuthError(401, "bad token"),
    ])
    lines = []
    code = poll.run(tmp_path, client=fake, interval=1, log=lines.append)
    assert code == 2 and fake.calls == 6
    assert all(s <= 60 for s in sleeps) and len(sleeps) == 5
    assert len(list((tmp_path / "snapshots").glob("*.json.gz"))) >= 1
    latest = json.loads(gzip.decompress((tmp_path / "latest.json.gz").read_bytes()))
    assert latest["files"]["lowerHouse"].startswith("State2026")
    assert list((tmp_path / "issues").glob("*.json"))
    text = "\n".join(lines)
    assert "404" in text and "unchanged" in text and "TELL ANGUS" in text and text.count("NEW FEED") == 2
    assert (tmp_path / "csv" / "lower_districts.csv").exists()
    assert "Bearer" not in (tmp_path / "poll.log").read_text()
