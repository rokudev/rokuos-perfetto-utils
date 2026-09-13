#!/usr/bin/env python3
"""Run one of this skill's named queries against a trace.

    query.py <trace> <name> [--limit N] [--set field=applanguages]
    query.py --list

The queries live in `queries/` beside this script. Running them here rather
than pasting the SQL keeps the query text out of the agent's context - only
the result comes back. Read the .sql file directly when you need to adapt a
query rather than just run it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from perfetto.trace_processor import TraceProcessor
except ImportError:  # pragma: no cover
    sys.exit("The 'perfetto' package is required: pip install perfetto")

QUERIES = Path(__file__).resolve().parent / "queries"


def available() -> list[str]:
    return sorted(p.stem for p in QUERIES.glob("*.sql"))


def load(name: str, params: dict[str, str]) -> str:
    """Read a query and fill its {placeholders}.

    A query with an unfilled placeholder is a usage error, not something to
    send to the database - say which one is missing rather than failing with
    an opaque SQL error.
    """
    path = QUERIES / f"{name}.sql"
    if not path.exists():
        sys.exit(f"No query named '{name}'. Available: {', '.join(available())}")
    sql = path.read_text(encoding="utf-8")
    try:
        return sql.format(**params)
    except KeyError as missing:
        sys.exit(f"Query '{name}' needs --set {missing.args[0]}=<value>")


def table(rows: list) -> None:
    """Print rows aligned, numeric columns right-justified."""
    if not rows:
        print("  (no rows)")
        return
    cols = list(rows[0].__dict__)
    cells = [[("-" if getattr(r, c) is None else str(getattr(r, c)))
              for c in cols] for r in rows]
    width = [max(len(c), *(len(row[i]) for row in cells))
             for i, c in enumerate(cols)]
    numeric = [all(row[i].replace(".", "").replace("-", "").isdigit()
                   for row in cells) for i in range(len(cols))]

    def line(values):
        return "  " + "  ".join(
            v.rjust(width[i]) if numeric[i] else v.ljust(width[i])
            for i, v in enumerate(values)).rstrip()

    print(line(cols))
    print("  " + "  ".join("-" * w for w in width))
    for row in cells:
        print(line(row))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", nargs="?", help="Perfetto trace file")
    ap.add_argument("name", nargs="?", help="query name (see --list)")
    ap.add_argument("--limit", type=int, default=20,
                    help="row limit for queries that take one (default 20)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="fill a {placeholder} in the query; repeatable")
    ap.add_argument("--list", action="store_true", help="list query names")
    args = ap.parse_args()

    if args.list or not (args.trace and args.name):
        print("\n".join(available()))
        return 0 if args.list else 2

    params = {"limit": args.limit}
    for pair in args.set:
        key, _, value = pair.partition("=")
        params[key] = value

    sql = load(args.name, params)
    tp = TraceProcessor(trace=args.trace)
    try:
        table(list(tp.query(sql)))
    finally:
        tp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
