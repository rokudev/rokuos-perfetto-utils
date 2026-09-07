---
name: channel-performance-analysis
description: Find performance bottlenecks in a Roku channel from a Perfetto trace. Use when analysing a .bin/.trace capture from a Roku device to explain why a channel is slow.
---

# Analysing channel performance from a Perfetto trace

This skill finds *why* a channel is slow from a Perfetto capture, using the
`perfetto` Python package to run SQL against the trace.

Work through the sections in order. Section 1 tells you which of the later
sections is worth your time; skipping it usually means analysing the wrong
thing.

## Workflow

Copy this into your response and tick items off as you go:

    - [ ] 1. Run channel_perf.py; read the whole report before querying anything
    - [ ] 2. Run the `args` query; note which of cpu_us, depth and id this trace has
    - [ ] 3. Work the sections the report flags, largest cost first
    - [ ] 4. Verify every slice id and number you intend to quote
    - [ ] 5. Write the report, then say what the capture could not tell you

Step 4 is not optional. Pass the ids you are about to quote back to the trace:

    .venv/bin/python $Q <trace> verify --set ids=22079,22087,27133

An id missing from the output does not exist; a duration that disagrees with
what you were about to write means you have the wrong slice. Both happen when
reading across several query results, and both are obvious in the report and
impossible for the reader to check.

## Start here: run the report

`channel_perf.py` analyzes the trace. **Run it before writing any analysis of
your own**, then use the queries below to investigate what it flags.

    python channel_perf.py trace.bin

It needs the `perfetto` package (`pip install perfetto`); installed
(`uv pip install -e .`) it is also `channel-perf trace.bin`. `--top N` for more
rows, `--section NAME` (repeatable) for one of `overview`, `network`,
`rendezvous`, `callfunc`, `copies`, `repeats`, `observers`.

It already handles what is easy to get wrong - unfinished slices, argument
extraction, a copy's field name living on its parent slice. Extend it rather
than reimplementing it. It does not cover section 3b; run that by hand.

## Running queries

The analysis is a set of named queries in `queries/`, run through the bundled
`query.py`. Set this once:

    Q=.agents/skills/channel-performance-analysis/query.py
    .venv/bin/python $Q --list
    .venv/bin/python $Q <trace> rendezvous --limit 30

`--limit` defaults to 20; queries needing a field say so (`--set
field=applanguages`). **Run them rather than retyping the SQL** - that is what
keeps the query text out of context. To *adapt* one, read `queries/<name>.sql`
and work from it; that is one file, not all of them. For anything the named
queries do not cover, use the `perfetto` package directly.

Durations are **nanoseconds**. The queries convert, and each column carries
its unit: `_ms` for anything that blocks a thread, `_us` for individual
operations like copies and field reads. Keep those units in the report - do
not restate a large `_ms` in microseconds, or round a `_us` up to `0.01 ms`.

### Always report the slice id

A finding without a slice id cannot be checked - the reader has no way back to
the thing you are describing. Every query returns the id of the row it points
at; quote it for every finding, not just the first.

To look one up, in the Perfetto UI or here:

    .venv/bin/python $Q <trace> slice --set id=434050

### Three rules that prevent wrong answers

1. **Always filter `dur >= 0`.** A slice still open at capture end has
   `dur = -1`, which corrupts every `SUM` and `MAX`. If such a slice is itself
   the finding, measure it as `trace_end() - ts` and label it a lower bound.
2. **Read event arguments with `EXTRACT_ARG`**, not by joining `args`:
   `EXTRACT_ARG(arg_set_id, 'debug.name')`. Joining `args` multiplies rows.
3. **Report totals as well as worst cases.** One 600 ms stall and 600 one-ms
   stalls need completely different fixes.

### Check which arguments the trace has

Three arguments were only added recently. A capture without them is not broken
but it cannot answer what they answer.

Ask the trace which slices carry them. **Never work from a remembered list**:
the instrumented set differs between builds and keeps changing.

    .venv/bin/python $Q <trace> args

