-- Cross-thread callFunc, split into queueing latency, function body and copy residual.
WITH cf AS (
  SELECT ct.name AS calling_thread, op.arg_set_id AS aset,
         rz.id AS slice_id, rz.ts AS rz_ts, rz.dur AS total_ns,
         (deq.ts - enq.ts) AS latency_ns,
         deq.ts AS deq_ts, deq.parent_id AS batch
  FROM slice rz
  JOIN slice enq ON enq.parent_id = rz.id AND enq.name = 'rendezvous-enqueue'
  JOIN flow  f   ON f.slice_out = enq.id
  JOIN slice deq ON deq.id = f.slice_in
  JOIN slice op  ON op.id = rz.parent_id AND op.name = 'roSGNode.callFunc'
  JOIN thread_track ctt ON rz.track_id = ctt.id
  JOIN thread ct ON ctt.utid = ct.utid
  WHERE rz.name = 'Rendezvous' AND rz.dur >= 0
)
SELECT calling_thread, slice_id,
  IFNULL(EXTRACT_ARG(aset, 'debug.component'), '?') || '.' ||
  IFNULL(EXTRACT_ARG(aset, 'debug.name'), '?') AS function,
  ROUND(total_ns   / 1e6, 2) AS total_ms,
  ROUND(latency_ns / 1e6, 2) AS latency_ms,
  ROUND(IFNULL((SELECT SUM(e.dur) FROM slice e
                WHERE e.parent_id = cf.batch AND e.name = 'ExecBrightScript'
                  AND e.ts >= cf.deq_ts AND e.ts < cf.rz_ts + cf.total_ns
                  AND e.dur >= 0), 0) / 1e6, 2) AS body_ms
FROM cf ORDER BY total_ns DESC LIMIT {limit};
