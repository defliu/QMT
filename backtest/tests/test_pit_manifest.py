# coding: utf-8
"""MS-H · P2 验证：PIT manifest 路径 (universe_by_date) 接入 v0.4。

MS-D commit 32238be 把 stash 里的 _load_pit_manifest + universe_by_date 合并进来，
但零测试覆盖。本测试补：
  1. _load_pit_manifest 解析正确
  2. run_backtest(universe_by_date=...) 每天 evaluate_day 收到的 universe
     是对应 as_of 快照
"""
import json
import os
import tempfile

import pandas as pd
import pytest

from backtest.engine.daily_engine import run_backtest
from backtest.scripts.run_backtest import _load_pit_manifest


# 与 test_daily_engine 同款 FakeReader
class FakeReader(object):
    def __init__(self, market, calendar, db_path="fake.duckdb",
                 db_mtime="2026-06-14T00:00:00", wal=False):
        self.market = market
        self.calendar = calendar
        self.db_path = db_path
        self._db_mtime = db_mtime
        self.wal_detected = wal
        self.wal_warning_message = ""

    def coverage(self, codes=None, start_date=None, end_date=None):
        cov = {
            "min_date":           self.calendar[0],
            "max_date":           self.calendar[-1],
            "n_codes":            len(self.market),
            "n_rows_after_dedup": sum(len(df) for df in self.market.values()),
            "dedup_count":        0,
            "db_mtime":           self._db_mtime,
        }
        if codes is not None:
            present = [c for c in codes if c in self.market]
            missing = [c for c in codes if c not in self.market]
            cov["universe_coverage"] = {
                "universe_size":   len(codes),
                "codes_with_data": len(present),
                "codes_missing":   missing,
                "missing_count":   len(missing),
            }
        return cov

    def trading_calendar(self, start_date, end_date):
        return [d for d in self.calendar if start_date <= d <= end_date]

    def load_window(self, codes, start_date, end_date):
        out = {}
        for code in codes:
            if code not in self.market:
                continue
            df = self.market[code]
            sub = df[(df["date"].astype(str) >= start_date)
                     & (df["date"].astype(str) <= end_date)]
            if len(sub) > 0:
                out[code] = sub.reset_index(drop=True)
        return out

    def close(self):
        pass


def _build_market(codes, n_days=15, start="2025-09-02"):
    base = pd.date_range(start=start, periods=n_days, freq="B").strftime("%Y-%m-%d").tolist()
    market = {}
    for code in codes:
        df = pd.DataFrame({
            "date":   base,
            "open":   [10.0] * n_days,
            "high":   [10.5] * n_days,
            "low":    [9.5]  * n_days,
            "close":  [10.0] * n_days,
            "vol":    [1000] * n_days,
            "amount": [10000.0] * n_days,
        })
        market[code] = df
    return market, base


def test_load_pit_manifest_parses_index_and_csvs():
    """_load_pit_manifest 能解析 index.json + 多个 as_of csv。"""
    tmp = tempfile.mkdtemp()
    # 准备 2 个 as_of snapshot
    csv1 = os.path.join(tmp, "snap_20250901.csv")
    csv2 = os.path.join(tmp, "snap_20250915.csv")
    with open(csv1, "w", encoding="utf-8-sig") as f:
        f.write("code\n000001.SZ\n000002.SZ\n")
    with open(csv2, "w", encoding="utf-8-sig") as f:
        f.write("code\n000001.SZ\n000003.SZ\n")
    index = {
        "snapshots": [
            {"as_of": "2025-09-01", "n_chosen": 2, "csv": csv1},
            {"as_of": "2025-09-15", "n_chosen": 2, "csv": csv2},
        ]
    }
    index_path = os.path.join(tmp, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f)

    universe_by_date, union = _load_pit_manifest(index_path)
    assert set(universe_by_date.keys()) == {"2025-09-01", "2025-09-15"}
    assert universe_by_date["2025-09-01"] == ["000001.SZ", "000002.SZ"]
    assert universe_by_date["2025-09-15"] == ["000001.SZ", "000003.SZ"]
    assert union == ["000001.SZ", "000002.SZ", "000003.SZ"]


