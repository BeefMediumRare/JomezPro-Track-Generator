#!/usr/bin/env python3
"""Server mode: keep generating tracks for new JomezPro coverage, unattended.

The loop is small: refresh the checkout, find new coverage videos, build a track
for each, commit the good ones, push, sleep, repeat. One video failing — a flaky
download, an odd video — is logged and skipped; it never stops the round or the
loop.

    python serve.py                 run forever, scanning every SCAN_INTERVAL_SEC
    python serve.py --once          one scan, then exit
    python serve.py --discover-only list what would be processed; no downloads, no commits

Env knobs (see src/config.py): CHANNEL_URL, COVERAGE_REGEX, SCAN_INTERVAL_SEC,
MAX_AGE_DAYS, MAX_SCAN_ENTRIES, REPO_DIR, REPO_URL, REPO_BRANCH, GIT_USER_NAME,
GIT_USER_EMAIL, and GITHUB_TOKEN for the push. DRY_RUN=1 generates tracks but
commits and pushes nothing.

Tracks are written into the checkout's tracks/JomezPro, so OUTPUT_DIR is set from
REPO_DIR here and any external OUTPUT_DIR is ignored in server mode.
"""

import os
import signal
import sys
import threading
import time

from src.config import CONFIG
from src import discover, publish
import generate

_stop = threading.Event()


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _discard(path):
    """Drop a track we decided not to commit, so the video stays unprocessed and
    a later round can retry it, and the checkout stays clean for the push."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def run_round(cfg, dry_run):
    """One scan: refresh, discover, generate, commit the keepers, push."""
    publish.ensure_repo(cfg)
    cfg.output_dir = os.path.join(cfg.repo_dir, "tracks", "JomezPro")

    log("Scanning for new coverage ...")
    new = discover.find_new(cfg, log=log)
    if not new:
        log("Nothing new.")
        return

    committed = 0
    for v in new:
        log(f"Generating {v['id']} — {v['title']}")
        try:
            result = generate.cmd_generate(v["id"])
        except Exception as e:  # one bad video must not stop the round
            log(f"  ERROR generating {v['id']}: {e}")
            continue

        if not result.has_holes:
            log(f"  skip: {result.reason or 'no useful structure'} (not committing)")
            _discard(result.path)
            continue
        if result.validated is False:
            log("  skip: track failed the extension's validation (not committing)")
            _discard(result.path)
            continue
        if dry_run:
            log(f"  DRY_RUN: would commit {os.path.basename(result.path)}")
            _discard(result.path)
            continue

        if publish.commit_track(cfg, result.path, result.title):
            log(f"  committed {os.path.basename(result.path)}")
            committed += 1
        else:
            log("  nothing to commit (already up to date)")

    if committed and not dry_run:
        publish.push(cfg)
        log(f"Pushed {committed} new track(s).")
    elif committed:
        log(f"DRY_RUN: would push {committed} track(s).")


def _handle_signal(signum, frame):
    log(f"Got signal {signum}, finishing up and exiting.")
    _stop.set()


def main(argv):
    args = argv[1:]
    once = "--once" in args
    discover_only = "--discover-only" in args
    dry_run = "--dry-run" in args or os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")
    cfg = CONFIG

    if discover_only:
        # No checkout, no downloads — just report against the configured tracks dir.
        new = discover.find_new(cfg, log=log)
        for v in new:
            log(f"  would process: {v['id']} — {v['title']}")
        return 0

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if dry_run:
        log("DRY_RUN is on: generating tracks but committing/pushing nothing.")

    while not _stop.is_set():
        try:
            run_round(cfg, dry_run)
        except Exception as e:
            log(f"Round failed: {e}")
        if once or _stop.is_set():
            break
        log(f"Sleeping {cfg.scan_interval_sec}s until the next scan.")
        _stop.wait(cfg.scan_interval_sec)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
