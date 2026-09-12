import importlib.resources
import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# used for ssh commands (~ expanded by remote shell)
REMOTE_SSH_OPEN_DIR = "~/.ssh_open"
# used in bootstrap (expanded by remote shell)
REMOTE_SSH_OPEN_DIR_SH = "$HOME/.ssh_open"
REMOTE_BROWSER_PATH = f"{REMOTE_SSH_OPEN_DIR}/browser"
REMOTE_ENV_PATH_SH = f"{REMOTE_SSH_OPEN_DIR_SH}/env"
LISTENER_PORT = 9999


def is_listener_running(port: int = LISTENER_PORT) -> bool:
    """Check if the listener is already running by attempting a connection."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def start_listener() -> threading.Thread:
    """Start the listener in a background daemon thread."""
    from ssh_open.host.listener import main as listener_main

    log.info("Starting ssh-open listener...")
    thread = threading.Thread(target=listener_main, daemon=True)
    thread.start()

    for _ in range(10):
        time.sleep(0.3)
        if is_listener_running():
            log.info("Listener is up.")
            return thread

    log.warning("Listener may not have started in time.")
    return thread


def get_asset(name: str) -> Path:
    """Resolve the path to a bundled asset."""
    return importlib.resources.files("ssh_open.assets").joinpath(name)  # ty: ignore[invalid-return-type]


def push_assets(ssh_host: str, ssh_args: list[str]) -> None:
    """Copy the browser and env scripts to the remote host."""
    log.info(f"Pushing assets to {ssh_host}:{REMOTE_SSH_OPEN_DIR}")

    subprocess.run(
        ["ssh", *ssh_args, ssh_host, f"mkdir -p {REMOTE_SSH_OPEN_DIR}"],
        check=True,
    )

    for asset_name, remote_path in [
        ("browser", f"{REMOTE_SSH_OPEN_DIR}/browser"),
        ("env", f"{REMOTE_SSH_OPEN_DIR}/env"),
    ]:
        with open(get_asset(asset_name), "rb") as f:
            subprocess.run(
                ["ssh", *ssh_args, ssh_host, f"cat > {remote_path}"],
                stdin=f,
                check=True,
            )

    subprocess.run(
        ["ssh", *ssh_args, ssh_host, f"chmod +x {REMOTE_BROWSER_PATH}"],
        check=True,
    )


def build_ssh_command(ssh_host: str, extra_args: list[str]) -> list[str]:
    """Build the SSH command with reverse tunnel and shell-agnostic env setup."""
    bootstrap = (
        'REAL_SHELL=$(getent passwd "$USER" | cut -d: -f7 | xargs basename); '
        'case "$REAL_SHELL" in '
        "bash) "
        f"  printf '[ -f $HOME/.bashrc ] && source $HOME/.bashrc\\nsource {REMOTE_ENV_PATH_SH}\\n'"
        f"    > {REMOTE_SSH_OPEN_DIR_SH}/.bashrc; "
        f"  exec bash --rcfile {REMOTE_SSH_OPEN_DIR_SH}/.bashrc -i ;; "
        "zsh) "
        f"  printf '[ -f $HOME/.zshrc ] && source $HOME/.zshrc\\nsource {REMOTE_ENV_PATH_SH}\\n'"
        f"    > {REMOTE_SSH_OPEN_DIR_SH}/.zshrc; "
        f"  exec env ZDOTDIR={REMOTE_SSH_OPEN_DIR_SH} zsh -i ;; "
        "*) "
        f"  source {REMOTE_ENV_PATH_SH}; "
        '  exec "$REAL_SHELL" -i ;; '
        "esac"
    )

    return [
        "ssh",
        "-t",
        "-R",
        f"{LISTENER_PORT}:localhost:{LISTENER_PORT}",
        *extra_args,
        ssh_host,
        bootstrap,
    ]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    args = sys.argv[1:]
    if not args:
        print("Usage: ssh-open [ssh-options] <host>", file=sys.stderr)
        sys.exit(1)

    # The host is the last non-option argument (simple heuristic)
    ssh_host = args[-1]
    ssh_extra = args[:-1]

    if not is_listener_running():
        start_listener()

    push_assets(ssh_host, ssh_extra)
    cmd = build_ssh_command(ssh_host, ssh_extra)
    log.info(f"Connecting to {ssh_host}...")
    subprocess.run(cmd, check=False)


if __name__ == "__main__":
    main()
