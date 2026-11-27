# results

Client for the Victorian Socialists election-night **Analysis API** (Victorian state election,
Saturday 28 November 2026). It fetches the VEC results feed as JSON, checks it against the
API's OpenAPI contract, and turns it into flat tables for display and analysis.

Python 3.10+, standard library only. `jsonschema` is optional (for `validate`), `pytest` for tests.

## Rules (from the API brief)

- One host only: `https://2026.victoriansocialists.org.au`. The client refuses any other.
- Token comes from the `ANALYSIS_TOKEN` environment variable. It is never printed, logged,
  written to disk or committed. Don't paste it anywhere.
- Poll at most once a minute, with a 30 s+ timeout (default 60 s). The whole body is read
  before parsing (~11 MB for a full count).
- Feed data is preliminary and for internal use only. **This repo is public**: `data/`
  and all `*.json` files are git-ignored. Don't commit snapshots, samples or the contract.

## Use

```sh
export ANALYSIS_TOKEN=...            # set in the environment, never in code

python -m vicresults contract -o data/openapi.json      # the source of truth
python -m vicresults validate --sample 7pm --contract data/openapi.json
python -m vicresults summary  --sample 10pm             # statewide + VS highlights
python -m vicresults fetch    --sample final -o data/final.json.gz

# On the night (live data from 6 pm AEDT; 404 before then is normal):
python -m vicresults poll --out data --until 23:59
```

Samples: `6pm` (zero votes), `7pm`, `10pm`, `final`. They are the real 2022 VEC files; their
`files` names start `State2022`. Live polling drops the sample parameter.

### What `poll` writes

| Path | What |
| --- | --- |
| `data/latest.json.gz` | newest feed |
| `data/snapshots/<time>.json.gz` | every distinct feed (Melbourne time) |
| `data/csv/lower_districts.csv` | per district: turnout, informal, booths in, leader, VS %, 2CP |
| `data/csv/lower_candidates.csv` | per candidate: votes, %, votes by type, 2CP |
| `data/csv/lower_booths.csv` | per booth per candidate, with booth type and coordinates |
| `data/csv/upper_groups.csv` | per region group: votes, %, quotas |
| `data/csv/party_totals_{lower,upper}.csv` | statewide first preferences by party key |
| `data/issues/<time>.json` | 500 schema-mismatch bodies |
| `data/poll.log` | one line per poll |

A new feed is detected by comparing `files` between polls. If the VEC stalls, `files` stops
changing and the log shows `unchanged`.

### Errors

| Code | Meaning | Poller does |
| --- | --- | --- |
| 400 | unknown sample | (CLI error) |
| 401 | missing or wrong token | stops (exit 2) |
| 404 | no feed files yet (normal before 6 pm) | retries next minute |
| 500 | converted files didn't match the schema | saves `issues`, logs `TELL ANGUS`, retries |

## In Python

```python
from vicresults import AnalysisClient, summary

data = AnalysisClient().analysis("10pm")      # or .analysis() live
summary.lower_house_districts(data)            # list of dicts
summary.party_totals(data, "upper")
```

Party keys from the API join: `socialists`, `greens`, `labor`, `liberal`, `nationals`,
`oneNation`, or `null` (shown as `other` in totals).

## Tests

```sh
python -m pytest -q
```

Tests use small synthetic responses in `tests/factory.py`; no real feed data is committed.
