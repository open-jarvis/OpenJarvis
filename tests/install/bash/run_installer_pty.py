"""Run the real curl-pipe installer under a terminal with scripted answers."""

from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import subprocess
import sys
import termios
import time


def main() -> int:
    script = sys.argv[1]
    answers = json.loads(sys.argv[2])
    master, slave = pty.openpty()

    def attach_terminal() -> None:
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    process = subprocess.Popen(
        [
            "bash",
            "-c",
            'cat "$1" | bash -s -- --no-bg-orchestrator --minimal',
            "_",
            script,
        ],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        preexec_fn=attach_terminal,
    )
    os.close(slave)
    output = bytearray()
    answered = 0
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 0.1)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
                prompts = output.count(
                    b"Press Enter or Y to consent, or N to decline: "
                )
                if prompts > answered and answered < len(answers):
                    os.write(master, answers[answered].encode())
                    answered += 1
            elif process.poll() is not None:
                break
        else:
            process.kill()
            raise TimeoutError("Installer terminal test timed out")
        return process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
        sys.stdout.buffer.write(output)


if __name__ == "__main__":
    raise SystemExit(main())
