-- Total time per slice name. Slices nest, so these totals overlap.
SELECT name, COUNT(*) AS n,
       ROUND(SUM(dur) / 1e6, 2) AS total_ms,
       ROUND(MAX(dur) / 1e6, 2) AS worst_ms,
       id AS worst_id
FROM slice WHERE dur >= 0
GROUP BY name ORDER BY total_ms DESC LIMIT {limit};
