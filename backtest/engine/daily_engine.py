# coding: utf-8
"""DailyBacktestEngine -- main loop wiring reader -> strategy_core ->
execution -> portfolio -> metrics.

Frozen contracts:
  - 03_interface_freeze.md: evaluate_day signature + decision shape.
  - 04_output_schema_freeze.md: trades/equity/positions row shapes,
    diagnostics_aggregate keys.

Trading model: next_open (SPEC v0.2 §2.2 default).
  Signal at close of T -> fill at open of T+1. Implementation:
    for each trading day T in calendar:
      1. advance_holding_days() (T+1 unfreeze of yesterday's buys)
      2. apply pending fills (yesterday's decision sells, then buys)
      3. mark_to_market(close of T)
      4. snapshot equity/positions rows for T
      5. evaluate_day on window <= T -> store as next-day pending decision

Constraints (CC night-shift authorization):
  - Engine writes ONLY in-memory result struct; file IO is Phase 4 report.py.
  - No xtquant / passorder / QMT imports.
  - DuckDB reader passed in by caller (or constructed internally with
    JINCE_DB_PATH); we never open it for write.
"""
import os
import datetime as _dt
import hashlib
import logging

from backtest.strategy_core.interface import evaluate_day
from backtest.engine.execution import fill_buy, fill_sell
from backtest.engine.portfolio import Portfolio
from backtest.engine.metrics import compute_metrics

log = logging.getLogger(__name__)

_STRATEGY_CORE_VERSION = "0.2.0"
_SUMMARY_SCHEMA_VERSION = "0.2"


def _make_run_id(now=None):
    """YYYYMMDD_HHMMSS_<short_hash> per SPEC §2.6.1."""
    t = now or _dt.datetime.now()
    stamp = t.strftime("%Y%m%d_%H%M%S")
    h = hashlib.sha256(stamp.encode("utf-8")).hexdigest()[:6]
    return stamp + "_" + h


def _slice_window_up_to(market_data, today):
    """For each code, return a DataFrame view containing rows where date <= today.

    Keeps signal-time leakage out: evaluate_day must NOT see future bars.
    """
    out = {}
    fd = str(today)
    for code, df in market_data.items():
        sub = df[df["date"].astype(str) <= fd]
        if len(sub) > 0:
            out[code] = sub.reset_index(drop=True)
    return out


def _avg_filter_counts(daily_filter_counts, n_days):
    if n_days <= 0:
        return {}
    keys = set()
    for fc in daily_filter_counts:
        keys.update(fc.keys())
    out = {}
    for k in keys:
        total = sum(fc.get(k, 0) for fc in daily_filter_counts)
        out[k] = round(float(total) / float(n_days), 6)
    return out


def _sum_trigger_counts(daily_trigger_counts):
    keys = set()
    for tc in daily_trigger_counts:
        keys.update(tc.keys())
    out = {k: 0 for k in keys}
    for tc in daily_trigger_counts:
        for k, v in tc.items():
            out[k] += int(v)
    return out


def _unique_warnings(daily_warnings):
    seen = []
    seen_set = set()
    for w_list in daily_warnings:
        for w in (w_list or []):
            if w not in seen_set:
                seen_set.add(w)
                seen.append(w)
    return seen


