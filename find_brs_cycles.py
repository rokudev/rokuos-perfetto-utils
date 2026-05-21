#!/usr/bin/env python3
"""
Find and report BrightScript reference cycles in a Perfetto heap graph trace.

A BrightScript reference cycle is a set of objects that reference each other
in a loop, preventing the reference-counting GC from reclaiming them. Perfetto
marks the roots of such cycles with a synthetic '$unreachable' field in the
heap graph.

Usage:
    find-brs-cycles <trace.perfetto-trace> [options]

Options:
    --show-example-ids  For each distinct cycle pattern, print one example
                        set of object IDs that can be inspected in the
                        Perfetto UI.
    --hide-global       Suppress cycles that pass through $m.global. Because
                        $m.global is referenced by almost every object, it
                        frequently appears in cycles that are not true leaks
                        in the BrightScript domain.

Cycles with the same sequence of type names and field names are grouped
together and reported with a count. Results are sorted by descending count.

Installation:
    pip install .

Perfetto Python API: https://perfetto.dev/docs/analysis/trace-processor-python
"""

import argparse
from collections import Counter
from perfetto.trace_processor import TraceProcessor


def get_unreachable_ids(tp):
    result = tp.query("""
        SELECT owned_id
        FROM heap_graph_reference
        WHERE field_name = '$unreachable'
    """)
    return {row.owned_id for row in result}


def get_references(tp):
    result = tp.query("SELECT owner_id, owned_id, field_name FROM heap_graph_reference")
    refs = {}
    for row in result:
        if row.owned_id is not None:
            refs.setdefault(row.owner_id, []).append((row.owned_id, row.field_name))
    return refs


def get_type_names(tp):
    result = tp.query("""
        SELECT obj.id, cls.name
        FROM heap_graph_object AS obj
        JOIN heap_graph_class AS cls ON cls.id = obj.type_id
    """)
    return {row.id: row.name for row in result}


def fanout(refs, node_id, visited, on_stack, path, cycles):
    on_stack.add(node_id)
    for owned_id, field_name in refs.get(node_id, []):
        new_path = path + [(node_id, field_name)]
        if owned_id in on_stack:
            # Back edge: extract the cycle portion of the current path.
            cycle_start = next(i for i, (nid, _) in enumerate(new_path) if nid == owned_id)
            cycles.append(new_path[cycle_start:])
        elif owned_id not in visited:
            visited.add(owned_id)
            fanout(refs, owned_id, visited, on_stack, new_path, cycles)
    on_stack.discard(node_id)


def normalize_cycle(cycle):
    # Rotate to lexicographically smallest form so A->B->A and B->A->B compare equal.
    n = len(cycle)
    return min(tuple(cycle[i:] + cycle[:i]) for i in range(n))


def main():
    parser = argparse.ArgumentParser(description="Find BrightScript cycles in a Perfetto heap graph trace.")
    parser.add_argument("trace", help="Path to the .perfetto-trace file")
    parser.add_argument("--show-example-ids", action="store_true",
                        help="For each distinct cycle pattern, print one example set of object IDs")
    parser.add_argument("--hide-global", action="store_true",
                        help="Hide cycles that pass through $m.global (a common non-leaking pattern)")
    args = parser.parse_args()

    tp = TraceProcessor(trace=args.trace)

    unreachable = get_unreachable_ids(tp)
    refs = get_references(tp)
    type_names = get_type_names(tp)

    visited = set()
    raw_cycles = []
    for uid in unreachable:
        if uid not in visited:
            visited.add(uid)
            fanout(refs, uid, visited, {uid}, [], raw_cycles)

    counter = Counter()
    examples = {}
    for cycle in raw_cycles:
        typed = [(type_names.get(nid, f'<unknown #{nid}>'), field) for nid, field in cycle]
        if args.hide_global and any(type_name == '$m.global' for type_name, _ in typed):
            continue
        canon = normalize_cycle(typed)
        counter[canon] += 1
        if canon not in examples:
            examples[canon] = cycle

    for canon, count in sorted(counter.items(), key=lambda x: -x[1]):
        print(f"Cycle (x{count}):")
        for type_name, field in canon:
            print(f"  {type_name} --[{field}]-->")
        print(f"  {canon[0][0]}")
        if args.show_example_ids:
            print("  Example IDs:")
            for nid, field in examples[canon]:
                print(f"    {nid} --[{field}]-->")
            print(f"    {examples[canon][0][0]}")
        print()


if __name__ == '__main__':
    main()
