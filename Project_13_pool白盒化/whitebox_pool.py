# -*- coding: utf-8 -*-
"""whitebox_pool.py - 通达信505选股公式白盒化(QMT原生实现, 不依赖TDX)

Project 12.7 T004 step1。将通达信505选股公式(双带主升浪BS, 无L2版)拆解为原子条件,
在QMT/Python原生复现(纯pandas/numpy), 供逐条归因。

=== 505公式原子条件拆解(启用过滤=0 默认) ===
源码: knowledge_base/20_策略知识库/黄氏策略/gs_1_505选股.txt
注: 双带(紫带/红带EMA链)在买点1中未引用(此版本vestigial), 不计入有效条件。

有效过滤条件(C1-C9):
  C1  收盘站上MA5        close > MA5
  C2  均线多头(短)       MA5 > MA10
  C3  均线多头(中)       MA10 > MA20
  C4  均线多头(长)       MA20 > MA60
  C5  收阳               close > open
  C6  低点不远离MA5      low >= MA5 * 0.98
  C7  MA5斜率角度>=45    ATAN((MA5/REF(MA5,1)-1)*100)*180/π >= 45
  C8  筹码集中度<15%     SCR < 15            [TDX筹码, QMT不可原生复现->T006偏差]
  C9  获利盘>90%         WINNER(C)*100 > 90  [TDX筹码, QMT不可原生复现->T006偏差]

恒过/分类(不影响选股输出):
  - 资金OK=1 (无L2恒过)
  - 过滤条件=1 (启用过滤=0时恒过; =1时加 大盘股FINANCE(40)>250亿 + 大盘INDEXC>MA20>MA60)
  - BIAS5分类(<=10正常 / >10高乖离): 两者OR, 不影响XG, 仅分类标注

QMT原生可复现: C1-C7 (price/MA based)
QMT不可复现: C8, C9 (TDX筹码WINNER/SCR黑箱, 见T006, 禁止逆向)

依赖: pandas, numpy (与 dimension6plus2.py 同风格)
"""
import numpy as np
import pandas as pd

try:
    from core.utils import ma, safe_last
except Exception:
    # 兜底(独立运行时)
    def ma(s, n):
        return s.rolling(n).mean()
    def safe_last(s):
        v = s.iloc[-1] if len(s) > 0 else np.nan
        return v if not pd.isna(v) else 0.0


def _ma5_slope_angle(df):
    """C7: MA5斜率角度 ATAN((MA5/REF(MA5,1)-1)*100)*180/π."""
    if len(df) < 6:
        return 0.0
    close = df['close']
    m = ma(close, 5)
    if len(m) < 2 or pd.isna(m.iloc[-1]) or pd.isna(m.iloc[-2]) or m.iloc[-2] == 0:
        return 0.0
    ratio = m.iloc[-1] / m.iloc[-2] - 1
    return float(np.arctan(ratio * 100) * 180 / np.pi)


# ===== 每条原子条件(返回bool) =====
def cond_c1_close_above_ma5(df):
    """C1: close > MA5."""
    if len(df) < 5:
        return False
    return float(df['close'].iloc[-1]) > float(ma(df['close'], 5).iloc[-1])

def cond_c2_ma5_gt_ma10(df):
    """C2: MA5 > MA10."""
    if len(df) < 10:
        return False
    return float(ma(df['close'], 5).iloc[-1]) > float(ma(df['close'], 10).iloc[-1])

def cond_c3_ma10_gt_ma20(df):
    """C3: MA10 > MA20."""
    if len(df) < 20:
        return False
    return float(ma(df['close'], 10).iloc[-1]) > float(ma(df['close'], 20).iloc[-1])

def cond_c4_ma20_gt_ma60(df):
    """C4: MA20 > MA60."""
    if len(df) < 60:
        return False
    return float(ma(df['close'], 20).iloc[-1]) > float(ma(df['close'], 60).iloc[-1])

def cond_c5_bullish_candle(df):
    """C5: close > open (收阳)."""
    if len(df) < 1:
        return False
    return float(df['close'].iloc[-1]) > float(df['open'].iloc[-1])

def cond_c6_low_near_ma5(df):
    """C6: low >= MA5 * 0.98."""
    if len(df) < 5:
        return False
    return float(df['low'].iloc[-1]) >= float(ma(df['close'], 5).iloc[-1]) * 0.98

def cond_c7_ma5_angle_ge45(df):
    """C7: MA5斜率角度 >= 45度."""
    return _ma5_slope_angle(df) >= 45.0

# C8/C9: TDX筹码, QMT不可原生复现
def cond_c8_chip_concentrated(df, scr_value=None):
    """C8: SCR < 15 (筹码集中度). [TDX筹码, QMT无原生SCR]
    需外部传入scr_value(TDX导出). QMT原生不可得->T006量化偏差."""
    if scr_value is None:
        return None  # 未知, 跳过
    return scr_value < 15.0

