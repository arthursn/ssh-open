import argparse
import asyncio
import importlib.resources
import logging
import socket
import subprocess
from pathlib import Path

from .listener import Listener

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
        log.info(f"Transferred asset '{asset_name}' to {ssh_host}:{remote_path}")

    subprocess.run(
        ["ssh", *ssh_args, ssh_host, f"chmod +x {REMOTE_BROWSER_PATH}"],
        check=True,
    )
    log.info("Assets successfully pushed and permissions set.")


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


async def run(
    ssh_host: str,
    ssh_extra: list[str],
    timeout: int = 30,
    push: bool = True,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    listener = Listener(host=ssh_host, timeout=timeout)

    if not is_listener_running():
        asyncio.create_task(listener.run())
        for _ in range(10):
            await asyncio.sleep(0.3)
            if is_listener_running():
                log.info("Listener is up.")
                break
        else:
            log.warning("Listener may not have started in time.")

    if push:
        push_assets(ssh_host, ssh_extra)
    cmd = build_ssh_command(ssh_host, ssh_extra)
    log.info(f"Connecting to {ssh_host}...")

    proc = await asyncio.create_subprocess_exec(*cmd)
    await proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ssh-open",
        description="Open a browser on the local host from a remote SSH session.",
    )
    parser.add_argument("host", help="SSH host to connect to")
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Tunnel idle timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip pushing assets to the remote host",
    )
    our_args, ssh_extra = parser.parse_known_args()

    asyncio.run(
        run(
            our_args.host,
            ssh_extra,
            timeout=our_args.timeout,
            push=not our_args.no_push,
        )
    )
