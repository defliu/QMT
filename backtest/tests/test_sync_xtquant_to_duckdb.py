# coding: utf-8
"""sync_xtquant_to_duckdb 的单元/集成测试（不依赖真实 xtquant/MiniQMT）。

测试范围：
  - schema DDL 幂等
  - upsert 模式：DELETE 匹配键 + INSERT 清洗后行
  - _normalize_market_df：列校验、NaN/停牌过滤、time 单位推断
  - safety_assert：路径前缀、period、adjustment、code count
  - sync_report 字段齐全（用 fake xtdata mock 全流程）
"""
import datetime as _dt
import json
import os
import tempfile
import types

import duckdb
import pandas as pd
import pytest

from backtest.data_tools import sync_xtquant_to_duckdb as sx


def _mk_conn(tmp_path):
    p = str(tmp_path / "qmt.duckdb")
    conn = duckdb.connect(p, read_only=False)
    sx._ddl(conn)
    return conn, p


def test_ddl_idempotent(tmp_path):
    conn, _ = _mk_conn(tmp_path)
    sx._ddl(conn)
    sx._ddl(conn)
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name").fetchall()
    names = [r[0] for r in rows]
    assert "dat_day" in names
    assert "sync_log" in names
    conn.close()


def test_upsert_delete_then_insert(tmp_path):
    conn, _ = _mk_conn(tmp_path)
    d1 = _dt.date(2025, 1, 2)
    d2 = _dt.date(2025, 1, 3)
    synced = _dt.datetime(2026, 6, 14, 11, 0, 0)
    rows1 = [("000001.SZ", d1, 10.0, 11.0, 9.5, 10.5, 1000, 10500.0,
             "hfq", "xtquant", synced)]
    inserted, updated = sx._upsert_code(
        conn, "000001.SZ", rows1, "hfq", "xtquant", d1, d2)
    assert inserted == 1 and updated == 0

    rows2 = [
        ("000001.SZ", d1, 10.1, 11.1, 9.6, 10.6, 1100, 11600.0, "hfq", "xtquant", synced),
        ("000001.SZ", d2, 10.7, 11.0, 10.2, 10.9, 1200, 13000.0, "hfq", "xtquant", synced),
    ]
    inserted, updated = sx._upsert_code(
        conn, "000001.SZ", rows2, "hfq", "xtquant", d1, d2)
    assert inserted == 2
    assert updated == 1

    cnt, mn, mx = conn.execute(
        "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM dat_day"
    ).fetchone()
    assert cnt == 2 and mn == d1 and mx == d2

    open_d1 = conn.execute(
        "SELECT open FROM dat_day WHERE trade_date = ?", [d1]).fetchone()[0]
    assert abs(open_d1 - 10.1) < 1e-9
    conn.close()


def test_upsert_other_source_untouched(tmp_path):
    conn, _ = _mk_conn(tmp_path)
    d1 = _dt.date(2025, 1, 2)
    synced = _dt.datetime(2026, 6, 14, 11, 0, 0)

    rows_jin = [("000001.SZ", d1, 9.0, 9.5, 8.9, 9.2, 500, 4500.0,
                 "hfq", "jince_zhisuan", synced)]
    sx._upsert_code(conn, "000001.SZ", rows_jin, "hfq", "jince_zhisuan", d1, d1)

    rows_xtq = [("000001.SZ", d1, 10.0, 10.5, 9.9, 10.2, 600, 6120.0,
                 "hfq", "xtquant", synced)]
    sx._upsert_code(conn, "000001.SZ", rows_xtq, "hfq", "xtquant", d1, d1)

    cnt = conn.execute("SELECT COUNT(*) FROM dat_day").fetchone()[0]
    assert cnt == 2
    sources = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT source FROM dat_day").fetchall())
    assert sources == ["jince_zhisuan", "xtquant"]
    conn.close()


