-- Outermost observers via the slice tree, for traces without debug.depth.
SELECT EXTRACT_ARG(arg_set_id, 'debug.fieldName') AS field,
       EXTRACT_ARG(arg_set_id, 'debug.function')  AS function,
       COUNT(*) AS n,
       ROUND(SUM(dur) / 1e6, 2) AS total_ms,
       ROUND(MAX(dur) / 1e6, 2) AS worst_ms,
       id AS worst_id
FROM slice WHERE name = 'observer.callback' AND dur >= 0
  AND NOT EXISTS (SELECT 1 FROM ancestor_slice(slice.id) a
                  WHERE a.name = 'observer.callback')
GROUP BY 1, 2 ORDER BY total_ms DESC LIMIT {limit};
