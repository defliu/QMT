# coding=utf-8
"""黄氏主升浪「箱体突破初选 + 双中军精筛」组合选股 selector.

SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
原始公式: F:/天翼云盘同步盘/Obsidian/量化知识库/20_策略知识库/黄氏主升浪策略.txt

最终唯一输出: combo_XG = box_window_hit AND double_zhongjun_XG (SPEC v1.2 §C)

离线纯 Python 模块, 不进 build_strategy.py, 不接 QMT 实盘下单接口.
Python 3.6.8 兼容: 禁 dict[str,...] / str | None / walrus / match-case / dataclass.
"""
import numpy as _np
import pandas as _pd

DEFAULT_PARAMS = {
    # 箱体突破
    'box_N': 60,
    'box_amp_thresh': 20.0,
    'box_ma_short': 5,
    'box_ma_adhere_thresh': 5.0,
    'box_vol_ratio': 1.5,
    'box_break_tol': 0.995,
    'box_pct_thresh': 0.05,
    # 双中军
    'zj_ma5': 5,
    'zj_ma10': 10,
    'zj_ma20': 20,
    'zj_ma60': 60,
    'zj_ma120': 120,
    'zj_angle_thresh': 30.0,
    'zj_divergence_thresh': 1.05,
    'zj_macd_fast': 12,
    'zj_macd_slow': 26,
    'zj_macd_signal': 9,
    'zj_cci_period': 14,
    'zj_cci_thresh': 100.0,
    'zj_breakout_N': 20,
    'zj_breakout_upper': 1.08,
    'zj_ma20_up_n': 5,
    'zj_ma60_up_n': 5,
    # 大盘指数
    'benchmark_code': '000001.SH',
    # SPEC v1.2 §C: 时间窗口串联 (废弃同日 AND)
    'box_window_N': 120,  # 最近 N 个交易日内曾触发 box_breakout_XG; 默认 120 (诚哥拍板)
}


def tdx_ma(s, n):
    """MA(X,N): N 日简单移动平均"""
    return s.rolling(window=n, min_periods=n).mean()


def tdx_ema(s, n):
    """EMA(X,N) 通达信口径: alpha=2/(N+1), 递归 (adjust=False)"""
    return s.ewm(alpha=2.0 / (n + 1), adjust=False).mean()


def tdx_ref(s, n):
    """REF(X,N): 向前 N 日引用 (不含当日, 严禁未来数据)"""
    return s.shift(n)


def tdx_hhv(s, n):
    """HHV(X,N): 最近 N 日最高 (含当日)"""
    return s.rolling(window=n, min_periods=n).max()


def tdx_llv(s, n):
    """LLV(X,N): 最近 N 日最低 (含当日)"""
    return s.rolling(window=n, min_periods=n).min()


def tdx_cross(a, b):
    """CROSS(A,B): 当日 A>B 且昨日 A<=B"""
    return (a > b) & (a.shift(1) <= b.shift(1))


def tdx_count(cond, n):
    """COUNT(COND,N): 最近 N 日条件成立次数"""
    return cond.astype(float).rolling(window=n, min_periods=n).sum()


def tdx_avedev(s, n):
    """AVEDEV(X,N): N 日平均绝对偏差, 用于 CCI"""
    return s.rolling(window=n, min_periods=n).apply(
        lambda x: _np.mean(_np.abs(x - _np.mean(x))), raw=True
    )


