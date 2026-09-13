-- Bursts of consecutive blocking writes on one thread - candidates for batching.
WITH ops AS (
  SELECT rz.id, rz.ts, rz.dur, op.name AS op, tt.utid, t.name AS thread,
         (deq.ts - enq.ts) AS latency_ns,
         IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.name'), '?') AS field
  FROM slice rz
  JOIN slice op  ON op.id = rz.parent_id
  JOIN slice enq ON enq.parent_id = rz.id AND enq.name = 'rendezvous-enqueue'
  JOIN flow  f   ON f.slice_out = enq.id
  JOIN slice deq ON deq.id = f.slice_in
  JOIN thread_track tt ON rz.track_id = tt.id
  JOIN thread t ON tt.utid = t.utid
  WHERE rz.name = 'Rendezvous' AND rz.dur >= 0
), marked AS (
  -- brk = 1 starts a new burst: a non-write breaks it, so does a gap
  SELECT *,
    CASE WHEN op != 'roSGNode.setField' THEN 1
         WHEN IFNULL(LAG(op) OVER w, '') != 'roSGNode.setField' THEN 1
         WHEN ts - (LAG(ts) OVER w + LAG(dur) OVER w) > 5000000 THEN 1
         ELSE 0 END AS brk
  FROM ops WINDOW w AS (PARTITION BY utid ORDER BY ts)
), burst AS (
  SELECT *, SUM(brk) OVER (PARTITION BY utid ORDER BY ts
                           ROWS UNBOUNDED PRECEDING) AS bid
  FROM marked
), ordered AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY utid, bid ORDER BY ts) AS rk
  FROM burst WHERE op = 'roSGNode.setField'
)
SELECT thread, COUNT(*) AS writes,
       ROUND(SUM(dur)/1e6, 2)              AS blocked_ms,
       ROUND(SUM(latency_ns)/1e6, 2)       AS latency_ms,
       ROUND((MAX(ts+dur)-MIN(ts))/1e6, 2) AS span_ms,
       MAX(CASE WHEN rk = 1 THEN id END)   AS first_id,
       GROUP_CONCAT(DISTINCT field)        AS fields
FROM ordered
GROUP BY utid, bid
HAVING COUNT(*) >= 3
ORDER BY blocked_ms DESC
LIMIT {limit};
