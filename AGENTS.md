# Analysing a Roku trace

If you have been asked to find out why a channel is slow, or to analyse a
Perfetto trace from a Roku device:

1. Read `.agents/skills/channel-performance-analysis/SKILL.md`.
2. Run the existing report **before** writing any analysis of your own:

   ```
   python channel_perf.py <trace file>
   ```

   It needs the `perfetto` package: `pip install perfetto` (or
   `uv venv && uv pip install -r pyproject.toml`).

3. Use the queries in that skill to investigate whatever the report flags.

`channel_perf.py` already handles several things that are easy to get wrong -
unfinished slices with `dur = -1`, reading event arguments without multiplying
rows, and the fact that a copy's field name lives on its parent slice. Extend
it or query alongside it, but do not reimplement it from scratch.