def _calc_box_breakout_conditions(df, params):
    """箱体突破版初选条件计算.

    输入 df 必须含列: open, high, low, close, volume, 按日期升序.
    返回 DataFrame, 含以下中间字段 + box_breakout_XG:
      box_箱顶, box_箱底, box_箱体振幅,
      box_MA5, box_MA10, box_MA20, box_均线差1, box_均线差2,
      box_前5日量, box_量比, box_涨幅,
      box_箱体振幅_ok, box_均线黏连_ok, box_放量_ok, box_突破_ok, box_涨幅_ok,
      box_breakout_XG
    """
    N = params['box_N']
    out = _pd.DataFrame(index=df.index)

    # 箱体识别
    out['box_箱顶'] = tdx_hhv(df['high'], N)
    out['box_箱底'] = tdx_llv(df['low'], N)
    out['box_箱体振幅'] = (out['box_箱顶'] - out['box_箱底']) / out['box_箱底'] * 100.0

    # 均线黏连
    out['box_MA5'] = tdx_ma(df['close'], 5)
    out['box_MA10'] = tdx_ma(df['close'], 10)
    out['box_MA20'] = tdx_ma(df['close'], 20)
    out['box_均线差1'] = (out['box_MA5'] - out['box_MA10']).abs() / out['box_MA5'] * 100.0
    out['box_均线差2'] = (out['box_MA10'] - out['box_MA20']).abs() / out['box_MA10'] * 100.0

    # 放量突破
    out['box_前5日量'] = tdx_ma(df['volume'], 5)
    out['box_量比'] = df['volume'] / out['box_前5日量']
    out['box_涨幅'] = df['close'] / tdx_ref(df['close'], 1) - 1.0

    # 子条件 (NaN 视为 False)
    amp_thresh = params['box_amp_thresh']
    adh = params['box_ma_adhere_thresh']
    vr = params['box_vol_ratio']
    btol = params['box_break_tol']
    pct = params['box_pct_thresh']

    out['box_箱体振幅_ok'] = (out['box_箱体振幅'] < amp_thresh).fillna(False)
    out['box_均线黏连_ok'] = ((out['box_均线差1'] < adh) & (out['box_均线差2'] < adh)).fillna(False)
    out['box_放量_ok'] = (df['volume'] > out['box_前5日量'] * vr).fillna(False)
    out['box_突破_ok'] = (df['close'] >= out['box_箱顶'] * btol).fillna(False)
    out['box_涨幅_ok'] = (out['box_涨幅'] > pct).fillna(False)

    out['box_breakout_XG'] = (
        out['box_箱体振幅_ok'] & out['box_均线黏连_ok'] & out['box_放量_ok']
        & out['box_突破_ok'] & out['box_涨幅_ok']
    )
    return out


def _calc_double_zhongjun_conditions(df, index_df, params):
    """双中军版精筛条件计算.

    输入:
      df: 个股 DataFrame, 含 open, high, low, close, volume, 日期升序
      index_df: 大盘指数 DataFrame, 含 close, 日期升序, index 必须与 df 对齐 (或前向 reindex)

    返回 DataFrame, 含以下中间字段 + double_zhongjun_XG:
      double_MA5/10/20/60/120, double_MA5角度,
      double_DIF, double_DEA, double_MACD红柱,
      double_TYP, double_CCI14,
      double_近期高点,
      double_大盘指数, double_大盘MA20, double_大盘MA60,
      double_多头排列_ok, double_均线发散_ok, double_MACD_ok, double_CCI_ok,
      double_突破压力_ok, double_MA20向上_ok, double_MA60向上_ok, double_大盘_ok,
      double_zhongjun_XG
    """
    out = _pd.DataFrame(index=df.index)

    # 1. 多头排列
    MA5 = tdx_ma(df['close'], params['zj_ma5'])
    MA10 = tdx_ma(df['close'], params['zj_ma10'])
    MA20 = tdx_ma(df['close'], params['zj_ma20'])
    MA60 = tdx_ma(df['close'], params['zj_ma60'])
    MA120 = tdx_ma(df['close'], params['zj_ma120'])
    out['double_MA5'] = MA5
    out['double_MA10'] = MA10
    out['double_MA20'] = MA20
    out['double_MA60'] = MA60
    out['double_MA120'] = MA120
    out['double_多头排列_ok'] = (
        (MA5 > MA10) & (MA10 > MA20) & (MA20 > MA60) & (MA60 > MA120)
    ).fillna(False)

    # 2. 均线刚发散
    angle_pct = (MA5 / tdx_ref(MA5, 1) - 1.0) * 100.0
    out['double_MA5角度'] = _np.degrees(_np.arctan(angle_pct))
    out['double_均线发散_ok'] = (
        (out['double_MA5角度'] > params['zj_angle_thresh'])
        & (MA5 / MA20 > params['zj_divergence_thresh'])
    ).fillna(False)

    # 3. MACD
    DIF = tdx_ema(df['close'], params['zj_macd_fast']) - tdx_ema(df['close'], params['zj_macd_slow'])
    DEA = tdx_ema(DIF, params['zj_macd_signal'])
    out['double_DIF'] = DIF
    out['double_DEA'] = DEA
    out['double_MACD红柱'] = (DIF - DEA) * 2.0
    out['double_MACD_ok'] = (
        (tdx_cross(DIF, DEA) & (DEA > 0))
        | ((DIF > DEA) & (DIF > tdx_ref(DIF, 1)) & (DEA > tdx_ref(DEA, 1)))
    ).fillna(False)

    # 4. CCI
    TYP = (df['high'] + df['low'] + df['close']) / 3.0
    out['double_TYP'] = TYP
    cci_p = params['zj_cci_period']
    cci = (TYP - tdx_ma(TYP, cci_p)) / (0.015 * tdx_avedev(TYP, cci_p))
    out['double_CCI14'] = cci
    cci_th = params['zj_cci_thresh']
    out['double_CCI_ok'] = (
        tdx_cross(cci, _pd.Series(cci_th, index=cci.index))
        | ((cci > cci_th) & (cci > tdx_ref(cci, 1)))
    ).fillna(False)

    # 5. 突破压力位
    bk_N = params['zj_breakout_N']
    near_high = tdx_ref(tdx_hhv(df['high'], bk_N), 1)
    out['double_近期高点'] = near_high
    out['double_突破压力_ok'] = (
        (df['close'] > near_high) & (df['close'] / near_high < params['zj_breakout_upper'])
    ).fillna(False)

    # 8. 中期趋势确认
    out['double_MA20向上_ok'] = (MA20 > tdx_ref(MA20, params['zj_ma20_up_n'])).fillna(False)
    out['double_MA60向上_ok'] = (MA60 > tdx_ref(MA60, params['zj_ma60_up_n'])).fillna(False)

    # 9. 大盘环境过滤
    if index_df is None or 'close' not in index_df.columns:
        out['double_大盘指数'] = _np.nan
        out['double_大盘MA20'] = _np.nan
        out['double_大盘MA60'] = _np.nan
        out['double_大盘_ok'] = False
    else:
        idx_close = index_df['close'].reindex(df.index, method='ffill')
        idx_ma20 = tdx_ma(idx_close, 20)
        idx_ma60 = tdx_ma(idx_close, 60)
        out['double_大盘指数'] = idx_close
        out['double_大盘MA20'] = idx_ma20
        out['double_大盘MA60'] = idx_ma60
        out['double_大盘_ok'] = (
            (idx_close > idx_ma20) & (idx_ma20 > idx_ma60)
        ).fillna(False)

    # 组合
    out['double_zhongjun_XG'] = (
        out['double_多头排列_ok']
        & out['double_均线发散_ok']
        & out['double_MACD_ok']
        & out['double_CCI_ok']
        & out['double_突破压力_ok']
        & out['double_MA20向上_ok']
        & out['double_MA60向上_ok']
        & out['double_大盘_ok']
    )
    return out


