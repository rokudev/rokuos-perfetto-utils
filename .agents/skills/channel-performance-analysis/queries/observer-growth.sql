-- Observers registered over the capture. observeField and observeFieldScopedEx
-- add an observer rather than replacing one, so registering the same field
-- twice notifies twice - a leak that shows as a rising count.
SELECT ROUND(MIN(c.value), 0) AS first,
       ROUND(MAX(c.value), 0) AS peak,
       ROUND(MAX(c.value) - MIN(c.value), 0) AS growth,
       (SELECT COUNT(*) FROM slice WHERE name LIKE 'roSGNode.observeField%'
          AND dur >= 0) AS observe_calls,
       (SELECT COUNT(*) FROM slice WHERE name LIKE 'roSGNode.unobserve%'
          AND dur >= 0) AS unobserve_calls
FROM counter c JOIN counter_track t ON c.track_id = t.id
WHERE t.name = 'field_observer_count';
