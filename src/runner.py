#!/usr/bin/env python3
"""Supervise Proton with an HDR lease; expose display status and recovery."""
import argparse
import json
import os
import signal
import subprocess
import sys

from sessions import Sessions


def log(message):
    print(f'proton-ge-hdr-toggler: {message}', file=sys.stderr, flush=True)


def supervise(command, *, monitor=None, strict=False, sessions=None):
    sessions = sessions if sessions is not None else Sessions()
    lease = None
    child = None
    interrupted = None
    previous_handlers = {}

    def forward(signum, frame):
        nonlocal interrupted
        interrupted = signum
        if child is not None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous_handlers[signum] = signal.signal(signum, forward)
    try:
        try:
            lease = sessions.acquire(monitor)
            log(f'HDR session acquired for {lease[0]}')
        except Exception as exc:
            log(f'HDR activation failed: {exc}')
            if strict:
                return 1
            log('Launching command with the current display state')
        if interrupted is not None:
            return 128 + interrupted
        try:
            child = subprocess.Popen(command, start_new_session=True)
        except FileNotFoundError as exc:
            log(str(exc))
            return 127
        except OSError as exc:
            log(str(exc))
            return 126
        # A signal may arrive between the interruption check and spawning the child.
        if interrupted is not None:
            forward(interrupted, None)
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        if lease is not None:
            try:
                sessions.release(lease)
                log('HDR session released')
            except Exception as exc:
                log(f'Restoration failed: {exc}; run recovery after games exit')
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inspect monitors or recover abandoned Proton HDR sessions.')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--status', action='store_true', help='Inspect monitors without changing display configuration')
    actions.add_argument('--recover', action='store_true', help='Restore abandoned sessions, leaving live sessions alone')
    args = parser.parse_args(argv)
    try:
        if args.status:
            import mutter
            print(json.dumps(mutter.status(), indent=2))
        else:
            Sessions().recover()
            log('Recovery complete; live sessions left active')
        return 0
    except Exception as exc:
        log(str(exc))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
