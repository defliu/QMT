# coding: utf-8
"""research/huang_zhongjun_combo —— 黄氏 zhongjun + 6+2 + V1.1 无状态版。

纯函数约束（v0.4 接口冻结 03 §1）：
  - 不 IO / 不 random / 不读时间 / 不改输入对象
  - 不 import xtquant / passorder / ContextInfo
  - Python 3.6 兼容（禁 walrus/match/f-string/dict[str,...]/dataclass）

设计：
  zhongjun 信号 → 过滤 universe → 6+2 评分 → V1.1 无状态触发器 → next_open 撮合
"""
import math
import numpy as _np
import pandas as _pd

from backtest.strategies import register_strategy
from backtest.strategies.production.ima_uptrend_v31.scoring_adapter import score_universe
from backtest.strategies.production.ima_uptrend_v31.decision import make_decision


ALLOWED_TRADING_MODELS = ["next_open"]


# =============================================================
# 黄氏 zhongjun 参数（与 huang_main_uptrend_combo_selector.DEFAULT_PARAMS 一致）
# =============================================================
_ZJ_DEFAULTS = {
    "zj_ma5": 5, "zj_ma10": 10, "zj_ma20": 20, "zj_ma60": 60, "zj_ma120": 120,
    "zj_angle_thresh": 30.0,
    "zj_divergence_thresh": 1.05,
    "zj_macd_fast": 12, "zj_macd_slow": 26, "zj_macd_signal": 9,
    "zj_cci_period": 14, "zj_cci_thresh": 100.0,
    "zj_breakout_N": 20, "zj_breakout_upper": 1.08,
    "zj_ma20_up_n": 5, "zj_ma60_up_n": 5,
}


# =============================================================
# TDX 映射函数（与 huang_main_uptrend_combo_selector 等价；
# 这里 inline 避免跨包 import 选股器纯函数）
# =============================================================
def _ma(s, n):
    return s.rolling(window=n, min_periods=n).mean()


def _ema(s, n):
    return s.ewm(alpha=2.0 / (n + 1), adjust=False).mean()


def _ref(s, n):
    return s.shift(n)


def _hhv(s, n):
    return s.rolling(window=n, min_periods=n).max()


def _cross(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))


def _avedev(s, n):
    return s.rolling(window=n, min_periods=n).apply(
        lambda x: _np.mean(_np.abs(x - _np.mean(x))), raw=True
    )


# =============================================================
# 大盘 close 序列（从 aux_data 切片到 current_date）
# =============================================================
def _bench_series_up_to(aux_data, current_date):
    """从 aux_data["benchmark_closes"] 取截至 current_date（含）的 close 序列。

    Args:
        aux_data: dict, 含 "benchmark_closes" key（MS-I 注入）
        current_date: "YYYY-MM-DD"

    Returns:
        (pd.Series indexed by date_str, benchmark_close at current_date or None)
        都为 None 表示未启用基准。
    """
    if not aux_data:
        return None, None
    bm = aux_data.get("benchmark_closes")
    if bm is None or not bm:
        return None, None
    fd = str(current_date)
    items = [(d, c) for d, c in bm.items() if str(d) <= fd]
    if not items:
        return None, None
    items.sort(key=lambda x: x[0])
    dates = [d for d, _ in items]
    closes = [float(c) for _, c in items]
    s = _pd.Series(closes, index=dates)
    last_close = closes[-1] if closes else None
    return s, last_close


# =============================================================
# 大盘条件（close > MA20 > MA60）
# =============================================================
def _benchmark_ok(bench_series):
    """SPEC §B 大盘环境过滤。"""
    if bench_series is None or len(bench_series) < 60:
        return False
    ma20 = _ma(bench_series, 20).iloc[-1]
    ma60 = _ma(bench_series, 60).iloc[-1]
    close = bench_series.iloc[-1]
    if _pd.isna(ma20) or _pd.isna(ma60) or _pd.isna(close):
        return False
    return bool((close > ma20) and (ma20 > ma60))


