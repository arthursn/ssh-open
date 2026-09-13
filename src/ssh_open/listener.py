import asyncio
import logging
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

from .protocol import DEFAULT_PORT, OpenRequest, OpenResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def extract_localhost_ports(url: str) -> list[int]:
    """Parse a URL and find any localhost ports referenced in it."""
    ports = set()

    def check_url(u: str):
        try:
            parsed = urlparse(u)
            # Direct localhost URL
            if parsed.hostname in ("localhost", "127.0.0.1") and parsed.port:
                ports.add(parsed.port)
            # Scan query parameters for nested localhost URLs
            for values in parse_qs(parsed.query).values():
                for value in values:
                    check_url(value)
        except Exception:
            pass

    check_url(url)
    return list(ports)


def open_url_on_host(url: str) -> None:
    """Open a URL using the host OS default browser."""
    if sys.platform == "win32":
        import os

        os.startfile(url)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url])
    else:
        subprocess.Popen(["xdg-open", url])


class TunnelManager:
    def __init__(self, timeout: int, ssh_host: str):
        self.timeout = timeout
        self.ssh_host = ssh_host
        # port -> asyncio.Task
        self._tunnels: dict[int, asyncio.Task] = {}

    async def forward_port(self, port: int) -> None:
        if port in self._tunnels and not self._tunnels[port].done():
            log.info(f"Port {port} already forwarded, resetting timer.")
            self._tunnels[port].cancel()

        self._tunnels[port] = asyncio.create_task(self._tunnel_with_timeout(port))

    async def _tunnel_with_timeout(self, port: int) -> None:
        log.info(f"Opening forward tunnel for port {port} (timeout: {self.timeout}s)")
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-N",  # no remote command
            "-L",
            f"{port}:localhost:{port}",
            "p510",
            # stdout=asyncio.subprocess.DEVNULL,
            # stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=self.timeout)
        except TimeoutError:
            log.info(f"Tunnel timeout reached for port {port}, closing.")
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
            self._tunnels.pop(port, None)
            log.info(f"Tunnel for port {port} closed.")


class Listener:
    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        timeout: int = 30,
    ):
        self.host: str = host
        self.port: int = port
        self.timeout: int = timeout
        self.tunnel_manager = TunnelManager(self.timeout, self.host)

    async def handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        addr = writer.get_extra_info("peername")
        log.info(f"Connection from {addr}")
        try:
            raw = await reader.readline()
            if not raw:
                return

            request = OpenRequest.deserialize(raw)
            log.info(f"Received URL: {request.url}")

            ports = extract_localhost_ports(request.url)
            log.info(f"Detected localhost ports: {ports}")

            for port in ports:
                await self.tunnel_manager.forward_port(port)

            open_url_on_host(request.url)

            response = OpenResponse(success=True, forwarded_ports=ports)
            writer.write(response.serialize())
            await writer.drain()

        except Exception as e:
            log.error(f"Error handling request: {e}")
            response = OpenResponse(success=False, forwarded_ports=[], error=str(e))
            writer.write(response.serialize())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def run(self) -> None:
        server = await asyncio.start_server(
            self.handle_client,
            host="127.0.0.1",
            port=self.port,
        )
        addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
        log.info(f"Listening on {addrs}")
        async with server:
            await server.serve_forever()
