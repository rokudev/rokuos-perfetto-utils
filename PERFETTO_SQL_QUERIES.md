# Perfetto SQL Queries

## HeapGraph Queries

### Unreachable Objects

An unreachable object is one that has been leaked and not reclaimed via refcounting because
it contains cyclic references to other unreachable objects.

For example:

```
aa = {}
aa.sub_aa = {}
aa.sub_aa.cycle = aa
```

Here `aa` references `sub_aa`, which in turn references `aa`.

This construct will result in a leak, unless `RunGarbageCollector()` is called on this thread.

In the Perfetto HeapGraph these objects are flagged with a fake field from the BrightScript domain
in which the objects live (usually the thread) called `$unreachable`.

```
$bscDomain
    |
    | $unreachable
    |
   aa----<--------
    |             |
    | sub_aa      |
    |             |
    |             |
     -------------    cycle
```

These unreachable objects are identified via `heap_graph_reference` rows where
`field_name = '$unreachable'`. This query then follows one hop outward to find
what those unreachable objects themselves point to.

```sql
SELECT
    obj.id,
    hgc.name AS type_name,
    refs.field_name
FROM heap_graph_reference AS refs
JOIN heap_graph_object AS obj ON obj.id = refs.owned_id
JOIN heap_graph_class AS hgc ON hgc.id = obj.type_id
WHERE refs.owner_id IN (
    SELECT owned_id
    FROM heap_graph_reference
    WHERE field_name = '$unreachable'
)
ORDER BY hgc.name;
```

Paste this query into the Perfetto UI (hit `:` to enter SQL mode).

#### Columns

- `id` — the object ID in `heap_graph_object`
- `type_name` — the class name from `heap_graph_class`
- `field_name` — the field on the unreachable object that holds this reference

#### Variant: summary by type

To see a count per type instead of individual objects:

```sql
SELECT
    hgc.name AS type_name,
    COUNT(*) AS count
FROM heap_graph_reference AS refs
JOIN heap_graph_object AS obj ON obj.id = refs.owned_id
JOIN heap_graph_class AS hgc ON hgc.id = obj.type_id
WHERE refs.owner_id IN (
    SELECT owned_id
    FROM heap_graph_reference
    WHERE field_name = '$unreachable'
)
GROUP BY hgc.name
ORDER BY count DESC;
```