# =============================================================
# 单 code 的 zhongjun 信号（移植 _calc_double_zhongjun_conditions）
# =============================================================
def _zhongjun_xg_last(df, params, bench_ok):
    """对单 code 算 double_zhongjun_XG，返回 last row 的 bool。

    Args:
        df: DataFrame[date,open,high,low,close,vol,amount], 升序，已切到 current_date
        params: zhongjun 参数 dict
        bench_ok: bool，大盘条件是否通过

    Returns:
        bool（True = 该 code 在 current_date 触发 zhongjun_XG）
    """
    if df is None or len(df) < 130:
        return False
    if not bench_ok:
        return False

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # 1. 多头排列
    MA5 = _ma(close, params["zj_ma5"])
    MA10 = _ma(close, params["zj_ma10"])
    MA20 = _ma(close, params["zj_ma20"])
    MA60 = _ma(close, params["zj_ma60"])
    MA120 = _ma(close, params["zj_ma120"])
    bullish_align = (
        (MA5 > MA10) & (MA10 > MA20) & (MA20 > MA60) & (MA60 > MA120)
    ).fillna(False)
    if not bool(bullish_align.iloc[-1]):
        return False

    # 2. 均线刚发散
    angle_pct = (MA5 / _ref(MA5, 1) - 1.0) * 100.0
    angle_deg = _np.degrees(_np.arctan(angle_pct))
    angle_deg = _pd.Series(angle_deg, index=MA5.index)
    diverge = (
        (angle_deg > params["zj_angle_thresh"])
        & (MA5 / MA20 > params["zj_divergence_thresh"])
    ).fillna(False)
    if not bool(diverge.iloc[-1]):
        return False

    # 3. MACD
    DIF = _ema(close, params["zj_macd_fast"]) - _ema(close, params["zj_macd_slow"])
    DEA = _ema(DIF, params["zj_macd_signal"])
    macd_ok = (
        (_cross(DIF, DEA) & (DEA > 0))
        | ((DIF > DEA) & (DIF > _ref(DIF, 1)) & (DEA > _ref(DEA, 1)))
    ).fillna(False)
    if not bool(macd_ok.iloc[-1]):
        return False

    # 4. CCI
    TYP = (high + low + close) / 3.0
    cci_p = params["zj_cci_period"]
    cci_denom = 0.015 * _avedev(TYP, cci_p)
    cci = (TYP - _ma(TYP, cci_p)) / cci_denom
    cci_th = params["zj_cci_thresh"]
    cci_thresh_series = _pd.Series(cci_th, index=cci.index)
    cci_ok = (
        _cross(cci, cci_thresh_series)
        | ((cci > cci_th) & (cci > _ref(cci, 1)))
    ).fillna(False)
    if not bool(cci_ok.iloc[-1]):
        return False

    # 5. 突破压力位
    bk_N = params["zj_breakout_N"]
    near_high = _ref(_hhv(high, bk_N), 1)
    break_ok = (
        (close > near_high) & (close / near_high < params["zj_breakout_upper"])
    ).fillna(False)
    if not bool(break_ok.iloc[-1]):
        return False

    # 6. MA20 / MA60 向上
    ma20_up = (MA20 > _ref(MA20, params["zj_ma20_up_n"])).fillna(False)
    ma60_up = (MA60 > _ref(MA60, params["zj_ma60_up_n"])).fillna(False)
    if not bool(ma20_up.iloc[-1]) or not bool(ma60_up.iloc[-1]):
        return False

    return True


# =============================================================
# 主入口
# =============================================================
@register_strategy("research/huang_zhongjun_combo")
def evaluate_day(
    current_date,
    market_window,
    positions,
    cash,
    universe,
    account_state,
    strategy_config,
    aux_data,
):
    """黄氏 zhongjun + 6+2 + V1.1 无状态版 evaluate_day。

    流程见模块 docstring。
    """
    cfg = strategy_config or {}
    aux = aux_data if aux_data is not None else {}

    # ---- Step 1: 大盘条件 ----
    bench_series, bench_last_close = _bench_series_up_to(aux, current_date)
    bench_ok = _benchmark_ok(bench_series)

    # ---- Step 2 & 3: 个股 zhongjun 信号 + 过滤 universe ----
    params = dict(_ZJ_DEFAULTS)
    for k, v in cfg.items():
        if k in params:
            params[k] = v

    mw = market_window or {}
    zhongjun_pass_codes = []
    for code in (universe or []):
        df = mw.get(code)
        if _zhongjun_xg_last(df, params, bench_ok):
            zhongjun_pass_codes.append(code)

    # 持仓票必须保留在 filtered universe 里——卖出层要评估它们
    held = set()
    for p in (positions or []):
        held.add(p["code"])
    pass_set = set(zhongjun_pass_codes)
    filtered_universe = list(zhongjun_pass_codes)
    for code in held:
        if code not in pass_set:
            filtered_universe.append(code)

    # 同步构造 filtered_window（zhongjun=True ∪ 持仓）
    filtered_window = {}
    for code in filtered_universe:
        if code in mw:
            filtered_window[code] = mw[code]

    # ---- Step 4: 6+2 评分 ----
    sector_heat_mode = cfg.get("sector_heat_mode", "zero")
    score_records, score_warnings = score_universe(
        filtered_window,
        sector_heat_mode=sector_heat_mode,
        aux_data=aux,
        return_warnings=True,
    )

    # ---- Step 5: 走 6+2 decision 拿完整 decision 结构 ----
    decision = make_decision(
        current_date=current_date,
        market_window=filtered_window,
        positions=positions,
        cash=cash,
        universe=zhongjun_pass_codes,
        account_state=account_state,
        strategy_config=strategy_config,
        aux_data=aux,
        score_records=score_records,
    )

    # score warnings 并入 decision.warnings
    if score_warnings:
        decision["diagnostics"]["warnings"].extend(score_warnings)

    # ---- Step 6: namespace 重命名 + 追加 zhongjun_counts ----
    ss = decision["diagnostics"]["strategy_specific"]
    inner = ss.pop("ima_uptrend_v31", {})
    inner["zhongjun_counts"] = {
        "universe_size":    int(len(universe or [])),
        "zhongjun_pass":    int(len(zhongjun_pass_codes)),
        "benchmark_ok":     bool(bench_ok),
        "benchmark_close":  (float(bench_last_close)
                             if bench_last_close is not None else None),
    }
    ss["huang_zhongjun_combo"] = inner

    return decision
