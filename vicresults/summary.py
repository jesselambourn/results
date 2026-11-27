"""Turn an Analysis response into flat rows (lists of dicts) for display and analysis.

All percentages are of formal votes, rounded to 2 dp. Party keys come from the
API's join: socialists, greens, labor, liberal, nationals, oneNation, or None.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

VOTE_TYPES = (
    "ordinary", "early", "evcEarly", "postal", "absent",
    "provisional", "markedAsVoted", "mobileVotingEarly",
)


def _pct(n: int | None, d: int | None) -> float | None:
    return round(100.0 * n / d, 2) if n is not None and d else None


def _lh_contests(data: dict[str, Any]) -> list[dict[str, Any]]:
    return data["lowerHouse"]["mediaFeed"]["election"]["house"]["contests"]["contest"]


def _uh_contests(data: dict[str, Any]) -> list[dict[str, Any]]:
    return data["upperHouse"]["mediaFeed"]["election"]["senate"]["contests"]["contest"]


def _cand(c: dict[str, Any]) -> dict[str, Any]:
    ci = c["candidateIdentifier"]
    return {
        "candidate_id": ci["id"],
        "candidate": ci.get("name") or ci.get("candidateName"),
        "party": ci.get("party"),
        "affiliation": ci.get("affiliationName"),
    }


def feed_info(data: dict[str, Any]) -> dict[str, Any]:
    lh = data["lowerHouse"]["mediaFeed"]
    uh = data["upperHouse"]["mediaFeed"]
    return {
        "files": data.get("files"),
        "phase": lh.get("phase"),
        "lower_created": lh.get("created"),
        "upper_created": uh.get("created"),
        "event": lh.get("eventIdentifier", {}).get("eventName"),
    }


def lower_house_districts(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per Legislative Assembly district."""
    rows = []
    for c in _lh_contests(data):
        fp = c["firstPreferences"]
        formal = fp["formal"]["votes"]
        cands = sorted(fp.get("candidate") or [], key=lambda x: -x["votes"])
        leader = cands[0] if cands and cands[0]["votes"] > 0 else None
        soc = next((x for x in cands if x["candidateIdentifier"].get("party") == "socialists"), None)
        tcp = c.get("twoCandidatePreferred") or {}
        tcp_c = sorted(tcp.get("candidate") or [], key=lambda x: -x["votes"])
        tcp_total = sum(x["votes"] for x in tcp_c)
        pdi = c["pollingDistrictIdentifier"]
        row = {
            "district_id": pdi["id"],
            "district": pdi["name"],
            "region_id": pdi.get("regionId"),
            "declared": c["declared"],
            "updated": c.get("updated") or fp.get("updated"),
            "enrolment": c["enrolment"],
            "formal": formal,
            "informal": fp["informal"]["votes"],
            "total": fp["total"]["votes"],
            "turnout_pct": _pct(fp["total"]["votes"], c["enrolment"]),
            "informal_pct": _pct(fp["informal"]["votes"], fp["total"]["votes"]),
            "booths_returned": fp["pollingPlacesReturned"],
            "booths_expected": fp["pollingPlacesExpected"],
            "leader": _cand(leader)["candidate"] if leader else None,
            "leader_party": _cand(leader)["party"] if leader else None,
            "leader_pct": _pct(leader["votes"], formal) if leader else None,
            "socialists_candidate": _cand(soc)["candidate"] if soc else None,
            "socialists_votes": soc["votes"] if soc else None,
            "socialists_pct": _pct(soc["votes"], formal) if soc else None,
            "socialists_rank": (cands.index(soc) + 1) if soc and soc["votes"] > 0 else None,
            "tcp_maverick": bool(tcp.get("maverick")),
            "tcp_booths_returned": tcp.get("pollingPlacesReturned"),
            "tcp_leader": None, "tcp_leader_party": None, "tcp_leader_pct": None,
            "tcp_runner_up": None, "tcp_runner_up_party": None,
        }
        if len(tcp_c) == 2 and tcp_total:
            a, b = _cand(tcp_c[0]), _cand(tcp_c[1])
            row.update(
                tcp_leader=a["candidate"], tcp_leader_party=a["party"],
                tcp_leader_pct=_pct(tcp_c[0]["votes"], tcp_total),
                tcp_runner_up=b["candidate"], tcp_runner_up_party=b["party"],
            )
        rows.append(row)
    return rows


