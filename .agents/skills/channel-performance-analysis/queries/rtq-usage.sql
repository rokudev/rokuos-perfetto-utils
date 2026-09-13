-- roRenderThreadQueue postMessage and deliver usage, and what they cost.
SELECT s.name, t.name AS thread, COUNT(*) AS n,
       ROUND(SUM(s.dur)/1e6, 2) AS total_ms,
       ROUND(MAX(s.dur)/1e6, 2) AS worst_ms
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE s.name LIKE 'roRenderThreadQueue%' AND s.dur >= 0
GROUP BY 1, 2 ORDER BY n DESC;