| argument | what it tells you | if absent |
|---|---|---|
| `debug.cpu_us` | whether the slice was executing or blocked | you cannot tell work from a stall; say so rather than assuming either |
| `debug.depth` | an observer's cascade nesting level | nested observers double-count; dedupe via the slice tree (section 5) |
| `debug.id` | which node an operation touched | one hot node is indistinguishable from many |

Read the result per slice, not as a yes/no for the trace. `debug.id` is the
trap: it has always been emitted on `roSGNodeEvent` slices, so its presence
proves nothing about field operations - what matters is whether the slices you
are about to group carry it. A node also only has an id if its markup sets
one, so roughly a third of field operations lack one even on a build that
emits it.

An empty result means an older build; say so in the report. If a build that
should carry an argument is missing it on a few finished slices, check
`SELECT name, value FROM stats WHERE name LIKE '%loss%' AND value > 0` before
blaming the build - lost packets cost end-event arguments.

## 1. Orient: where does the time actually go?

    .venv/bin/python $Q <trace> overview

Slices nest, so these totals overlap — `ExecBrightScript` contains almost
everything else. Use it to decide where to look, not to apportion blame.

### Wall time vs CPU time

`dur` is wall-clock; `debug.cpu_us` is thread CPU time over the same interval,
inclusive of nested slices, so the two compare directly.

    .venv/bin/python $Q <trace> cpu-vs-wall

- **`cpu_ms` close to `ms`** — executing. A long script slice with no traced
  children is a loop or an expensive builtin in the channel's own code, and
  the callstack names the function and line. Report the cost and the location;
  there is no platform fix to propose.
- **`cpu_ms` far below `ms`** — not running. It was blocked or descheduled, so
  the work shown is not the cost. On a slice that can block - `Print`, a copy
  - that is a finding in itself. For a slice carrying no `cpu_us`, read the
  enclosing slice that has one.

A value of `0` means unmeasurable, not free.

What the names mean:

| slice | meaning |
|---|---|
| `roSGNode.getField` / `setField` | a field read/write, possibly cross-thread |
| `Rendezvous` | a thread is **blocked** waiting for the render thread |
| `rendezvous-enqueue` / `-dequeue` | request queued / picked up (instant events) |
| `bscCopyToDomainEx` | data copied between BrightScript domains |
| `observer.callback` | a field observer running |
| `consumeAllTasks` | the render thread servicing queued requests |
| `roRenderThreadQueue.postMessage` | work posted to the render thread **without** blocking |
| `roRenderThreadQueue.deliver` | the render thread running posted work |
| `AsyncGetToString` / `AsyncPostFromString` | an HTTP request **issued** (instant, `dur = 0`) |
| `postEvent` | an event delivered, including a request's response |

If `Rendezvous` is high, go to section 3. If `bscCopyToDomainEx` is high, go to
section 2. If `observer.callback` is high, go to section 5. These are all
on-device costs - if the channel is slow but none of them are large, check
network time (section 6).

### Identifying which field an operation touched

`roSGNode.getField`, `setField` and `callFunc` carry:

- `debug.component` — the node type, e.g. `ContentNode`
- `debug.name` — the field (or function) name
- `debug.callstack` — the BrightScript callstack
- `debug.id` — the node's markup `id`, when it has one. It distinguishes 35
  writes to one node from one write to each of 35 nodes, which changes the fix
  completely. Group by it alongside `debug.component`, and treat a NULL as
  unknown identity rather than as a distinct node.

  It is emitted for cross-thread accesses too, so the expensive rendezvous
  rows carry it. A NULL means the node simply has no markup `id` - common for
  `ContentNode`s built at runtime - not that the access was cross-thread.

`observer.callback` carries `debug.fieldName`, `debug.function` and
`debug.depth` (section 5) instead.

**`bscCopyToDomainEx` carries no arguments at all.** To find out what a copy
was copying, join to its parent slice and read the parent's arguments. This
catches people out.

## 2. Cross-domain copies

Every value crossing a BrightScript domain boundary is deep-copied, even when
not rendezvousing.

