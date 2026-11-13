#!/usr/bin/env python3
"""Run a finite shell-plugin helper with bounded output and a hard deadline.

Usage: bounded-run.py {lookup,ocr,probe,shortcut} COMMAND [ARG...]
Output is buffered here, not in Quickshell, and forwarded only within the
profile's byte budget. Timeout, overflow and cancellation kill the entire
helper process group, including children which inherited its pipes.
"""

import argparse
import os
import selectors
import signal
import subprocess
import sys
import time


# seconds, stdout bytes; all profiles allow 8 KiB of stderr including errors.
PROFILES = {
    "lookup": (10, 1024 * 1024),
    "ocr": (120, 16 * 1024),
    "probe": (5, 1024),
    "shortcut": (5, 1024 * 1024),
}
STDERR_LIMIT = 8192
DIAGNOSTIC_RESERVE = 256
CHUNK_SIZE = 65536


def run(command, timeout, stdout_limit):
    """Return (exit code, stdout bytes, stderr bytes), never partial overflow."""
    output = [bytearray(), bytearray()]
    limits = [stdout_limit, STDERR_LIMIT - DIAGNOSTIC_RESERVE]
    cancelled = 0
    child = None
    failure = b""
    code = 126

    def cancel(signum, _frame):
        nonlocal cancelled
        # Do not raise inside Popen: cancellation must not race assignment of
        # the child handle and orphan its new process group.
        cancelled = signum

    previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    deadline = time.monotonic() + timeout
    try:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
        with selectors.DefaultSelector() as streams:
            for index, pipe in enumerate((child.stdout, child.stderr)):
                os.set_blocking(pipe.fileno(), False)
                streams.register(pipe, selectors.EVENT_READ, index)
            while True:
                if cancelled:
                    code, failure = 128 + cancelled, b"process cancelled"
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    code, failure = 124, b"process timed out"
                    break
                if not streams.get_map() and child.poll() is not None:
                    code = child.returncode if child.returncode >= 0 else 128 - child.returncode
                    break
                for key, _ in streams.select(min(remaining, 0.05)):
                    try:
                        chunk = os.read(key.fileobj.fileno(), CHUNK_SIZE)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        streams.unregister(key.fileobj)
                        continue
                    index = key.data
                    if len(output[index]) + len(chunk) > limits[index]:
                        code = 125
                        failure = b"process stdout limit exceeded" if index == 0 else b"process stderr limit exceeded"
                        break
                    output[index].extend(chunk)
                if failure:
                    break
    except OSError as exc:
        failure = ("cannot run helper: " + str(exc)).encode("utf-8", "replace")[:DIAGNOSTIC_RESERVE - 32]
    finally:
        if child is not None:
            # Also clean up descendants if the leader already exited or closed
            # its output. Only signal the private group created by this Popen.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            child.stdout.close()
            child.stderr.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if failure:
        return code, b"", b"kanji-lookup: " + failure + b"\n" + bytes(output[1])
    return code, bytes(output[0]), bytes(output[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("a helper command is required")
    timeout, stdout_limit = PROFILES[args.profile]
    code, out, err = run(args.command, timeout, stdout_limit)
    sys.stdout.buffer.write(out)
    sys.stderr.buffer.write(err)
    return code


if __name__ == "__main__":
    sys.exit(main())
