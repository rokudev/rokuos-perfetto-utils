-- swapBuffers waits for the GPU and should return by the next vsync, so ~16 ms
-- is the ceiling. Lists the slow ones individually rather than only counting
-- them: the shape matters. A tight cluster of similar values is one
-- phenomenon; a lone outlier among them is another, and an aggregate hides it.
--
-- over_16ms is the total across the capture, repeated on each row. The first
-- swap is excluded - it is long for unrelated startup reasons.
SELECT COUNT(*) OVER () AS over_16ms,
       id,
       ROUND((ts - TRACE_START()) / 1e6, 0) AS at_ms,
       ROUND(dur / 1e6, 2) AS ms
FROM slice
WHERE name = 'swapBuffers' AND dur > 16000000
  AND ts > (SELECT MIN(ts) FROM slice WHERE name = 'swapBuffers')
ORDER BY dur DESC LIMIT {limit};