def test_load_pit_manifest_skips_zero_chosen():
    """n_chosen=0 的 snapshot 必须跳过。"""
    tmp = tempfile.mkdtemp()
    csv1 = os.path.join(tmp, "snap_a.csv")
    with open(csv1, "w", encoding="utf-8-sig") as f:
        f.write("code\n000001.SZ\n")
    index = {
        "snapshots": [
            {"as_of": "2025-09-01", "n_chosen": 0, "csv": csv1},
            {"as_of": "2025-09-15", "n_chosen": 1, "csv": csv1},
        ]
    }
    index_path = os.path.join(tmp, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f)

    universe_by_date, _ = _load_pit_manifest(index_path)
    assert "2025-09-01" not in universe_by_date
    assert "2025-09-15" in universe_by_date


_EXEC = {"price": "next_open", "slippage": 0.001,
         "commission_rate": 0.00025, "tax_rate": 0.0001}


def test_pit_universe_by_date_forward_fills():
    """run_backtest(universe_by_date=...) 每天 evaluate 收到的 universe 是
    截至当天最近一个 as_of 的快照（forward-fill）。"""
    codes = ["AAA", "BBB", "CCC"]
    market, dates = _build_market(codes, n_days=15)
    reader = FakeReader(market, dates)

    # PIT 字典：dates[0] 起 [AAA,BBB]；dates[7] 切换为 [BBB,CCC]
    universe_by_date = {
        dates[0]: ["AAA", "BBB"],
        dates[7]: ["BBB", "CCC"],
    }

    # spy 拦截 evaluate_day，记录每天收到的 universe
    seen = []
    from backtest.strategies import _REGISTRY
    name = "production/ima_uptrend_v31"
    real = _REGISTRY[name]

    def spy(current_date, market_window, universe=None, **kw):
        seen.append((str(current_date), list(universe or [])))
        return real(current_date=current_date, market_window=market_window,
                    universe=universe, **kw)

    _REGISTRY[name] = spy
    try:
        run_backtest(
            reader=reader, universe=codes,
            start_date=dates[0], end_date=dates[-1],
            strategy_config={"max_positions": 5}, execution_cfg=_EXEC,
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
            universe_by_date=universe_by_date,
        )
    finally:
        _REGISTRY[name] = real

    # 检查：dates[0..6] 应都看到 [AAA, BBB]，dates[7..13] 应都看到 [BBB, CCC]
    # （注意 evaluate_day 在最后一天不调，所以 seen 长度 = n_days - 1 = 14）
    early = [u for d, u in seen if d <= dates[6]]
    late  = [u for d, u in seen if d >= dates[7] and d < dates[-1]]
    assert early, "dates[0..6] 应有 evaluate 调用"
    assert late,  "dates[7..13] 应有 evaluate 调用"
    for u in early:
        assert u == ["AAA", "BBB"], "early universe 应为 [AAA, BBB], got " + repr(u)
    for u in late:
        assert u == ["BBB", "CCC"], "late universe 应为 [BBB, CCC], got " + repr(u)


def test_pit_first_day_before_first_snapshot_is_empty():
    """如果第一个交易日早于第一个 as_of，evaluate 应收到 [] 而非 codes。"""
    codes = ["AAA", "BBB"]
    market, dates = _build_market(codes, n_days=10)
    reader = FakeReader(market, dates)

    # snapshot 在第 5 天才有
    universe_by_date = {dates[4]: ["AAA"]}

    seen = []
    from backtest.strategies import _REGISTRY
    name = "production/ima_uptrend_v31"
    real = _REGISTRY[name]

    def spy(current_date, market_window, universe=None, **kw):
        seen.append((str(current_date), list(universe or [])))
        return real(current_date=current_date, market_window=market_window,
                    universe=universe, **kw)

    _REGISTRY[name] = spy
    try:
        run_backtest(
            reader=reader, universe=codes,
            start_date=dates[0], end_date=dates[-1],
            strategy_config={"max_positions": 5}, execution_cfg=_EXEC,
            initial_cash=1_000_000.0, universe_hash="u", config_hash="c",
            universe_by_date=universe_by_date,
        )
    finally:
        _REGISTRY[name] = real

    # dates[0..3] 应都是空 universe
    pre = [u for d, u in seen if d < dates[4]]
    post = [u for d, u in seen if d >= dates[4] and d < dates[-1]]
    assert pre, "dates[0..3] 应有 evaluate 调用"
    for u in pre:
        assert u == [], "pre-snapshot universe 应为空, got " + repr(u)
    for u in post:
        assert u == ["AAA"], "post-snapshot universe 应为 [AAA], got " + repr(u)
