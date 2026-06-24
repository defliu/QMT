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

from backtest.strategies import get_strategy, list_strategies
import importlib as _importlib
from backtest.engine.execution import fill_buy, fill_sell
from backtest.engine.portfolio import Portfolio
from backtest.engine.metrics import compute_metrics

log = logging.getLogger(__name__)

_STRATEGY_CORE_VERSION = "0.2.0"
_SUMMARY_SCHEMA_VERSION = "0.2"

DEFAULT_BENCHMARK_DB = "F:/backtest_workspace/data/duckdb/benchmark_index.duckdb"


def _load_benchmark_series(benchmark_code, calendar, benchmark_db_path):
    """Load benchmark closes aligned to the run calendar (forward-fill on gaps).

    Returns (closes_by_date, note). closes_by_date is dict {date: close}
    covering every day in `calendar` (forward-filled from the latest prior
    benchmark close). Returns (None, note) if benchmark cannot be used.
    """
    if not benchmark_code:
        return None, ""
    if not benchmark_db_path:
        return None, u"benchmark_db_path 未配置"
    if not os.path.isfile(benchmark_db_path):
        return None, u"benchmark_index.duckdb 不存在: %s" % benchmark_db_path
    try:
        from backtest.data_tools.benchmark_reader import BenchmarkIndexReader
        br = BenchmarkIndexReader(benchmark_db_path)
        try:
            # Pull a small lead-in window so we can forward-fill the first day
            # if the calendar's first date predates the first benchmark bar.
            rows = br.load_series(benchmark_code, calendar[0], calendar[-1])
        finally:
            br.close()
    except Exception as e:
        return None, u"benchmark 加载失败: %s" % e
    if not rows:
        return None, u"benchmark 在窗口内无数据 code=%s" % benchmark_code
    bm_map = {d: c for d, c in rows if c is not None}
    if not bm_map:
        return None, u"benchmark close 全为空 code=%s" % benchmark_code
    bm_dates_sorted = sorted(bm_map.keys())
    # Forward-fill onto the run calendar. Days before the first benchmark
    # row are left out of closes_by_date; the engine will treat them as gaps.
    closes = {}
    last = None
    bi = 0
    for d in calendar:
        while bi < len(bm_dates_sorted) and bm_dates_sorted[bi] <= d:
            last = bm_map[bm_dates_sorted[bi]]
            bi += 1
        if last is not None:
            closes[d] = last
    if not closes:
        return None, (u"benchmark 起点晚于回测窗口 (首条=%s)" % bm_dates_sorted[0])
    missing_head = [d for d in calendar if d not in closes]
    if missing_head:
        # Calendar 起点早于 benchmark 首条（常见原因：QMT 日历含元旦/周末
        # placeholder bar，而 benchmark 只含真实交易日）。容忍最多 14 天的
        # head gap：用 benchmark 首条 close 反向回填，使元旦期 benchmark
        # daily_return = 0，不影响超额收益统计。
        head_gap_tolerance_days = 14
        if len(missing_head) <= head_gap_tolerance_days:
            first_bm_close = bm_map[bm_dates_sorted[0]]
            for d in missing_head:
                closes[d] = first_bm_close
        else:
            return None, (u"benchmark 在窗口前期缺失 %d 天 (首=%s, 首条 bm=%s)"
                          % (len(missing_head), missing_head[0],
                         bm_dates_sorted[0]))
    return closes, ""


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


def _aggregate_strategy_specific(daily_ss, n_days):
    """v0.4 通用 strategy_specific 聚合 —— SPEC §3.3。

    输入: daily_ss = [{strategy_name: {key: dict_or_list}}, ...] 每天一份
    输出: {strategy_name: {key + "_avg_per_day"_or_"_total": aggregated_value}}

    聚合规则（按值类型分两类）：
      - dict[str, number]   → 求和后除以 n_days；输出 key 加 "_avg_per_day" 后缀
      - dict[str, dict]     → 不聚合，保留每个内层 dict 的 union（即 scores 等"按 code 索引"的结构）
    """
    if n_days <= 0:
        return {}
    by_strat = {}   # {strategy_name: {sub_key: type_hint}}
    for ss in daily_ss:
        if not isinstance(ss, dict):
            continue
        for sname, sdict in ss.items():
            if not isinstance(sdict, dict):
                continue
            sub_map = by_strat.setdefault(sname, {})
            for sub_key, sub_val in sdict.items():
                sub_map.setdefault(sub_key, sub_val)

    out = {}
    for sname, sub_map in by_strat.items():
        sname_out = {}
        for sub_key, sample_val in sub_map.items():
            if isinstance(sample_val, dict) and sample_val and all(
                isinstance(v, (int, float)) for v in sample_val.values()
            ):
                agg = {}
                inner_keys = set()
                for ss in daily_ss:
                    sd = (ss or {}).get(sname, {}) or {}
                    sk = sd.get(sub_key, {}) or {}
                    if isinstance(sk, dict):
                        inner_keys.update(sk.keys())
                for ik in inner_keys:
                    total = 0.0
                    for ss in daily_ss:
                        sd = (ss or {}).get(sname, {}) or {}
                        sk = sd.get(sub_key, {}) or {}
                        if isinstance(sk, dict):
                            total += float(sk.get(ik, 0) or 0)
                    agg[ik] = round(total / float(n_days), 6)
                if sub_key == "trigger_counts":
                    sname_out["trigger_counts_total"] = {
                        k: int(round(v * n_days)) for k, v in agg.items()
                    }
                else:
                    sname_out[sub_key + "_avg_per_day"] = agg
            else:
                sname_out[sub_key + "_present"] = True
        out[sname] = sname_out
    return out


