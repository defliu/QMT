# coding: utf-8
"""Tests for backtest.engine.report writers."""
import csv
import json
import os
import shutil

import pytest

from backtest import paths
from backtest.engine import report


def _build_result(run_id="20260614_010101_aaaaaa", short_sample=True,
                  with_trades=True, with_wal=True, dedup=12,
                  benchmark=False):
    summary = {
        "summary_schema_version": "0.2",
        "run_id":                 run_id,
        "run_started_at":         "2026-06-14T01:01:01+08:00",
        "runtime_seconds":        1.234,
        "config_name":            "test_cfg",
        "results_dir":            "",
        "strategy_core_version":  "0.2.0",
        "config_hash":            "c" * 64,
        "data_hash":              "d" * 64,
        "universe_hash":          "u" * 64,
        "data_source":            "jince_zhisuan",
        "data_path":              "F:/sample.duckdb",
        "data_mtime":             "2026-06-13T23:59:00",
        "data_adjustment":        "hfq",
        "data_coverage_actual": {
            "min_date":           "2025-09-01",
            "max_date":           "2025-09-30",
            "n_codes":            10,
            "n_rows_after_dedup": 200,
            "dedup_count":        dedup,
            "universe_coverage": {
                "universe_size":   3, "codes_with_data": 3,
                "codes_missing":   [], "missing_count": 0,
            },
        },
        "data_dedup_applied":           True,
        "data_concurrent_sync_warning": with_wal,
        "data_wal_detected":            with_wal,
        "data_wal_warning_message":     "wal detected" if with_wal else "",
        "benchmark_code":      None if not benchmark else "000300.SH",
        "benchmark_available": benchmark,
        "benchmark_note":      "DuckDB 当前无指数数据，benchmark 已禁用" if not benchmark else "",
        "sector_heat_available": False,
        "sector_heat_mode":      "zero",
        "sector_heat_warning":   "historical sector heat unavailable; sector score set to 0",
        "sample_period_warning": {
            "is_short_sample":  bool(short_sample),
            "requested_range":  ["2025-09-01", "2025-09-30"],
            "actual_range":     ["2025-09-01", "2025-09-30"],
            "trading_days":     21,
            "warning":          u"样本期约 1.0 个月，仅用于 MVP 管线验证，不可作为策略最终定论",
        } if short_sample else {
            "is_short_sample": False, "requested_range": ["", ""],
            "actual_range": ["", ""], "trading_days": 252, "warning": "",
        },
        "execution":   {"price": "next_open", "slippage": 0.001,
                        "commission_rate": 0.00025, "tax_rate": 0.0001},
        "performance": {"total_return": 0.05, "annual_return": 0.6,
                        "max_drawdown": -0.04, "sharpe": 1.2, "calmar": 15.0,
                        "win_rate": 0.6, "n_trades": 4 if with_trades else 0,
                        "n_buy": 2 if with_trades else 0,
                        "n_sell": 2 if with_trades else 0,
                        "avg_holding_days": 5.0,
                        "excess_return": None, "information_ratio": None,
                        "tracking_error": None},
        "portfolio_end": {"total_asset": 1_050_000.0, "cash": 100000.0,
                          "market_value": 950000.0, "n_positions": 1},
        "diagnostics_aggregate": {
            "warnings_unique": [],
            "candidate_total_avg_per_day": 2.0,
            "candidate_passed_avg_per_day": 1.5,
            "unfilled_order_count": 0,
            "strategy_specific": {
                "ima_uptrend_v31": {
                    "filter_counts_avg_per_day": {"blocked_min_score": 1.0},
                    "trigger_counts_total": {"early_stop": 0, "early_kick": 0,
                                             "stop_loss": 1, "score_drop": 0,
                                             "replace": 0, "warning": 0, "confirm": 0},
                },
            },
        },
    }

    trades = [
        {"run_id": run_id, "date": "2025-09-02", "code": "000001.SZ",
         "side": "buy", "volume": 1000, "price": 12.5125, "amount": 12512.5,
         "slippage_amt": 12.5, "commission": 3.13, "tax": 0.0,
         "reason": "top_candidate", "layer": "", "model": "next_open"},
        {"run_id": run_id, "date": "2025-09-10", "code": "000001.SZ",
         "side": "sell", "volume": 1000, "price": 13.4865, "amount": 13486.5,
         "slippage_amt": 13.5, "commission": 3.37, "tax": 1.35,
         "reason": "stop_loss", "layer": "bottom_line", "model": "next_open"},
    ] if with_trades else []

    equity = [
        {"run_id": run_id, "date": "2025-09-01", "total_asset": 1_000_000.0,
         "cash": 1_000_000.0, "market_value": 0.0, "daily_return": 0.0,
         "benchmark_close": "", "benchmark_return": ""},
        {"run_id": run_id, "date": "2025-09-02", "total_asset": 1_005_000.0,
         "cash": 487487.5, "market_value": 517512.5, "daily_return": 0.005,
         "benchmark_close": "", "benchmark_return": ""},
    ]

    positions = [
        {"run_id": run_id, "date": "2025-09-02", "code": "000001.SZ",
         "volume": 1000, "available_volume": 0, "cost_price": 12.51,
         "last_price": 12.65, "unrealized_pnl": 140.0, "holding_days": 1},
    ]

    logs = ["[INFO]  2025-09-01 evaluate_day candidates=3 passed=2 sell=0 buy=2",
            "[INFO]  2025-09-02 fill buy 000001.SZ vol=1000 price=12.5125 amt=12512.50",
            "[ERROR] 2025-09-10 unfilled_order code=000002.SZ reason=suspended"]

    return {"summary": summary, "trades": trades, "equity_rows": equity,
            "positions_rows": positions, "logs": logs,
            "trading_calendar": ["2025-09-01", "2025-09-02"]}


