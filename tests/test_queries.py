#!/usr/bin/env python3
"""Check the skill's queries against a trace whose answers are known.

    python tests/test_queries.py

Builds two synthetic traces - one from a build carrying cpu_us, depth and id,
one without - and asserts the queries report the values make_trace.py put
there. Exits non-zero on the first failure.

The point is the degradation paths as much as the numbers: several queries are
supposed to return nothing on the older build and be replaced by a fallback,
and that is easy to break without noticing.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_trace import EXPECTED, build  # noqa: E402

try:
    from perfetto.trace_processor import TraceProcessor
except ImportError:  # pragma: no cover
    sys.exit("The 'perfetto' package is required: pip install perfetto")

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".agents" / "skills" / "channel-performance-analysis"
failures: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ok   {label}: {got}")
    else:
        print(f"  FAIL {label}: got {got}, want {want}")
        failures.append(label)


def scalar(tp, sql):
    rows = list(tp.query(sql))
    return getattr(rows[0], "v") if rows else None


def run_query(trace: Path, name: str, *extra: str) -> str:
    """Run one of the skill's named queries, as the skill tells you to."""
    out = subprocess.run(
        [sys.executable, str(SKILL / "query.py"), str(trace), name, *extra],
        capture_output=True, text=True)
    if out.returncode != 0:
        failures.append(f"query {name} exited {out.returncode}")
    return out.stdout


def check_trace(path: Path, new_build: bool) -> None:
    label = "newer build" if new_build else "older build"
    print(f"\n{label} ({path.name})")
    tp = TraceProcessor(trace=str(path))
    try:
        # Observer cascades: the outermost total is the real one. The naive sum
        # counts every level, which is the mistake the skill exists to prevent.
        check("outermost observer ms", scalar(tp, """
            SELECT ROUND(SUM(dur) / 1e6, 1) AS v FROM slice
            WHERE name = 'observer.callback' AND dur >= 0
              AND NOT EXISTS (SELECT 1 FROM ancestor_slice(slice.id) a
                              WHERE a.name = 'observer.callback')"""),
              EXPECTED["observer_outermost_ms"])
        check("naive observer ms", scalar(tp, """
            SELECT ROUND(SUM(dur) / 1e6, 1) AS v FROM slice
            WHERE name = 'observer.callback' AND dur >= 0"""),
              EXPECTED["observer_naive_ms"])

        # Cross-thread writes, and the flows the latency split depends on.
        check("rendezvous count", scalar(tp, """
            SELECT COUNT(*) AS v FROM slice
            WHERE name = 'Rendezvous' AND dur >= 0"""),
              EXPECTED["field_writes"])
        check("blocked ms", scalar(tp, """
            SELECT ROUND(SUM(dur) / 1e6, 1) AS v FROM slice
            WHERE name = 'Rendezvous' AND dur >= 0"""),
              EXPECTED["field_blocked_ms"])
        check("flows paired", scalar(tp, "SELECT COUNT(*) AS v FROM flow"),
              EXPECTED["field_writes"])

        # Frames: the signal is the swap-to-swap interval, not the length of
        # any one slice, since a frame can miss three different ways.
        check("frames", scalar(tp, """
            SELECT COUNT(*) AS v FROM slice WHERE name = 'render'"""),
              EXPECTED["frames"])
        cadence = """
            WITH sw AS (SELECT ts, LEAD(ts) OVER (ORDER BY ts) AS next_ts
                        FROM slice WHERE name = 'swapBuffers' AND dur >= 0)
            SELECT %s AS v FROM sw WHERE next_ts IS NOT NULL"""
        check("frame intervals", scalar(tp, cadence % "COUNT(*)"),
              EXPECTED["frame_intervals"])
        check("intervals over 16.7 ms",
              scalar(tp, cadence % "SUM((next_ts - ts) > 16700000)"),
              EXPECTED["intervals_over_16_7ms"])
        # An idle gap is over budget but is not a missed frame: the channel
        # had nothing to draw. The cadence query must tell them apart.
        check("missed frames (busy gaps only)", scalar(tp, """
            WITH sw AS (
              SELECT s.id, s.ts, s.dur, tt.utid,
                     LEAD(s.ts) OVER (ORDER BY s.ts) AS next_ts
              FROM slice s JOIN thread_track tt ON s.track_id = tt.id
              WHERE s.name = 'swapBuffers' AND s.dur >= 0)
            SELECT SUM(len > 16700000 AND busy * 2 > len) AS v FROM (
              SELECT sw.next_ts - sw.ts AS len,
                     sw.dur + IFNULL((SELECT SUM(b.dur) FROM slice b
                             JOIN thread_track btt ON b.track_id = btt.id
                             WHERE btt.utid = sw.utid AND b.depth = 0
                               AND b.dur >= 0 AND b.ts >= sw.ts + sw.dur
                               AND b.ts < sw.next_ts), 0) AS busy
              FROM sw WHERE sw.next_ts IS NOT NULL)"""),
              EXPECTED["intervals_missed"])
        check("swaps over 16 ms (first excluded)", scalar(tp, """
            SELECT SUM(dur > 16000000) AS v FROM slice
            WHERE name = 'swapBuffers' AND dur >= 0
              AND ts > (SELECT MIN(ts) FROM slice WHERE name = 'swapBuffers')"""),
              EXPECTED["swaps_over_16ms"])

        # The unfinished slice must not be counted anywhere.
        check("unfinished slices present", scalar(tp, """
            SELECT COUNT(*) AS v FROM slice WHERE dur < 0"""), 1)

        # The later arguments, and the degradation when they are absent.
        depth_rows = scalar(tp, """
            SELECT COUNT(*) AS v FROM slice
            WHERE name = 'observer.callback'
              AND EXTRACT_ARG(arg_set_id, 'debug.depth') = 0""")
        check("depth=0 rows", depth_rows,
              EXPECTED["observers_at_depth_0"] if new_build else 0)
        check("node ids on field ops", scalar(tp, """
            SELECT COUNT(DISTINCT EXTRACT_ARG(arg_set_id, 'debug.id')) AS v
            FROM slice WHERE name LIKE 'roSGNode.%'"""),
              1 if new_build else 0)
        check("cpu_us present", scalar(tp, """
            SELECT COUNT(*) AS v FROM slice WHERE dur >= 0
              AND EXTRACT_ARG(arg_set_id, 'debug.cpu_us') IS NOT NULL"""),
              2 if new_build else 0)
    finally:
        tp.close()

    # The named queries must at least run, and the observers pair must behave:
    # the depth one returns nothing without the argument, the fallback does not.
    for name in ("args", "overview", "rendezvous", "observers-no-depth",
                 "frames", "frame-cadence", "frame-breakdown", "swapbuffers",
                 "repeated-reads", "write-bursts"):
        if not run_query(path, name).strip():
            failures.append(f"query {name} produced no output")
    has_rows = "onOuter" in run_query(path, "observers")
    check("observers query returns rows", has_rows, new_build)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        for new_build in (True, False):
            path = Path(tmp) / ("new.pb" if new_build else "old.pb")
            build(new_build).write(str(path))
            check_trace(path, new_build)
    print()
    if failures:
        print(f"{len(failures)} failure(s): {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
