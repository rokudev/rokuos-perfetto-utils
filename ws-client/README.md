# perfetto-client - RokuOS Perfetto Client

This script assists in downloading Perfetto traces from your RokuOS device.

## Installation

```
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Usage

After booting the device:

```
perfetto-client $ip [options]
```

### Options

#### --log

Outputs logs to the console as each Perfetto packet is received from the device.

### --validate

Validates the trace file is a valid Protobuf file. It does not validate the actual trace events but is 
nonetheless useful for checking that corruption is not happening.

This relies on the external program `protoc`.

### --channel <channel>

Specifies a channel to enable for tracing on the device. This can be specified multiple times.
e.g.

```
perfetto-client $ip --channel dev
```

This is just a shortcut for using the ECP command to enable Perfetto for the given channel.

### Example

```
perfetto-client 10.2.3.4 \
        --log \
        --validate \
        --channel dev
```

