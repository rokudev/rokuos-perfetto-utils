-- Adjacent read pairs of one field with nothing else on the thread between them.
WITH reads AS (
  SELECT s.id, s.ts, s.dur, tt.utid, t.name AS thread,
         EXTRACT_ARG(s.arg_set_id, 'debug.component') AS comp,
         EXTRACT_ARG(s.arg_set_id, 'debug.name')      AS field
  FROM slice s
  JOIN thread_track tt ON s.track_id = tt.id
  JOIN thread t ON tt.utid = t.utid
  WHERE s.name = 'roSGNode.getField' AND s.dur >= 0
), p AS (
  SELECT *,
    LAG(ts)    OVER w AS prev_ts,
    LAG(dur)   OVER w AS prev_dur,
    LAG(comp)  OVER w AS prev_comp,
    LAG(field) OVER w AS prev_field
  FROM reads
  WINDOW w AS (PARTITION BY utid ORDER BY ts)
)
SELECT thread, comp || '.' || field AS field,
       COUNT(*) AS adjacent_pairs,
       ROUND(SUM(dur) / 1000.0, 1) AS total_us,
       MIN(ts) AS first_ts, id AS first_id
FROM p
WHERE prev_ts IS NOT NULL AND comp = prev_comp AND field = prev_field
  AND NOT EXISTS (
    SELECT 1 FROM slice o
    JOIN thread_track ott ON o.track_id = ott.id
    WHERE ott.utid = p.utid AND o.id != p.id
      AND o.ts > p.prev_ts + p.prev_dur AND o.ts < p.ts
  )
GROUP BY 1, 2 ORDER BY adjacent_pairs DESC
LIMIT {limit};
