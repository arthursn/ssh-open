import pytest

from ssh_open.ssh_wrapper import build_ssh_command, get_asset


@pytest.mark.parametrize("name", ["browser", "env", "find-sock"])
def test_asset_is_readable_with_lf_endings(name):
    with get_asset(name).open("rb") as f:
        content = f.read()

    assert content
    # Assets are executed by the remote shell; CRLF would break them.
    assert b"\r\n" not in content


def test_build_ssh_command():
    sock = "/home/u/.ssh-open/sock/abc.sock"
    cmd = build_ssh_command("host", ["-p", "2222"], host_port=5555, remote_sock=sock)

    assert cmd[0] == "ssh"
    assert cmd[cmd.index("-R") + 1] == f"{sock}:localhost:5555"
    assert cmd.index("-p") < cmd.index("host")
    assert cmd[-1].startswith(f"export SSH_OPEN_SOCK={sock};")
