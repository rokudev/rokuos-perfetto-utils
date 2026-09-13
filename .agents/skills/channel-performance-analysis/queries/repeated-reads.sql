-- Runs of consecutive reads of one field on one thread.
WITH reads AS (
  SELECT s.id, s.ts, s.dur, tt.utid, t.name AS thread,
         EXTRACT_ARG(s.arg_set_id, 'debug.component') AS comp,
         EXTRACT_ARG(s.arg_set_id, 'debug.name')      AS field
  FROM slice s
  JOIN thread_track tt ON s.track_id = tt.id
  JOIN thread t ON tt.utid = t.utid
  WHERE s.name = 'roSGNode.getField' AND s.dur >= 0
), seq AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY utid ORDER BY ts) AS rn,
    ROW_NUMBER() OVER (PARTITION BY utid, comp, field ORDER BY ts) AS rn_field
  FROM reads
)
SELECT thread, comp || '.' || field AS field,
       COUNT(*) AS consecutive_reads,
       ROUND(SUM(dur) / 1000.0, 1) AS total_us,
       MIN(ts) AS first_ts, id AS first_id
FROM seq
GROUP BY thread, comp, field, rn - rn_field
HAVING COUNT(*) > 1
ORDER BY consecutive_reads DESC
LIMIT {limit};
