-- Individual cross-domain copies of one field, worst first. Pass --set field=<name>.
SELECT cp.ts, ROUND(cp.dur / 1000.0, 1) AS dur_us
FROM slice cp JOIN slice op ON op.id = cp.parent_id
WHERE cp.name = 'bscCopyToDomainEx' AND cp.dur >= 0
  AND EXTRACT_ARG(op.arg_set_id, 'debug.name') = '{field}'
ORDER BY cp.dur DESC;
