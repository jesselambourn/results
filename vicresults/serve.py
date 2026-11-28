"""Local results pages: `python -m vicresults serve` and `python -m vicresults build`.

`serve` polls the Analysis API (at most once a minute, via the poller, so it also
keeps the snapshots and CSVs) and serves the pages on http://127.0.0.1:8000.
`build` writes a static copy (index.html + data.json) from one feed.

The baseline for swings is the 2022 `final` sample, fetched once and cached in
<out>/baseline-2022-final.json.gz (git-ignored, like all feed data).
"""

from __future__ import annotations

import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .dashboard import build_model, empty_model, load_extras

WEB = Path(__file__).parent / "web" / "index.html"
SHELL = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
         "<style>body{margin:0}[hidden]{display:none!important}</style></head><body>%s</body></html>")
BASELINE_NAME = "baseline-2022-final.json.gz"


def page_html() -> str:
    return SHELL % WEB.read_text(encoding="utf-8")


def read_feed(path: Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw)


def load_baseline(out: Path, client=None, path: Path | None = None, log=print) -> tuple[dict[str, Any] | None, bool]:
    """Returns (baseline, fetched_now). Uses the cached file when there is one."""
    path = path or out / BASELINE_NAME
    if path.exists():
        return read_feed(path), False
    if client is None:
        return None, False
    log("fetching the 2022 final sample as the swing baseline (once)")
    base = client.analysis("final")
    out.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(json.dumps(base, separators=(",", ":")).encode()))
    tmp.replace(path)
    return base, True


def build_site(cur: dict[str, Any], base: dict[str, Any] | None, site: Path, extras=None) -> None:
    site.mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(page_html(), encoding="utf-8")
    (site / "data.json").write_text(json.dumps(build_model(cur, base, extras=extras), separators=(",", ":")), encoding="utf-8")


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = gzip.compress(json.dumps(empty_model("Starting up.")).encode())
        self.status = "Starting up."

    def set_model(self, model: dict[str, Any]) -> None:
        blob = gzip.compress(json.dumps(model, separators=(",", ":")).encode(), 5)
        with self.lock:
            self.data = blob

    def set_status(self, line: str) -> None:
        with self.lock:
            self.status = line


def _handler(state: State):
    class H(BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str, gz: bool = False):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            if gz:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._send(page_html().encode(), "text/html; charset=utf-8")
            elif path == "/data.json":
                with state.lock:
                    body = state.data
                if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                    self._send(body, "application/json", gz=True)
                else:
                    self._send(gzip.decompress(body), "application/json")
            elif path == "/status.json":
                with state.lock:
                    s = state.status
                self._send(json.dumps({"status": s}).encode(), "application/json")
            else:
                self.send_error(404)

        def log_message(self, *a):  # keep the console for poll lines
            pass
    return H


def serve(out: Path, port: int = 8000, host: str = "127.0.0.1", sample: str | None = None,
          file: str | None = None, baseline: str | None = None, until=None, log=print) -> int:
    from .poll import run

    state = State()
    httpd = ThreadingHTTPServer((host, port), _handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log(f"Results pages: http://{host}:{port}/")

    client = None
    if not file:
        from .client import AnalysisClient
        client = AnalysisClient()
    try:
        base, fetched = load_baseline(out, client, Path(baseline) if baseline else None, log)
    except Exception as e:  # the pages still work without swings
        base, fetched = None, False
        log(f"could not load the baseline ({type(e).__name__}: {e}); swings will be blank")

    def show(data, _changed=None):
        try:
            state.set_model(build_model(data, base, extras=load_extras(out)))
        except Exception as e:  # never let a surprise in the feed kill the poller
            say(f"could not build the pages from this feed: {type(e).__name__}: {e}")

    def say(line: str):
        log(line)
        state.set_status(line.split(" ", 3)[-1] if line[:4].isdigit() else line)

    if file:
        show(read_feed(Path(file)))
        say(f"showing {file} (not polling)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    latest = out / "latest.json.gz"
    if latest.exists():
        try:
            show(read_feed(latest))
        except Exception:
            pass
    else:
        state.set_model(empty_model("No results yet. The live feed starts at 6 pm; checking every minute."))
    if fetched:
        time.sleep(60)  # keep to one request a minute
    try:
        return run(out, client=client, sample=sample, until=until, on_change=show, log=say)
    except KeyboardInterrupt:
        return 0