**`bscCopyToDomainEx` does not cover every copy** - only the fast path, which
currently means `roAssociativeArray`. Other types, and `callFunc` arguments
and return values, are not traced individually. A field showing no copies here
may still be copying; rendezvous execution time (section 3) is the more
complete signal.

    .venv/bin/python $Q <trace> copies

Two distinct problems show up here, and they have different fixes:

- **Many small copies** (`copies` in the thousands, small `worst_us`) — a field
  read in a loop. A possible fix is to read it once into a local variable, but
  only code inspection can tell for sure.
- **One huge copy** (`copies` = 1, large `worst_us`) — a single very large
  structure. A possible fix is `moveIntoField`/`moveFromField` or
  `setRef`/`getRef` (section 2a), or splitting the structure so only the
  needed part crosses.

To confirm a suspicion about one field, look at the individual copies:

    .venv/bin/python $Q <trace> copies-for-field --set field=<field>

## 2a. Reducing copy cost: references and moves

Two APIs avoid a copy, each with a constraint deciding where it applies.
Classify the copy first - the wrong constraint makes the suggestion useless.

**`getRef` / `setRef`** work with a reference instead of a copy, and are
usable **only on the render thread**. So they replace accesses in code already
running there: observers, component code, `callFunc` bodies.

**`moveIntoField` / `moveFromField`** move the data between a BrightScript
domain and the standalone domain inside an assocarray field, rather than
copying it, and work across threads - so they cover the copies `getRef`
cannot. They are **destructive**: after the move the source no longer holds
the value, so the caller must be finished with it. Handing a large associative
array to a node once and never reading it back is the case that fits.
`moveIntoField` is O(N) in the number of objects moved; `moveFromField` is
always O(1).

### Finding candidates

A copy's enclosing access was cross-thread if that operation also contains a
`Rendezvous`. Note the copy is a *sibling* of the `Rendezvous`, not a child, so
test the parent operation rather than looking at ancestors of the copy:

    .venv/bin/python $Q <trace> copy-candidates

Read the result as:

- `cross_thread = 0` **and** on `RenderThr:Main` or `AuxRenderThread` — a
  `getRef`/`setRef` candidate.
- `cross_thread = 1` — `getRef`/`setRef` cannot be used. Consider a move if the
  caller can give up the value, otherwise reduce how often the access happens
  or make the value smaller.
- `cross_thread = 0` on a task thread — still not a `getRef` candidate, since
  that API is render-thread only. Treat as above.

Check what the channel already does before suggesting anything:

    SELECT name, COUNT(*) AS n,
           ROUND(SUM(dur) / 1000.0, 1) AS total_us
    FROM slice
    WHERE name IN ('roSGNode.getRef', 'roSGNode.setRef',
                   'roSGNode.moveIntoField', 'roSGNode.moveFromField')
      AND dur >= 0
    GROUP BY name;

Both techniques are **candidates, not conclusions**. Whether a move is safe
depends on whether the value is read again afterwards, and whether a reference
is usable depends on where that code path can run - neither is visible in the
trace. Present them as "this copy costs X ms and is a candidate for Y",
and let the developer confirm.

## 3. Rendezvous: latency vs execution

When a task thread reads or writes a field owned by the render thread, it
blocks. Sorting `roSGNode.setField` by duration cannot tell you *why* it was
slow. A rendezvous has two separable costs:

      task thread:   ... roSGNode.setField ── Rendezvous [BLOCKED ......... ] ...
                                               │
                                        rendezvous-enqueue
                                               │  (flow)         latency
                                               ▼
      render thread: ...... consumeAllTasks ── rendezvous-dequeue ─── copy + observers ...
                                                                      execution

- **latency** — time queued before the render thread got to it. High latency
  means the render thread is busy: the fix is elsewhere in the channel.
- **execution** — time doing the work, dominated by the copy and by any
  observers that fire. The fix is at this field.

`Rendezvous.dur` is the caller's total block. The flow from
`rendezvous-enqueue` to `rendezvous-dequeue` gives the latency. Execution is
the remainder:

    .venv/bin/python $Q <trace> rendezvous

