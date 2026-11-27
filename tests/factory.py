"""Tiny synthetic Analysis responses (no real feed data is committed)."""


def cand(cid, name, party, votes, pos=1, aff=None):
    return {"candidateIdentifier": {"id": cid, "affiliationId": None, "affiliationName": aff, "name": name, "party": party},
            "ballotPosition": pos, "votes": votes, "votesByType": {"ordinary": votes, "postal": 0}}


def district(did, name, cands, tcp=None, booths=None, enrolment=1000):
    formal = sum(c["votes"] for c in cands)
    d = {
        "contestIdentifier": {"contestName": name, "id": did},
        "pollingDistrictIdentifier": {"id": did + 1, "name": name, "regionId": 1},
        "declared": False, "numberOfPositions": 1, "enrolment": enrolment, "updated": None,
        "firstPreferences": {
            "formal": {"votes": formal}, "informal": {"votes": 10}, "total": {"votes": formal + 10},
            "pollingPlacesExpected": 5, "pollingPlacesReturned": 2, "updated": None, "candidate": cands,
        },
        "pollingPlaces": {"pollingPlace": booths or []},
    }
    if tcp:
        d["twoCandidatePreferred"] = {"candidate": tcp, "pollingPlacesExpected": 5, "pollingPlacesReturned": 1, "updated": None}
    return d


def booth(bid, name, cands):
    return {"pollingPlaceIdentifier": {"id": bid, "name": name, "classification": "VotingCentre", "latitude": -37.8, "longitude": 144.9},
            "firstPreferences": {"formal": {"votes": sum(c["votes"] for c in cands)}, "updated": None,
                                 "candidate": [{"candidateIdentifier": c["candidateIdentifier"], "votes": c["votes"]} for c in cands]},
            "updated": None}


def region(rid, name, groups, quota=None, ungrouped=()):
    formal = sum(v for _, _, v in groups) + sum(c["votes"] for c in ungrouped)
    return {
        "contestIdentifier": {"contestName": name, "id": rid}, "pollingDistrictIdentifier": {"id": rid + 1, "name": name},
        "declared": False, "numberOfPositions": 5, "enrolment": 10000, "updated": None,
        "quota": {"provisional": True, **({"value": quota} if quota else {})},
        "firstPreferences": {
            "formal": {"votes": formal}, "informal": {"votes": 0}, "total": {"votes": formal},
            "pollingPlacesExpected": 10, "pollingPlacesReturned": 3, "updated": None,
            "group": [{"groupIdentifier": {"id": gid, "groupName": gname, "party": party},
                       "groupVotes": {"votes": v}, "ticketVotes": {"votes": v // 2}}
                      for gid, (gname, party, v) in enumerate(groups, start=100)],
            "ungroupedCandidate": [dict(c, elected=None) for c in ungrouped],
        },
    }


def analysis(districts, regions, lh_file="State2022mediafilelitepplh_20221126_190004.zip"):
    feed = lambda key, body: {"mediaFeed": {"id": "x", "created": "2022-11-26T19:00:01", "phase": "ElectionNight", "verbose": False,
                                           "eventIdentifier": {"id": 1, "eventName": "State Election"},
                                           "election": {"electionIdentifier": {"id": "L", "electionName": "x", "electionCategory": "LowerHouse"},
                                                        key: {"contests": {"contest": body}}}}}
    return {
        "files": {"lowerHouse": lh_file, "upperHouse": "uh.zip", "candidates": "c.zip", "groups": "g.zip", "pollingLocations": "p.zip"},
        "lowerHouse": feed("house", districts),
        "upperHouse": feed("senate", regions),
        "candidates": {}, "groups": {}, "pollingLocations": {},
    }
