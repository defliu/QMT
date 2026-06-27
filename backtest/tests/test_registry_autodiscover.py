# coding: utf-8
"""Phase 3 验证：Strategy Registry 自动发现。

验证 auto-discover 机制在删除手写 import 后仍然正确发现所有策略。
"""
import importlib
import os
import shutil
import sys

import pytest


def _import_fresh():
    """Import backtest.strategies fresh, clearing cached submodules."""
    to_remove = [k for k in sys.modules if k.startswith("backtest.strategies")]
    for k in to_remove:
        del sys.modules[k]
    mod = importlib.import_module("backtest.strategies")
    return mod


def test_autodiscover_finds_all_three_strategies():
    """删手写 import 后，list_strategies() 输出与迁移前一致（3 策略）。"""
    mod = _import_fresh()
    names = mod.list_strategies()
    assert "production/ima_uptrend_v31" in names
    assert "research/example_ma_cross" in names
    assert "research/huang_zhongjun_combo" in names
    assert len(names) == 3


def test_autodiscover_finds_new_strategy_dir():
    """新加一个空策略目录（临时 fixture）能被自动发现。"""
    research_dir = os.path.join(
        os.path.dirname(__file__), "..", "strategies", "research"
    )
    tmp_name = "_test_autodiscover_temp"
    tmp_dir = os.path.join(research_dir, tmp_name)
    try:
        # Create a minimal strategy package
        os.makedirs(tmp_dir)
        with open(os.path.join(tmp_dir, "__init__.py"), "w") as f:
            f.write("")
        with open(os.path.join(tmp_dir, "strategy.py"), "w") as f:
            f.write(
                "# coding: utf-8\n"
                "from backtest.strategies import register_strategy\n\n"
                "@register_strategy('research/_test_autodiscover_temp')\n"
                "def evaluate_day(*args, **kwargs):\n"
                "    pass\n"
            )
        # Fresh import to trigger autodiscover with new dir
        mod = _import_fresh()
        names = mod.list_strategies()
        assert "research/_test_autodiscover_temp" in names
    finally:
        # Cleanup
        if os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir)
        # Fresh import to restore clean state
        _import_fresh()
