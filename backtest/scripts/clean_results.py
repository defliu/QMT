# coding: utf-8
"""clean_results.py — results retention helper (Task 5.3, SPEC §2.6).

ISOLATION CONTRACT (硬约束 #6):
  - This script is STAND-ALONE. It MUST NOT be imported by any reader / engine /
    run_backtest / run_batch module. It only runs via
    `py -3.10 -m backtest.scripts.clean_results`.
  - Verified by `tests/test_clean_results_isolation.py`.

Behavior:
  * Default = dry-run: list what *would* happen, do nothing.
  * --apply                : actually move runs older than --archive-days (default 30)
                             from RESULTS_DIR to ARCHIVE_DIR.
  * --apply --delete-archived
                           : also delete archived runs older than --delete-days (90).

Boundaries (night-shift §四):
  * Reads/writes only F:/backtest_workspace/{results, results_archive}.
  * Never touches D:/C:/E:\\金策智算\\.
"""
import argparse
import datetime as _dt
import logging
import os
import shutil
import sys

from backtest import paths

log = logging.getLogger("clean_results")


def _list_run_dirs(parent):
    """Return list of (full_path, mtime_dt) for immediate subdirs of parent."""
    if not os.path.isdir(parent):
        return []
    out = []
    for name in os.listdir(parent):
        full = os.path.join(parent, name).replace("\\", "/")
        if not os.path.isdir(full):
            continue
        try:
            mt = os.path.getmtime(full)
        except OSError:
            continue
        out.append((full, _dt.datetime.fromtimestamp(mt)))
    return out


def find_archive_candidates(now, archive_days, results_dir=None):
    """Return list of run dirs in RESULTS_DIR whose mtime is older than archive_days."""
    rdir = results_dir if results_dir is not None else paths.RESULTS_DIR
    cutoff = now - _dt.timedelta(days=archive_days)
    return [p for (p, mt) in _list_run_dirs(rdir) if mt < cutoff]


def find_delete_candidates(now, delete_days, archive_dir=None):
    """Return list of archived run dirs older than delete_days."""
    adir = archive_dir if archive_dir is not None else paths.ARCHIVE_DIR
    cutoff = now - _dt.timedelta(days=delete_days)
    return [p for (p, mt) in _list_run_dirs(adir) if mt < cutoff]


def archive_run(src_path, archive_dir=None):
    """Move src_path to archive_dir/<basename>. Returns destination path."""
    adir = archive_dir if archive_dir is not None else paths.ARCHIVE_DIR
    os.makedirs(adir, exist_ok=True)
    name = os.path.basename(src_path.rstrip("/"))
    dst = os.path.join(adir, name).replace("\\", "/")
    if os.path.exists(dst):
        # collision: append timestamp suffix to keep both
        suffix = _dt.datetime.now().strftime("_%Y%m%d%H%M%S")
        dst = dst + suffix
    shutil.move(src_path, dst)
    return dst


def delete_archived(path):
    """Recursively delete an archived run dir."""
    shutil.rmtree(path)


def main(argv=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Backtest results retention helper")
    parser.add_argument("--apply", action="store_true",
                        help="actually move/delete; otherwise dry-run")
    parser.add_argument("--delete-archived", action="store_true",
                        help="when --apply, also delete archived runs older than --delete-days")
    parser.add_argument("--archive-days", type=int, default=30,
                        help="archive runs in RESULTS_DIR older than N days (default 30)")
    parser.add_argument("--delete-days", type=int, default=90,
                        help="delete archived runs older than N days (default 90)")
    args = parser.parse_args(argv)

    now = _dt.datetime.now()
    archive_targets = find_archive_candidates(now, args.archive_days)
    delete_targets = (find_delete_candidates(now, args.delete_days)
                      if args.delete_archived else [])

    log.info("archive candidates (>%d days): %d", args.archive_days, len(archive_targets))
    for p in archive_targets:
        log.info("  archive: %s", p)
    log.info("delete candidates (>%d days, archived): %d", args.delete_days, len(delete_targets))
    for p in delete_targets:
        log.info("  delete:  %s", p)

    if not args.apply:
        log.info("dry-run: no changes made (use --apply to execute)")
        return 0

    moved = 0
    for p in archive_targets:
        try:
            archive_run(p)
            moved += 1
        except OSError as e:
            log.error("archive failed for %s: %s", p, e)

    deleted = 0
    if args.delete_archived:
        for p in delete_targets:
            try:
                delete_archived(p)
                deleted += 1
            except OSError as e:
                log.error("delete failed for %s: %s", p, e)

    log.info("done: archived=%d deleted=%d", moved, deleted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