def resolve_strategy(strategy_name, trading_model):
    """v0.4 Strategy Registry: 取策略 evaluate_fn + 校验 trading_model。

    Args:
        strategy_name: 如 'production/ima_uptrend_v31'；None 时默认 6+2。
        trading_model: 如 'next_open'；None 时默认 'next_open'。

    Returns:
        (evaluate_fn, validated_trading_model)

    Raises:
        KeyError: 策略未注册（来自 get_strategy）
        ValueError: trading_model 不在策略 ALLOWED_TRADING_MODELS 内

    SPEC: specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md §3.2
    """
    name = strategy_name or "production/ima_uptrend_v31"
    fn = get_strategy(name)

    mod_name = "backtest.strategies." + name.replace("/", ".") + ".strategy"
    try:
        mod = _importlib.import_module(mod_name)
        allowed = list(getattr(mod, "ALLOWED_TRADING_MODELS", ["next_open"]))
    except ImportError:
        allowed = ["next_open"]

    tm = trading_model or "next_open"
    if tm not in allowed:
        raise ValueError(
            "trading_model=" + str(tm) +
            " not in strategy.ALLOWED_TRADING_MODELS=" + str(allowed) +
            " (strategy=" + name + ")"
        )
    return fn, tm


def run_backtest(
    reader,                 # DuckDBDailyReader instance (or compatible)
    universe,               # list of code strings (PIT mode: union of all snapshots)
    start_date,             # "YYYY-MM-DD"
    end_date,               # "YYYY-MM-DD"
    strategy_config,        # dict (03 §4)
    execution_cfg,          # dict (04 §1.1 execution): price/slippage/commission_rate/tax_rate
    initial_cash,           # float
    aux_data=None,
    benchmark_code=None,
    benchmark_db_path=DEFAULT_BENCHMARK_DB,
    config_name="baseline",
    config_hash="",
    universe_hash="",
    run_id=None,
    now=None,
    universe_by_date=None,  # P2.1 PIT: {as_of_date_str: [codes]}; if set, evaluate_day
                            # receives the as-of snapshot per day (forward-fill prior).
                            # `universe` MUST be the union of all snapshot codes so that
                            # load_window pre-loads every code that any snapshot needs.
    strategy_name=None,     # v0.4: registry key, 默认 'production/ima_uptrend_v31'
    trading_model=None,     # v0.4: 默认 'next_open'；不在策略 ALLOWED 里则 ValueError
):
    """Run the full backtest. Returns an in-memory result struct.

    The result struct is the source of truth for Phase 4 report writers; this
    function intentionally does NOT touch the filesystem. (Test isolation +
    boundary clarity per night-shift §四.8.)
    """
    # v0.4: Strategy Registry —— 解除与 6+2 的硬绑定
    _evaluate_day, _trading_model = resolve_strategy(strategy_name, trading_model)

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

    # ----- Benchmark series (optional; degrade gracefully) -----
    benchmark_closes, benchmark_note = _load_benchmark_series(
        benchmark_code, calendar, benchmark_db_path)
    benchmark_available = benchmark_closes is not None
    if benchmark_code and not benchmark_available:
        log.warning("benchmark disabled: %s", benchmark_note)

    pf = Portfolio(initial_cash=initial_cash)
    aux_for_eval = aux_data if aux_data is not None else {}
    if "trading_calendar" not in aux_for_eval or not aux_for_eval.get("trading_calendar"):
        aux_for_eval = dict(aux_for_eval)
        aux_for_eval["trading_calendar"] = calendar

    # P2.1 PIT: pre-compute per-day universe from snapshots (forward-fill).
    # universe_by_date maps as_of -> [codes]; for each calendar day pick the latest
    # snapshot whose as_of <= today. Days before the first valid snapshot use [].
    if universe_by_date:
        snap_dates = sorted(universe_by_date.keys())
        per_day_universe = {}
        cur = []
        snap_i = 0
        for today in calendar:
            while snap_i < len(snap_dates) and snap_dates[snap_i] <= today:
                cur = list(universe_by_date[snap_dates[snap_i]])
                snap_i += 1
            per_day_universe[today] = list(cur)
    else:
        per_day_universe = None

    trades = []
    equity_rows = []
    positions_rows = []
    daily_logs = []
    daily_filter_counts = []
    daily_trigger_counts = []
    daily_warnings = []
    daily_candidate_total = []
    daily_candidate_passed = []
    daily_strategy_specific = []   # list[dict] — 每天一份 strategy_specific 整体（任意 namespace）
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
            decision = _evaluate_day(
                current_date=today,
                market_window=window,
                positions=pf.position_list(),
                cash=pf.cash,
                universe=(per_day_universe[today] if per_day_universe is not None
                          else universe),
                account_state=account_state,
                strategy_config=strategy_config,
                aux_data=aux_for_eval,
            )
            diag = decision.get("diagnostics", {})
            # v0.4 通用字段
            daily_warnings.append(diag.get("warnings", []))
            daily_candidate_total.append(int(diag.get("candidate_total", 0)))
            daily_candidate_passed.append(int(diag.get("candidate_passed", 0)))
            # v0.4 策略私有字段：按 namespace 整体采集，支持任意策略
            ss_today = diag.get("strategy_specific", {}) or {}
            daily_strategy_specific.append(ss_today)
            # 兼容旧 6+2 通路（被某些测试 fixture 引用）：从 ima_uptrend_v31 namespace 提取
            _ima = ss_today.get("ima_uptrend_v31", {}) or {}
            daily_filter_counts.append(_ima.get("filter_counts", {}) or {})
            daily_trigger_counts.append(_ima.get("trigger_counts", {}) or {})
            for line in decision.get("logs", []):
                daily_logs.append("[INFO]  " + line)
            pending = decision
        else:
            pending = None

    # ----- Benchmark fill on equity_rows (post-loop, in-place) -----
    benchmark_returns = None
    benchmark_total_return = None
    if benchmark_available:
        prev_close = None
        bm_series = []  # parallel to equity_rows
        for row in equity_rows:
            d = row["date"]
            close = benchmark_closes.get(d)
            if close is None:
                row["benchmark_close"] = ""
                row["benchmark_return"] = ""
                bm_series.append(None)
                prev_close = None
                continue
            if prev_close is None or prev_close == 0:
                bm_ret = 0.0
            else:
                bm_ret = (close / prev_close) - 1.0
            row["benchmark_close"] = round(float(close), 6)
            row["benchmark_return"] = round(float(bm_ret), 8)
            bm_series.append(close)
            prev_close = close
        # Daily benchmark returns aligned with equity_rows[1:]; drop None pairs.
        benchmark_returns = []
        valid_pair = True
        for i in range(1, len(bm_series)):
            a, b = bm_series[i - 1], bm_series[i]
            if a is None or b is None or a == 0:
                valid_pair = False
                break
            benchmark_returns.append((b / a) - 1.0)
        if not valid_pair:
            benchmark_available = False
            benchmark_note = u"benchmark 数据存在断点，禁用 IR/excess"
            benchmark_returns = None
        else:
            first_close = bm_series[0]
            last_close = bm_series[-1]
            if first_close and first_close != 0:
                benchmark_total_return = (last_close / first_close) - 1.0
            else:
                benchmark_available = False
                benchmark_returns = None
                benchmark_note = u"benchmark 起点价格为 0，禁用 IR/excess"

    # ----- Aggregate diagnostics -----
    # v0.4: 聚合按 SPEC §3.3 分通用 / 策略私有；策略私有自动支持任意 namespace
    _n_days = max(1, n_days)
    _ct_avg = sum(daily_candidate_total)  / float(_n_days)
    _cp_avg = sum(daily_candidate_passed) / float(_n_days)
    diagnostics_aggregate = {
        # 通用
        "warnings_unique":              _unique_warnings(daily_warnings),
        "candidate_total_avg_per_day":  _ct_avg,
        "candidate_passed_avg_per_day": _cp_avg,
        "unfilled_order_count":         int(unfilled_order_count),
        # 策略私有：遍历所有出现过的 namespace 自动聚合
        "strategy_specific": _aggregate_strategy_specific(
            daily_strategy_specific, _n_days
        ),
    }

    # ----- Performance -----
    performance = compute_metrics(
        equity_rows=equity_rows,
        trades=trades,
        trading_calendar=calendar,
        initial_cash=initial_cash,
        benchmark_available=benchmark_available,
        benchmark_returns=benchmark_returns,
        benchmark_total_return=benchmark_total_return,
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

        "data_source":     getattr(reader, "data_source", "jince_zhisuan"),
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
        "benchmark_note":      (benchmark_note if not benchmark_available else ""),

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

        "pit_universe": (
            {
                "enabled":      True,
                "n_snapshots":  len(universe_by_date),
                "snapshot_dates": sorted(universe_by_date.keys()),
                "union_size":   len(universe),
            } if universe_by_date else
            {"enabled": False}
        ),
    }

    return {
        "summary":        summary,
        "trades":         trades,
        "equity_rows":    equity_rows,
        "positions_rows": positions_rows,
        "logs":           daily_logs,
        "trading_calendar": calendar,
    }
