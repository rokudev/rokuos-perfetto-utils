-- Cross-domain copies grouped by the field and operation that caused them.
SELECT
  IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.component'), '?') || '.' ||
  IFNULL(EXTRACT_ARG(op.arg_set_id, 'debug.name'), '?') AS field,
  op.name  AS operation,
  COUNT(*) AS copies,
  ROUND(SUM(cp.dur) / 1000.0, 1) AS total_us,
  ROUND(MAX(cp.dur) / 1000.0, 1) AS worst_us,
  cp.id AS worst_id
FROM slice cp
JOIN slice op ON op.id = cp.parent_id
WHERE cp.name = 'bscCopyToDomainEx' AND cp.dur >= 0
GROUP BY 1, 2
ORDER BY total_us DESC
LIMIT {limit};
