-- BrightScript compilation at launch. Channel code is compiled in the Channel
-- Store, but DCLs fetched from an external URL are not, so they compile on the
-- device every launch. Names are truncated - these are C++ symbols.
SELECT SUBSTR(name, 1, 48) AS phase, COUNT(*) AS n,
       ROUND(SUM(dur) / 1e6, 2) AS total_ms, id AS worst_id
FROM slice
WHERE dur >= 0 AND (name LIKE '%Compile%' OR name = 'parseComponentXML')
GROUP BY 1 ORDER BY total_ms DESC LIMIT {limit};
