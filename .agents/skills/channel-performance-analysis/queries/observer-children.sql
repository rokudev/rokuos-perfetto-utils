-- What runs inside observer callbacks, by slice name.
SELECT c.name, COUNT(*) AS n,
       ROUND(SUM(c.dur) / 1e6, 2) AS total_ms
FROM slice c JOIN slice p ON c.parent_id = p.id
WHERE p.name = 'observer.callback' AND c.dur >= 0
GROUP BY 1 ORDER BY total_ms DESC LIMIT {limit};
