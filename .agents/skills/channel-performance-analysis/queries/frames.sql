-- Frame count and how many missed 16.7 ms and 33.4 ms.
SELECT COUNT(*) AS frames,
       SUM(dur > 16700000) AS over_16_7ms,
       SUM(dur > 33400000) AS over_33_4ms,
       ROUND(MAX(dur) / 1e6, 2) AS worst_ms,
       id AS worst_id
FROM slice WHERE name = 'render' AND dur >= 0;