def run_backtest(
    reader,                 # DuckDBDailyReader instance (or compatible)
    universe,               # list of code strings
    start_date,             # "YYYY-MM-DD"
    end_date,               # "YYYY-MM-DD"
    strategy_config,        # dict (03 §4)
    execution_cfg,          # dict (04 §1.1 execution): price/slippage/commission_rate/tax_rate
    initial_cash,           # float
    aux_data=None,
    benchmark_code=None,
    config_name="baseline",
    config_hash="",
    universe_hash="",
    run_id=None,
    now=None,
):
    """Run the full backtest. Returns an in-memory result struct.

    The result struct is the source of truth for Phase 4 report writers; this
    function intentionally does NOT touch the filesystem. (Test isolation +
    boundary clarity per night-shift §四.8.)
    """
    started_at = now or _dt.datetime.now()
    run_id = run_id or _make_run_id(started_at)

    cov = reader.coverage(codes=universe, start_date=start_date, end_date=end_date)
    calendar = reader.trading_calendar(start_date, end_date)
    if not calendar:
        raise ValueError("empty trading_calendar for [%s, %s]" % (start_date, end_date))
    actual_min = calendar[0]
    actual_max = calendar[-1]

    # Pre-load full market window for the run period.
    market_data = reader.load_window(universe, actual_min, actual_max)

    pf = Portfolio(initial_cash=initial_cash)
    aux_for_eval = aux_data if aux_data is not None else {}
    if "trading_calendar" not in aux_for_eval or not aux_for_eval.get("trading_calendar"):
        aux_for_eval = dict(aux_for_eval)
        aux_for_eval["trading_calendar"] = calendar

    trades = []
    equity_rows = []
    positions_rows = []
    daily_logs = []
    daily_filter_counts = []
    daily_trigger_counts = []
    daily_warnings = []
    unfilled_order_count = 0

    pending = None
    n_days = len(calendar)

    for i, today in enumerate(calendar):
        # 1. Advance holding days (T+1 unfreeze) -- skip on first day, no prior fills.
        if i > 0:
            pf.advance_holding_days()

        # 2. Apply yesterday's pending fills using today's open.
        if pending is not None:
            # Sells first so cash is available for buys.
            for sell_dec in pending.get("sell_decisions", []):
                code = sell_dec["code"]
                pos = pf.positions.get(code)
                if pos is None:
                    daily_logs.append("[ERROR] %s unfilled_order code=%s reason=position_gone"
                                      % (today, code))
                    unfilled_order_count += 1
                    continue
                # Build a position-shaped dict for execution.fill_sell.
                pos_arg = {
                    "code":             code,
                    "volume":           int(pos["volume"]),
                    "available_volume": int(pos["available_volume"]),
                    "cost_price":       float(pos["cost_price"]),
                    "entry_date":       pos["entry_date"],
                    "holding_days":     int(pos["holding_days"]),
                    "last_price":       float(pos["last_price"]),
                    "unrealized_pnl":   float(pos["unrealized_pnl"]),
                }
                trade, unfilled = fill_sell(sell_dec, pos_arg, market_data,
                                            today, execution_cfg, run_id)
                if trade is not None:
                    pf.apply_trade(trade)
                    trades.append(trade)
                    daily_logs.append("[INFO]  %s fill sell %s vol=%d price=%.4f amt=%.2f"
                                      % (today, code, trade["volume"],
                                         trade["price"], trade["amount"]))
                else:
                    daily_logs.append("[ERROR] %s unfilled_order code=%s reason=%s"
                                      % (today, code, unfilled))
                    unfilled_order_count += 1
            for cand in pending.get("buy_candidates", []):
                trade, unfilled = fill_buy(cand, market_data, today,
                                           execution_cfg, run_id)
                if trade is not None:
                    pf.apply_trade(trade)
                    trades.append(trade)
                    daily_logs.append("[INFO]  %s fill buy %s vol=%d price=%.4f amt=%.2f"
                                      % (today, trade["code"], trade["volume"],
                                         trade["price"], trade["amount"]))
                else:
                    daily_logs.append("[ERROR] %s unfilled_order code=%s reason=%s"
                                      % (today, cand["code"], unfilled))
                    unfilled_order_count += 1

        # 3. Mark to market using today's close.
        pf.mark_to_market(market_data, today)

        # 4. Snapshot rows for today.
        equity_rows.append(pf.equity_row(run_id, today))
        positions_rows.extend(pf.positions_rows(run_id, today))

        # 5. Evaluate signals for today (will be filled tomorrow). Skip on last day.
        if i < n_days - 1:
            window = _slice_window_up_to(market_data, today)
            account_state = {
                "current_date":         today,
                "trading_day_index":    i,
                "total_asset":          pf.total_asset(),
                "market_value":         pf.market_value(),
                "is_last_trading_day":  False,
                "max_positions":        int(strategy_config.get("max_positions", 5)),
            }
            decision = evaluate_day(
                current_date=today,
                market_window=window,
                positions=pf.position_list(),
                cash=pf.cash,
                universe=universe,
                account_state=account_state,
                strategy_config=strategy_config,
                aux_data=aux_for_eval,
            )
            diag = decision.get("diagnostics", {})
            daily_filter_counts.append(diag.get("filter_counts", {}))
            daily_trigger_counts.append(diag.get("trigger_counts", {}))
            daily_warnings.append(diag.get("warnings", []))
            for line in decision.get("logs", []):
                daily_logs.append("[INFO]  " + line)
            pending = decision
        else:
            pending = None

    # ----- Aggregate diagnostics -----
    diagnostics_aggregate = {
        "trigger_counts_total":      _sum_trigger_counts(daily_trigger_counts),
        "filter_counts_avg_per_day": _avg_filter_counts(daily_filter_counts, n_days),
        "unfilled_order_count":      unfilled_order_count,
        "warnings_unique":           _unique_warnings(daily_warnings),
    }

    # ----- Performance -----
    benchmark_available = bool(benchmark_code)
    performance = compute_metrics(
        equity_rows=equity_rows,
        trades=trades,
        trading_calendar=calendar,
        initial_cash=initial_cash,
        benchmark_available=benchmark_available,
    )

    # ----- Sample period warning (04 §1.3) -----
    is_short_sample = (n_days < 252) or (not benchmark_available)
    months = round(n_days / 21.0, 1)
    sample_warning = {
        "is_short_sample":  bool(is_short_sample),
        "requested_range":  [start_date, end_date],
        "actual_range":     [actual_min, actual_max],
        "trading_days":     n_days,
        "warning":          (u"样本期约 %s 个月，仅用于 MVP 管线验证，不可作为策略最终定论"
                             % months) if is_short_sample else "",
    }

    # ----- Compute data_hash now that we know actual coverage -----
    from backtest.engine.hashing import compute_data_hash
    data_hash = compute_data_hash(
        db_path=reader.db_path,
        db_mtime=cov.get("db_mtime", ""),
        adjustment="hfq",
        requested_start=start_date,
        requested_end=end_date,
        actual_min=actual_min,
        actual_max=actual_max,
        n_codes=cov.get("n_codes", 0),
        n_rows_after_dedup=cov.get("n_rows_after_dedup", 0),
        dedup_count=cov.get("dedup_count", 0),
        universe_hash=universe_hash,
    )

    end_total = pf.total_asset()
    end_cash = pf.cash
    end_mv = pf.market_value()

    runtime = (_dt.datetime.now() - started_at).total_seconds()

    summary = {
        "summary_schema_version": _SUMMARY_SCHEMA_VERSION,
        "run_id":                 run_id,
        "run_started_at":         started_at.isoformat(timespec="seconds"),
        "runtime_seconds":        round(runtime, 3),
        "config_name":            config_name,
        "results_dir":            "",   # filled by report writer (Phase 4)
        "strategy_core_version":  _STRATEGY_CORE_VERSION,

        "config_hash":     config_hash,
        "data_hash":       data_hash,
        "universe_hash":   universe_hash,

        "data_source":     "jince_zhisuan",   # OPEN_QUESTION (OQ-2): pending v0.3
        "data_path":       reader.db_path,
        "data_mtime":      cov.get("db_mtime", ""),
        "data_adjustment": "hfq",
        "data_coverage_actual": {
            "min_date":           cov.get("min_date", ""),
            "max_date":           cov.get("max_date", ""),
            "n_codes":            cov.get("n_codes", 0),
            "n_rows_after_dedup": cov.get("n_rows_after_dedup", 0),
            "dedup_count":        cov.get("dedup_count", 0),
            "universe_coverage":  cov.get("universe_coverage", {
                "universe_size":   len(universe),
                "codes_with_data": len(market_data),
                "codes_missing":   [c for c in universe if c not in market_data],
                "missing_count":   len([c for c in universe if c not in market_data]),
            }),
        },
        "data_dedup_applied":           True,
        "data_concurrent_sync_warning": bool(getattr(reader, "wal_detected", False)),
        "data_wal_detected":            bool(getattr(reader, "wal_detected", False)),
        "data_wal_warning_message":     getattr(reader, "wal_warning_message", ""),

        "benchmark_code":      benchmark_code,
        "benchmark_available": benchmark_available,
        "benchmark_note":      ("DuckDB 当前无指数数据，benchmark 已禁用"
                                if not benchmark_available else ""),

        "sector_heat_available": False,
        "sector_heat_mode":      strategy_config.get("sector_heat_mode", "zero"),
        "sector_heat_warning":   "historical sector heat unavailable; sector score set to 0",

        "sample_period_warning": sample_warning,

        "execution":   dict(execution_cfg),
        "performance": performance,
        "portfolio_end": {
            "total_asset":  round(end_total, 6),
            "cash":         round(end_cash, 6),
            "market_value": round(end_mv, 6),
            "n_positions":  len(pf.positions),
        },
        "diagnostics_aggregate": diagnostics_aggregate,
    }

    return {
        "summary":        summary,
        "trades":         trades,
        "equity_rows":    equity_rows,
        "positions_rows": positions_rows,
        "logs":           daily_logs,
        "trading_calendar": calendar,
    }
