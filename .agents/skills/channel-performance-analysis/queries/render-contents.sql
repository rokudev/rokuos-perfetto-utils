-- What runs inside the render phase. Rendering is not only tree traversal -
-- observers can run within it - so a long render is not by itself evidence
-- that the scene is complex. Slices are counted wherever they nest, so these
-- overlap: an ExecBrightScript inside an observer appears under both.
SELECT c.name, COUNT(*) AS n, ROUND(SUM(c.dur) / 1e6, 2) AS total_ms
FROM slice c
WHERE c.dur >= 0
  AND EXISTS (SELECT 1 FROM ancestor_slice(c.id) a WHERE a.name = 'render')
GROUP BY 1 ORDER BY total_ms DESC LIMIT {limit};