def lower_house_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per district candidate, with first preferences by vote type."""
    rows = []
    for c in _lh_contests(data):
        fp = c["firstPreferences"]
        formal = fp["formal"]["votes"]
        pdi = c["pollingDistrictIdentifier"]
        tcp = {x["candidateIdentifier"]["id"]: x["votes"] for x in (c.get("twoCandidatePreferred") or {}).get("candidate") or []}
        for x in fp.get("candidate") or []:
            r = {"district_id": pdi["id"], "district": pdi["name"], **_cand(x),
                 "ballot_position": x["ballotPosition"], "votes": x["votes"],
                 "pct": _pct(x["votes"], formal), "tcp_votes": tcp.get(x["candidateIdentifier"]["id"])}
            vbt = x.get("votesByType") or {}
            for t in VOTE_TYPES:
                r[t] = vbt.get(t)
            rows.append(r)
    return rows


def lower_house_booths(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per booth per candidate (first preferences), with booth details and 2CP votes."""
    rows = []
    for c in _lh_contests(data):
        pdi = c["pollingDistrictIdentifier"]
        for pp in ((c.get("pollingPlaces") or {}).get("pollingPlace") or []):
            ppi = pp["pollingPlaceIdentifier"]
            fp = pp["firstPreferences"]
            formal = (fp.get("formal") or {}).get("votes")
            tcp = {x["candidateIdentifier"]["id"]: x["votes"] for x in (pp.get("twoCandidatePreferred") or {}).get("candidate") or []}
            for x in fp.get("candidate") or []:
                rows.append({
                    "district_id": pdi["id"], "district": pdi["name"],
                    "booth_id": ppi["id"], "booth": ppi.get("name"),
                    "classification": ppi.get("classification"),
                    "latitude": ppi.get("latitude"), "longitude": ppi.get("longitude"),
                    "booth_formal": formal, "booth_updated": fp.get("updated"),
                    **_cand(x), "votes": x["votes"], "pct": _pct(x["votes"], formal),
                    "tcp_votes": tcp.get(x["candidateIdentifier"]["id"]),
                })
    return rows


def upper_house_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per Legislative Council region group (and ungrouped candidate)."""
    rows = []
    for c in _uh_contests(data):
        fp = c["firstPreferences"]
        formal = fp["formal"]["votes"]
        quota = (c.get("quota") or {}).get("value")
        quota_source = "vec" if quota else None
        if not quota and formal:  # the VEC often leaves Quota empty; use the Droop quota
            quota = formal // (c["numberOfPositions"] + 1) + 1
            quota_source = "droop"
        pdi = c["pollingDistrictIdentifier"]
        base = {"region_id": pdi["id"], "region": pdi["name"], "declared": c["declared"],
                "positions": c["numberOfPositions"], "enrolment": c["enrolment"], "formal": formal,
                "booths_returned": fp["pollingPlacesReturned"], "booths_expected": fp["pollingPlacesExpected"],
                "quota": quota, "quota_source": quota_source, "quota_provisional": (c.get("quota") or {}).get("provisional")}
        for g in fp.get("group") or []:
            v = g["groupVotes"]["votes"]
            rows.append({**base, "group_id": g["groupIdentifier"]["id"],
                         "group": g["groupIdentifier"].get("groupName"), "party": g["groupIdentifier"].get("party"),
                         "votes": v, "ticket_votes": g["ticketVotes"]["votes"],
                         "pct": _pct(v, formal), "quotas": round(v / quota, 3) if quota else None})
        for u in fp.get("ungroupedCandidate") or []:
            cc = _cand(u)
            rows.append({**base, "group_id": None, "group": f"Ungrouped: {cc['candidate']}", "party": cc["party"],
                         "votes": u["votes"], "ticket_votes": None, "pct": _pct(u["votes"], formal),
                         "quotas": round(u["votes"] / quota, 3) if quota else None})
    return rows


def party_totals(data: dict[str, Any], house: str = "lower") -> list[dict[str, Any]]:
    """Statewide first-preference totals by party key ('other' for everyone else)."""
    totals: dict[str, int] = defaultdict(int)
    formal = 0
    if house == "lower":
        for c in _lh_contests(data):
            formal += c["firstPreferences"]["formal"]["votes"]
            for x in c["firstPreferences"].get("candidate") or []:
                totals[x["candidateIdentifier"].get("party") or "other"] += x["votes"]
    elif house == "upper":
        for r in upper_house_groups(data):
            totals[r["party"] or "other"] += r["votes"]
        formal = sum(c["firstPreferences"]["formal"]["votes"] for c in _uh_contests(data))
    else:
        raise ValueError("house must be 'lower' or 'upper'")
    return sorted(({"party": p, "votes": v, "pct": _pct(v, formal)} for p, v in totals.items()),
                  key=lambda r: -r["votes"])


def changed_districts(prev: dict[str, Any] | None, cur: dict[str, Any]) -> list[str]:
    """Names of lower house districts whose total or 2CP count changed between two responses."""
    if prev is None:
        return []
    def key(d):
        return {c["pollingDistrictIdentifier"]["name"]: (
            c["firstPreferences"]["total"]["votes"],
            sum(x["votes"] for x in (c.get("twoCandidatePreferred") or {}).get("candidate") or []),
        ) for c in _lh_contests(d)}
    a, b = key(prev), key(cur)
    return sorted(n for n in b if a.get(n) != b[n])


def to_csv(rows: Iterable[dict[str, Any]], path) -> None:
    import csv
    rows = list(rows)
    with open(path, "w", newline="") as f:
        if not rows:
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
