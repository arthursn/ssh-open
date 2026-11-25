# ssh-open

A tool that replicates VS Code's terminal behavior of opening URLs from a remote SSH server on the host machine. When `xdg-open <URL>` is called on the remote, the link opens in the host's default browser. If the URL contains OAuth redirects to `localhost`, the necessary ports are automatically forwarded via SSH tunnels.

## How it works

1. `ssh-open` starts a per-session listener on the host, on a free port picked by the OS (override with `--port`)
2. It pushes helper scripts to the remote `~/.ssh-open/`: `browser`, `env` and `find-sock`
3. It connects via SSH with:
   - A reverse tunnel from a per-session Unix socket on the remote (`-R ~/.ssh-open/sock/<session-id>.sock:localhost:<port>`) to the host listener, so multiple sessions never collide and other remote users can't reach it
   - A shell bootstrap that exports `SSH_OPEN_SOCK=<socket path>` and sets `BROWSER=~/.ssh-open/browser` after init files run
4. When any program on the remote calls `xdg-open <URL>`, the `browser` script sends the URL to the host listener through `$SSH_OPEN_SOCK` (falling back to any other live session's socket if that one is gone)
5. The host opens the URL in the default browser
6. If the URL contains `localhost` ports (e.g. OAuth redirects), forward tunnels are opened automatically and closed after a configurable timeout

## Installation

```bash
pip install git+https://github.com/arthursn/ssh-open.git
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
- OpenSSH 6.7+ on both ends (Unix socket forwarding)
- `nc` (netcat) with Unix socket support (`-U`) on the remote, e.g. `netcat-openbsd` or `nmap-ncat`

## Stale shells (tmux, screen, plain ssh logins)

A tmux/screen session keeps the `SSH_OPEN_SOCK` of the `ssho` session that started it, and that socket goes away when that connection closes. Opening URLs still works: `browser` checks that its socket is live and, if it isn't, uses the newest live one under `~/.ssh-open/sock/`.

To fix `SSH_OPEN_SOCK` itself in such a shell (or to set up ssh-open in a shell that wasn't started by `ssho`), run either of these:

```bash
source ~/.ssh-open/env   # full setup: BROWSER, SSH_OPEN_SOCK, ...
ssh_open_refresh         # once env is sourced: just re-point SSH_OPEN_SOCK
```

A live `ssho` connection to the host is still required.
