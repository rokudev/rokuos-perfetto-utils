-- Distinct BrightScript callstacks that read one field. Pass --set field=<name>.
SELECT DISTINCT EXTRACT_ARG(arg_set_id, 'debug.callstack') AS callstack
FROM slice
WHERE name = 'roSGNode.getField'
  AND EXTRACT_ARG(arg_set_id, 'debug.name') = '{field}';
