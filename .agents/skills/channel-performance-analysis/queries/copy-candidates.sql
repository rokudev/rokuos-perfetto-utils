-- Copies classified by thread and by whether the access rendezvoused, for getRef vs move.
WITH cp AS (
  SELECT c.id, c.dur, t.name AS thread, op.name AS operation,
    IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.component'), '?') || '.' ||
    IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.name'), '?') AS field,
    EXISTS (SELECT 1 FROM slice rz
            WHERE rz.parent_id = op.id AND rz.name = 'Rendezvous')
      AS cross_thread
  FROM slice c
  JOIN slice op ON op.id = c.parent_id
  JOIN thread_track tt ON c.track_id = tt.id
  JOIN thread t ON tt.utid = t.utid
  WHERE c.name = 'bscCopyToDomainEx' AND c.dur >= 0
)
SELECT thread, operation, field, cross_thread, COUNT(*) AS copies,
       ROUND(SUM(dur) / 1000.0, 1) AS total_us,
       ROUND(MAX(dur) / 1000.0, 1) AS worst_us,
       id AS worst_id
FROM cp
GROUP BY 1, 2, 3, 4
ORDER BY total_us DESC
LIMIT {limit};
