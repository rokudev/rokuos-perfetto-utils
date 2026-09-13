# perfetto
Perfetto utility scripts

## Installation

Using uv:

```
uv venv
source .venv/bin/activate
uv pip install -r pyproject.toml
```

## Contents

- ws-client/perfetto-client - simple python script to capture Perfetto protobuf data from RokuOS
- find\_brs\_cycles - attempt to report on cycles in a captured heapgraph
- channel\_perf - report on channel performance bottlenecks in a trace
- .agents/skills/channel-performance-analysis/ - skill for an AI agent
  analysing a trace for performance problems: SKILL.md, the named queries in
  queries/, and query.py to run them
- AGENTS.md - entry point for coding agents working in this repository
- PERFETTO\_SQL\_QUERIES.md - useful queries to run directly in the Perfetto UI

## Tests

    python tests/test_queries.py

Builds synthetic traces with known answers - one from a build carrying the
cpu_us, depth and id arguments and one without - and checks the skill's
queries reproduce them. Real captures are recordings of somebody's channel and
are not committed, so the fixtures are generated: `tests/make_trace.py` writes
one if you want to look at it.

## Diagnosing a slow channel

Capture a trace from your device, then:

```
pip install perfetto          # if you don't have it already
python channel_perf.py trace.bin
```

Or point an AI agent at this repository and your trace file, and ask it to find
out why your channel is slow; it will follow the channel-performance-analysis
skill. This has been tested with Claude Haiku 4.5 and Sonnet 5 (much better
results).

If you install the package (`uv pip install -e .`), the report is also
available as the `channel-perf` command.