def cond_c9_winner_gt90(df, winner_value=None):
    """C9: WINNER(C)*100 > 90 (获利盘>90%). [TDX筹码, QMT无原生WINNER]
    需外部传入winner_value. QMT原生不可得->T006量化偏差."""
    if winner_value is None:
        return None
    return winner_value * 100 > 90


# ===== 条件注册表(供归因逐条toggle) =====
# (key, 名称, 函数, 是否QMT原生可复现, 与6+2维度重叠度)
CONDITIONS = [
    ('C1', '收盘站上MA5',      cond_c1_close_above_ma5, True,  '低(Breakout看20日突破, C1看MA5)'),
    ('C2', 'MA5>MA10',         cond_c2_ma5_gt_ma10,      True,  '中(Trend有MA20/bias5)'),
    ('C3', 'MA10>MA20',        cond_c3_ma10_gt_ma20,     True,  '中(Trend有MA20)'),
    ('C4', 'MA20>MA60',        cond_c4_ma20_gt_ma60,     True,  '中(Trend有MA20)'),
    ('C5', '收阳C>O',          cond_c5_bullish_candle,    True,  '低(6+2无直接收阳维度)'),
    ('C6', '低点>=MA5*0.98',   cond_c6_low_near_ma5,     True,  '中(Consolidation看low>=ma5)'),
    ('C7', 'MA5角度>=45',      cond_c7_ma5_angle_ge45,   True,  '低(6+2无角度维度)'),
    ('C8', '筹码集中SCR<15',   cond_c8_chip_concentrated, False, '无(筹码独立维度, [[huang-chip-not-alpha]]已证伪非alpha)'),
    ('C9', '获利盘WINNER>90',  cond_c9_winner_gt90,       False, '无(筹码独立维度)'),
]


def check_all_conditions(df, scr_value=None, winner_value=None):
    """对单只股票检查所有条件, 返回 {cond_key: bool/None}."""
    res = {}
    for key, name, fn, native, overlap in CONDITIONS:
        if key == 'C8':
            res[key] = fn(df, scr_value)
        elif key == 'C9':
            res[key] = fn(df, winner_value)
        else:
            try:
                res[key] = bool(fn(df))
            except Exception:
                res[key] = False
    return res


def passes_505_qmt_native(df, scr_value=None, winner_value=None):
    """QMT原生复现505选股(C1-C7, C8/C9若有外部值则纳入).
    返回 (通过bool, 各条件结果dict). 与通达信差异=筹码C8/C9(见T006)."""
    conds = check_all_conditions(df, scr_value, winner_value)
    # C1-C7 必须(原生可复现); C8/C9 若有值则纳入, 无值则跳过(不阻塞)
    for key in ['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7']:
        if conds.get(key) is not True:
            return False, conds
    for key in ['C8', 'C9']:
        if conds.get(key) is False:  # 有值且不满足->不通过
            return False, conds
        # None(无值)或True->继续
    return True, conds


def filter_pool_qmt_native(pool_dict, scr_map=None, winner_map=None):
    """对整个pool做505(QMT原生)筛选. pool_dict={code: df}.
    返回通过code列表 + 每code条件结果dict."""
    scr_map = scr_map or {}
    winner_map = winner_map or {}
    passed = []
    detail = {}
    for code, df in pool_dict.items():
        if df is None or len(df) < 60:
            continue
        clean = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        ok, conds = passes_505_qmt_native(
            df, scr_value=scr_map.get(code) or scr_map.get(clean),
            winner_value=winner_map.get(code) or winner_map.get(clean))
        detail[code] = {'pass': ok, 'conds': conds}
        if ok:
            passed.append(code)
    return passed, detail


if __name__ == '__main__':
    # 自测: 用合成数据验证条件函数
    np.random.seed(1)
    n = 80
    close = pd.Series(np.cumsum(np.random.uniform(0.1, 0.4, n)) + 10)
    df = pd.DataFrame({
        'open': close - np.random.uniform(-0.1, 0.2, n),
        'high': close + np.random.uniform(0.05, 0.3, n),
        'low': close - np.random.uniform(0.05, 0.2, n),
        'close': close,
        'volume': pd.Series(np.random.uniform(1e6, 5e6, n)),
    })
    conds = check_all_conditions(df)
    print('=== whitebox_pool 自测(合成上涨数据) ===')
    for key, name, fn, native, overlap in CONDITIONS:
        print(f'  {key} {name}: {conds[key]}  (QMT原生={native})')
    ok, _ = passes_505_qmt_native(df)
    print(f'  505(QMT原生C1-C7)通过: {ok}')
    print('  注: C8/C9筹码需TDX外部值, 此处None=跳过')
