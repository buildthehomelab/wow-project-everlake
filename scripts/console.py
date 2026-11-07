#!/usr/bin/env python3
"""Runs one command on the worldserver console and prints the reply.

    ./scripts/console.py "bnetaccount create name@example.com Password"
    ./scripts/console.py "server info"

The console is the container's terminal (docker compose attach). This script attaches through a pseudo-terminal,
types the command, collects the reply for a few seconds and detaches with Ctrl+P Ctrl+Q, so the server keeps running.
"""
import os
import pty
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_for(fd, seconds):
    out = b""
    end = time.time() + seconds
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
    return out.decode(errors="replace")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    command = " ".join(sys.argv[1:])
    container = subprocess.run(["docker", "compose", "ps", "-q", "worldserver"], cwd=HERE,
                               capture_output=True, text=True, check=True).stdout.strip()
    if not container:
        sys.exit("worldserver is not running")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("docker", ["docker", "attach", "--sig-proxy=false", container])
    read_for(fd, 1.5)
    os.write(fd, command.encode() + b"\r")
    reply = read_for(fd, 4)
    os.write(fd, b"\x10\x11")  # Ctrl+P Ctrl+Q: detach, the server keeps running
    read_for(fd, 1)
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    lines = [l for l in reply.replace("\r", "").split("\n") if l.strip() and l.strip() != command]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
