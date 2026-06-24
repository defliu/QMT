# coding: utf-8
"""MS-J: 验证 _load_benchmark_series 注入 lead-in 数据。

测试用最小 mock benchmark_reader, 不依赖真 DuckDB。
"""
import os
import datetime as _dt
import pytest


# ---- 复用 daily_engine.py 内部函数 ----
from backtest.engine import daily_engine as _de


class _MockBenchReader(object):
    """模拟 BenchmarkIndexReader。"""
    def __init__(self, db_path):
        self.db_path = db_path
        # 提供 2025-04-01 到 2025-12-31 的日 close (252 条左右,
        # 含 lead-in 范围 2025-05-05 ~ 2025-09-01)。
        rows = []
        d = _dt.date(2025, 4, 1)
        end = _dt.date(2025, 12, 31)
        close = 3500.0
        while d <= end:
            if d.weekday() < 5:  # 简化: 跳过周末
                rows.append((d.strftime("%Y-%m-%d"), close))
                close += 1.5
            d += _dt.timedelta(days=1)
        self._rows = rows

    def load_series(self, code, start_date, end_date):
        return [(d, c) for (d, c) in self._rows
                if start_date <= d <= end_date]

    def close(self):
        pass


def _fake_isfile(p):
    return True


def test_lead_in_120_natural_days_loaded(monkeypatch):
    """calendar=2025-09-02..2025-09-05 时, closes 必须含 2025-05-05 起的 lead-in。"""
    monkeypatch.setattr(os.path, "isfile", _fake_isfile)
    import backtest.data_tools.benchmark_reader as _br_mod
    monkeypatch.setattr(_br_mod, "BenchmarkIndexReader", _MockBenchReader)

    calendar = ["2025-09-02", "2025-09-03", "2025-09-04", "2025-09-05"]
    closes, note = _de._load_benchmark_series(
        "000001.SH", calendar, "fake.duckdb")

    assert closes is not None, "lead-in 修复后应该返回 dict, note=%r" % note
    # lead-in 范围应能覆盖 calendar[0] - 120 自然日 ≈ 2025-05-05
    assert "2025-05-05" in closes or "2025-05-06" in closes, \
        "lead-in 未覆盖到 2025-05-05 (calendar[0]=%s, _BENCHMARK_LEAD_IN_DAYS=%d)" % (
            calendar[0], _de._BENCHMARK_LEAD_IN_DAYS)
    # calendar 内 key 仍存在
    for d in calendar:
        assert d in closes, "calendar 日 %s 必须在 closes 中" % d
    # 新增 key 不破坏旧行为: closes 数量 > calendar 长度
    assert len(closes) > len(calendar), \
        "lead-in 后 closes 应严格多于 calendar (len=%d vs %d)" % (
            len(closes), len(calendar))


def test_lead_in_preserves_calendar_alignment(monkeypatch):
    """回归: calendar 内每一天仍能通过 closes[d] 查到值, 与原行为一致。"""
    monkeypatch.setattr(os.path, "isfile", _fake_isfile)
    import backtest.data_tools.benchmark_reader as _br_mod
    monkeypatch.setattr(_br_mod, "BenchmarkIndexReader", _MockBenchReader)

    calendar = ["2025-09-02", "2025-09-03", "2025-09-04"]
    closes, _ = _de._load_benchmark_series(
        "000001.SH", calendar, "fake.duckdb")

    for d in calendar:
        v = closes.get(d)
        assert v is not None and v > 0, \
            "calendar 日 %s 必须有 close 值, 实际=%r" % (d, v)


def test_lead_in_constant_value():
    """_BENCHMARK_LEAD_IN_DAYS 必须 >= 120 (黄氏 MA120 需求)。"""
    assert _de._BENCHMARK_LEAD_IN_DAYS >= 120
