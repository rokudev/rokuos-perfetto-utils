#!/usr/bin/env python3
"""Generate a synthetic Perfetto trace with known answers, for testing.

Real captures cannot be committed - they are recordings of somebody's channel.
This builds a trace whose numbers are chosen rather than measured, so a test
can assert exact values, and can include cases a real capture will not produce
on demand: a build without the later arguments, an unfinished slice, a node
with no markup id.

    python tests/make_trace.py out.pb            # newer build, all arguments
    python tests/make_trace.py out.pb --old      # older build, none of them

The expected values are in EXPECTED below, and tests/test_queries.py asserts
the skill's queries reproduce them.

JSON traces will not do for this: trace_processor files their arguments under
`args.*` rather than `debug.*`, and does not populate the flow table from
them, so neither the argument handling nor the rendezvous split could be
tested.
"""

from __future__ import annotations

import argparse
import sys

from perfetto.protos.perfetto.trace import perfetto_trace_pb2 as pb

MS = 1_000_000  # nanoseconds
SEQ = 1

# What the generated trace contains, and what the queries should report.
EXPECTED = {
    # A 300 ms cascade four levels deep, plus the 30 ms observer that makes
    # one frame miss below - both are outermost, so 330 ms between them.
    "observer_outermost_ms": 330.0,
    "observer_naive_ms": 1223.0,     # what summing every level would give
    "observer_cascade_depth": 4,
    "observers_at_depth_0": 2,
    "field_writes": 12,              # writes of one field from a task thread
    "field_blocked_ms": 240.0,
    "repeated_reads_run": 20,        # consecutive reads of one field
    # Frames run at a 60 Hz cadence: 2 ms of observer work, 4 ms of render,
    # 10 ms of swap, so 16 ms from one swap to the next. Three frames are
    # made to miss, one for each of the three reasons a frame can miss.
    "frames": 11,
    "frame_intervals": 10,
    "intervals_over_16_7ms": 4,      # three missed frames plus one idle gap
    "intervals_missed": 3,           # the idle gap is not a missed frame
    "swaps_over_16ms": 1,            # the slow-swap frame; first swap excluded
}


class Builder:
    """Emits TrackEvent slices. Timestamps must not go backwards on a track."""

    def __init__(self) -> None:
        self.trace = pb.Trace()
        self.uuid = {}
        self.clock = {}
        first = self._packet()
        first.first_packet_on_sequence = True
        first.sequence_flags = 1  # SEQ_INCREMENTAL_STATE_CLEARED

    def _packet(self):
        p = self.trace.packet.add()
        p.trusted_packet_sequence_id = SEQ
        return p

    def thread(self, name: str, tid: int) -> None:
        p = self._packet()
        p.track_descriptor.uuid = 100 + tid
        p.track_descriptor.thread.pid = 1
        p.track_descriptor.thread.tid = tid
        p.track_descriptor.thread.thread_name = name
        self.uuid[name] = 100 + tid
        self.clock[name] = 0

    def begin(self, track, ts, name, args=None, flow=None, terminates=None):
        ts = max(ts, self.clock[track])
        self.clock[track] = ts
        p = self._packet()
        p.timestamp = ts
        e = p.track_event
        e.type = pb.TrackEvent.TYPE_SLICE_BEGIN
        e.name = name
        e.track_uuid = self.uuid[track]
        for key, value in (args or {}).items():
            a = e.debug_annotations.add()
            a.name = key
            if isinstance(value, int):
                a.int_value = value
            else:
                a.string_value = str(value)
        if flow is not None:
            e.flow_ids.append(flow)
        if terminates is not None:
            e.terminating_flow_ids.append(terminates)
        return ts

    def end(self, track, ts) -> int:
        ts = max(ts, self.clock[track])
        self.clock[track] = ts
        p = self._packet()
        p.timestamp = ts
        p.track_event.type = pb.TrackEvent.TYPE_SLICE_END
        p.track_event.track_uuid = self.uuid[track]
        return ts

    def slice(self, track, ts, dur, name, **kw) -> int:
        """A complete slice. Returns the end timestamp."""
        self.begin(track, ts, name, **kw)
        return self.end(track, ts + dur)

    def write(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.trace.SerializeToString())


