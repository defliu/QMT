# coding: utf-8
"""Tests for backtest.scripts.clean_results (Task 5.3 retention)."""
import datetime as _dt
import os
import time

import pytest

from backtest import paths
from backtest.scripts import clean_results


def _touch_dir(path, days_old):
    """Create dir at path and set mtime to `days_old` days in the past."""
    os.makedirs(path, exist_ok=True)
    past = time.time() - days_old * 86400
    os.utime(path, (past, past))


def test_find_archive_candidates_threshold(tmp_path):
    rdir = tmp_path / "results"
    rdir.mkdir()
    fresh = rdir / "20260610_090000_aaa_cfg"
    old = rdir / "20260401_090000_bbb_cfg"
    _touch_dir(str(fresh), days_old=2)
    _touch_dir(str(old), days_old=60)

    now = _dt.datetime.now()
    cands = clean_results.find_archive_candidates(
        now, archive_days=30, results_dir=str(rdir))
    assert str(old).replace("\\", "/") in [c.replace("\\", "/") for c in cands]
    assert str(fresh).replace("\\", "/") not in [c.replace("\\", "/") for c in cands]


def test_archive_run_moves_to_archive_dir(tmp_path):
    rdir = tmp_path / "results"; rdir.mkdir()
    adir = tmp_path / "archive"; adir.mkdir()
    src = rdir / "20260101_010101_xxx_cfg"
    src.mkdir()
    (src / "summary.json").write_text("{}", encoding="utf-8")

    dst = clean_results.archive_run(str(src), archive_dir=str(adir))
    assert os.path.isdir(dst)
    assert not os.path.exists(str(src))
    # File migrated.
    assert os.path.isfile(os.path.join(dst, "summary.json"))


def test_find_delete_candidates(tmp_path):
    adir = tmp_path / "archive"; adir.mkdir()
    fresh = adir / "fresh_run"; old = adir / "old_run"
    _touch_dir(str(fresh), days_old=10)
    _touch_dir(str(old), days_old=200)

    now = _dt.datetime.now()
    cands = clean_results.find_delete_candidates(
        now, delete_days=90, archive_dir=str(adir))
    paths_norm = [c.replace("\\", "/") for c in cands]
    assert str(old).replace("\\", "/") in paths_norm
    assert str(fresh).replace("\\", "/") not in paths_norm


def test_dry_run_does_not_move(tmp_path, monkeypatch):
    rdir = tmp_path / "results"; rdir.mkdir()
    adir = tmp_path / "archive"; adir.mkdir()
    monkeypatch.setattr(paths, "RESULTS_DIR", str(rdir).replace("\\", "/"))
    monkeypatch.setattr(paths, "ARCHIVE_DIR", str(adir).replace("\\", "/"))

    old = rdir / "20260101_010101_xxx_cfg"
    _touch_dir(str(old), days_old=60)

    rc = clean_results.main([])  # no --apply -> dry run
    assert rc == 0
    assert os.path.isdir(str(old))      # untouched
    assert os.listdir(str(adir)) == []  # no archive yet


def test_apply_archives_old_runs(tmp_path, monkeypatch):
    rdir = tmp_path / "results"; rdir.mkdir()
    adir = tmp_path / "archive"; adir.mkdir()
    monkeypatch.setattr(paths, "RESULTS_DIR", str(rdir).replace("\\", "/"))
    monkeypatch.setattr(paths, "ARCHIVE_DIR", str(adir).replace("\\", "/"))

    fresh = rdir / "fresh_cfg"
    old = rdir / "old_cfg"
    _touch_dir(str(fresh), days_old=2)
    _touch_dir(str(old), days_old=45)

    rc = clean_results.main(["--apply", "--archive-days", "30"])
    assert rc == 0
    assert os.path.isdir(str(fresh))     # kept
    assert not os.path.exists(str(old))  # moved
    archived = os.listdir(str(adir))
    assert "old_cfg" in archived


def test_apply_with_delete_archived(tmp_path, monkeypatch):
    rdir = tmp_path / "results"; rdir.mkdir()
    adir = tmp_path / "archive"; adir.mkdir()
    monkeypatch.setattr(paths, "RESULTS_DIR", str(rdir).replace("\\", "/"))
    monkeypatch.setattr(paths, "ARCHIVE_DIR", str(adir).replace("\\", "/"))

    very_old = adir / "very_old_run"
    _touch_dir(str(very_old), days_old=200)

    rc = clean_results.main(["--apply", "--delete-archived",
                             "--delete-days", "90"])
    assert rc == 0
    assert not os.path.exists(str(very_old))
