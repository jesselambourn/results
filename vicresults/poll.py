"""Election-night poller.

Polls GET /api/analysis at most once a minute. Whenever the `files` block changes,
it saves a gzipped snapshot and refreshes CSV summaries in the output folder:

    <out>/snapshots/<melbourne time>.json.gz   every distinct feed
    <out>/latest.json.gz                       the newest feed
    <out>/csv/*.csv                            summaries of the newest feed
    <out>/issues/<melbourne time>.json         500 schema-mismatch bodies (tell Angus)
    <out>/poll.log                             one line per poll

404 (before 6 pm) and network errors are logged and retried next minute.
401 stops the poller. The token is never written anywhere.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import summary
from .client import AnalysisClient, AuthError, NotReadyError, SchemaMismatchError

MELBOURNE = ZoneInfo("Australia/Melbourne")
MIN_INTERVAL = 60.0


def now_mel() -> datetime:
    return datetime.now(MELBOURNE)


def write_outputs(data: dict[str, Any], out: Path, stamp: str) -> None:
    (out / "snapshots").mkdir(parents=True, exist_ok=True)
    (out / "csv").mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, separators=(",", ":")).encode()
    (out / "snapshots" / f"{stamp}.json.gz").write_bytes(gzip.compress(blob))
    tmp = out / "latest.json.gz.tmp"
    tmp.write_bytes(gzip.compress(blob))
    tmp.replace(out / "latest.json.gz")
    summary.to_csv(summary.lower_house_districts(data), out / "csv" / "lower_districts.csv")
    summary.to_csv(summary.lower_house_candidates(data), out / "csv" / "lower_candidates.csv")
    summary.to_csv(summary.lower_house_booths(data), out / "csv" / "lower_booths.csv")
    summary.to_csv(summary.upper_house_groups(data), out / "csv" / "upper_groups.csv")
    summary.to_csv(summary.party_totals(data, "lower"), out / "csv" / "party_totals_lower.csv")
    summary.to_csv(summary.party_totals(data, "upper"), out / "csv" / "party_totals_upper.csv")


def run(
    out: Path,
    client: AnalysisClient | None = None,
    sample: str | None = None,
    interval: float = MIN_INTERVAL,
    until: datetime | None = None,
    once: bool = False,
    on_change: Callable[[dict[str, Any], list[str]], None] | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Poll until `until` (Melbourne time), forever if None. Returns a process exit code."""
    client = client or AnalysisClient()
    interval = max(interval, MIN_INTERVAL)
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "poll.log", "a")

    def say(msg: str) -> None:
        line = f"{now_mel():%Y-%m-%d %H:%M:%S %Z} {msg}"
        log(line)
        logf.write(line + "\n")
        logf.flush()

    last_files = None
    prev = None
    latest = out / "latest.json.gz"
    if latest.exists():
        try:
            prev = json.loads(gzip.decompress(latest.read_bytes()))
            last_files = prev.get("files")
        except Exception:
            prev = None

    try:
        while True:
            started = time.monotonic()
            stamp = now_mel().strftime("%Y%m%dT%H%M%S")
            try:
                data = client.analysis(sample)
            except NotReadyError as e:
                say(f"404 not ready yet: {e.message}")
            except SchemaMismatchError as e:
                (out / "issues").mkdir(exist_ok=True)
                (out / "issues" / f"{stamp}.json").write_text(json.dumps(e.body, indent=1))
                say(f"500 schema mismatch ({len(e.issues)} issues) saved to issues/{stamp}.json. TELL ANGUS. Retrying next poll.")
            except AuthError as e:
                say(f"401 token rejected: {e.message}. Stopping.")
                return 2
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                say(f"network/parse error: {type(e).__name__}: {e}. Retrying next poll.")
            else:
                files = data.get("files")
                if files != last_files:
                    changed = summary.changed_districts(prev, data)
                    write_outputs(data, out, stamp)
                    info = summary.feed_info(data)
                    say(f"NEW FEED {files.get('lowerHouse')} / {files.get('upperHouse')} phase={info['phase']} "
                        f"districts changed={len(changed)}")
                    if on_change:
                        on_change(data, changed)
                    last_files, prev = files, data
                else:
                    say(f"unchanged ({files.get('lowerHouse')})")
            if once:
                return 0
            if until and now_mel() >= until:
                say("reached stop time")
                return 0
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
    finally:
        logf.close()