Reading the result — compare the two `MAX` columns per row:

    sum_total_ms    n   max_latency_ms   max_exec_ms   field                thread
         2454.90   20             7.94        640.14   NodeType.itemsField  TN:someTask
          325.00  294           131.44          7.53   TaskType.quitFlag    TN:otherTask

Row one is **execution-bound** - no queueing, 640 ms of work per call. Go to
section 5; an observer on that field is slow. Row two is **latency-bound** -
trivial work, but 294 calls queued behind a busy render thread. Reduce the
call count (section 4) rather than optimising the field.

To split execution further - which copies and observers ran inside one service
window - fetch the rendezvous rows and render-thread slices separately and
match them in Python. SQL for aggregation, Python for correlation.

## 3a. callFunc

`callFunc` on a node owned by another thread costs three things:

1. copying the arguments to the render thread
2. running the function there
3. copying the return value back

Neither copy is traced individually (see the note in section 2), so they appear
only as a residual. What *can* be measured is the total, the queueing latency,
and the function body — which runs as an `ExecBrightScript` slice on the
servicing thread. Attribute it via the dequeue's parent `consumeAllTasks`
rather than by time alone, so that other work the render thread interleaves is
not counted:

    .venv/bin/python $Q <trace> callfunc

Then `total - latency - body` is the copy overhead plus dispatch. Which of the
three dominates tells you what to do:

- **latency dominates** — the render thread is busy. The call itself is fine;
  reduce how often it happens, or fix whatever is occupying the render thread.
- **body dominates** — the function is slow. Optimise it, or call it less
  often.
- **the residual dominates** — argument or return-value copying. Pass node
  references rather than large associative arrays or arrays, and return
  something small.

A `callFunc` invoked from the render thread has no rendezvous - it appears as
`roSGNode.callFunc` with an `ExecBrightScript` child and no `Rendezvous`.
**It still copies.** `callFunc` always copies its arguments and its return
value, wherever it is invoked from, and those copies are not traced
individually - so a same-thread `callFunc` is cheaper than a cross-thread one,
never free, and the copy cost is not visible in the trace at all.

## 3b. Batching writes with `roRenderThreadQueue`

A task thread writing several fields in a row blocks on a rendezvous for each.
`roRenderThreadQueue.postMessage` hands the write to the render thread without
blocking, to run later inside a `roRenderThreadQueue.deliver`.

**It saves the waiting, not the work.** The render thread still performs the
writes, and `postMessage` *moves* its payload rather than copying - but moving
is O(N) in objects moved, and anything referenced from outside the payload is
copied instead. The cost depends on the shape of the data, not just its size.

**Propose it for `setField`**, and for a `callFunc` whose return value is
unused - though the trace cannot show whether it is, so that needs the code.
A `getField` always needs its result and must rendezvous. Posting is
fire-and-forget either way, so it is unsafe if the next line assumes the write
has landed - again not visible here. Offer it as a candidate for the developer
to judge, never quote a per-message cost from another trace, and never predict
the saving.

Bursts of consecutive blocking writes on one thread, uninterrupted by anything
needing a value back and within 5 ms of each other - long enough to hold a
burst together, short enough that unrelated writes do not merge into one:

    .venv/bin/python $Q <trace> write-bursts

Reading the result:

- **`blocked_ms`** is what the thread waited, the upper bound on what batching
  recovers - not free savings, since the posts cost something too.
- **`latency_ms` close to `blocked_ms`** - almost entirely queueing. Strongest
  candidate.
- **`latency_ms` far below `blocked_ms`** - the writes are expensive to
  execute. Batching stops the waiting but leaves the render-thread cost; fix
  that first (sections 2a and 5).
- **`span_ms` much larger than `blocked_ms`** - not really one burst. Weaker.
- `first_id` and `fields` locate the code.

What the channel already does, and what its posts cost:

    .venv/bin/python $Q <trace> rtq-usage

