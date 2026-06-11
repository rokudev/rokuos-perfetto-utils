# perfetto
Perfetto utility scripts

## Installation

Using uv:

```
uv venv
source .venv/bin/activate
uv pip install -r pyproject.toml
```

## Contents

- ws-client/perfetto-client - simple python script to capture Perfetto protobuf data from RokuOS
- find\_brs\_cycles - attempt to report on cycles in a captured heapgraph
