#!/usr/bin/env python3
"""Report on channel performance bottlenecks in a Perfetto trace.

Finds the things that usually make a Roku channel slow:

  * cross-thread field access (rendezvous), split into queueing latency
    versus work done on the render thread
  * cross-domain data copies
  * fields read repeatedly in a loop
  * slow field observers
  * network requests, from issue to response

Some of this needs arguments that only newer firmware emits - thread CPU time,
observer nesting depth, node ids. Which slices carry them is discovered from
the trace, not assumed, because it differs between builds. The report says
what the capture has and falls back where it can, so it still runs against an
older trace.

Run with no options for the full report:

    channel-perf trace.bin

See the channel-performance-analysis skill in this repository for what the
numbers mean and for queries to
dig further into any individual finding.
"""

from __future__ import annotations

import argparse
import sys

try:
    from perfetto.trace_processor import TraceProcessor
except ImportError:  # pragma: no cover
    sys.exit("The 'perfetto' package is required: pip install perfetto")

MS = 1e6

# Every section reports the slice id of the row it is pointing at, so a
# finding can be looked up in the trace instead of hunted for by eye.
#
# Two ways to get it out of a GROUP BY, both used below:
#
#   * When the query has exactly one MIN() or MAX(), a bare column takes its
#     value from the row that produced it - a documented SQLite behaviour that
#     trace processor inherits. `MAX(dur) ... , id` is that row's id.
#   * Otherwise the choice would be arbitrary, so the row is picked explicitly
#     with ROW_NUMBER() and read back as MAX(CASE WHEN rk = 1 THEN id END).


def ms(ns) -> str:
    """Nanoseconds as milliseconds, or '-' when absent."""
    return "-" if ns is None else f"{ns / MS:.2f}"


def short(text, width: int = 22) -> str:
    """A node id shortened to keep the table readable, or '-' when absent.

    Content node ids are often long generated keys, so the tail is kept -
    that is where such keys differ. The width leaves markup ids, which are
    hand-written and short, untouched.
    """
    if not text:
        return "-"
    return text if len(text) <= width else "\u2026" + text[-(width - 1):]


