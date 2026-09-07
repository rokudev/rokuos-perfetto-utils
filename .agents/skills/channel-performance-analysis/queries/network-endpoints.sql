-- Request time grouped by endpoint, query string stripped.
SELECT CASE WHEN INSTR(url, '?') > 0
            THEN SUBSTR(url, 1, INSTR(url, '?') - 1) ELSE url END AS endpoint,
       COUNT(*) AS requests,
       ROUND(SUM(done.ts - st.ts) / 1e6, 2) AS total_ms,
       ROUND(MAX(done.ts - st.ts) / 1e6, 2) AS worst_ms
FROM (SELECT id, ts, EXTRACT_ARG(arg_set_id, 'debug.url') AS url FROM slice
      WHERE name IN ('AsyncGetToString', 'AsyncPostFromString')) st
LEFT JOIN flow f ON f.slice_out = st.id
LEFT JOIN slice done ON done.id = f.slice_in
GROUP BY 1 ORDER BY IFNULL(total_ms, 0) DESC LIMIT {limit};
