-- Cost of building nodes. Deep extends hierarchies, many fields, default
-- values and slow init() all land here.
SELECT IFNULL(EXTRACT_ARG(s.arg_set_id, 'debug.name'),
              EXTRACT_ARG(s.arg_set_id, 'debug.type')) AS component,
       s.name, COUNT(*) AS n,
       ROUND(SUM(s.dur) / 1e6, 2) AS total_ms,
       ROUND(MAX(s.dur) / 1e6, 2) AS worst_ms, s.id AS worst_id
FROM slice s
WHERE s.name IN ('component.init', 'CreateObject') AND s.dur >= 0
GROUP BY 1, 2 ORDER BY total_ms DESC LIMIT {limit};