def build(new_build: bool) -> Builder:
    """Compose the scenario. `new_build` controls the later arguments."""
    b = Builder()
    RENDER, AUX, TASK = "RenderThr:Main", "AuxRenderThread", "TN:testTask"
    b.thread(RENDER, 1)
    b.thread(AUX, 2)
    b.thread(TASK, 3)

    def depth(level):
        return {"depth": level} if new_build else {}

    def node(component, name, node_id=None):
        args = {"component": component, "name": name}
        if new_build and node_id:
            args["id"] = node_id
        return args

    # --- one 300 ms observer cascade, four levels deep on the render thread.
    # Summing every level gives 1193 ms; only the outermost 300 ms is real.
    t = 10 * MS
    b.begin(RENDER, t, "observer.callback",
            args={"fieldName": "outerField", "function": "onOuter",
                  **depth(0)})
    b.begin(RENDER, t + 1 * MS, "observer.callback",
            args={"fieldName": "middleField", "function": "onMiddle", **depth(1)})
    b.begin(RENDER, t + 2 * MS, "observer.callback",
            args={"fieldName": "innerField", "function": "onInner",
                  **depth(2)})
    b.begin(RENDER, t + 3 * MS, "observer.callback",
            args={"fieldName": "leafField", "function": "onLeaf", **depth(3)})
    b.end(RENDER, t + 299 * MS)
    b.end(RENDER, t + 300 * MS - 1)
    b.end(RENDER, t + 300 * MS - 1)
    b.end(RENDER, t + 300 * MS)

    # --- 12 cross-thread writes of one field, 20 ms blocked each.
    # Flow ids pair each enqueue with its dequeue, 5 ms of queueing.
    for i in range(EXPECTED["field_writes"]):
        start = (400 + i * 30) * MS
        flow = 1000 + i
        b.begin(TASK, start, "roSGNode.setField",
                args=node("TaskNode", "itemsField", "theTaskNode"))
        b.begin(TASK, start + 1 * MS, "Rendezvous")
        b.slice(TASK, start + 2 * MS, 1, "rendezvous-enqueue", flow=flow)
        b.slice(RENDER, start + 7 * MS, 1, "rendezvous-dequeue",
                terminates=flow)
        b.end(TASK, start + 21 * MS)   # Rendezvous: 20 ms
        b.end(TASK, start + 21 * MS)   # setField

    # --- a run of 20 consecutive reads of one field on the task thread
    for i in range(EXPECTED["repeated_reads_run"]):
        b.slice(TASK, (800 + i) * MS, 100_000, "roSGNode.getField",
                args=node("Node", "polledField"))

    # --- BrightScript execution: one slice mostly blocked, one mostly running
    b.slice(TASK, 900 * MS, 100 * MS, "ExecBrightScript",
            args={"callstack": "waitfn pkg:/blocked.brs:1",
                  **({"cpu_us": 2_000} if new_build else {})})
    b.slice(TASK, 1010 * MS, 100 * MS, "ExecBrightScript",
            args={"callstack": "busyfn pkg:/looping.brs:42",
                  **({"cpu_us": 98_000} if new_build else {})})

    # --- frames, back to back at a 60 Hz cadence.
    # Each is (observer work before render, render, swap); a frame keeping up
    # is 2 + 4 + 10 = 16 ms from one swap to the next. Three frames miss, one
    # for each reason: too long reaching render, a slow render, a slow swap.
    frames = [(2, 4, 10)] * 11
    frames[3] = (30, 4, 10)   # never reached render in time
    frames[6] = (2, 40, 10)   # scene too complex to traverse
    frames[9] = (2, 4, 40)    # too long waiting for the GPU
    # Frame 5 follows a 500 ms gap with nothing running: the channel had
    # nothing to draw. Over budget, but not a missed frame.
    idle_before = 5
    cursor = 1200 * MS
    for i, (before, render, swap) in enumerate(frames):
        if i == idle_before:
            cursor += 500 * MS
        if before > 2:
            b.slice(RENDER, cursor, before * MS, "observer.callback",
                    args={"fieldName": "frameField", "function": "onFrame",
                          **depth(0)})
        cursor += before * MS
        b.slice(RENDER, cursor, render * MS, "render")
        cursor += render * MS
        b.slice(RENDER, cursor, swap * MS, "swapBuffers")
        cursor += swap * MS

    # --- a slice left open at capture end, to exercise the dur = -1 rule
    b.begin(AUX, 2200 * MS, "ExecBrightScript",
            args={"callstack": "unfinished pkg:/never.brs:1"})
    return b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="path to write the trace to")
    ap.add_argument("--old", action="store_true",
                    help="omit cpu_us, depth and id, as an older build would")
    args = ap.parse_args()
    build(new_build=not args.old).write(args.out)
    print(f"wrote {args.out} ({'older' if args.old else 'newer'} build)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
