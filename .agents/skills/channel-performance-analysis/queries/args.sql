-- Which slices carry the later-added arguments: cpu_us, depth, id.
SELECT name AS slice, COUNT(*) AS n,
       SUM(EXTRACT_ARG(arg_set_id, 'debug.cpu_us') IS NOT NULL) AS cpu_us,
       SUM(EXTRACT_ARG(arg_set_id, 'debug.depth')  IS NOT NULL) AS depth,
       SUM(EXTRACT_ARG(arg_set_id, 'debug.id')     IS NOT NULL) AS id
FROM slice WHERE dur >= 0
GROUP BY 1 HAVING cpu_us + depth + id > 0
ORDER BY n DESC;