@pytest.fixture
def isolated_results_dir(tmp_path, monkeypatch):
    """Redirect paths.RESULTS_DIR to a temp dir (still under F:/ if tmp_path is on F:)."""
    target = tmp_path / "results"
    target.mkdir()
    monkeypatch.setattr(paths, "RESULTS_DIR", str(target).replace("\\", "/"))
    return str(target).replace("\\", "/")


def test_make_results_dir_creates_under_RESULTS_DIR(isolated_results_dir):
    rd = report.make_results_dir("RUN1", "cfg")
    assert os.path.isdir(rd)
    assert rd.startswith(isolated_results_dir)
    assert rd.endswith("/RUN1_cfg")


def test_write_trades_csv_columns_and_order(isolated_results_dir):
    result = _build_result()
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_trades_csv(rd, result["trades"])
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["run_id", "date", "code", "side", "volume", "price",
                       "amount", "slippage_amt", "commission", "tax",
                       "reason", "layer", "model"]
    assert len(rows) == 1 + len(result["trades"])


def test_write_equity_csv_columns(isolated_results_dir):
    result = _build_result()
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_equity_curve_csv(rd, result["equity_rows"])
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["run_id", "date", "total_asset", "cash", "market_value",
                       "daily_return", "benchmark_close", "benchmark_return"]


def test_write_positions_csv_columns(isolated_results_dir):
    result = _build_result()
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_positions_csv(rd, result["positions_rows"])
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["run_id", "date", "code", "volume", "available_volume",
                       "cost_price", "last_price", "unrealized_pnl",
                       "holding_days"]


def test_write_logs_txt_warn_block_order(isolated_results_dir):
    result = _build_result(short_sample=True, with_wal=True, dedup=42)
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_logs_txt(rd, result["summary"], result["logs"])
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
    # Order: SHORT_SAMPLE_PERIOD -> BENCHMARK_DISABLED -> DATA_DEDUP_APPLIED
    #        -> SECTOR_HEAT_MODE_ZERO -> DATA_WAL_DETECTED
    i_short = content.index("SHORT_SAMPLE_PERIOD")
    i_bench = content.index("BENCHMARK_DISABLED")
    i_dedup = content.index("DATA_DEDUP_APPLIED")
    i_sector = content.index("SECTOR_HEAT_MODE_ZERO")
    i_wal = content.index("DATA_WAL_DETECTED")
    assert i_short < i_bench < i_dedup < i_sector < i_wal


def test_write_logs_txt_omits_wal_when_not_detected(isolated_results_dir):
    result = _build_result(with_wal=False)
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_logs_txt(rd, result["summary"], result["logs"])
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
    assert "DATA_WAL_DETECTED" not in content


def test_write_logs_txt_omits_dedup_when_zero(isolated_results_dir):
    result = _build_result(dedup=0)
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_logs_txt(rd, result["summary"], result["logs"])
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()
    assert "DATA_DEDUP_APPLIED" not in content


def test_write_report_md_has_sample_period_banner(isolated_results_dir):
    result = _build_result(short_sample=True)
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_report_md(rd, result["summary"], result["equity_rows"],
                               result["positions_rows"], result["logs"])
    with open(p, "r", encoding="utf-8") as f:
        text = f.read()
    assert "样本期警告" in text
    assert "MVP" in text


def test_write_report_md_omits_banner_when_not_short(isolated_results_dir):
    result = _build_result(short_sample=False)
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_report_md(rd, result["summary"], result["equity_rows"],
                               result["positions_rows"], result["logs"])
    with open(p, "r", encoding="utf-8") as f:
        text = f.read()
    assert "样本期警告" not in text


def test_write_summary_json_round_trip(isolated_results_dir):
    result = _build_result()
    rd = report.make_results_dir(result["summary"]["run_id"], "cfg")
    p = report.write_summary_json(rd, result["summary"])
    with open(p, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["summary_schema_version"] == "0.2"
    assert loaded["run_id"] == result["summary"]["run_id"]
    assert loaded["performance"]["total_return"] == 0.05
    assert loaded["results_dir"].endswith("_cfg")


def test_write_all_produces_six_files(isolated_results_dir):
    result = _build_result()
    rd = report.write_all(result, config_name="cfg")
    files = sorted(os.listdir(rd))
    assert files == ["equity_curve.csv", "logs.txt", "positions.csv",
                     "report.md", "summary.json", "trades.csv"]
    # results_dir gets stamped into summary
    assert result["summary"]["results_dir"].endswith("_cfg")
