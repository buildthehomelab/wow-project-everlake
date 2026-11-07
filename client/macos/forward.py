#!/usr/bin/env python3
"""Forwards the Everlake ports from this Mac's 127.0.0.1 to the server.

    forward.py <server address> [port ...]      (default ports: 1119 8081 8085)

Why: since macOS 15, an app needs the Local Network permission to connect to other machines on the LAN. The
re-signed game copy doesn't get it (macOS blocks it without asking), while Terminal has it. Connections to
127.0.0.1 aren't covered by that permission, so the game connects here and this script, started from Terminal,
passes the bytes on. TLS stays end to end: nothing is decrypted here.
"""
import asyncio
import sys

PORTS = [1119, 8081, 8085]


async def pipe(reader, writer):
    """Copies one direction; at its end, half-closes so the other direction can still finish."""
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    except (ConnectionError, OSError):
        pass


def handler(server, port):
    async def handle(client_reader, client_writer):
        try:
            server_reader, server_writer = await asyncio.wait_for(asyncio.open_connection(server, port), 10)
        except (OSError, asyncio.TimeoutError) as e:
            print(f"[forward] {port}: cannot reach {server}: {e}", flush=True)
            client_writer.close()
            return
        print(f"[forward] {port}: connection", flush=True)
        try:
            await asyncio.gather(pipe(client_reader, server_writer), pipe(server_reader, client_writer))
        finally:
            for w in (client_writer, server_writer):
                try:
                    w.close()
                except Exception:
                    pass
    return handle


async def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    server = sys.argv[1]
    ports = [int(p) for p in sys.argv[2:]] or PORTS
    servers = [await asyncio.start_server(handler(server, p), "127.0.0.1", p) for p in ports]
    print(f"[forward] 127.0.0.1:{','.join(map(str, ports))} -> {server}", flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
