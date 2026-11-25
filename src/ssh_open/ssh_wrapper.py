import argparse
import asyncio
import contextlib
import importlib.resources
import logging
import shlex
import subprocess
import uuid
from importlib.resources.abc import Traversable
from pathlib import Path

import tomli
from platformdirs import user_config_dir

from .listener import Listener

log = logging.getLogger(__name__)

# used for ssh commands (~ expanded by remote shell)
REMOTE_SSH_OPEN_DIR = "~/.ssh-open"
# used in bootstrap (expanded by remote shell)
REMOTE_SSH_OPEN_DIR_SH = "$HOME/.ssh-open"
REMOTE_BROWSER_PATH = f"{REMOTE_SSH_OPEN_DIR}/browser"
REMOTE_FIND_SOCK_PATH = f"{REMOTE_SSH_OPEN_DIR}/find-sock"
REMOTE_ENV_PATH_SH = f"{REMOTE_SSH_OPEN_DIR_SH}/env"
REMOTE_SOCK_SUBDIR = "sock"

DEFAULT_TIMEOUT_SEC = 30
DEFAULT_LISTENER_PORT = 0  # 0 = let the OS pick a free port


def load_config() -> dict:
    """Load config from the user config directory if it exists."""
    config_path = Path(user_config_dir("ssh-open")) / "config.toml"
    if config_path.exists():
        with open(config_path, "rb") as f:
            return tomli.load(f)
    return {}


def get_asset(name: str) -> Traversable:
    """Resolve the path to a bundled asset."""
    return importlib.resources.files("ssh_open.assets").joinpath(name)


def prepare_remote_dir(ssh_host: str, ssh_args: list[str]) -> str:
    """Create the remote ssh-open dirs and return the remote $HOME."""
    result = subprocess.run(
        [
            "ssh",
            *ssh_args,
            ssh_host,
            (
                f"mkdir -p {REMOTE_SSH_OPEN_DIR}/{REMOTE_SOCK_SUBDIR} && "
                f"chmod 700 {REMOTE_SSH_OPEN_DIR} && "
                'printf %s "$HOME"'
            ),
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    home = result.stdout.strip()
    if not home.startswith("/"):
        raise RuntimeError(f"Could not resolve remote home directory (got {home!r})")
    return home


def push_assets(ssh_host: str, ssh_args: list[str]) -> None:
    """Copy the browser, env and find-sock scripts to the remote host."""
    log.info(f"Pushing assets to {ssh_host}:{REMOTE_SSH_OPEN_DIR}")

    for asset_name, remote_path in [
        ("browser", f"{REMOTE_SSH_OPEN_DIR}/browser"),
        ("env", f"{REMOTE_SSH_OPEN_DIR}/env"),
        ("find-sock", REMOTE_FIND_SOCK_PATH),
    ]:
        with get_asset(asset_name).open("rb") as f:
            subprocess.run(
                ["ssh", *ssh_args, ssh_host, f"cat > {remote_path}"],
                stdin=f,
                check=True,
            )
        log.info(f"Transferred asset '{asset_name}' to {ssh_host}:{remote_path}")

    subprocess.run(
        ["ssh", *ssh_args, ssh_host, f"chmod +x {REMOTE_BROWSER_PATH} {REMOTE_FIND_SOCK_PATH}"],
        check=True,
    )
    log.info("Assets successfully pushed and permissions set.")


def build_ssh_command(
    ssh_host: str,
    extra_args: list[str],
    host_port: int,
    remote_sock: str,
) -> list[str]:
    """Build the SSH command with reverse tunnel and shell-agnostic env setup."""
    bootstrap = (
        f"export SSH_OPEN_SOCK={shlex.quote(remote_sock)}; "
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
        f"{remote_sock}:localhost:{host_port}",
        *extra_args,
        ssh_host,
        bootstrap,
    ]


async def run(
    ssh_host: str,
    ssh_extra: list[str],
    port: int,
    timeout: int,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    listener = Listener(host=ssh_host, port=port, timeout=timeout)
    await listener.start()
    serve_task = asyncio.create_task(listener.serve())

    remote_home = prepare_remote_dir(ssh_host, ssh_extra)
    session_id = uuid.uuid4().hex[:12]
    remote_sock = f"{remote_home}/.ssh-open/{REMOTE_SOCK_SUBDIR}/{session_id}.sock"

    # Always push: the browser script must match this version's protocol.
    push_assets(ssh_host, ssh_extra)
    cmd = build_ssh_command(
        ssh_host, ssh_extra, host_port=listener.port, remote_sock=remote_sock
    )
    log.info(
        f"Connecting to {ssh_host} (listener port {listener.port}, socket {remote_sock})..."
    )

    try:
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()
    finally:
        # sshd does not unlink streamlocal sockets on exit; clean up best-effort.
        with contextlib.suppress(Exception):
            cleanup = await asyncio.create_subprocess_exec(
                "ssh",
                *ssh_extra,
                ssh_host,
                f"rm -f {shlex.quote(remote_sock)}",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(cleanup.wait(), timeout=10)
        serve_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await serve_task


def main() -> None:
    config = load_config()

    parser = argparse.ArgumentParser(
        prog="ssh-open",
        description="Open a browser on the local host from a remote SSH session.",
    )
    parser.add_argument("host", help="SSH host to connect to")
    parser.add_argument(
        "--port",
        type=int,
        default=(default := config.get("port", DEFAULT_LISTENER_PORT)),
        help=f"Host listener port, 0 = pick a free port (default: {default})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=(default := config.get("timeout", DEFAULT_TIMEOUT_SEC)),
        help=f"Tunnel idle timeout in seconds (default: {default})",
    )
    our_args, ssh_extra = parser.parse_known_args()

    asyncio.run(
        run(
            our_args.host,
            ssh_extra,
            port=our_args.port,
            timeout=our_args.timeout,
        )
    )
