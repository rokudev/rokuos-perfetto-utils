-- What ran during the missed frames, by thread and slice name. Both render
-- threads matter: they alternate rather than run together, so observer time on
-- either is time the render side was not rendering.
--
-- The window runs from the end of one swap to the start of the next, so the
-- swap's own duration is not in it - a frame that missed because the swap was
-- slow shows up in frame-breakdown, not here. Slices are counted at depth 0
-- only, so work nested inside consumeAllTasks is attributed to it.
WITH sw AS (
  SELECT s.id, s.ts, s.dur, tt.utid,
         LEAD(s.ts) OVER (ORDER BY s.ts) AS next_ts
  FROM slice s JOIN thread_track tt ON s.track_id = tt.id
  WHERE s.name = 'swapBuffers' AND s.dur >= 0
), missed AS (
  SELECT sw.ts + sw.dur AS a, sw.next_ts AS b
  FROM sw WHERE sw.next_ts IS NOT NULL
    AND sw.next_ts - sw.ts > 16700000
    AND (sw.dur + IFNULL((SELECT SUM(x.dur) FROM slice x
                  JOIN thread_track xtt ON x.track_id = xtt.id
                  WHERE xtt.utid = sw.utid AND x.depth = 0 AND x.dur >= 0
                    AND x.ts >= sw.ts + sw.dur AND x.ts < sw.next_ts), 0)) * 2
        > sw.next_ts - sw.ts
)
SELECT t.name AS thread, s.name AS slice, COUNT(*) AS n,
       ROUND(SUM(s.dur) / 1e6, 2) AS total_ms
FROM missed m
JOIN slice s ON s.ts >= m.a AND s.ts < m.b AND s.depth = 0 AND s.dur >= 0
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
GROUP BY 1, 2 ORDER BY total_ms DESC LIMIT {limit};
