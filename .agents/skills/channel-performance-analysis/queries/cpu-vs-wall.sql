-- Longest BrightScript slices with thread CPU time beside wall time.
SELECT id, ROUND(dur / 1e6, 2) AS ms,
       ROUND(EXTRACT_ARG(arg_set_id, 'debug.cpu_us') / 1000.0, 2) AS cpu_ms,
       EXTRACT_ARG(arg_set_id, 'debug.callstack') AS callstack
FROM slice WHERE name = 'ExecBrightScript' AND dur >= 0
ORDER BY dur DESC LIMIT {limit};