def select_huang_main_uptrend_combo(data, index_data, params=None):
    """主入口: 组合选股.

    Args:
        data: dict {code: DataFrame} 或单个 DataFrame.
              每个 DataFrame 必须含列 [open, high, low, close, volume], 日期升序 (index 是日期).
        index_data: DataFrame, 含列 [close], 日期升序 (index 是日期). 大盘指数(INDEXC).
                    None 表示无指数, 大盘条件视为 False.
        params: dict 可选, 覆盖 DEFAULT_PARAMS 部分键. None 用全默认值.

    Returns:
        DataFrame, 行 = code * date, 列含:
          code, date,
          box_* 中间字段 + box_breakout_XG,
          double_* 中间字段 + double_zhongjun_XG,
          combo_XG (= box_window_hit AND double_zhongjun_XG, SPEC v1.2 §C)
    """
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update(params)

    if isinstance(data, _pd.DataFrame):
        data = {'_single': data}

    results = []
    for code, df in data.items():
        if df is None or df.empty:
            continue
        df = df.sort_index()
        box = _calc_box_breakout_conditions(df, p)
        dbl = _calc_double_zhongjun_conditions(df, index_data, p)
        merged = _pd.concat([box, dbl], axis=1)

        # SPEC v1.2 §C: 时间窗口串联
        # 1) box_window_hit: 最近 N 个交易日内曾触发 box_breakout_XG
        # 2) box_last_signal_date: 最近一次 box_breakout_XG=True 的日期
        # 3) box_days_since_last_signal: 距上次 box 信号的天数
        # 4) combo_XG = box_window_hit AND 今日 double_zhongjun_XG
        win_N = p['box_window_N']
        box_xg = merged['box_breakout_XG'].astype(bool)
        # rolling.max 在 bool->int 上等价 "窗口内任一日 True"
        # min_periods=1 让窗口起步阶段也能产出 (前 N-1 日可视为更短窗口)
        merged['box_window_hit'] = box_xg.rolling(window=win_N, min_periods=1).max().astype(bool)

        # box_last_signal_date / box_days_since_last_signal: 用累计前向最近 True 计算
        date_series = _pd.Series(df.index, index=df.index)
        # 在 box=True 的位置记下日期, 其它位置 NaT, 再 ffill
        box_last = date_series.where(box_xg, other=_pd.NaT).ffill()
        merged['box_last_signal_date'] = box_last
        days_since = (date_series - box_last).dt.days
        merged['box_days_since_last_signal'] = days_since

        merged['combo_XG'] = merged['box_window_hit'] & merged['double_zhongjun_XG']

        merged.insert(0, 'date', df.index)
        merged.insert(0, 'code', code)
        results.append(merged)

    if not results:
        return _pd.DataFrame()
    return _pd.concat(results, axis=0, ignore_index=True)
