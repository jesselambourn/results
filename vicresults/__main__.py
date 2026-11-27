"""Command line: python -m vicresults <command> ...

  contract [-o FILE]                 fetch the OpenAPI contract
  fetch [--sample S] [-o FILE]       fetch one response (gzip if FILE ends .gz)
  validate [--sample S | --file F]   check a response against the contract
  summary [--sample S | --file F]    print a statewide + district summary
  poll [--out DIR] [--sample S] [--until HH:MM] [--once]
  serve [--out DIR] [--port N] [--sample S | --file F] [--until HH:MM]
                                     poll and show the results pages locally
  build [--sample S | --file F] [--site DIR] [--out DIR]
                                     write a static copy of the pages
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import summary
from .client import SAMPLES, AnalysisClient, AnalysisError, is_sample, validate


def _load(args) -> dict:
    if getattr(args, "file", None):
        raw = Path(args.file).read_bytes()
        if args.file.endswith(".gz"):
            raw = gzip.decompress(raw)
        return json.loads(raw)
    return AnalysisClient().analysis(args.sample)


def _save(obj, path: str) -> None:
    blob = json.dumps(obj, separators=(",", ":")).encode()
    Path(path).write_bytes(gzip.compress(blob) if path.endswith(".gz") else blob)


def _p(x) -> str:
    return "-" if x is None else f"{x}"


def _print_summary(data: dict, top: int) -> None:
    info = summary.feed_info(data)
    print(f"Feed: {info['files']['lowerHouse']}  phase={info['phase']}  created={info['lower_created']}"
          + ("  [2022 SAMPLE]" if is_sample(data) else ""))
    for house in ("lower", "upper"):
        print(f"\n{house.title()} house statewide first preferences:")
        for r in summary.party_totals(data, house):
            print(f"  {r['party']:<12} {r['votes']:>10,}  {_p(r['pct']):>6}%")
    d = summary.lower_house_districts(data)
    counted = [r for r in d if r["formal"]]
    print(f"\nDistricts with votes: {len(counted)}/{len(d)}")
    soc = sorted((r for r in d if r["socialists_pct"]), key=lambda r: -r["socialists_pct"])[:top]
    if soc:
        print(f"\nTop {len(soc)} Victorian Socialists districts (first preferences):")
        for r in soc:
            print(f"  {r['district']:<28} {r['socialists_pct']:>6}%  rank {r['socialists_rank']}  "
                  f"booths {r['booths_returned']}/{r['booths_expected']}")
    u = [r for r in summary.upper_house_groups(data) if r["party"] == "socialists"]
    if any(r["votes"] for r in u):
        print("\nVictorian Socialists, upper house:")
        for r in (r for r in u if r["votes"]):
            print(f"  {r['region']:<32} {r['votes']:>8,}  {_p(r['pct']):>6}%  quotas {_p(r['quotas'])}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vicresults")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("contract"); c.add_argument("-o", "--out")
    f = sub.add_parser("fetch"); f.add_argument("--sample", choices=SAMPLES); f.add_argument("-o", "--out", required=True)
    for name in ("validate", "summary"):
        s = sub.add_parser(name)
        g = s.add_mutually_exclusive_group()
        g.add_argument("--sample", choices=SAMPLES)
        g.add_argument("--file")
        if name == "validate":
            s.add_argument("--contract", help="local contract file (default: fetch it)")
        else:
            s.add_argument("--top", type=int, default=15)
    pl = sub.add_parser("poll")
    pl.add_argument("--out", default="data")
    pl.add_argument("--sample", choices=SAMPLES)
    pl.add_argument("--until", help="Melbourne time HH:MM to stop (next occurrence); default: run until stopped")
    pl.add_argument("--once", action="store_true")
    sv = sub.add_parser("serve")
    sv.add_argument("--out", default="data")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--baseline", help="baseline feed file (default: <out>/baseline-2022-final.json.gz, fetched once)")
    sv.add_argument("--until", help="Melbourne time HH:MM to stop polling")
    bd = sub.add_parser("build")
    bd.add_argument("--out", default="data")
    bd.add_argument("--site", default="site")
    bd.add_argument("--baseline")
    for q in (sv, bd):
        g = q.add_mutually_exclusive_group()
        g.add_argument("--sample", choices=SAMPLES)
        g.add_argument("--file")
    args = p.parse_args(argv)

    try:
        if args.cmd == "contract":
            doc = AnalysisClient().openapi()
            if args.out:
                _save(doc, args.out)
            else:
                json.dump(doc, sys.stdout, indent=1)
        elif args.cmd == "fetch":
            data = AnalysisClient().analysis(args.sample)
            _save(data, args.out)
            print(json.dumps(data.get("files"), indent=1))
        elif args.cmd == "validate":
            data = _load(args)
            contract = json.loads(Path(args.contract).read_text()) if args.contract else AnalysisClient().openapi()
            problems = validate(data, contract)
            for x in problems[:50]:
                print(x)
            print("OK: matches components.schemas.Analysis" if not problems else f"{len(problems)} problems")
            return 1 if problems else 0
        elif args.cmd == "summary":
            _print_summary(_load(args), args.top)
        elif args.cmd == "poll":
            from .poll import MELBOURNE, now_mel, run
            until = None
            if args.until:
                hh, mm = map(int, args.until.split(":"))
                n = now_mel()
                until = n.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if until <= n:
                    until += timedelta(days=1)
            return run(Path(args.out), sample=args.sample, until=until, once=args.once)
        elif args.cmd == "serve":
            from .poll import now_mel
            from .serve import serve
            until = None
            if args.until:
                hh, mm = map(int, args.until.split(":"))
                n = now_mel()
                until = n.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if until <= n:
                    until += timedelta(days=1)
            return serve(Path(args.out), port=args.port, host=args.host, sample=args.sample,
                         file=args.file, baseline=args.baseline, until=until)
        elif args.cmd == "build":
            from .serve import build_site, load_baseline
            cur = _load(args)
            client = None if args.baseline or (Path(args.out) / "baseline-2022-final.json.gz").exists() else AnalysisClient()
            base, _ = load_baseline(Path(args.out), client, Path(args.baseline) if args.baseline else None)
            build_site(cur, base, Path(args.site))
            print(f"wrote {args.site}/index.html and {args.site}/data.json")
    except AnalysisError as e:
        print(f"API error {e}", file=sys.stderr)
        if e.body.get("issues"):
            print(json.dumps(e.body["issues"][:20], indent=1), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
