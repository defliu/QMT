# coding: utf-8
"""Milestone C 验证：migrate_yaml_v03_to_v04 一次性脚本。

SPEC: specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md §5.2
"""
import os
import tempfile

import pytest

from backtest.scripts.migrate_yaml_v03_to_v04 import migrate


_V03_BASELINE = """# coding: utf-8
# backtest factory v0.2 baseline config

backtest:
  name: baseline
  start_date: "2025-09-02"
  end_date:   "2025-09-26"
  initial_cash: 1000000.0
  benchmark_code: null

data:
  source: jince_zhisuan
  path:   "E:/somewhere/db.duckdb"
  adjustment: hfq

strategy:
  max_positions: 5
  min_score: 60.0
"""


def _tmp(content):
    fd, path = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_migrate_injects_strategy_name_and_trading_model():
    src = _tmp(_V03_BASELINE)
    dst = src + ".v04"
    try:
        migrate(src, dst)
        with open(dst, "r", encoding="utf-8") as f:
            out = f.read()
        assert "strategy_name: production/ima_uptrend_v31" in out
        assert "trading_model: next_open" in out
        assert "max_positions: 5" in out
        assert "min_score: 60.0" in out
    finally:
        os.unlink(src)
        if os.path.exists(dst):
            os.unlink(dst)


def test_migrate_refuses_already_v04():
    src = _tmp(
        "strategy_name: production/ima_uptrend_v31\n"
        "trading_model: next_open\n"
        "backtest: { name: x }\n"
    )
    dst = src + ".v04"
    try:
        with pytest.raises(SystemExit):
            migrate(src, dst)
    finally:
        os.unlink(src)
        if os.path.exists(dst):
            os.unlink(dst)
