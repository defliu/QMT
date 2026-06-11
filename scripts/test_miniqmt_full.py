# coding=utf-8
"""
MiniQMT 全流程集成测试脚本
1. 连接 MiniQMT（xtquant xtdata API）
2. 加载 D:/QMT_POOL/selected.txt 中的股票
3. 获取 120 根日 K 线
4. 初始化 ScoreCalculator8D 并逐股评分
5. 输出评分排名 + 策略状态

用法:
    python scripts/test_miniqmt_full.py

前置条件:
    - MiniQMT 数据服务已启动 (端口 58610)
    - Windows Python 3.10
"""

import os
import sys
import time
import traceback
from datetime import datetime

# ============================================================
#  路径常量
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

POOL_FILE = 'D:/QMT_POOL/selected.txt'
REQUIRED_BARS = 120
MIN_BARS = 60
MARKET_INDEX_CODE = '000001.SH'
MARKET_MA20 = 20
MARKET_MA60 = 60
CONNECT_TIMEOUT = 30  # MiniQMT 连接超时（秒）


# ============================================================
#  工具函数
# ============================================================

def _normalize_code(code):
    """规范化股票代码为 6位.SH/.SZ 格式。"""
    code = str(code).strip()
    if '.' in code.upper():
        return code.upper()
    if code.startswith(('6', '5', '9')):
        return code + '.SH'
    elif code.startswith(('0', '3', '2')):
        return code + '.SZ'
    elif code.startswith(('4', '8')):
        return code + '.BJ'
    return code


def load_pool(filepath):
    """加载股票池文件，返回规范化后的代码列表。"""
    if not os.path.exists(filepath):
        print("  [股票池] 文件不存在: %s" % filepath)
        return []

    codes = []
    with open(filepath, 'r', encoding='gbk', errors='ignore') as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            if '\t' in text:
                parts = text.split('\t')
                code = parts[0].strip()
            else:
                code = text
            std = _normalize_code(code)
            if std and std not in codes:
                codes.append(std)

    print("  [股票池] 加载 %d 只股票" % len(codes))
    return codes


def connect_miniqmt():
    """连接 MiniQMT 数据服务，返回是否成功。"""
    from xtquant import xtdata
    print("\n  [MiniQMT] 正在连接 (端口 58610)...")
    try:
        xtdata.connect(port=58610)
        print("  [MiniQMT] 连接成功")
        return True
    except Exception as e:
        print("  [MiniQMT] 连接失败: %s" % e)
        return False


def ensure_stock_data(stock_code):
    """确保本地有足够的历史K线数据，如有需要先下载。"""
    from xtquant import xtdata

    # 先尝试读取本地数据
    df = get_stock_data(stock_code)
    if df is not None:
        return df

    # 数据不足，下载
    from datetime import datetime, timedelta
    start = (datetime.now() - timedelta(days=400)).strftime('%Y%m%d')
    try:
        xtdata.download_history_data(stock_code, '1d', start)
    except Exception:
        pass

    # 下载后再尝试读取
    return get_stock_data(stock_code)


def get_index_data():
    """获取大盘指数数据用于市场系数计算。"""
    from xtquant import xtdata
    try:
        raw = xtdata.get_local_data(
            field_list=['open', 'high', 'low', 'close', 'volume'],
            stock_list=[MARKET_INDEX_CODE],
            period='1d',
            count=REQUIRED_BARS,
            dividend_type='front',
            fill_data=True,
        )
        if raw and MARKET_INDEX_CODE in raw:
            arr = raw[MARKET_INDEX_CODE]
            if arr is not None and len(arr) >= 60:
                import pandas as pd
                df = pd.DataFrame({
                    'open': arr['open'].astype(float),
                    'close': arr['close'].astype(float),
                    'high': arr['high'].astype(float),
                    'low': arr['low'].astype(float),
                    'volume': arr['volume'].astype(float),
                })
                if len(df) > REQUIRED_BARS:
                    df = df.iloc[-REQUIRED_BARS:]
                df.reset_index(drop=True, inplace=True)
                print("  [大盘] %s 数据已获取 (%d 条)" % (MARKET_INDEX_CODE, len(df)))
                return df
    except Exception as e:
        print("  [大盘] 获取失败: %s" % e)
    return None


