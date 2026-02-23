# devbox-connect

SSH tunnel manager for connecting local ports to your devbox.

## Features

- **Simple YAML configuration** - Define tunnels in a readable config file
- **Auto-reconnect** - Automatically reconnects with exponential backoff when connections drop
- **Multiple tunnels** - Manage many port forwards to one or more hosts
- **Windows service support** - Run as a background service with auto-start

## Installation

```bash
# Install with uv
uv tool install git+https://github.com/YOUR_USERNAME/devbox-connect

# Or install from local directory
cd devbox-connect
uv tool install .
```

## Quick Start

1. Create a configuration file `tunnels.yaml`:

```yaml
user: your-username
key_file: ~/.ssh/id_rsa

tunnels:
  - name: web-dev
    host: devbox.example.com
    remote_port: 8080

  - name: database
    host: devbox.example.com
    remote_port: 5432
```

2. Start the tunnels:

```bash
devbox-connect -c tunnels.yaml start
```

3. Access your devbox services locally:
   - `localhost:8080` → devbox:8080
   - `localhost:5432` → devbox:5432

## Usage

```
devbox-connect [-c CONFIG] COMMAND

Commands:
  start      Start tunnels and keep running (default)
  status     Show configured tunnels
  validate   Validate configuration file

Options:
  -c, --config PATH    Path to config file (default: tunnels.yaml)
  -v, --verbose        Enable verbose output
```

## Configuration

See `tunnels.example.yaml` for a complete example.

### Simple Format (single host)

```yaml
user: username
key_file: ~/.ssh/id_rsa  # Optional

tunnels:
  - name: web
    host: devbox.example.com
    remote_port: 8080
    local_port: 8080      # Optional, defaults to remote_port

  - name: jupyter
    host: devbox.example.com
    remote_port: 8888
    local_port: 9999      # Use different local port
```

### Grouped Format (multiple hosts)

```yaml
hosts:
  - host: devbox1.example.com
    user: username
    tunnels:
      - name: web
        remote_port: 8080

  - host: devbox2.example.com
    user: username
    tunnels:
      - name: api
        remote_port: 3000
```

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `user` | SSH username | (required) |
| `host` | Remote hostname | (required) |
| `key_file` | Path to SSH private key | SSH agent/default |
| `remote_port` | Port on remote host | (required) |
| `local_port` | Local port to listen on | Same as remote_port |
| `remote_host` | Host on remote side | `localhost` |
| `reconnect_delay` | Initial reconnect delay (seconds) | `5` |
| `max_reconnect_delay` | Max reconnect delay | `60` |

### Forwarding Through Devbox

You can access services on other hosts through your devbox:

```yaml
tunnels:
  - name: internal-db
    host: devbox.example.com
    remote_port: 5432
    remote_host: internal-db.corp  # Accessed via devbox
```

## Windows Service

To run devbox-connect as a Windows service that starts automatically:

### Prerequisites

1. Install NSSM (Non-Sucking Service Manager):
   ```powershell
   winget install nssm
   ```

2. Install devbox-connect:
   ```powershell
   uv tool install .
   ```

### Install Service

Run PowerShell as Administrator:

```powershell
.\service\install-service.ps1 -ConfigPath C:\path\to\tunnels.yaml
```

### Manage Service

```powershell
# Check status
Get-Service DevboxConnect

# Start/Stop
Start-Service DevboxConnect
Stop-Service DevboxConnect

# View logs
Get-Content $env:LOCALAPPDATA\devbox-connect\service.log -Tail 50

# Uninstall
.\service\install-service.ps1 -Uninstall
```

### Manual Run (without service)

```batch
service\run-manual.bat C:\path\to\tunnels.yaml
```

## SSH Key Setup

devbox-connect uses SSH key authentication. Ensure your key is set up:

1. Generate a key (if needed):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/devbox_key
   ```

2. Copy to devbox:
   ```bash
   ssh-copy-id -i ~/.ssh/devbox_key user@devbox.example.com
   ```

3. Reference in config:
   ```yaml
   key_file: ~/.ssh/devbox_key
   ```

Or use SSH agent (key_file not needed if agent has your key loaded).

## Troubleshooting

### Connection refused
- Check the remote service is running on the specified port
- Verify you can SSH to the host manually: `ssh user@devbox`

### Permission denied
- Check your SSH key is correct and has proper permissions
- On Windows, ensure key file isn't world-readable

### Port already in use
- Change `local_port` to an unused port
- Check what's using the port: `netstat -an | findstr :8080`

### Tunnels disconnect frequently
- Check network stability
- Increase `reconnect_delay` and `max_reconnect_delay`
- Some networks/firewalls drop idle connections; the remote service may need keepalive

## License

MIT
