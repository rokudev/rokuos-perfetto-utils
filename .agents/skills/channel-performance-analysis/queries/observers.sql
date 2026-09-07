-- Outermost observers via debug.depth. Returns nothing on a trace lacking it - use observers-no-depth.
SELECT EXTRACT_ARG(arg_set_id, 'debug.fieldName') AS field,
       EXTRACT_ARG(arg_set_id, 'debug.function')  AS function,
       COUNT(*) AS n,
       ROUND(SUM(dur) / 1e6, 2) AS total_ms,
       ROUND(MAX(dur) / 1e6, 2) AS worst_ms,
       id AS worst_id
FROM slice WHERE name = 'observer.callback' AND dur >= 0
  AND EXTRACT_ARG(arg_set_id, 'debug.depth') = 0
GROUP BY 1, 2 ORDER BY total_ms DESC LIMIT {limit};
