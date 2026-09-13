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

Use `ssho` as a drop-in replacement for `ssh`:

```bash
ssho user@remote-host
ssho -p 2222 user@remote-host
```

## Requirements

- Python 3.11+
- SSH client on the host (Windows, macOS, Linux)
- `nc` (netcat) on the remote for the `browser` script
