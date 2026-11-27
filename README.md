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

## Results pages

Results and swings at state, region, district and booth level, as sortable tables and dials.

```sh
export ANALYSIS_TOKEN=...
python -m vicresults serve --out data --until 23:59     # then open http://127.0.0.1:8000/
```

`serve` is the poller plus a local web page: it polls once a minute (so don't run `poll` as
well), keeps the same snapshots and CSVs in `data/`, and the page reloads itself every minute.
Before 6 pm it shows "Waiting for the first results". To rehearse, add `--sample 7pm` (or
`10pm`, `final`), or `--file data/latest.json.gz` to show a saved feed without polling.
`python -m vicresults build --sample 10pm --site site` writes a static copy (`index.html` +
`data.json`).

Pages: Overview, Regions, Districts, Booths, one page per region and per district, and
"Baseline and method", which reports how the current feed matched 2022.

### Swings and the 2022 baseline

Swings are against the 2022 `final` sample, fetched once and cached as
`data/baseline-2022-final.json.gz`. Ids change between elections, so regions and districts are
matched by name, booths by name within their district, candidates by party key (else registered
party name; independents by their own name).

- **Like-for-like swing** (default): each reporting booth against the same booth in 2022, and
  each other vote type (early, postal, absent...) against that type's 2022 result in the same
  district, weighted by its size in the current count. Booths with no 2022 match are left out.
- **Vs 2022 final**: current share minus the final 2022 share. Misleading until most votes are in.

Booth rows are ordinary election-day votes only; early and postal votes exist per district by
vote type. 2CP swing is shown only where the same two parties made the final count in 2022.
Narracan has no 2022 baseline (its 2022 election was postponed).

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
