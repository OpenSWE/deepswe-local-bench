#!/usr/bin/env python3
"""Forward 127.0.0.1:80 -> 127.0.0.1:8000 so Pier's no-network sandbox can reach a local server.

Pier runs DeepSWE tasks on an isolated network behind a squid proxy whose config allows
only destination ports 80 and 443, so an agent cannot reach a server on port 8000.
macOS reserves ports below 1024 for root, so this forwarder (and only this forwarder)
runs under sudo, leaving the inference server unprivileged.

    sudo ./scripts/port80_forward.py [--listen-port 80] [--target-port 8000]

Binds loopback only: reachable from containers as host.docker.internal (Docker Desktop
proxies that to the host's loopback) and not from the LAN.
"""
import argparse
import asyncio
import os
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, TimeoutError):
        pass
    finally:
        writer.close()


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen-host", default="127.0.0.1")
    ap.add_argument("--listen-port", type=int, default=80)
    ap.add_argument("--target-host", default="127.0.0.1")
    ap.add_argument("--target-port", type=int, default=8000)
    a = ap.parse_args()

    async def handle(cr: asyncio.StreamReader, cw: asyncio.StreamWriter) -> None:
        try:
            sr, sw = await asyncio.open_connection(a.target_host, a.target_port)
        except OSError as e:
            print(f"upstream {a.target_host}:{a.target_port} unreachable: {e}", file=sys.stderr, flush=True)
            cw.close()
            return
        await asyncio.gather(pipe(cr, sw), pipe(sr, cw))

    server = await asyncio.start_server(handle, a.listen_host, a.listen_port)
    # Drop root for everything after the privileged bind.
    if os.geteuid() == 0 and (uid := os.environ.get("SUDO_UID")):
        os.setgid(int(os.environ.get("SUDO_GID", uid)))
        os.setuid(int(uid))
    print(f"forwarding {a.listen_host}:{a.listen_port} -> {a.target_host}:{a.target_port} "
          f"(uid {os.geteuid()})", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
