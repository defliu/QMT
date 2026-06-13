# coding: utf-8
"""Create F:/backtest_workspace/ on first run; redirect Python tempfile to F-cache."""
import os
import tempfile
from backtest import paths

README_BODY = (
    "本目录由 D:\\QMT_STRATEGIES\\backtest 工厂自动管理，请勿手动修改。\n"
    "results / batch_summary / sample_db / cache / logs / results_archive\n"
)

def ensure_workspace():
    os.makedirs(paths.WORKSPACE_ROOT, exist_ok=True)
    for d in paths.WORKSPACE_SUBDIRS:
        os.makedirs(d, exist_ok=True)
    if not os.path.isfile(paths.WORKSPACE_README):
        with open(paths.WORKSPACE_README, "w", encoding="utf-8") as f:
            f.write(README_BODY)

def redirect_tempdir():
    os.makedirs(paths.CACHE_DIR, exist_ok=True)
    tempfile.tempdir = paths.CACHE_DIR
    os.environ["TMPDIR"] = paths.CACHE_DIR
    os.environ["TEMP"]   = paths.CACHE_DIR
    os.environ["TMP"]    = paths.CACHE_DIR

if __name__ == "__main__":
    ensure_workspace()
    redirect_tempdir()
    print("workspace ok:", paths.WORKSPACE_ROOT)