`postMessage` rows are the task-thread cost of posting; `deliver` rows are the
render-thread cost of running the work. A `postMessage` has no `Rendezvous`
child - if one appears to block, something else is going on.

### `Node.queueFields()` - the other way to batch

`queueFields(true)` makes a node queue its own field updates instead of
applying them one at a time; they land when `queueFields(false)` is called.

It is **not** an asynchronous hand-off. The node must be owned by the render
thread, so a task thread still rendezvouses to use it - what it removes is the
per-field work, not the crossing. That makes it the alternative worth
mentioning when a burst is dominated by execution rather than queueing, which
is exactly the case `roRenderThreadQueue` does not help.

## 4. Repeated access to the same field

Re-reading an unchanged field is pure overhead, and cross-thread it is a
rendezvous every time. This finds runs of consecutive reads of one field on one
thread:

    .venv/bin/python $Q <trace> repeated-reads

`rn - rn_field` is constant across a run of consecutive reads of the same
field, which is what groups each run. Note this means "no *other field read*
in between" — other work may have happened. That is usually the right
question, since it finds the loop regardless of what else is in it.

For the stricter "nothing at all happened in between", pair each read with the
one before it on the same thread and require the gap to be empty. This counts
adjacent pairs rather than whole runs - a run of N back-to-back reads shows as
N-1 pairs - and the `NOT EXISTS` makes it much slower, so use it to confirm a
specific finding, not to scan:

    .venv/bin/python $Q <trace> repeated-reads-strict

A long run of reads of one field *may* be a polling loop, but the trace shows
only the reads, not the reason for them - do not assert why the code does what
it does. Observing the field instead, or caching it in a local, are good
suggestions either way; offer them as such.

Use `debug.callstack` on those slices to point the developer at the code:

    .venv/bin/python $Q <trace> callstack-for-field --set field=<field>

## 5. Slow field observers

An observer runs on the render thread and blocks it, delaying every other
thread's rendezvous. This is the usual cause of an execution-bound result in
section 3.

**There are two render threads and they alternate**: `AuxRenderThread` takes
over while the real render thread is inside `swapBuffers`. Both run observers;
only the real one renders or waits on `swapBuffers`. They never run at the
same time, so neither blocks the other.

The consequence is that **which of the two an observer runs on does not change
its impact** - it is one budget, not two. Name the thread so the reader can
find the code, never to argue a cascade matters more or less.

**Observers nest, so a naive sum counts the same milliseconds repeatedly.** An
observer whose body writes an observed field runs the next one inside its own
slice: a four-deep cascade reports one 1345 ms event as four rows of ~1340 ms,
which can total more observer time than the capture is long. `debug.depth`
gives the nesting level, 0 being outermost:

    .venv/bin/python $Q <trace> observers

**Report the outermost total. Never quote the naive sum**, even alongside it -
it is the same milliseconds counted once per level, so it cannot be compared
against anything, including `ExecBrightScript`.

Drop the `depth` filter to see the cascade itself: a row with a large
`total_ms` at depth > 0 is work triggered by another observer, so the fix
belongs at the write that started the cascade, not at the field where the time
appears. Walk `ancestor_slice(<worst_id>)` to see the chain.

On a trace without `debug.depth` this query silently returns nothing — the
`= 0` comparison is NULL for every row, so an empty result means the argument
is missing, not that the channel has no observers. Use the slice-tree variant
instead, which is slower but always available, and say in the report which one
the totals came from:

    .venv/bin/python $Q <trace> observers-no-depth

`channel_perf.py` does this for you, picking whichever applies and saying
which it used.

A single observer taking hundreds of milliseconds is stalling the whole
channel. The work usually cannot be relocated - the observer runs where the
field lives - so the fix is to do less of it: run the observer less often
(coalesce or debounce the writes that trigger it), or cut what it does per
call. The common hidden cost is an observer setting more fields and triggering
further observers - check whether its slice has `roSGNode.setField` children:

    .venv/bin/python $Q <trace> observer-children

### Do not suggest moving observer work off the render thread