class Report:
    """Runs the analysis sections against one trace and prints the report.

    Each public method is one section of the report and is named in
    ``SECTIONS``, so ``--section`` can select it by name.
    """

    def __init__(self, tp: TraceProcessor, top: int) -> None:
        """`top` caps the rows printed per section."""
        self.tp = tp
        self.top = top

    def q(self, sql: str) -> list:
        """Run a query and return all rows."""
        return list(self.tp.query(sql))

    def scalar(self, sql: str, field: str, default=0):
        """One value from the first row, or `default` if absent or NULL."""
        rows = self.q(sql)
        if not rows:
            return default
        value = getattr(rows[0], field)
        return default if value is None else value

    @staticmethod
    def heading(title: str) -> None:
        print(f"\n{title}\n{'=' * len(title)}")

    @staticmethod
    def table(headers: list[str], rows: list[list[str]]) -> None:
        """Print an aligned table, right-justifying numeric columns."""
        if not rows:
            print("  (nothing found)")
            return
        widths = [
            max(len(str(h)), *(len(str(r[i])) for r in rows))
            for i, h in enumerate(headers)
        ]
        # numeric-looking columns right-align, text left-aligns
        right = [
            all(str(r[i]).replace(".", "").replace("-", "").isdigit()
                for r in rows)
            for i in range(len(headers))
        ]

        def line(cells):
            return "  " + "  ".join(
                str(c).rjust(widths[i]) if right[i] else str(c).ljust(widths[i])
                for i, c in enumerate(cells)
            ).rstrip()

        print(line(headers))
        print("  " + "  ".join("-" * w for w in widths))
        for r in rows:
            print(line(r))

    # -- sections ---------------------------------------------------------

    def trace_info(self) -> None:
        """What the capture contains. Always printed, before any section.

        Also records the flow count, which the rendezvous and callFunc
        sections need in order to separate queueing from execution.
        """
        self.heading("Trace")
        span = self.scalar(
            "SELECT end_ts - start_ts AS v FROM trace_bounds", "v")
        slices = self.scalar("SELECT COUNT(*) AS v FROM slice", "v")
        threads = self.scalar(
            "SELECT COUNT(DISTINCT utid) AS v FROM thread_track", "v")
        print(f"  duration      {span / 1e9:.1f} s")
        print(f"  slices        {slices}")
        print(f"  threads       {threads}")

        procs = self.q("""
            SELECT IFNULL(p.name, '?') AS nm, p.pid AS pid, COUNT(*) AS n
            FROM slice s
            JOIN thread_track tt ON s.track_id = tt.id
            JOIN thread t ON tt.utid = t.utid
            JOIN process p ON t.upid = p.upid
            GROUP BY 1, 2 ORDER BY n DESC
        """)
        for p in procs:
            print(f"  process       {p.nm} (pid {p.pid}), {p.n} slices")

        self.flows = self.scalar("SELECT COUNT(*) AS v FROM flow", "v")
        print(f"  flow records  {self.flows}")
        self.probe_args()

    def probe_args(self) -> None:
        """Record which optional arguments this capture has, and say so.

        Three arguments were added to the firmware later than the rest.
        Sections degrade rather than lie when they are absent, but the reader
        has to be told, so a finding is never mistaken for a measurement that
        could not be made.

        `dur >= 0` matters: an unfinished slice never ran its end event, so it
        never carries `debug.cpu_us`, and counting those as missing makes a
        working build look broken.
        """
        # Ask the trace which slices carry them rather than assuming: the set
        # is a property of the firmware build and keeps changing, so a list
        # written into this file would go stale.
        rows = self.q("""
            SELECT name AS slice,
                   SUM(EXTRACT_ARG(arg_set_id, 'debug.cpu_us') IS NOT NULL)
                     AS cpu_us,
                   SUM(EXTRACT_ARG(arg_set_id, 'debug.depth') IS NOT NULL)
                     AS depth,
                   SUM(EXTRACT_ARG(arg_set_id, 'debug.id') IS NOT NULL)
                     AS node_id
            FROM slice WHERE dur >= 0
            GROUP BY 1 HAVING cpu_us + depth + node_id > 0
        """)
        # A slice name can be NULL, so never call string methods on it bare.
        self.cpu_us_slices = sorted(r.slice for r in rows
                                    if r.cpu_us and r.slice)
        self.has_cpu_us = bool(self.cpu_us_slices)
        # These two are scoped to the slices the sections below read them
        # from, which is not the same as "the argument appears somewhere".
        # debug.id in particular predates node ids on field operations - it
        # has always been on roSGNodeEvent slices, and matching those would
        # report the capability on a build that lacks it. Note roSGNodeEvent
        # does not match 'roSGNode.%'.
        self.has_depth = any(r.depth for r in rows
                             if r.slice == "observer.callback")
        self.has_node_id = any(r.node_id for r in rows
                               if (r.slice or "").startswith("roSGNode."))

        have = [n for n, ok in (("cpu_us", self.has_cpu_us),
                                ("depth", self.has_depth),
                                ("id", self.has_node_id)) if ok]
        missing = [n for n, ok in (("cpu_us", self.has_cpu_us),
                                   ("depth", self.has_depth),
                                   ("id", self.has_node_id)) if not ok]
        print(f"  extra args    {', '.join(have) if have else 'none'}"
              + (f" (missing: {', '.join(missing)} - older build)"
                 if missing else ""))
        if self.cpu_us_slices:
            print(f"  cpu_us on     {', '.join(self.cpu_us_slices)}")

        # Lost packets cost end-event arguments, so a few slices can be
        # missing cpu_us on a build that emits it. Say so before anyone
        # concludes the instrumentation is broken.
        lost = self.q("""
            SELECT name, value FROM stats
            WHERE value > 0 AND (name LIKE '%loss%' OR name LIKE '%skipped%')
            ORDER BY value DESC LIMIT 3
        """)
        if lost:
            detail = ", ".join(f"{r.name}={r.value}" for r in lost)
            print(f"  packet loss   {detail}")
            print("                some slices may be missing arguments or "
                  "flows as a result")

    def overview(self) -> None:
        """Total time per slice name: which later section is worth reading.

        Slices nest, so these totals overlap and do not apportion blame.
        """
        self.heading("Where the time goes")
        print("  Slices nest, so these totals overlap. Use this to decide "
              "where to look.")
        if self.has_cpu_us:
            print("  cpu_ms is thread CPU time. Far below total_ms means the "
                  "thread was\n  blocked, not working - the time shown is "
                  "not a cost to optimise.\n")
        else:
            print("  No cpu_us in this capture, so a long slice cannot be "
                  "told apart from\n  a blocked one. Do not assume either.\n")
        rows = self.q(f"""
            SELECT name, COUNT(*) AS n, SUM(dur) AS total, MAX(dur) AS worst,
                   SUM(EXTRACT_ARG(arg_set_id, 'debug.cpu_us')) AS cpu_us,
                   id AS worst_id
            FROM slice WHERE dur >= 0
            GROUP BY name ORDER BY total DESC LIMIT {self.top}
        """)
        if self.has_cpu_us:
            # cpu_us is only on the BrightScript-emitted slices; '-' elsewhere
            # is "not measured", not zero.
            self.table(
                ["total_ms", "cpu_ms", "count", "worst_ms", "worst_id",
                 "slice"],
                [[ms(r.total),
                  "-" if r.cpu_us is None else f"{r.cpu_us / 1000.0:.2f}",
                  r.n, ms(r.worst), r.worst_id, r.name] for r in rows],
            )
        else:
            self.table(
                ["total_ms", "count", "worst_ms", "worst_id", "slice"],
                [[ms(r.total), r.n, ms(r.worst), r.worst_id, r.name]
                 for r in rows],
            )

    def rendezvous(self) -> None:
        """Cross-thread field access, split into queueing and execution.

        A `Rendezvous` slice is the caller blocked waiting for the render
        thread. Its duration is the total cost; the flow from
        `rendezvous-enqueue` to `rendezvous-dequeue` is how much of that was
        spent queued, and the remainder is the work itself. The distinction
        matters: queueing means the render thread is busy elsewhere, while
        execution means this particular field is expensive.
        """
        self.heading("Cross-thread field access (rendezvous)")
        total = self.scalar(
            "SELECT COUNT(*) AS v FROM slice WHERE name = 'Rendezvous'", "v")
        if not total:
            print("  No 'Rendezvous' slices - no cross-thread field access "
                  "was traced.")
            return

        print("  latency = queued before the render thread ran it "
              "(render thread is busy)")
        print("  exec    = work once started: the copy, plus any observers "
              "(this field is slow)\n")
        rows = self.q(f"""
            WITH rv AS (
              SELECT ct.name AS calling_thread, rz.id AS slice_id,
                IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.component'), '?')
                || '.' ||
                IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.name'), '?') AS field,
                EXTRACT_ARG(op.arg_set_id, 'debug.id') AS node_id,
                rz.dur AS total_ns,
                (deq.ts - enq.ts) AS latency_ns,
                rz.dur - (deq.ts - enq.ts) AS exec_ns
              FROM slice rz
              JOIN slice enq
                ON enq.parent_id = rz.id AND enq.name = 'rendezvous-enqueue'
              JOIN flow f ON f.slice_out = enq.id
              JOIN slice deq ON deq.id = f.slice_in
              LEFT JOIN slice op ON op.id = rz.parent_id
              JOIN thread_track ctt ON rz.track_id = ctt.id
              JOIN thread ct ON ctt.utid = ct.utid
              WHERE rz.name = 'Rendezvous' AND rz.dur >= 0
            ), ranked AS (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY calling_thread, field
                                           ORDER BY total_ns DESC) AS rk
              FROM rv
            )
            SELECT calling_thread, field, node_id, COUNT(*) AS n,
                   SUM(total_ns) AS total,
                   MAX(latency_ns) AS max_lat, MAX(exec_ns) AS max_exec,
                   SUM(latency_ns) AS sum_lat,
                   MAX(CASE WHEN rk = 1 THEN slice_id END) AS worst_id
            FROM ranked GROUP BY 1, 2, 3 ORDER BY total DESC LIMIT {self.top}
        """)
        # Grouping by the node id splits a field that several nodes share,
        # which is the point: one node written 35 times and 35 nodes written
        # once need different fixes.
        out = []
        for r in rows:
            bound = "latency" if (r.sum_lat or 0) * 2 > (r.total or 1) \
                else "exec"
            row = [ms(r.total), r.n, ms(r.max_lat), ms(r.max_exec),
                   bound, r.worst_id, r.field]
            if self.has_node_id:
                row.append(short(r.node_id))
            row.append(r.calling_thread)
            out.append(row)
        headers = ["total_ms", "count", "max_lat_ms", "max_exec_ms",
                   "bound_by", "worst_id", "field"]
        if self.has_node_id:
            headers.append("node")
        headers.append("calling_thread")
        self.table(headers, out)

        resolved = self.scalar("""
            SELECT COUNT(*) AS v FROM slice rz
            JOIN slice enq ON enq.parent_id = rz.id
              AND enq.name = 'rendezvous-enqueue'
            JOIN flow f ON f.slice_out = enq.id
            WHERE rz.name = 'Rendezvous' AND rz.dur >= 0
        """, "v")
        if resolved < total:
            print(f"\n  ({resolved} of {total} rendezvous had a matching flow; "
                  "the rest are omitted.)")

    def callfunc(self) -> None:
        """callFunc cost, split into queueing, function body and copying.

        A cross-thread callFunc copies its arguments over, runs the function
        on the render thread, and copies the result back. The body is the
        `ExecBrightScript` slice under the same `consumeAllTasks` batch as
        the dequeue - matching on the batch rather than on time alone keeps
        out other work the render thread interleaves. Neither copy is traced,
        so copying is reported as the unexplained remainder.
        """
        self.heading("callFunc")
        same = self.scalar("""
            SELECT COUNT(*) AS v FROM slice cf
            WHERE cf.name = 'roSGNode.callFunc' AND cf.dur >= 0
              AND NOT EXISTS (SELECT 1 FROM slice rz
                  WHERE rz.parent_id = cf.id AND rz.name = 'Rendezvous')
        """, "v")
        print("  A cross-thread callFunc copies its arguments over, runs the "
              "function on the\n  render thread, then copies the result back. "
              "The copies are not traced\n  individually, so they show up as "
              "'copy_ms' - the unexplained remainder.\n")
        rows = self.q(f"""
            WITH cf AS (
              SELECT ct.name AS calling_thread, op.arg_set_id AS aset,
                     rz.id AS slice_id,
                     rz.ts AS rz_ts, rz.dur AS total_ns,
                     (deq.ts - enq.ts) AS latency_ns,
                     deq.ts AS deq_ts, deq.parent_id AS batch
              FROM slice rz
              JOIN slice enq ON enq.parent_id = rz.id
                AND enq.name = 'rendezvous-enqueue'
              JOIN flow f ON f.slice_out = enq.id
              JOIN slice deq ON deq.id = f.slice_in
              JOIN slice op ON op.id = rz.parent_id
                AND op.name = 'roSGNode.callFunc'
              JOIN thread_track ctt ON rz.track_id = ctt.id
              JOIN thread ct ON ctt.utid = ct.utid
              WHERE rz.name = 'Rendezvous' AND rz.dur >= 0
            ), parts AS (
              SELECT calling_thread, slice_id,
                IFNULL(EXTRACT_ARG(aset, 'debug.component'), '?') || '.' ||
                IFNULL(EXTRACT_ARG(aset, 'debug.name'), '?') AS function,
                total_ns, latency_ns,
                IFNULL((SELECT SUM(e.dur) FROM slice e
                        WHERE e.parent_id = cf.batch
                          AND e.name = 'ExecBrightScript'
                          AND e.ts >= cf.deq_ts
                          AND e.ts < cf.rz_ts + cf.total_ns
                          AND e.dur >= 0), 0) AS body_ns
              FROM cf
            ), ranked AS (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY calling_thread, function
                                           ORDER BY total_ns DESC) AS rk
              FROM parts
            )
            SELECT calling_thread, function, COUNT(*) AS n,
                   SUM(total_ns) AS total, SUM(latency_ns) AS lat,
                   SUM(body_ns) AS body,
                   SUM(total_ns - latency_ns - body_ns) AS copy,
                   MAX(CASE WHEN rk = 1 THEN slice_id END) AS worst_id
            FROM ranked GROUP BY 1, 2 ORDER BY total DESC LIMIT {self.top}
        """)
        out = []
        for r in rows:
            parts = {"latency": r.lat or 0, "body": r.body or 0,
                     "copy": r.copy or 0}
            out.append([ms(r.total), r.n, ms(r.lat), ms(r.body), ms(r.copy),
                        max(parts, key=parts.get), r.worst_id, r.function,
                        r.calling_thread])
        self.table(
            ["total_ms", "count", "latency_ms", "body_ms", "copy_ms",
             "dominated_by", "worst_id", "function", "calling_thread"], out)
        if rows:
            print("\n  latency - the render thread is busy; call it less often")
            print("  body    - the function itself is slow")
            print("  copy    - arguments or return value are large; pass node "
                  "references")
        if same:
            print(f"\n  ({same} more callFunc calls ran on the owning thread "
                  "with no rendezvous;\n   those involve no copying and are "
                  "not shown.)")

    def copies(self) -> None:
        """Cross-domain copies, attributed to a field.

        `bscCopyToDomainEx` carries no arguments, so the field name comes
        from the enclosing operation. Note the event covers only the newer
        fast path, so this under-reports total copying.

        Each copy is classified by whether its enclosing access went via a
        rendezvous, which decides what can replace it: `getRef`/`setRef` are
        render-thread only and cannot replace a cross-thread access, whereas
        the move functions work either way but are destructive. The copy is a
        sibling of the `Rendezvous`, not a child, so the test is on the parent
        operation.
        """
        self.heading("Cross-domain copies")
        print("  Data copied between BrightScript domains. The field name "
              "comes from the\n  enclosing operation - the copy itself "
              "carries no arguments.\n")
        rows = self.q(f"""
            WITH cp AS (
              SELECT c.dur, c.id, t.name AS thread, op.name AS operation,
                IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.component'), '?')
                || '.' ||
                IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.name'), '?') AS field,
                EXTRACT_ARG(op.arg_set_id, 'debug.id') AS node_id,
                EXISTS (SELECT 1 FROM slice rz
                        WHERE rz.parent_id = op.id AND rz.name = 'Rendezvous')
                  AS cross_thread
              FROM slice c
              JOIN slice op ON op.id = c.parent_id
              JOIN thread_track tt ON c.track_id = tt.id
              JOIN thread t ON tt.utid = t.utid
              WHERE c.name = 'bscCopyToDomainEx' AND c.dur >= 0
            )
            SELECT field, operation, thread, cross_thread, node_id,
                   COUNT(*) AS n,
                   SUM(dur) AS total, MAX(dur) AS worst, id AS worst_id
            FROM cp GROUP BY 1, 2, 3, 4, 5 ORDER BY total DESC
            LIMIT {self.top}
        """)
        out = []
        for r in rows:
            on_render = r.thread in ("RenderThr:Main", "AuxRenderThread")
            # getRef/setRef are render-thread only and cannot replace an
            # access that goes via a rendezvous; a move works either way but
            # is destructive.
            if not r.cross_thread and on_render:
                fix = "getRef?"
            else:
                fix = "move?"
            row = [ms(r.total), r.n, ms(r.worst),
                   "yes" if r.cross_thread else "no", fix, r.worst_id,
                   r.operation, r.field]
            if self.has_node_id:
                row.append(short(r.node_id))
            row.append(r.thread)
            out.append(row)
        headers = ["total_ms", "copies", "worst_ms", "cross_thread",
                   "candidate", "worst_id", "operation", "field"]
        if self.has_node_id:
            headers.append("node")
        headers.append("thread")
        self.table(headers, out)
        if rows:
            print("\n  getRef? - same-thread access on a render thread: "
                  "getRef/setRef may avoid the copy")
            print("  move?   - getRef/setRef not usable here; "
                  "moveIntoField/moveFromField may help,")
            print("            but they are destructive - only if the caller "
                  "is done with the value")
            print("  Both are candidates only; the trace cannot show whether "
                  "the value is reused.")

        used = self.q("""
            SELECT name, COUNT(*) AS n FROM slice
            WHERE name IN ('roSGNode.getRef', 'roSGNode.setRef',
                           'roSGNode.moveIntoField',
                           'roSGNode.moveFromField') AND dur >= 0
            GROUP BY name ORDER BY n DESC
        """)
        if used:
            print("\n  Already in use: "
                  + ", ".join(f"{r.name.split('.')[-1]} x{r.n}" for r in used))

    def repeats(self) -> None:
        """Runs of consecutive reads of one field on one thread.

        Two row numberings, one per thread and one per thread-and-field,
        stay a constant distance apart for as long as the same field is read
        consecutively, so their difference groups each run. A long run is
        usually a polling loop.
        """
        self.heading("Repeated reads of the same field")
        print("  Runs of consecutive reads of one field on one thread. A long "
              "run is\n  usually a polling loop: observe the field instead, "
              "or cache it.\n")
        rows = self.q(f"""
            WITH reads AS (
              SELECT s.id, s.ts, s.dur, tt.utid, t.name AS thread,
                     EXTRACT_ARG(s.arg_set_id, 'debug.component') AS comp,
                     EXTRACT_ARG(s.arg_set_id, 'debug.name') AS field,
                     EXTRACT_ARG(s.arg_set_id, 'debug.id') AS node_id
              FROM slice s
              JOIN thread_track tt ON s.track_id = tt.id
              JOIN thread t ON tt.utid = t.utid
              WHERE s.name = 'roSGNode.getField' AND s.dur >= 0
            ), seq AS (
              SELECT *,
                ROW_NUMBER() OVER (PARTITION BY utid ORDER BY ts) AS rn,
                ROW_NUMBER() OVER (PARTITION BY utid, comp, field ORDER BY ts)
                  AS rn_field
              FROM reads
            )
            SELECT thread, comp || '.' || field AS field,
                   COUNT(*) AS n, SUM(dur) AS total,
                   MIN(ts) AS first_ts, id AS first_id, node_id
            FROM seq
            GROUP BY thread, comp, field, rn - rn_field
            HAVING COUNT(*) > 1
            ORDER BY n DESC LIMIT {self.top}
        """)
        # The single MIN(ts) makes the bare columns - first_id, node_id - come
        # from the run's first read, which is the one worth naming.
        if self.has_node_id:
            self.table(
                ["reads", "total_ms", "first_id", "field", "node", "thread"],
                [[r.n, ms(r.total), r.first_id, r.field,
                  short(r.node_id), r.thread] for r in rows],
            )
        else:
            self.table(
                ["reads", "total_ms", "first_id", "field", "thread"],
                [[r.n, ms(r.total), r.first_id, r.field, r.thread]
                 for r in rows],
            )

    def network(self) -> None:
        """Network requests, measured from issue to response event.

        `AsyncGetToString` and `AsyncPostFromString` are instant events marking
        the moment a transfer is started; the response arrives later as a
        `postEvent`, and a flow connects the two. The gap between them is the
        round trip. A request with no flow never completed within the capture.

        These intervals overlap - several requests are usually in flight at
        once - so the total is not wall-clock time the channel spent waiting.
        """
        self.heading("Network requests")
        started = self.scalar("""
            SELECT COUNT(*) AS v FROM slice
            WHERE name IN ('AsyncGetToString', 'AsyncPostFromString')
        """, "v")
        if not started:
            print("  No roUrlTransfer activity traced.")
            return

        print("  Measured from the request being issued to its response event "
              "arriving.\n  Requests overlap, so total_ms is not wall-clock "
              "time spent waiting.\n")
        rows = self.q(f"""
            WITH started AS (
              SELECT s.id, s.ts, s.name AS method, t.name AS thread,
                     EXTRACT_ARG(s.arg_set_id, 'debug.url') AS url
              FROM slice s
              JOIN thread_track tt ON s.track_id = tt.id
              JOIN thread t ON tt.utid = t.utid
              WHERE s.name IN ('AsyncGetToString', 'AsyncPostFromString')
            ), req AS (
              SELECT st.id, st.method, st.thread, st.url,
                     done.ts - st.ts AS elapsed
              FROM started st
              LEFT JOIN flow f ON f.slice_out = st.id
              LEFT JOIN slice done ON done.id = f.slice_in
            ), ranked AS (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY method, thread
                                           ORDER BY elapsed DESC) AS rk
              FROM req
            )
            SELECT method, thread, COUNT(*) AS n,
                   SUM(elapsed IS NULL) AS unfinished,
                   SUM(elapsed) AS total, AVG(elapsed) AS mean,
                   MAX(elapsed) AS worst,
                   MAX(CASE WHEN rk = 1 THEN id END) AS worst_id
            FROM ranked GROUP BY 1, 2
            ORDER BY IFNULL(total, 0) DESC LIMIT {self.top}
        """)
        self.table(
            ["total_ms", "count", "unfinished", "mean_ms", "worst_ms",
             "worst_id", "method", "thread"],
            [[ms(r.total), r.n, r.unfinished, ms(r.mean), ms(r.worst),
              r.worst_id if r.worst_id is not None else "-",
              r.method.replace("Async", ""), r.thread] for r in rows],
        )

        endpoints = self.q(f"""
            WITH started AS (
              SELECT s.id, s.ts,
                     EXTRACT_ARG(s.arg_set_id, 'debug.url') AS url
              FROM slice s
              WHERE s.name IN ('AsyncGetToString', 'AsyncPostFromString')
            )
            SELECT CASE WHEN INSTR(url, '?') > 0
                        THEN SUBSTR(url, 1, INSTR(url, '?') - 1)
                        ELSE url END AS endpoint,
                   COUNT(*) AS n, SUM(done.ts - st.ts) AS total,
                   MAX(done.ts - st.ts) AS worst
            FROM started st
            LEFT JOIN flow f ON f.slice_out = st.id
            LEFT JOIN slice done ON done.id = f.slice_in
            GROUP BY 1 ORDER BY IFNULL(total, 0) DESC LIMIT {self.top}
        """)
        if endpoints:
            print()
            self.table(
                ["total_ms", "count", "worst_ms", "endpoint"],
                [[ms(e.total), e.n, ms(e.worst),
                  (e.endpoint or "?")[:78]] for e in endpoints],
            )

        unfinished = self.scalar("""
            SELECT COUNT(*) AS v FROM slice s
            WHERE s.name IN ('AsyncGetToString', 'AsyncPostFromString')
              AND NOT EXISTS (SELECT 1 FROM flow f WHERE f.slice_out = s.id)
        """, "v")
        if unfinished:
            print(f"\n  ({unfinished} of {started} requests had not completed "
                  "when the capture ended;\n   they are counted but "
                  "contribute no time.)")

    def observers(self) -> None:
        """Field observer cost, counting each cascade once.

        Observers run on the render thread and block it, so a slow one
        delays every other thread's field access - the usual reason the
        rendezvous section reports high execution time.

        They also nest: an observer whose body writes an observed field runs
        the next observer inside its own slice. Summing every slice therefore
        counts the same milliseconds once per level, which can total more
        observer time than the capture is long. Only the outermost observer of
        each cascade is counted here - by `debug.depth` where the capture has
        it, otherwise by walking the slice tree, which is slower but always
        available.
        """
        self.heading("Field observers")
        print("  Observers run on the render thread and block it, delaying "
              "every other\n  thread's field access.")

        # Both filters mean "outermost observer of a cascade". The depth
        # comparison is NULL for every row on a capture without the argument,
        # so it must not be used as the fallback - it would silently match
        # nothing and report no observers at all.
        if self.has_depth:
            outermost = "EXTRACT_ARG(arg_set_id, 'debug.depth') = 0"
        else:
            outermost = ("NOT EXISTS (SELECT 1 FROM ancestor_slice(slice.id) a"
                         " WHERE a.name = 'observer.callback')")

        naive = self.scalar("""
            SELECT SUM(dur) AS v FROM slice
            WHERE name = 'observer.callback' AND dur >= 0
        """, "v")
        rows = self.q(f"""
            SELECT EXTRACT_ARG(arg_set_id, 'debug.fieldName') AS field,
                   EXTRACT_ARG(arg_set_id, 'debug.function') AS function,
                   COUNT(*) AS n, SUM(dur) AS total, MAX(dur) AS worst,
                   id AS worst_id
            FROM slice
            WHERE name = 'observer.callback' AND dur >= 0 AND {outermost}
            GROUP BY 1, 2 ORDER BY total DESC LIMIT {self.top}
        """)
        deduped = self.scalar(f"""
            SELECT SUM(dur) AS v FROM slice
            WHERE name = 'observer.callback' AND dur >= 0 AND {outermost}
        """, "v")
        how = "debug.depth" if self.has_depth else "slice tree"
        print(f"  Outermost observers only (via {how}): {ms(deduped)} ms of "
              f"observer time.\n  Nested calls add up to {ms(naive)} ms, but "
              "that counts cascades repeatedly.\n")
        self.table(
            ["total_ms", "count", "worst_ms", "worst_id", "field", "function"],
            [[ms(r.total), r.n, ms(r.worst), r.worst_id, r.field, r.function]
             for r in rows],
        )
        if self.has_depth:
            print("\n  A cascade's inner levels are not listed. To see one, "
                  "walk outwards from\n  a nested call with "
                  "`ancestor_slice(<id>)`: the fix usually belongs at the\n"
                  "  write that started the cascade, not where the time "
                  "appears.")


# Report sections, in the order they are printed. Each names a Report method.
SECTIONS = ("overview", "network", "rendezvous", "callfunc", "copies",
            "repeats", "observers")


def main() -> int:
    """Parse arguments and print the requested sections."""
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", help="Perfetto trace file")
    ap.add_argument("--top", type=int, default=15,
                    help="rows per section (default 15)")
    ap.add_argument("--section", action="append", choices=SECTIONS,
                    help="only this section; repeatable")
    args = ap.parse_args()

    tp = TraceProcessor(trace=args.trace)
    try:
        report = Report(tp, args.top)
        report.trace_info()
        for name in (args.section or SECTIONS):
            getattr(report, name)()
        print("\nworst_id / first_id is the slice the row points at - the "
              "slowest call in\nthat group, or the first read of that run. "
              "Look one up with:")
        print("\n  SELECT id, ts, dur, name, track_id FROM slice "
              "WHERE id = <worst_id>;\n")
        print("Its children are `WHERE parent_id = <worst_id>`, and running "
              "either query in\nthe Perfetto UI lets you click the row to "
              "select that slice on the timeline.")
        print("\nSee the channel-performance-analysis skill for what these "
              "numbers mean and how to dig further.")
    finally:
        tp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
