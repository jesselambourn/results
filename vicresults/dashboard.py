"""Build the compact model behind the results pages: results and swings at
state, region, district and booth level.

Swings compare the current feed with a baseline feed (the 2022 `final` sample).
Ids differ between elections, so everything is matched by name:

- regions and districts by name ("Albert Park District" -> "albertpark")
- booths by name within their district (lower house) or region (upper house)
- candidates by party key from the API join, else by registered party name,
  else (independents) by the candidate's own name

Two swings are given wherever possible:

- ``sw``  like-for-like: only what has been counted so far is compared with the
  same thing in the baseline (each reporting booth against the same booth; each
  non-ordinary vote type, e.g. early or postal, against that type's baseline
  total). Booths with no baseline match are left out of both sides.
- ``raw`` current share minus the party's final baseline share.

All shares are percentages of formal votes.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

PARTIES = {
    "socialists": ("Victorian Socialists", "VS"),
    "labor": ("Labor", "ALP"),
    "liberal": ("Liberal", "LIB"),
    "greens": ("Greens", "GRN"),
    "nationals": ("Nationals", "NAT"),
    "oneNation": ("One Nation", "ONP"),
    "ind": ("Independents", "IND"),
    "ung": ("Ungrouped", "UNG"),
}


def norm(s: str | None) -> str:
    """Matching key for a district, region or booth name. Drops "District"/"Region" and
    bracketed tags such as the VEC's "(HJVC)" for a joint venue's home district."""
    s = re.sub(r"\([^)]*\)", "", (s or "").lower())
    s = re.sub(r"\b(district|region)\b", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def _diff(a, b):
    return round(a - b, 2) if a is not None and b is not None else None


def _pp(c: dict) -> list[dict]:
    return ((c.get("pollingPlaces") or {}).get("pollingPlace")) or []


def _votes(x) -> int:
    return int((x or {}).get("votes") or 0)


def _vbt(x) -> dict:
    return {k: int(v or 0) for k, v in ((x or {}).get("votesByType") or {}).items()}


def _lh(data):
    return (((data.get("lowerHouse") or {}).get("mediaFeed") or {}).get("election") or {}).get("house", {}).get("contests", {}).get("contest") or []


def _uh(data):
    return (((data.get("upperHouse") or {}).get("mediaFeed") or {}).get("election") or {}).get("senate", {}).get("contests", {}).get("contest") or []


class Labels:
    """Collects a display name for every party key seen."""

    def __init__(self):
        self.names: dict[str, list[str]] = {k: list(v) for k, v in PARTIES.items()}

    def cand(self, ci: dict) -> str:
        if ci.get("party"):
            k = ci["party"]
            self.names.setdefault(k, [ci.get("affiliationName") or k, k[:3].upper()])
            return k
        if ci.get("affiliationName"):
            k = "aff:" + norm(ci["affiliationName"])
            self.names.setdefault(k, [ci["affiliationName"], ""])
            return k
        name = ci.get("name") or ci.get("candidateName") or ""
        k = "ind:" + norm(name)
        self.names.setdefault(k, ["Independent", "IND"])
        return k

    def group(self, gi: dict, names: dict[int, str]) -> str:
        if gi.get("party"):
            k = gi["party"]
            self.names.setdefault(k, [gi.get("groupName") or k, k[:3].upper()])
            return k
        name = gi.get("groupName") or names.get(gi.get("id")) or f"Group {gi.get('id')}"
        k = "grp:" + norm(name)
        self.names.setdefault(k, [name, ""])
        return k


def agg_key(k: str) -> str:
    return "ind" if k.startswith("ind:") else k


class Like:
    """Like-for-like accumulator: matched current and baseline votes per key."""

    def __init__(self):
        self.cf = 0
        self.bf = 0
        self.c: dict[str, int] = defaultdict(int)
        self.b: dict[str, int] = defaultdict(int)

    def add(self, cf, cvotes: dict, bf, bvotes: dict):
        """Add one matched component. Baseline votes are rescaled to the size of
        the current component, so a part-counted vote type or a booth that has
        grown or shrunk carries the same weight on both sides."""
        if not cf or not bf:
            return
        self.cf += cf
        self.bf += cf
        for k, v in cvotes.items():
            self.c[k] += v
        for k, v in bvotes.items():
            self.b[k] += v * cf / bf

    def merge(self, other: "Like", keyf=lambda k: k):
        self.cf += other.cf
        self.bf += other.bf
        for k, v in other.c.items():
            self.c[keyf(k)] += v
        for k, v in other.b.items():
            self.b[keyf(k)] += v

    def swing(self, k):
        if not self.cf or not self.bf:
            return None
        return round(100.0 * self.c.get(k, 0) / self.cf - 100.0 * self.b.get(k, 0) / self.bf, 2)


def _by_key(items, keyf, votef=_votes):
    out: dict[str, int] = defaultdict(int)
    for x in items:
        out[keyf(x)] += votef(x)
    return dict(out)


def _type_votes(items, keyf, t, getter=lambda x: x):
    out: dict[str, int] = defaultdict(int)
    for x in items:
        out[keyf(x)] += _vbt(getter(x)).get(t, 0)
    return dict(out)


# ---------------------------------------------------------------- lower house

def _tcp(c):
    t = c.get("twoCandidatePreferred") or {}
    cands = t.get("candidate") or []
    return cands if len(cands) == 2 else []


def _district(c, bc, L: Labels, expected_booths: list[str], stats: dict):
    fp = c["firstPreferences"]
    cands = fp.get("candidate") or []
    ck = lambda x: L.cand(x["candidateIdentifier"])
    keys = [ck(x) for x in cands]
    formal = _votes(fp.get("formal"))
    ftypes = _vbt(fp.get("formal"))
    pdi = c.get("pollingDistrictIdentifier") or {}
    name = pdi.get("name") or c["contestIdentifier"]["contestName"]

    # baseline lookups
    bfp = (bc or {}).get("firstPreferences") or {}
    bcands = bfp.get("candidate") or []
    bformal = _votes(bfp.get("formal"))
    bvotes = _by_key(bcands, ck)
    bbooths = {norm(p["pollingPlaceIdentifier"].get("name")): p for p in _pp(bc or {})}
    bftypes = _vbt(bfp.get("formal"))

    tcp = _tcp(c)
    btcp = _tcp(bc or {})
    tkeys = [ck(x) for x in tcp]
    btkeys = [ck(x) for x in btcp]
    same_pair = bool(tcp) and sorted(tkeys) == sorted(btkeys) and len(set(tkeys)) == 2
    tcp_ids = [x["candidateIdentifier"]["id"] for x in tcp]
    btcp_by_key = {ck(x): x for x in btcp}

    like, tlike = Like(), Like()
    booths_out = []
    seen = set()
    for p in _pp(c):
        pfp = p.get("firstPreferences") or {}
        pc = {x["candidateIdentifier"]["id"]: _votes(x) for x in pfp.get("candidate") or []}
        v = [pc.get(x["candidateIdentifier"]["id"], 0) for x in cands]
        f = _votes(pfp.get("formal")) or sum(v)
        bname = p["pollingPlaceIdentifier"].get("name") or ""
        seen.add(norm(bname))
        row = {"n": bname, "f": f, "inf": _votes(pfp.get("informal")), "v": v}
        ptc = {x["candidateIdentifier"]["id"]: _votes(x) for x in (p.get("twoCandidatePreferred") or {}).get("candidate") or []}
        if tcp and sum(ptc.get(i, 0) for i in tcp_ids):
            row["tc"] = [ptc.get(i, 0) for i in tcp_ids]
        bp = bbooths.get(norm(bname))
        if f:
            stats["booths"] += 1
        if bp is not None:
            bpfp = bp.get("firstPreferences") or {}
            bpv = _by_key(bpfp.get("candidate") or [], ck)
            bpf = _votes(bpfp.get("formal")) or sum(bpv.values())
            if bpf:
                row["bf"] = bpf
                row["bv"] = [bpv.get(k, 0) for k in keys]
                if f:
                    stats["boothsMatched"] += 1
                    like.add(f, dict(zip(keys, v)) if len(set(keys)) == len(keys) else _sum_keys(keys, v), bpf, bpv)
                if same_pair:
                    bptc = _by_key((bp.get("twoCandidatePreferred") or {}).get("candidate") or [], ck)
                    if sum(bptc.values()):
                        row["btc"] = [bptc.get(k, 0) for k in tkeys]
                        if "tc" in row:
                            tlike.add(sum(row["tc"]), dict(zip(tkeys, row["tc"])), sum(bptc.values()), bptc)
        booths_out.append(row)

    # booths expected (from the polling locations file or the baseline) but not in yet
    waiting = []
    pool = expected_booths or [p["pollingPlaceIdentifier"].get("name") for p in _pp(bc or {})]
    for bname in pool:
        if norm(bname) in seen:
            continue
        row = {"n": bname, "f": 0, "v": [0] * len(cands), "w": 1}
        bp = bbooths.get(norm(bname))
        if bp is not None:
            bpv = _by_key((bp.get("firstPreferences") or {}).get("candidate") or [], ck)
            bpf = _votes((bp.get("firstPreferences") or {}).get("formal")) or sum(bpv.values())
            if bpf:
                row["bf"] = bpf
                row["bv"] = [bpv.get(k, 0) for k in keys]
        waiting.append(row)
    booths_out.sort(key=lambda r: r["n"])
    booths_out += sorted(waiting, key=lambda r: r["n"])

    # non-ordinary vote types (and ordinary too when the feed has no booth rows)
    has_booths = any(r["f"] for r in booths_out)
    types_out = []
    for t, tf in ftypes.items():
        tv = _type_votes(cands, ck, t)
        btv = _type_votes(bcands, ck, t)
        btf = bftypes.get(t, 0)
        if tf or btf:
            types_out.append({"t": t, "f": tf, "v": [_vbt(x).get(t, 0) for x in cands],
                              "bf": btf, "bv": [btv.get(k, 0) for k in keys]})
        if t == "ordinary" and has_booths:
            continue
        like.add(tf, tv, btf, btv)
        if same_pair:
            ttv = _type_votes(tcp, ck, t)
            bttv = _type_votes(btcp, ck, t)
            tlike.add(sum(ttv.values()), ttv, sum(bttv.values()), bttv)

    cands_out = []
    for x, k in zip(cands, keys):
        ci = x["candidateIdentifier"]
        v = _votes(x)
        p = _pct(v, formal)
        bpct = _pct(bvotes[k], bformal) if k in bvotes else None
        cands_out.append({
            "name": ci.get("name") or ci.get("candidateName"), "k": k, "v": v, "p": p,
            "bp": bpct, "new": bool(bformal) and k not in bvotes,
            "sw": like.swing(k), "raw": _diff(p, bpct if bpct is not None else (0.0 if bformal else None)) if formal else None,
        })

    tcp_out = None
    if tcp:
        tt = sum(_votes(x) for x in tcp)
        btt = sum(_votes(x) for x in btcp)
        tcp_out = {"c": [], "total": tt, "same": same_pair,
                   "in": (c.get("twoCandidatePreferred") or {}).get("pollingPlacesReturned"),
                   "basePair": [{"k": k, "p": _pct(_votes(x), btt)} for k, x in zip(btkeys, btcp)] if btt else None}
        for x, k in zip(tcp, tkeys):
            ci = x["candidateIdentifier"]
            p = _pct(_votes(x), tt)
            bp = _pct(_votes(btcp_by_key[k]), btt) if same_pair and btt else None
            tcp_out["c"].append({"name": ci.get("name") or ci.get("candidateName"), "k": k, "v": _votes(x), "p": p,
                                 "bp": bp, "sw": tlike.swing(k) if same_pair else None, "raw": _diff(p, bp) if tt else None})

    # who is ahead, and who won last time
    lead = None
    if tcp_out and tcp_out["total"]:
        lead = max(tcp_out["c"], key=lambda x: x["v"])["k"]
    elif formal:
        lead = max(cands_out, key=lambda x: x["v"])["k"]
    held = None
    if btcp and sum(_votes(x) for x in btcp):
        held = ck(max(btcp, key=_votes))
    elif bformal:
        held = ck(max(bcands, key=_votes))

    total = _votes(fp.get("total"))
    out = {
        "id": norm(name), "name": re.sub(r"\s+District$", "", name), "regionId": pdi.get("regionId"),
        "enrol": c.get("enrolment"), "formal": formal, "informal": _votes(fp.get("informal")), "total": total,
        "in": fp.get("pollingPlacesReturned"), "exp": fp.get("pollingPlacesExpected"),
        "declared": bool(c.get("declared")), "updated": c.get("updated") or fp.get("updated"),
        "cands": cands_out, "tcp": tcp_out, "types": types_out, "booths": booths_out,
        "lead": lead, "held": held, "hasBase": bool(bformal),
        "matched": _pct(like.cf, formal), "bTotal": _votes(bfp.get("total")), "bEnrol": (bc or {}).get("enrolment"),
    }
    return out, like, {agg_key(k): v for k, v in _sum_keys([agg_key(k) for k in keys], [x["v"] for x in cands_out]).items()}, \
        _sum_keys([agg_key(k) for k in bvotes], list(bvotes.values())), bformal


def _sum_keys(keys, vals):
    out: dict[str, int] = defaultdict(int)
    for k, v in zip(keys, vals):
        out[k] += v
    return dict(out)


def _agg(votes: dict, formal: int, bvotes: dict, bformal: int, like: Like, extra=None):
    rows = []
    for k in sorted(set(votes) | set(bvotes), key=lambda k: -votes.get(k, 0)):
        p = _pct(votes.get(k, 0), formal)
        bp = _pct(bvotes.get(k, 0), bformal)
        r = {"k": k, "v": votes.get(k, 0), "p": p, "bp": bp, "sw": like.swing(k), "raw": _diff(p, bp),
             "gone": k not in votes}
        if extra:
            r.update(extra(k))
        rows.append(r)
    return rows


# ---------------------------------------------------------------- upper house

def _region(c, bc, L: Labels, group_names: dict[int, str], stats: dict):
    fp = c["firstPreferences"]
    pdi = c.get("pollingDistrictIdentifier") or {}
    name = pdi.get("name") or c["contestIdentifier"]["contestName"]
    groups = fp.get("group") or []
    for g in groups:
        gi = g["groupIdentifier"]
        if gi.get("groupName"):
            group_names[gi["id"]] = gi["groupName"]
    gk = lambda g: L.group(g["groupIdentifier"], group_names)
    gv = lambda g: _votes(g.get("groupVotes"))
    ung = fp.get("ungroupedCandidate") or []

    def tally(fpx):
        d = _by_key(fpx.get("group") or [], gk, gv)
        u = sum(_votes(x) for x in fpx.get("ungroupedCandidate") or [])
        if u or fpx.get("ungroupedCandidate"):
            d["ung"] = d.get("ung", 0) + u
        return d

    def tally_type(fpx, t):
        d = _type_votes(fpx.get("group") or [], gk, t, lambda g: g.get("groupVotes"))
        u = sum(_vbt(x).get(t, 0) for x in fpx.get("ungroupedCandidate") or [])
        if u:
            d["ung"] = d.get("ung", 0) + u
        return d

    votes = tally(fp)
    formal = _votes(fp.get("formal"))
    bfp = (bc or {}).get("firstPreferences") or {}
    bnames: dict[int, str] = {}
    for g in bfp.get("group") or []:
        if g["groupIdentifier"].get("groupName"):
            bnames[g["groupIdentifier"]["id"]] = g["groupIdentifier"]["groupName"]
    bgk = lambda g: L.group(g["groupIdentifier"], bnames)

    def btally(fpx):
        d = _by_key(fpx.get("group") or [], bgk, gv)
        u = sum(_votes(x) for x in fpx.get("ungroupedCandidate") or [])
        if u or fpx.get("ungroupedCandidate"):
            d["ung"] = d.get("ung", 0) + u
        return d

    bvotes = btally(bfp)
    bformal = _votes(bfp.get("formal"))
    keys = list(votes.keys())

    def merged(pps, tallyf):
        """Booths by normalised name; same-named booths in one region are added together."""
        out: dict[str, list] = {}
        for p in pps:
            pfp = p.get("firstPreferences") or {}
            pv = tallyf(pfp)
            f = _votes(pfp.get("formal")) or sum(pv.values())
            nm = p["pollingPlaceIdentifier"].get("name") or ""
            e = out.setdefault(norm(nm), [nm, 0, defaultdict(int)])
            e[1] += f
            for k, v in pv.items():
                e[2][k] += v
        return out

    bbooths = merged(_pp(bc or {}), btally)
    like = Like()
    booths_out = []
    for nk, (bname, f, pv) in merged(_pp(c), tally).items():
        row = {"n": bname, "f": f, "v": [pv.get(k, 0) for k in keys]}
        if f:
            stats["uBooths"] += 1
        bp = bbooths.get(nk)
        if bp is not None and bp[1]:
            row["bf"] = bp[1]
            row["bv"] = [bp[2].get(k, 0) for k in keys]
            if f:
                stats["uBoothsMatched"] += 1
                like.add(f, pv, bp[1], bp[2])
        booths_out.append(row)
    booths_out.sort(key=lambda r: r["n"])
    has_booths = any(r["f"] for r in booths_out)
    ftypes, bftypes = _vbt(fp.get("formal")), _vbt(bfp.get("formal"))
    for t, tf in ftypes.items():
        if t == "ordinary" and has_booths:
            continue
        btf = bftypes.get(t, 0)
        if tf and btf:
            bt = _type_votes(bfp.get("group") or [], bgk, t, lambda g: g.get("groupVotes"))
            bu = sum(_vbt(x).get(t, 0) for x in bfp.get("ungroupedCandidate") or [])
            if bu:
                bt["ung"] = bu
            like.add(tf, tally_type(fp, t), btf, bt)

    positions = c.get("numberOfPositions") or 5
    quota = (c.get("quota") or {}).get("value")
    qsrc = "VEC" if quota else None
    if not quota and formal:
        quota, qsrc = formal // (positions + 1) + 1, "Droop quota on votes counted so far"
    rows = _agg(votes, formal, bvotes, bformal, like,
                lambda k: {"q": round(votes.get(k, 0) / quota, 3) if quota else None})
    total = _votes(fp.get("total"))
    return {
        "id": norm(name), "name": re.sub(r"\s+Region$", "", name), "srcId": pdi.get("id"),
        "upper": {"enrol": c.get("enrolment"), "formal": formal, "informal": _votes(fp.get("informal")), "total": total,
                  "in": fp.get("pollingPlacesReturned"), "exp": fp.get("pollingPlacesExpected"),
                  "positions": positions, "quota": quota, "quotaSrc": qsrc, "declared": bool(c.get("declared")),
                  "rows": rows, "keys": keys, "booths": booths_out, "hasBase": bool(bformal),
                  "matched": _pct(like.cf, formal), "bTotal": _votes(bfp.get("total")), "bEnrol": (bc or {}).get("enrolment")},
    }, like, votes, bvotes, bformal


# ---------------------------------------------------------------- whole model

def _lower_summary(ds, parts):
    """parts: list of (like, votes, bvotes, bformal) for the districts in ds."""
    like, votes, bvotes = Like(), defaultdict(int), defaultdict(int)
    bformal = 0
    for lk, v, bv, bf in parts:
        like.merge(lk, agg_key)
        for k, n in v.items():
            votes[k] += n
        for k, n in bv.items():
            bvotes[k] += n
        bformal += bf
    formal = sum(d["formal"] for d in ds)
    leads, helds = defaultdict(int), defaultdict(int)
    for d in ds:
        if d["lead"]:
            leads[agg_key(d["lead"])] += 1
        if d["held"]:
            helds[agg_key(d["held"])] += 1
    rows = _agg(dict(votes), formal, dict(bvotes), bformal, like,
                lambda k: {"seats": leads.get(k, 0), "held": helds.get(k, 0)})
    return {
        "enrol": sum(d["enrol"] or 0 for d in ds), "formal": formal,
        "informal": sum(d["informal"] for d in ds), "total": sum(d["total"] for d in ds),
        "in": sum(d["in"] or 0 for d in ds), "exp": sum(d["exp"] or 0 for d in ds),
        "rows": rows, "matched": _pct(like.cf, formal), "seatsIn": sum(1 for d in ds if d["lead"]), "n": len(ds),
        "bTotal": sum(d["bTotal"] or 0 for d in ds), "bEnrol": sum(d["bEnrol"] or 0 for d in ds),
    }


def is_sample(data: dict[str, Any]) -> bool:
    return any(str(v).startswith("State2022") for v in (data.get("files") or {}).values())


def build_model(cur: dict[str, Any], base: dict[str, Any] | None, status: str | None = None) -> dict[str, Any]:
    L = Labels()
    base = base or {}
    stats = defaultdict(int)
    bdist = {norm((c.get("pollingDistrictIdentifier") or {}).get("name") or c["contestIdentifier"]["contestName"]): c for c in _lh(base)}
    breg = {norm((c.get("pollingDistrictIdentifier") or {}).get("name") or c["contestIdentifier"]["contestName"]): c for c in _uh(base)}
    expected: dict[str, list[str]] = {}
    for pd in ((cur.get("pollingLocations") or {}).get("pollingDistrictList") or {}).get("pollingDistrict") or []:
        nm = norm((pd.get("pollingDistrictIdentifier") or {}).get("name"))
        expected[nm] = [p["pollingPlaceIdentifier"].get("name") for p in ((pd.get("pollingPlaces") or {}).get("pollingPlace") or [])]

    regions, rparts, src2id = [], {}, {}
    unmatched_regions, unmatched_districts = [], []
    ulike_all, uvotes, ubvotes, ubformal = Like(), defaultdict(int), defaultdict(int), 0
    gnames: dict[int, str] = {}
    for c in _uh(cur):
        nm = norm((c.get("pollingDistrictIdentifier") or {}).get("name") or c["contestIdentifier"]["contestName"])
        if nm not in breg and base:
            unmatched_regions.append(c["contestIdentifier"]["contestName"])
        r, like, v, bv, bf = _region(c, breg.get(nm), L, gnames, stats)
        r["districts"] = []
        regions.append(r)
        src2id[r["srcId"]] = r["id"]
        ulike_all.merge(like)
        for k, n in v.items():
            uvotes[k] += n
        for k, n in bv.items():
            ubvotes[k] += n
        ubformal += bf

    districts, parts = [], []
    for c in _lh(cur):
        nm = norm((c.get("pollingDistrictIdentifier") or {}).get("name") or c["contestIdentifier"]["contestName"])
        if nm not in bdist and base:
            unmatched_districts.append(c["contestIdentifier"]["contestName"])
        d, like, v, bv, bf = _district(c, bdist.get(nm), L, expected.get(nm, []), stats)
        d["region"] = src2id.get(d.pop("regionId"))
        districts.append(d)
        parts.append((like, v, bv, bf))
        rparts.setdefault(d["region"], []).append((d, (like, v, bv, bf)))
    districts.sort(key=lambda d: d["name"])
    for r in regions:
        mine = rparts.get(r["id"], [])
        r["districts"] = sorted(d["id"] for d, _ in mine)
        r["lower"] = _lower_summary([d for d, _ in mine], [p for _, p in mine])
    regions.sort(key=lambda r: r["name"])

    uformal = sum(r["upper"]["formal"] for r in regions)
    state_upper = {
        "enrol": sum(r["upper"]["enrol"] or 0 for r in regions), "formal": uformal,
        "informal": sum(r["upper"]["informal"] for r in regions), "total": sum(r["upper"]["total"] for r in regions),
        "in": sum(r["upper"]["in"] or 0 for r in regions), "exp": sum(r["upper"]["exp"] or 0 for r in regions),
        "rows": _agg(dict(uvotes), uformal, dict(ubvotes), ubformal, ulike_all), "matched": _pct(ulike_all.cf, uformal),
        "bTotal": sum(r["upper"]["bTotal"] or 0 for r in regions), "bEnrol": sum(r["upper"]["bEnrol"] or 0 for r in regions),
    }
    lhf = (cur.get("lowerHouse") or {}).get("mediaFeed") or {}
    bhf = (base.get("lowerHouse") or {}).get("mediaFeed") or {}
    return {
        "meta": {
            "event": (lhf.get("eventIdentifier") or {}).get("eventName"), "created": lhf.get("created"),
            "phase": lhf.get("phase"), "files": cur.get("files"), "sample": is_sample(cur),
            "baseline": (bhf.get("eventIdentifier") or {}).get("eventName") if base else None,
            "baselineFile": (base.get("files") or {}).get("lowerHouse") if base else None,
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": status,
            "match": {"districts": len(districts), "districtsUnmatched": unmatched_districts,
                      "regionsUnmatched": unmatched_regions,
                      "booths": stats["booths"], "boothsMatched": stats["boothsMatched"],
                      "uBooths": stats["uBooths"], "uBoothsMatched": stats["uBoothsMatched"]},
        },
        "parties": L.names,
        "state": {"lower": _lower_summary(districts, parts), "upper": state_upper},
        "regions": regions,
        "districts": districts,
    }


def empty_model(status: str) -> dict[str, Any]:
    return {"meta": {"status": status, "waiting": True, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            "parties": {}, "state": None, "regions": [], "districts": []}
