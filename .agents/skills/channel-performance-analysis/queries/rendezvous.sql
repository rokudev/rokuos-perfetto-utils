-- Cross-thread field access, split into queueing latency and execution.
WITH rv AS (
  SELECT
    ct.name AS calling_thread,
    st.name AS servicing_thread,
    rz.id   AS slice_id,
    IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.component'), '?') || '.' ||
    IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.name'), '?') AS field,
    op.name AS operation,
    rz.dur                     AS total_ns,
    (deq.ts - enq.ts)          AS latency_ns,
    rz.dur - (deq.ts - enq.ts) AS exec_ns
  FROM slice rz
  JOIN slice enq ON enq.parent_id = rz.id AND enq.name = 'rendezvous-enqueue'
  JOIN flow  f   ON f.slice_out = enq.id
  JOIN slice deq ON deq.id = f.slice_in
  LEFT JOIN slice op ON op.id = rz.parent_id
  JOIN thread_track ctt ON rz.track_id  = ctt.id JOIN thread ct ON ctt.utid = ct.utid
  JOIN thread_track stt ON deq.track_id = stt.id JOIN thread st ON stt.utid = st.utid
  WHERE rz.name = 'Rendezvous' AND rz.dur >= 0
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY calling_thread, field
                               ORDER BY total_ns DESC) AS rk
  FROM rv
)
SELECT calling_thread, field, COUNT(*) AS n,
       ROUND(SUM(total_ns)   / 1e6, 2) AS sum_total_ms,
       ROUND(MAX(latency_ns) / 1e6, 2) AS max_latency_ms,
       ROUND(MAX(exec_ns)    / 1e6, 2) AS max_exec_ms,
       MAX(CASE WHEN rk = 1 THEN slice_id END) AS worst_id
FROM ranked
GROUP BY 1, 2
ORDER BY sum_total_ms DESC
LIMIT {limit};