def get_stock_data(stock_code):
    """获取单只股票的日 K 线数据。"""
    from xtquant import xtdata
    try:
        raw = xtdata.get_local_data(
            field_list=['open', 'high', 'low', 'close', 'volume'],
            stock_list=[stock_code],
            period='1d',
            count=REQUIRED_BARS,
            dividend_type='front',
            fill_data=True,
        )
        if raw and stock_code in raw:
            arr = raw[stock_code]
            if arr is not None and len(arr) >= MIN_BARS:
                import pandas as pd
                df = pd.DataFrame({
                    'open': arr['open'].astype(float),
                    'close': arr['close'].astype(float),
                    'high': arr['high'].astype(float),
                    'low': arr['low'].astype(float),
                    'volume': arr['volume'].astype(float),
                })
                if len(df) > REQUIRED_BARS:
                    df = df.iloc[-REQUIRED_BARS:]
                df.reset_index(drop=True, inplace=True)
                return df
    except Exception:
        pass
    return None


# ============================================================
#  主测试流程
# ============================================================

def main():
    print("=" * 60)
    print("  MiniQMT 全流程集成测试")
    print("  %s" % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("=" * 60)

    # ---- 阶段 1: 前置检查 ----
    print("\n[阶段 1/6] 前置检查")
    print("-" * 40)

    # Python 版本
    py_ver = sys.version
    print("  Python: %s" % py_ver.split()[0])

    # xtquant
    try:
        from xtquant import xtdata
        print("  xtquant: OK (%s)" % os.path.dirname(xtdata.__file__))
    except ImportError as e:
        print("  错误: xtquant 未安装: %s" % e)
        print("  请先运行: python scripts/setup_xtquant.py")
        sys.exit(1)

    # ---- 阶段 2: 连接 MiniQMT ----
    print("\n[阶段 2/6] 连接 MiniQMT 数据服务")
    print("-" * 40)
    if not connect_miniqmt():
        print("  无法连接 MiniQMT，退出测试")
        sys.exit(1)

    # ---- 阶段 3: 加载股票池 ----
    print("\n[阶段 3/6] 加载股票池")
    print("-" * 40)
    codes = load_pool(POOL_FILE)
    if not codes:
        print("  股票池为空，退出测试")
        sys.exit(1)
    print("  待评分: %d 只" % len(codes))

    # ---- 阶段 4: 获取数据 ----
    print("\n[阶段 4/6] 获取行情数据")
    print("-" * 40)

    # 逐股获取行情（必要时先下载）
    stock_data = {}
    stock_errors = []
    total = len(codes)
    for i, code in enumerate(codes, 1):
        print("  [%d/%d] %s" % (i, total, code), end=" ... ")
        sys.stdout.flush()
        try:
            df = ensure_stock_data(code)
            if df is not None and len(df) >= MIN_BARS:
                stock_data[code] = df
                print("OK (%d bars)" % len(df))
            else:
                msg = "数据不足 (%s)" % (len(df) if df is not None else 0)
                stock_errors.append((code, msg))
                print(msg)
        except Exception as e:
            msg = str(e).strip().split('\n')[0]
            stock_errors.append((code, msg))
            print("异常: %s" % msg)

    print("\n  数据获取完成: 成功 %d 只, 失败 %d 只" % (len(stock_data), len(stock_errors)))

    if not stock_data:
        print("  无可用数据，退出测试")
        sys.exit(1)

    # ---- 阶段 5: 6+2 评分 ----
    print("\n[阶段 5/6] 6+2 评分")
    print("-" * 40)

    from core.scoring.switch_scorer import SwitchScorer

    scorer = SwitchScorer(mode='6plus2')
    scored_results = []
    score_errors = []

    total_stocks = len(stock_data)
    for i, (code, df) in enumerate(stock_data.items(), 1):
        print("  [%d/%d] %s" % (i, total_stocks, code), end=" ... ")
        sys.stdout.flush()
        try:
            result = scorer.score_single(stock_code=code, df=df)
            scored_results.append((code, result))
            print("总分=%.1f" % result['score_total'])
        except Exception as e:
            detail = traceback.format_exc().split('\n')[-3]
            score_errors.append((code, detail))
            print("异常: %s" % detail)

    # 排序
    scored_results.sort(key=lambda x: x[1]['score_total'], reverse=True)

    print("\n  评分完成: 成功 %d 只, 失败 %d 只" % (len(scored_results), len(score_errors)))

    # ---- 阶段 6: 输出结果 ----
    print("\n[阶段 6/6] 结果报告")
    print("-" * 40)

    # Top 10 排名
    print("\n  ┌─ 评分排名 Top 10 " + "-" * 50)
    header = "  │ %s %s %s %s %s %s %s %s %s %s" % (
        '排名', '代码', '总分', '突破', '趋势', '回踩', '量价', 'MACD', '估值', '情绪+板块'
    )
    print(header)
    print("  │ " + "-" * 65)
    for rank, (code, r) in enumerate(scored_results[:10], 1):
        print("  │ %2d  %s %5.1f  %4.1f %4.1f %4.1f %4.1f %4.1f %4.1f  %4.1f+%4.1f" % (
            rank, code, r['score_total'],
            r.get('score_breakout', 0), r.get('score_trend', 0),
            r.get('score_consolidation', 0), r.get('score_volumeprice', 0),
            r.get('score_macd', 0), r.get('score_valuation', 0),
            r.get('score_sentiment', 0), r.get('score_sector', 0),
        ))
    if len(scored_results) > 10:
        print("  │   ... 还有 %d 只" % (len(scored_results) - 10))
    print("  └" + "-" * 65)

    # Top 1 详情
    if scored_results:
        print("\n  ┌─ 评分最高股票详情 " + "-" * 40)
        top_code, top_r = scored_results[0]
        print("  │ 代码:     %s" % top_code)
        print("  │ 评分器:   %s" % scorer.active_name)
        print("  │ 总分:     %.2f" % top_r['score_total'])
        for dim in ['score_breakout', 'score_trend', 'score_consolidation',
                     'score_volumeprice', 'score_macd', 'score_valuation',
                     'score_sentiment', 'score_sector']:
            print("  │   %s: %.1f" % (dim, top_r.get(dim, 0)))
        print("  └" + "-" * 52)

    # 尾部 Top 3 (最低分)
    if len(scored_results) >= 3:
        print("\n  ┌─ 评分最低 3 只 " + "-" * 50)
        for rank, (code, r) in enumerate(reversed(scored_results[-3:]), 1):
            print("  │ %d. %s  总分=%.1f" % (rank, code, r['score_total']))
        print("  └" + "-" * 60)

    # 评分统计
    if scored_results:
        scores = [r['score_total'] for _, r in scored_results]
        print("\n  评分统计:")
        print("    均值: %.1f" % (sum(scores) / len(scores)))
        print("    中位数: %.1f" % sorted(scores)[len(scores) // 2])
        print("    最高: %.1f  (%s)" % (scored_results[0][1]['score_total'], scored_results[0][0]))
        print("    最低: %.1f  (%s)" % (scored_results[-1][1]['score_total'], scored_results[-1][0]))

    # 策略状态
    print("\n  ┌─ 策略状态 " + "-" * 50)
    from adapters.qmt_wrapper import (
        ACCOUNT_ID, STRATEGY_CAPITAL, MAX_HOLD,
    )
    print("  │ 账号:       %s" % ACCOUNT_ID)
    print("  │ 策略本金:   %d" % STRATEGY_CAPITAL)
    print("  │ 持仓上限:   %d 只" % MAX_HOLD)
    print("  │ 评分日期:   %s" % datetime.now().strftime('%Y-%m-%d'))
    print("  └" + "-" * 60)

    # 异常汇总
    if stock_errors or score_errors:
        print("\n  ┌─ 异常汇总 " + "-" * 50)
        if stock_errors:
            print("  │  数据获取失败:")
            for code, err in stock_errors:
                print("  │    %s: %s" % (code, err))
        if score_errors:
            print("  │  评分失败:")
            for code, err in score_errors:
                print("  │    %s: %s" % (code, err))
        print("  └" + "-" * 60)

    # === 最终统计 ===
    print("\n" + "=" * 60)
    print("  测试完成")
    print("  总股票:  %d" % len(codes))
    print("  数据成功: %d" % len(stock_data))
    print("  数据失败: %d" % len(stock_errors))
    print("  评分成功: %d" % len(scored_results))
    print("  评分失败: %d" % len(score_errors))
    print("=" * 60)

    return 0 if len(scored_results) > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
