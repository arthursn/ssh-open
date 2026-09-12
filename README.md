# ssh-open

A tool that replicates VS Code's terminal behavior of opening URLs from a remote SSH server on the host machine. When `xdg-open <URL>` is called on the remote, the link opens in the host's default browser. If the URL contains OAuth redirects to `localhost`, the necessary ports are automatically forwarded via SSH tunnels.

## How it works

1. `ssh-open` starts a listener on the host (`localhost:9999`)
2. It pushes a `browser` script to the remote (`~/.ssh_open/browser`)
3. It connects via SSH with:
   - A reverse tunnel (`-R 9999:localhost:9999`) so the remote can reach the host listener
   - A shell bootstrap that sets `BROWSER=~/.ssh_open/browser` after init files run
4. When any program on the remote calls `xdg-open <URL>`, the `browser` script sends the URL to the host listener
5. The host opens the URL in the default browser
6. If the URL contains `localhost` ports (e.g. OAuth redirects), forward tunnels are opened automatically and closed after a configurable timeout

## Installation

```bash
pip install ssh-open
```

## Usage

Use `ssh-open` as a drop-in replacement for `ssh`:

```bash
ssh-open user@remote-host
ssh-open -p 2222 user@remote-host
```

## Configuration

Edit `config.toml`:

```toml
[ssh]
host = "user@remote-host"

[listener]
port = 9999

[tunnel]
timeout_seconds = 30
```

## Remote setup (one-time)

### Git Credential Manager (OAuth)

To make GCM use the host browser for OAuth flows, install the provided `gcm_wrapper` asset:

```bash
# On the remote machine
mkdir -p ~/.ssh_open
# Copy gcm_wrapper from the package assets to ~/.ssh_open/gcm_wrapper
chmod +x ~/.ssh_open/gcm_wrapper
git config --global credential.helper ~/.ssh_open/gcm_wrapper
```

The `gcm_wrapper` script sets the necessary environment variables to make GCM behave as if it's running inside a VS Code terminal, causing it to use `xdg-open` (and thus `BROWSER`) for OAuth flows.

## Requirements

- Python 3.11+
- SSH client on the host (Windows, macOS, Linux)
- `nc` (netcat) on the remote for the `browser` script