An observer runs on the render thread because that is where the field lives,
and there is no mechanism to run it elsewhere. "Move this to a task thread",
"run the observer asynchronously" and similar are **not available fixes**,
however slow the observer is. Reaching a task node costs a field write
observed on the render thread, and the result returns the same way - the
observer still runs there and you have added rendezvous traffic. Propose a
task node only when the work is long-running and the channel can proceed
without its result.

What is available, in the order worth trying:

1. **Fire it less often.** Coalesce or debounce the writes that trigger it.
   Section 3's `n` column tells you whether this is the lever.
2. **Cut the cascade.** If the observer sets fields that trigger further
   observers, that is often most of the cost - the query above shows it.
3. **Cut the work per call.** Fewer field accesses in the body, `getRef`
   instead of a copy where section 2a allows it, less work done per item.
4. **Accept it.** Some observers are doing necessary work on a large tree.
   Say so, with the number, rather than inventing a fix.

## 5a. Frame health

The one section that measures what the viewer sees, and it needs no extra
instrumentation - `render` and `swapBuffers` are in every capture.

**The signal is the interval from one `swapBuffers` to the next.** Keeping up
at 60 Hz means 16.7 ms between swaps; the target is always 60 Hz, so 33.4 ms
is two budgets missed rather than a device running at 30.

    .venv/bin/python $Q <trace> frame-cadence

**An interval is only a miss if the render thread was working through it.**
Idle gaps are the channel having nothing to draw, and they can be seconds
long - in one capture 264 intervals were over budget but only 75 had the
thread busy. The query counts those separately; report `missed`, not
`over_16_7ms`. A handful during launch is ordinary, a steady fraction during
scrolling is not.

A frame can miss for three different reasons, and they have different fixes:

    swapBuffers ──┤ before render ├─┤ render ├─┤ swapBuffers ├── next swap
                    observer work     draw calls   GPU + vsync

    .venv/bin/python $Q <trace> frame-breakdown

- **`before_render_ms` dominates** - the thread did not reach the render phase
  in time, usually observer work. Section 5, and the cascade is on one of the
  two render threads.
- **`render_ms` dominates** - the render phase itself. Do not call this scene
  complexity without looking: **observers can run inside `render`**, so a long
  one may be script rather than traversal. On one capture 2351 ms of 5001 ms
  of render time was `observer.callback`. Check before attributing it:

        .venv/bin/python $Q <trace> render-contents
- **`swap_ms` dominates** - waiting for the GPU, which should return by the
  next vsync, so ~16 ms is the ceiling. Over that, the scene is too expensive
  to draw and overdraw is a common reason.

  **Read the list, not just the count.** Look at the spread: a cluster of
  similar values is one phenomenon, and a single odd duration sitting apart
  from the rest is another worth calling out on its own, even when it is not
  the worst. An aggregate hides exactly that.

  **Magnitude matters as much as frequency.** A swap somewhat over budget is
  a scene that is too expensive. A swap several times over - 100 ms and up
  against a 16 ms ceiling - is not ordinary drawing cost, and attributing it
  to overdraw asserts more than the trace supports. Report the number, say it
  is far outside what the phase should ever take, and leave the cause open.

    .venv/bin/python $Q <trace> swapbuffers

To see what the render thread ran inside the frames that missed:

    .venv/bin/python $Q <trace> frame-jank-causes

It groups by thread as well as slice name, so both render threads appear.
Do not treat work on the frame-producing thread as the only kind that counts.

## 5b. Building nodes

`component.init` and `CreateObject` are often among the largest costs in a
launch and are easy to miss, since neither blocks another thread.

    .venv/bin/python $Q <trace> node-creation

The levers are structural: deep `extends` hierarchies cost more (fields are
looked up per level), as do many fields, default values in the XML, and slow
`init()`. Group by component - one type built 94 times is a different problem
from one built once and slow.

## 5c. Observer leaks

`observeField` and `observeFieldScopedEx` **add** an observer; they do not
replace one. Registering the same field twice means it fires twice, forever.
Components that observe in setup and are created repeatedly leak them.

    .venv/bin/python $Q <trace> observer-growth

