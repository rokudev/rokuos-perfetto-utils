-- The worst missed frames, split into where the time went: waiting to reach
-- render, rendering, and swapping. Whichever dominates names the cause.
-- Idle intervals are excluded - see frame-cadence.sql for why.
WITH sw AS (
  SELECT s.id, s.ts, s.dur, tt.utid,
         LEAD(s.ts) OVER (ORDER BY s.ts) AS next_ts
  FROM slice s JOIN thread_track tt ON s.track_id = tt.id
  WHERE s.name = 'swapBuffers' AND s.dur >= 0
), f AS (
  SELECT sw.id, sw.ts, sw.dur, sw.next_ts, sw.next_ts - sw.ts AS len,
         sw.dur + IFNULL((SELECT SUM(b.dur) FROM slice b
                 JOIN thread_track btt ON b.track_id = btt.id
                 WHERE btt.utid = sw.utid AND b.depth = 0 AND b.dur >= 0
                   AND b.ts >= sw.ts + sw.dur AND b.ts < sw.next_ts), 0) AS busy
  FROM sw WHERE sw.next_ts IS NOT NULL
)
SELECT f.id AS swap_id,
       ROUND(f.len / 1e6, 2) AS frame_ms,
       ROUND(f.busy / 1e6, 2) AS busy_ms,
       ROUND(f.dur / 1e6, 2) AS swap_ms,
       ROUND(((SELECT r.ts FROM slice r
               WHERE r.name = 'render' AND r.dur >= 0
                 AND r.ts >= f.ts + f.dur AND r.ts < f.next_ts
               ORDER BY r.ts LIMIT 1) - (f.ts + f.dur)) / 1e6, 2)
         AS before_render_ms,
       ROUND((SELECT r.dur FROM slice r
              WHERE r.name = 'render' AND r.dur >= 0
                AND r.ts >= f.ts + f.dur AND r.ts < f.next_ts
              ORDER BY r.ts LIMIT 1) / 1e6, 2) AS render_ms
FROM f
WHERE f.len > 16700000 AND f.busy * 2 > f.len
ORDER BY f.len DESC LIMIT {limit};
