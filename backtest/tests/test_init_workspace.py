import os
import shutil
import tempfile
from backtest import paths
from backtest.scripts import init_workspace

def test_init_workspace_creates_all_subdirs(tmp_path, monkeypatch):
    fake_root = str(tmp_path / "wsp")
    monkeypatch.setattr(paths, "WORKSPACE_ROOT", fake_root)
    monkeypatch.setattr(paths, "RESULTS_DIR",   fake_root + "/results")
    monkeypatch.setattr(paths, "ARCHIVE_DIR",   fake_root + "/results_archive")
    monkeypatch.setattr(paths, "BATCH_DIR",     fake_root + "/batch_summary")
    monkeypatch.setattr(paths, "SAMPLE_DB_DIR", fake_root + "/sample_db")
    monkeypatch.setattr(paths, "CACHE_DIR",     fake_root + "/cache")
    monkeypatch.setattr(paths, "LOGS_DIR",      fake_root + "/logs")
    monkeypatch.setattr(paths, "WORKSPACE_README", fake_root + "/README.txt")
    monkeypatch.setattr(paths, "WORKSPACE_SUBDIRS",
        [fake_root + "/results", fake_root + "/results_archive",
         fake_root + "/batch_summary", fake_root + "/sample_db",
         fake_root + "/cache", fake_root + "/logs"])

    init_workspace.ensure_workspace()

    for d in paths.WORKSPACE_SUBDIRS:
        assert os.path.isdir(d)
    assert os.path.isfile(paths.WORKSPACE_README)
    txt = open(paths.WORKSPACE_README, encoding="utf-8").read()
    assert "backtest" in txt and "请勿手动修改" in txt

def test_tempdir_redirected_into_cache(tmp_path, monkeypatch):
    fake_cache = str(tmp_path / "cache")
    os.makedirs(fake_cache, exist_ok=True)
    monkeypatch.setattr(paths, "CACHE_DIR", fake_cache)
    init_workspace.redirect_tempdir()
    import tempfile as _tmp
    assert _tmp.gettempdir().replace("\\", "/").startswith(fake_cache.replace("\\", "/"))