def test_normalize_basic_ms_time():
    df = pd.DataFrame({
        "time":   [pd.Timestamp("2025-01-02").value // 1_000_000,
                   pd.Timestamp("2025-01-03").value // 1_000_000],
        "open":   [10.0, 10.5],
        "high":   [11.0, 11.0],
        "low":    [9.5,  10.2],
        "close":  [10.5, 10.9],
        "volume": [1000, 1200],
        "amount": [10500.0, 13000.0],
    })
    rows, msg = sx._normalize_market_df(
        "000001.SZ", df, "hfq", "xtquant",
        _dt.datetime(2026, 6, 14))
    assert msg == "ok"
    assert len(rows) == 2
    assert rows[0][1] == _dt.date(2025, 1, 2)
    assert rows[0][8] == "hfq"
    assert rows[0][9] == "xtquant"


def test_normalize_yyyymmdd_int_time():
    df = pd.DataFrame({
        "time":   [20250102, 20250103],
        "open":   [10.0, 10.5],
        "high":   [11.0, 11.0],
        "low":    [9.5,  10.2],
        "close":  [10.5, 10.9],
        "volume": [1000, 1200],
        "amount": [10500.0, 13000.0],
    })
    rows, msg = sx._normalize_market_df(
        "000001.SZ", df, "hfq", "xtquant", _dt.datetime(2026, 6, 14))
    assert msg == "ok"
    assert rows[0][1] == _dt.date(2025, 1, 2)


def test_normalize_drops_suspended_day():
    df = pd.DataFrame({
        "time":   [20250102, 20250103],
        "open":   [10.0, 10.5],
        "high":   [11.0, 11.0],
        "low":    [9.5, 10.2],
        "close":  [10.5, 10.9],
        "volume": [0, 1200],     # 第一行停牌
        "amount": [0.0, 13000.0],
    })
    rows, msg = sx._normalize_market_df(
        "000001.SZ", df, "hfq", "xtquant", _dt.datetime(2026, 6, 14))
    assert msg == "ok" and len(rows) == 1
    assert rows[0][1] == _dt.date(2025, 1, 3)


def test_normalize_drops_nan_ohlc():
    df = pd.DataFrame({
        "time":   [20250102, 20250103],
        "open":   [float("nan"), 10.5],
        "high":   [11.0, 11.0],
        "low":    [9.5, 10.2],
        "close":  [10.5, 10.9],
        "volume": [1000, 1200],
        "amount": [10500.0, 13000.0],
    })
    rows, msg = sx._normalize_market_df(
        "000001.SZ", df, "hfq", "xtquant", _dt.datetime(2026, 6, 14))
    assert msg == "ok" and len(rows) == 1


def test_normalize_empty():
    rows, msg = sx._normalize_market_df(
        "000001.SZ", None, "hfq", "xtquant", _dt.datetime(2026, 6, 14))
    assert rows == [] and msg == "empty_dataframe"

    rows, msg = sx._normalize_market_df(
        "000001.SZ", pd.DataFrame(), "hfq", "xtquant", _dt.datetime(2026, 6, 14))
    assert rows == [] and msg == "empty_dataframe"


def test_normalize_missing_columns():
    df = pd.DataFrame({"time": [20250102], "open": [10.0]})
    rows, msg = sx._normalize_market_df(
        "000001.SZ", df, "hfq", "xtquant", _dt.datetime(2026, 6, 14))
    assert rows == []
    assert msg.startswith("missing_columns:")


def test_safety_assert_rejects_jince_path(tmp_path):
    args = types.SimpleNamespace(
        target="F:/金策智算/_internal/databases/duckdb/quantifydata.duckdb",
        report_dir="F:/backtest_workspace/data/sync_reports",
        period="1d", adjustment="hfq", max_codes=10)
    with pytest.raises(AssertionError):
        sx._safety_assert(args, ["000001.SZ"])


def test_safety_assert_rejects_d_drive(tmp_path):
    args = types.SimpleNamespace(
        target="D:/QMT_STRATEGIES/data/qmt.duckdb",
        report_dir="F:/backtest_workspace/data/sync_reports",
        period="1d", adjustment="hfq", max_codes=10)
    with pytest.raises(AssertionError):
        sx._safety_assert(args, ["000001.SZ"])


def test_safety_assert_rejects_period_5m():
    args = types.SimpleNamespace(
        target="F:/backtest_workspace/data/duckdb/qmt.duckdb",
        report_dir="F:/backtest_workspace/data/sync_reports",
        period="5m", adjustment="hfq", max_codes=10)
    with pytest.raises(AssertionError):
        sx._safety_assert(args, ["000001.SZ"])


def test_safety_assert_rejects_unknown_adjustment():
    args = types.SimpleNamespace(
        target="F:/backtest_workspace/data/duckdb/qmt.duckdb",
        report_dir="F:/backtest_workspace/data/sync_reports",
        period="1d", adjustment="qfq", max_codes=10)
    with pytest.raises(AssertionError):
        sx._safety_assert(args, ["000001.SZ"])


def test_safety_assert_rejects_too_many_codes():
    args = types.SimpleNamespace(
        target="F:/backtest_workspace/data/duckdb/qmt.duckdb",
        report_dir="F:/backtest_workspace/data/sync_reports",
        period="1d", adjustment="hfq", max_codes=10)
    with pytest.raises(AssertionError):
        sx._safety_assert(args, ["c%d" % i for i in range(11)])


def test_safety_assert_rejects_empty_universe():
    args = types.SimpleNamespace(
        target="F:/backtest_workspace/data/duckdb/qmt.duckdb",
        report_dir="F:/backtest_workspace/data/sync_reports",
        period="1d", adjustment="hfq", max_codes=10)
    with pytest.raises(AssertionError):
        sx._safety_assert(args, [])


def test_safety_assert_passes_under_workspace():
    args = types.SimpleNamespace(
        target="F:/backtest_workspace/data/duckdb/qmt.duckdb",
        report_dir="F:/backtest_workspace/data/sync_reports",
        period="1d", adjustment="hfq", max_codes=10)
    sx._safety_assert(args, ["000001.SZ", "600519.SH"])


def test_read_universe_filters_disabled(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text(
        "code,name,sector,enabled\n"
        "000001.SZ,A,X,true\n"
        "600519.SH,B,Y,false\n"
        "300750.SZ,C,Z,true\n",
        encoding="utf-8")
    codes = sx._read_universe(str(p))
    assert codes == ["000001.SZ", "300750.SZ"]


def test_read_universe_empty_code_skipped(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("code,enabled\n,true\n000001.SZ,true\n", encoding="utf-8")
    assert sx._read_universe(str(p)) == ["000001.SZ"]


def test_main_dry_run_aborts_when_miniqmt_down(monkeypatch, tmp_path):
    """dry_run + miniqmt down: 直接退出 1 写 failed report，不连库。"""
    universe = tmp_path / "u.csv"
    universe.write_text("code,enabled\n000001.SZ,true\n", encoding="utf-8")
    target = tmp_path / "qmt.duckdb"
    rdir = tmp_path / "reports"

    fake = types.SimpleNamespace(
        get_client=lambda: None,
        download_history_data=lambda *a, **kw: None,
        get_market_data_ex=lambda *a, **kw: {},
    )

    def _fake_probe():
        return fake, "fake-x", "not_detected"

    monkeypatch.setattr(sx, "_xtquant_probe", _fake_probe)

    rc = sx.main([
        "--scope", "B0_smoke10",
        "--universe", str(universe),
        "--start-date", "2025-01-01",
        "--end-date", "2026-06-13",
        "--target", str(target).replace("\\", "/"),
        "--report-dir", str(rdir).replace("\\", "/"),
        "--max-codes", "10",
    ])
    assert rc == 1
    files = list(rdir.glob("sync_report_*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert body["status"] == "failed"
    assert body["abort_reason"] == "miniqmt_not_running"
    assert body["sync_log_inserted"] is False


def _fake_volume_evidence_lot():
    return {
        "method": "amount_div_vol_div_close",
        "dividend_type": "none",
        "sample_codes": ["000001.SZ"],
        "sample_range": "20250101..20260101",
        "n_observations": 5,
        "mean_ratio": 99.9, "min_ratio": 99.0, "max_ratio": 100.5,
        "inferred_source_volume_unit": "lot",
        "stored_volume_unit": "share",
        "volume_multiplier": 100,
        "observations": [],
    }


def _fake_volume_evidence_unknown():
    return {
        "method": "amount_div_vol_div_close",
        "dividend_type": "none",
        "sample_codes": ["000001.SZ"],
        "sample_range": "20250101..20260101",
        "n_observations": 0,
        "mean_ratio": None, "min_ratio": None, "max_ratio": None,
        "inferred_source_volume_unit": "unknown",
        "stored_volume_unit": "share",
        "volume_multiplier": None,
        "observations": [],
    }


def test_main_with_fake_xtquant_writes_db(monkeypatch, tmp_path):
    """走完整 main 流程，fake 一只 code 的 xtquant 返回。"""
    universe = tmp_path / "u.csv"
    universe.write_text(
        "code,enabled\n000001.SZ,true\n", encoding="utf-8")
    target = tmp_path / "qmt.duckdb"
    rdir = tmp_path / "reports"

    df = pd.DataFrame({
        "time":   [20250102, 20250103, 20250106],
        "open":   [10.0, 10.5, 10.7],
        "high":   [11.0, 11.0, 11.2],
        "low":    [9.5,  10.2, 10.5],
        "close":  [10.5, 10.9, 11.0],
        "volume": [1000, 1200, 1100],
        "amount": [10500.0, 13000.0, 12100.0],
    })

    fake_xtdata = types.SimpleNamespace(
        download_history_data=lambda *a, **kw: None,
        get_market_data_ex=lambda *a, **kw: {a[1][0] if a else "000001.SZ": df},
    )

    def _fake_probe():
        return fake_xtdata, "fake-x", "running"

    monkeypatch.setattr(sx, "_xtquant_probe", _fake_probe)
    monkeypatch.setattr(
        sx, "_probe_volume_unit",
        lambda xt, s, e, probe_codes=None: _fake_volume_evidence_lot())

    rc = sx.main([
        "--scope", "B0_smoke10",
        "--universe", str(universe),
        "--start-date", "2025-01-01",
        "--end-date", "2025-01-10",
        "--target", str(target).replace("\\", "/"),
        "--report-dir", str(rdir).replace("\\", "/"),
        "--max-codes", "5",
    ])
    assert rc == 0

    conn = duckdb.connect(str(target), read_only=True)
    rows = conn.execute(
        "SELECT code, trade_date, open, source, adjustment, vol "
        "FROM dat_day ORDER BY trade_date").fetchall()
    conn.close()
    assert len(rows) == 3
    assert rows[0][0] == "000001.SZ"
    assert rows[0][3] == "xtquant"
    assert rows[0][4] == "hfq"
    assert rows[0][5] == 1000 * 100  # raw vol 1000 lots * 100 = 100000 shares

    files = list(rdir.glob("sync_report_*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert body["status"] == "ok"
    assert body["result"]["success_count"] == 1
    assert body["result"]["rows_inserted"] == 3
    assert body["target_db"]["n_rows_total"] == 3
    assert body["sync_log_inserted"] is True
    assert body["volume_unit_evidence"]["inferred_source_volume_unit"] == "lot"
    assert body["volume_unit_evidence"]["volume_multiplier"] == 100
    assert body["volume_unit_evidence"]["stored_volume_unit"] == "share"


def test_main_partial_failure(monkeypatch, tmp_path):
    """两只 code，一只成功一只 download_history_data 抛异常。"""
    universe = tmp_path / "u.csv"
    universe.write_text(
        "code,enabled\n000001.SZ,true\n600519.SH,true\n", encoding="utf-8")
    target = tmp_path / "qmt.duckdb"
    rdir = tmp_path / "reports"

    df_ok = pd.DataFrame({
        "time": [20250102], "open": [10.0], "high": [11.0],
        "low": [9.5], "close": [10.5], "volume": [1000], "amount": [10500.0],
    })

    def _dl(code, *a, **kw):
        if code == "600519.SH":
            raise RuntimeError("simulated download failure")
        return None

    fake_xtdata = types.SimpleNamespace(
        download_history_data=_dl,
        get_market_data_ex=lambda *a, **kw: {"000001.SZ": df_ok},
    )

    monkeypatch.setattr(sx, "_xtquant_probe",
                        lambda: (fake_xtdata, "fake-x", "running"))
    monkeypatch.setattr(
        sx, "_probe_volume_unit",
        lambda xt, s, e, probe_codes=None: _fake_volume_evidence_lot())

    rc = sx.main([
        "--scope", "B0_smoke10",
        "--universe", str(universe),
        "--start-date", "2025-01-01",
        "--end-date", "2025-01-10",
        "--target", str(target).replace("\\", "/"),
        "--report-dir", str(rdir).replace("\\", "/"),
        "--max-codes", "5",
    ])
    assert rc == 1

    files = list(rdir.glob("sync_report_*.json"))
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert body["status"] == "partial"
    assert body["result"]["success_count"] == 1
    assert body["result"]["failed_codes"] == ["600519.SH"]
    failed_per_code = [c for c in body["result"]["per_code"]
                       if c["status"] != "ok"]
    assert len(failed_per_code) == 1
    assert failed_per_code[0]["status"] == "download_failed"


def test_normalize_applies_volume_multiplier_lot():
    """multiplier=100 时 vol 字段应当 ×100（手→股）。"""
    df = pd.DataFrame({
        "time":   [20250102, 20250103],
        "open":   [10.0, 10.5], "high": [11.0, 11.0],
        "low":    [9.5, 10.2], "close": [10.5, 10.9],
        "volume": [1000, 1200],
        "amount": [10500.0, 13000.0],
    })
    rows, msg = sx._normalize_market_df(
        "000001.SZ", df, "hfq", "xtquant", _dt.datetime(2026, 6, 14),
        volume_multiplier=100)
    assert msg == "ok"
    # vol column index in row tuple = 6 (code, trade_date, open, high, low, close, vol, ...)
    assert rows[0][6] == 100000
    assert rows[1][6] == 120000


def test_normalize_applies_volume_multiplier_share_default():
    """不传 multiplier 默认 1（向后兼容；调用方默认值）。"""
    df = pd.DataFrame({
        "time":   [20250102],
        "open":   [10.0], "high": [11.0], "low": [9.5], "close": [10.5],
        "volume": [1000],
        "amount": [10500.0],
    })
    rows, msg = sx._normalize_market_df(
        "000001.SZ", df, "hfq", "xtquant", _dt.datetime(2026, 6, 14))
    assert msg == "ok"
    assert rows[0][6] == 1000


def test_main_aborts_on_unknown_volume_unit(monkeypatch, tmp_path):
    """volume_unit 推断失败时直接 abort，写 failed report。"""
    universe = tmp_path / "u.csv"
    universe.write_text("code,enabled\n000001.SZ,true\n", encoding="utf-8")
    target = tmp_path / "qmt.duckdb"
    rdir = tmp_path / "reports"

    fake_xtdata = types.SimpleNamespace(
        download_history_data=lambda *a, **kw: None,
        get_market_data_ex=lambda *a, **kw: {},
    )
    monkeypatch.setattr(sx, "_xtquant_probe",
                        lambda: (fake_xtdata, "fake-x", "running"))
    monkeypatch.setattr(
        sx, "_probe_volume_unit",
        lambda xt, s, e, probe_codes=None: _fake_volume_evidence_unknown())

    rc = sx.main([
        "--scope", "B0_smoke10",
        "--universe", str(universe),
        "--start-date", "2025-01-01",
        "--end-date", "2025-01-10",
        "--target", str(target).replace("\\", "/"),
        "--report-dir", str(rdir).replace("\\", "/"),
        "--max-codes", "5",
    ])
    assert rc == 1
    files = list(rdir.glob("sync_report_*.json"))
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert body["status"] == "failed"
    assert body["abort_reason"] == "volume_unit_unknown"
    assert body["sync_log_inserted"] is False
    assert body["volume_unit_evidence"]["inferred_source_volume_unit"] == "unknown"
    # 不该建库
    assert not target.exists()


def test_probe_volume_unit_classifies_lot():
    """_probe_volume_unit: ratio≈100 → lot/100。"""
    df = pd.DataFrame({
        "time":   [20250102, 20250103, 20250106, 20250107, 20250108],
        "open":   [10.0]*5, "high": [11.0]*5, "low": [9.0]*5, "close": [10.0]*5,
        "volume": [1000, 1100, 1200, 1300, 1400],
        # amount = vol_raw * close * 100  →  ratio = 100
        "amount": [1000*10*100, 1100*10*100, 1200*10*100, 1300*10*100, 1400*10*100],
    })
    fake = types.SimpleNamespace(
        download_history_data=lambda *a, **kw: None,
        get_market_data_ex=lambda *a, **kw: {kw["stock_list"][0]: df},
    )
    ev = sx._probe_volume_unit(fake, "20250101", "20250131",
                              probe_codes=["000001.SZ"])
    assert ev["inferred_source_volume_unit"] == "lot"
    assert ev["volume_multiplier"] == 100
    assert ev["n_observations"] == 5


def test_probe_volume_unit_classifies_share():
    df = pd.DataFrame({
        "time":   [20250102, 20250103],
        "open":   [10.0]*2, "high": [11.0]*2, "low": [9.0]*2, "close": [10.0]*2,
        "volume": [100000, 110000],
        # amount = vol_raw * close * 1 → ratio = 1
        "amount": [100000*10, 110000*10],
    })
    fake = types.SimpleNamespace(
        download_history_data=lambda *a, **kw: None,
        get_market_data_ex=lambda *a, **kw: {kw["stock_list"][0]: df},
    )
    ev = sx._probe_volume_unit(fake, "20250101", "20250131",
                              probe_codes=["000001.SZ"])
    assert ev["inferred_source_volume_unit"] == "share"
    assert ev["volume_multiplier"] == 1


def test_probe_volume_unit_unknown_when_empty():
    fake = types.SimpleNamespace(
        download_history_data=lambda *a, **kw: None,
        get_market_data_ex=lambda *a, **kw: {},
    )
    ev = sx._probe_volume_unit(fake, "20250101", "20250131",
                              probe_codes=["000001.SZ"])
    assert ev["inferred_source_volume_unit"] == "unknown"
    assert ev["volume_multiplier"] is None
    assert ev["n_observations"] == 0
