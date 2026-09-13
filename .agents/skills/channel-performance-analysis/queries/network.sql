-- Requests from issue to response, per method and thread. Unfinished ones counted separately.
WITH started AS (
  SELECT s.id, s.ts, s.name AS method, t.name AS thread,
         EXTRACT_ARG(s.arg_set_id, 'debug.url') AS url
  FROM slice s
  JOIN thread_track tt ON s.track_id = tt.id
  JOIN thread t ON tt.utid = t.utid
  WHERE s.name IN ('AsyncGetToString', 'AsyncPostFromString')
), req AS (
  -- LEFT JOIN: a request with no flow never completed in the capture
  SELECT st.id, st.method, st.thread, done.ts - st.ts AS elapsed_ns
  FROM started st
  LEFT JOIN flow f ON f.slice_out = st.id
  LEFT JOIN slice done ON done.id = f.slice_in
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY method, thread
                               ORDER BY elapsed_ns DESC) AS rk
  FROM req
)
SELECT method, thread, COUNT(*) AS requests,
       SUM(elapsed_ns IS NULL)            AS unfinished,
       ROUND(SUM(elapsed_ns) / 1e6, 2)    AS total_ms,
       ROUND(AVG(elapsed_ns) / 1e6, 2)    AS mean_ms,
       ROUND(MAX(elapsed_ns) / 1e6, 2)    AS worst_ms,
       MAX(CASE WHEN rk = 1 THEN id END)  AS worst_id
FROM ranked
GROUP BY 1, 2
ORDER BY IFNULL(total_ms, 0) DESC
LIMIT {limit};