**A rising count is not by itself a leak.** A launch capture is nearly all
construction, so the counter climbs because the channel is building its UI -
`observe_calls` will dwarf `unobserve_calls` for the same reason. Saying
otherwise produces a false finding on almost every trace.

The leak needs teardown in the capture to be visible: a count that does not
fall when a screen is dismissed, or one component type registering observers
across repeated create and destroy cycles. Without that, report the numbers
and say the capture cannot settle it. Where it is real it inflates every
observer cost in section 5 - the same work, done twice or ten times.

The fix depends on which side is short-lived: `observeField` stores the
observer on the observed node, so it is cleaned up when that node dies;
`observeFieldScopedEx` stores it on the observer. Match the call to whichever
is destroyed and recreated. `observeFieldScoped` is broken - never propose it.

## 5d. Launch compilation

    .venv/bin/python $Q <trace> launch-compile

Channel code is compiled in the Channel Store, so this should be small. **DCLs
loaded from an external URL are not**, and compile on the device at every
launch - seconds, for a large one. If compilation is significant, that is the
thing to ask about; there is no on-device fix.

## 6. Network requests

A request is issued with `AsyncGetToString` or `AsyncPostFromString`. Both are
**instant events** - `dur = 0` - marking only the moment the transfer started,
so their duration tells you nothing. The response arrives later as a
`postEvent`, and a **flow connects the two**. The gap between them is the round
trip.

The start carries `debug.url`, `debug.identity` (the transfer id) and
`debug.callstack`.

    .venv/bin/python $Q <trace> network

Group by endpoint instead to see which service is slow. Strip the query string
first, or every request looks unique:

    .venv/bin/python $Q <trace> network-endpoints

### Do not present the total as time the channel spent waiting

The sum is request time, not waiting time, for three reasons:

1. **Requests overlap**, so summing double-counts - in one capture the sum was
   117 s against 68 s of wall time with anything outstanding.
2. **A request in flight blocks nothing.** These are asynchronous; the trace
   shows a request was outstanding, never that the channel was waiting on it.
3. **It stops when the response event is posted**, not when the channel has
   used it. Parsing is a separate `ParseJSON` slice.

`unfinished` counts requests still outstanding at capture end. They have no
elapsed time and are excluded from every total - say how many there were
rather than letting them vanish.

If you need the wall-clock figure - how much of the capture had at least one
request outstanding - fetch the start/end pairs and merge the intervals in
Python. Section 5a's frame numbers are the better jank signal either way.

## Reporting findings

Give each finding a number, a location, a slice id and a fix. "`quitFlag` read
294 times on `TN:otherTask`, 325 ms, worst call slice 39371 - observe it
instead" is actionable; "there is a lot of rendezvous traffic" is not. Quote
the slice id for every finding, not just the first.

State totals in milliseconds and say what share of the capture they are. Be
explicit when a cost is unavoidable - not every expensive field access can be
removed.

Only propose fixes described here. The constraints on `getRef` (2a), on
`callFunc` copying (3a), on posting (3b) and on observers (5) are properties
of the platform, not preferences. Where a real cost has no available fix, say
so - that is a useful finding.

Do not:

- **Attach a fix to a trivial cost.** Under ~1% of the capture is context,
  not a finding: give the number and say that dimension looks healthy. A
  reader who sees a fix proposed for 2 ms of a 33 s trace trusts the rest
  less.
- **Predict savings.** Say what the cost is and what the lever is.
- **Blame a race condition.** Field access is serialised through the render
  thread; races do not happen here.
- **Invert the bound when `cpu_us` is missing.** Wall-clock is an upper bound
  on execution, never a lower one.
- **Assert why the code does what it does.** The trace shows what happened,
  not intent.

Finally, say what the capture could not tell you: name each absent argument
and the question it would have answered, so the reader can re-capture rather
than act on a guess. "Ran for 1.2 s, and the trace cannot say whether it was
executing or blocked" is a finding; "spent 1.2 s executing" is an invention.
