-- Frame cadence: swapBuffers to swapBuffers. 16.7 ms is keeping up at 60 Hz.
--
-- A long interval is only a missed frame if the render thread was working
-- through it. If it was idle the channel had nothing to draw, which is not
-- jank - so `missed` counts only the intervals where the thread was busy for
-- most of the interval, and that is the number to report.
--
-- The swap itself counts as busy: a frame can miss because swapBuffers took
-- too long, and that time is the frame's cost, not idleness.
WITH sw AS (
  SELECT s.id, s.ts, s.dur, tt.utid,
         LEAD(s.ts) OVER (ORDER BY s.ts) AS next_ts
  FROM slice s JOIN thread_track tt ON s.track_id = tt.id
  WHERE s.name = 'swapBuffers' AND s.dur >= 0
), gap AS (
  SELECT sw.id, sw.next_ts - sw.ts AS len,
         sw.dur + IFNULL((SELECT SUM(b.dur) FROM slice b
                 JOIN thread_track btt ON b.track_id = btt.id
                 WHERE btt.utid = sw.utid AND b.depth = 0 AND b.dur >= 0
                   AND b.ts >= sw.ts + sw.dur AND b.ts < sw.next_ts), 0) AS busy
  FROM sw WHERE sw.next_ts IS NOT NULL
)
SELECT COUNT(*) AS intervals,
       SUM(len > 16700000) AS over_16_7ms,
       SUM(len > 16700000 AND busy * 2 > len) AS missed,
       SUM(len > 33400000 AND busy * 2 > len) AS missed_by_two_budgets,
       ROUND(MAX(CASE WHEN busy * 2 > len THEN len END) / 1e6, 2) AS worst_ms
FROM gap;
