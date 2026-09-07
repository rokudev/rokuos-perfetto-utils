-- One slice and its children. Pass --set id=<slice id>.
SELECT id, ts, dur, name, track_id FROM slice WHERE id = {id}
UNION ALL
SELECT id, ts, dur, name, track_id FROM slice WHERE parent_id = {id};
