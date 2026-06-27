# coding: utf-8
"""Tests for batch checkpoint / --resume (Phase 4c, D7)."""
import json
import os

from backtest import paths
from backtest.scripts import run_batch


def test_checkpoint_path():
    cp = run_batch._checkpoint_path("test_batch_123")
    assert cp.endswith("test_batch_123_checkpoint.json")
    assert paths.BATCH_DIR in cp


def test_load_checkpoint_nonexistent():
    result = run_batch._load_checkpoint("nonexistent_batch_xyz")
    assert result == {}


def test_save_and_load_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BATCH_DIR", str(tmp_path).replace("\\", "/"))
    batch_id = "cp_test"
    entries = [
        {"batch_id": batch_id, "leaf_index": 0, "leaf_name": "a", "results_dir": "/r0"},
        {"batch_id": batch_id, "leaf_index": 1, "leaf_name": "b", "results_dir": "/r1"},
    ]
    run_batch._save_checkpoint(batch_id, entries)
    loaded = run_batch._load_checkpoint(batch_id)
    assert 0 in loaded and 1 in loaded
    assert loaded[0]["results_dir"] == "/r0"
    assert loaded[1]["leaf_name"] == "b"


def test_load_checkpoint_corrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BATCH_DIR", str(tmp_path).replace("\\", "/"))
    cp = os.path.join(str(tmp_path), "bad_checkpoint.json")
    with open(cp, "w") as f:
        f.write("not json {{{")
    result = run_batch._load_checkpoint("bad")
    assert result == {}
