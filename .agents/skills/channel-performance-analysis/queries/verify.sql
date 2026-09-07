-- Check the slices you are about to quote. Pass --set ids=22079,22087,27133
-- An id missing from the output does not exist in this trace.
SELECT s.id, s.name, ROUND(s.dur / 1e6, 2) AS ms, t.name AS thread,
       IFNULL(EXTRACT_ARG(s.arg_set_id, 'debug.name'),
              EXTRACT_ARG(s.arg_set_id, 'debug.function')) AS what
FROM slice s
JOIN thread_track tt ON s.track_id = tt.id
JOIN thread t ON tt.utid = t.utid
WHERE s.id IN ({ids})
ORDER BY s.dur DESC;
