# coding=utf-8
"""
QMT 策略端到端测试
完整链路: 连接 MiniQMT → 拉真实行情K线 → 跑 core/ 选股+打分+信号检测 → 输出HTML测试报告

用法:
    python scripts/run_integration_test.py

前置条件:
    - MiniQMT 已启动 (检查进程)
    - xtquant 已安装 (pip install xtquant 或运行 setup_xtquant.py)
"""

import os
import sys
import yaml
from datetime import datetime

# 确保能找到策略源码目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============================================================
#  路径常量
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'global_config.yaml')
REPORT_PATH = os.path.join(BASE_DIR, 'integration_report.html')
POOL_FILE = 'D:/QMT_POOL/selected.txt'
SECTOR_HEAT_FILE = 'D:/QMT_POOL/sector_heat.json'

# ============================================================
#  沪深300 备选股票池（完整列表，当 selected.txt 不存在时使用）
# ============================================================

HS300_FALLBACK = [
    '600519.SH', '601318.SH', '600036.SH', '000858.SZ', '002415.SZ',
    '600276.SH', '600887.SH', '601166.SH', '000333.SZ', '600030.SH',
    '601398.SH', '600900.SH', '002594.SZ', '000651.SZ', '601288.SH',
    '600809.SH', '002714.SZ', '000001.SZ', '601012.SH', '600585.SH',
    '601328.SH', '600031.SH', '600000.SH', '601989.SH', '002352.SZ',
    '300760.SZ', '601816.SH', '002475.SZ', '688981.SH', '600690.SH',
    '600309.SH', '600436.SH', '000568.SZ', '601899.SH', '002304.SZ',
    '601857.SH', '688041.SH', '600028.SH', '000792.SZ', '000002.SZ',
    '300750.SZ', '601088.SH', '600104.SH', '601888.SH', '002230.SZ',
    '000725.SZ', '600048.SH', '688012.SH', '600660.SH', '002142.SZ',
    '600016.SH', '600015.SH', '002311.SZ', '601668.SH', '600041.SH',
    '601601.SH', '601628.SH', '600547.SH', '601390.SH', '688111.SH',
]


# ============================================================
#  阶段0: 前置检查
# ============================================================

def preflight_checks():
    """执行前置检查，返回是否继续。"""
    print("=" * 60)
    print("QMT 策略端到端测试 v1.0")
    print("=" * 60)

    # 检查 xtquant
    print("\n[检查] xtquant 模块 ...")
    try:
        from xtquant import xtdata
        print("  OK")
    except ImportError:
        print("  未安装 xtquant。请先运行: python scripts/setup_xtquant.py")
        print("  或手动复制 xtquant 到 site-packages。")
        return False

    # 检查 MiniQMT 进程
    print("\n[检查] MiniQMT 进程 ...")
    if not _is_miniqmt_running():
        print("  MiniQMT 未运行。")
        print("  请先启动 MiniQMT 交易终端，然后再运行本脚本。")
        return False
    print("  OK")

    # 检查配置文件
    print("\n[检查] 配置文件 ...")
    if not os.path.exists(CONFIG_PATH):
        print("  未找到: %s" % CONFIG_PATH)
        return False
    print("  OK: %s" % CONFIG_PATH)

    return True


def _is_miniqmt_running():
    """检查 MiniQMT 进程是否在运行。"""
    try:
        import subprocess
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq XtMiniQmt.exe'],
            capture_output=True, text=True, timeout=5
        )
        return 'XtMiniQmt.exe' in result.stdout
    except Exception:
        return False


# ============================================================
#  阶段1: 加载配置和股票池
# ============================================================

def load_config():
    """加载全局配置。"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _normalize_code(code):
    """将股票代码规范化为 xtquant 格式:
    6位数字 + .SH/.SZ 后缀
    """
    code = code.strip()
    if '.' in code.upper():
        # 已经带后缀
        return code.upper()
    if code.startswith(('6', '9')):
        return code + '.SH'
    elif code.startswith(('0', '3', '2')):
        return code + '.SZ'
    return code


def load_stock_pool():
    """加载股票池，如果 selected.txt 不存在则使用沪深300。"""
    stocks = []
    if os.path.exists(POOL_FILE):
        print("\n[股票池] 加载: %s" % POOL_FILE)
        with open(POOL_FILE, 'r', encoding='gbk') as f:
            for line in f:
                parts = line.strip().split('\t')
                if parts and parts[0].strip():
                    code = _normalize_code(parts[0])
                    stocks.append(code)
        stocks = list(dict.fromkeys(stocks))  # 去重保持顺序
        print("  读取 %d 只股票" % len(stocks))
    else:
        print("\n[股票池] %s 不存在，使用沪深300备选池 (%d 只)" % (POOL_FILE, len(HS300_FALLBACK)))
        stocks = list(HS300_FALLBACK)

    return stocks


# ============================================================
#  阶段2: 数据拉取与分析
# ============================================================

def ensure_data(stock_code):
    """确保本地有足够的历史K线数据。"""
    from xtquant import xtdata
    try:
        # 尝试直接读取本地数据
        df = xtdata.get_local_data(
            field_list=['open', 'close', 'high', 'low', 'volume'],
            stock_list=[stock_code],
            period='1d',
            count=150,
            dividend_type='front',
        )
        if df and stock_code in df and len(df[stock_code]) >= 60:
            return True

        # 数据不足，下载
        from datetime import datetime, timedelta
        start = (datetime.now() - timedelta(days=400)).strftime('%Y%m%d')
        xtdata.download_history_data(stock_code, '1d', start)
        return True
    except Exception:
        return False


def pull_klines(stock_code):
    """拉取120根日K线（前复权），返回 DataFrame。"""
    from xtquant import xtdata

    df_raw = xtdata.get_local_data(
        field_list=['open', 'close', 'high', 'low', 'volume', 'amount'],
        stock_list=[stock_code],
        period='1d',
        count=150,
        dividend_type='front',
    )

    if not df_raw or stock_code not in df_raw:
        return None

    arr = df_raw[stock_code]
    if arr is None or len(arr) < 60:
        return None

    import pandas as pd
    import numpy as np

    # 转换为 DataFrame
    df = pd.DataFrame({
        'open': arr['open'].astype(float),
        'close': arr['close'].astype(float),
        'high': arr['high'].astype(float),
        'low': arr['low'].astype(float),
        'volume': arr['volume'].astype(float),
    })

    # 截取最近120根
    if len(df) > 120:
        df = df.iloc[-120:]

    # 重置索引
    df.reset_index(drop=True, inplace=True)
    return df


def get_stock_name(stock_code):
    """通过 xtquant 获取股票名称。"""
    from xtquant import xtdata
    try:
        detail = xtdata.get_instrument_detail(stock_code)
        if detail:
            return detail.get('InstrumentName', stock_code)
    except Exception:
        pass
    return stock_code


def analyze_stock(stock_code, scorer, index_close, index_ma20, index_ma60):
    """对单只股票跑完整分析链路。"""
    result = {
        'code': stock_code,
        'name': stock_code,
        'pool_signal': False,
        'buy_signal': False,
        'buy_type': None,
        'buy_reason': '',
        'score_detail': {},
        'final_score': 0,
        'rating': 'D',
        'error': None,
    }

    try:
        # 获取股票名称
        result['name'] = get_stock_name(stock_code)

        # 拉数据
        df = pull_klines(stock_code)
        if df is None:
            result['error'] = '数据不足'
            return result

        # a. 筹码密集突破选股
        from core.pool_filter import select_breakout_stocks
        pool_ok = select_breakout_stocks(df)
        result['pool_signal'] = pool_ok

        # b. 主升浪买点信号
        from core.signal_main_rise import check_buy
        buy_ok, reason, buy_type = check_buy(df)
        result['buy_signal'] = buy_ok
        result['buy_reason'] = reason
        result['buy_type'] = buy_type

        # c. 8D 打分系统
        from core.signal_main_rise import ScoreCalculator8D
        score_dict = scorer.total_score(
            df, stock_code=stock_code,
            index_close=index_close,
            index_ma20=index_ma20,
            index_ma60=index_ma60,
        )
        result['score_detail'] = score_dict
        result['final_score'] = score_dict.get('final_total', 0)
        result['rating'] = score_dict.get('rating', 'D')

    except Exception as e:
        result['error'] = str(e)

    return result


def get_index_data():
    """获取大盘指数数据进行市场系数计算。"""
    try:
        df = pull_klines('000001.SH')
        if df is not None and len(df) >= 60:
            close = df['close'].iloc[-1]
            ma20 = df['close'].rolling(20).mean().iloc[-1]
            ma60 = df['close'].rolling(60).mean().iloc[-1]
            return close, ma20, ma60
    except Exception:
        pass
    return None, None, None


# ============================================================
#  阶段2b: 卖出信号检测 (仅触发信号的股票)
# ============================================================

def check_sell_signals(stock_code):
    """卖出信号检测（简化版，仅检查是否有卖出信号模块可用）。"""
    try:
        from core.risk_manager import StrategyRiskManager
        return '有卖出模块 (StrategyRiskManager)'
    except ImportError:
        return '无专用卖出模块'
    except Exception as e:
        return '检查异常: %s' % e


# ============================================================
#  阶段3: HTML 报告生成
# ============================================================

def generate_report(results, stock_count):
    """生成 HTML 测试报告。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    # 统计
    triggered_pool = [r for r in results if r.get('pool_signal')]
    triggered_buy = [r for r in results if r.get('buy_signal')]
    scored = [r for r in results if r.get('final_score', 0) > 0]
    errored = [r for r in results if r.get('error')]

    pool_rate = len(triggered_pool) / len(results) * 100 if results else 0
    buy_rate = len(triggered_buy) / len(results) * 100 if results else 0
    avg_score = sum(r.get('final_score', 0) for r in scored) / len(scored) if scored else 0

    rows_html = ''
    for r in results:
        pool_mark = 'O' if r.get('pool_signal') else '-'
        buy_mark = r.get('buy_type', '-') or '-'
        score = r.get('final_score', 0)
        rating = r.get('rating', 'D')
        reason = r.get('buy_reason', '')
        err = r.get('error', '')
        name = r.get('name', r['code'])
        row_class = ' class="signal"' if r.get('buy_signal') else (' class="pooled"' if r.get('pool_signal') else '')

        rows_html += '''
        <tr{row_class}>
            <td>{code}</td>
            <td>{name}</td>
            <td>{pool}</td>
            <td>{buy}</td>
            <td>{score}</td>
            <td>{rating}</td>
            <td>{reason}</td>
            <td class="err">{err}</td>
        </tr>'''.format(
            row_class=row_class,
            code=r['code'],
            name=name[:8],
            pool=pool_mark,
            buy=buy_mark,
            score='%.1f' % score if score else '-',
            rating=rating,
            reason=reason or '-',
            err=err or '-',
        )

    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>QMT 策略端到端测试报告</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; margin: 20px; background: #f5f7fa; }}
h1 {{ color: #1a1a2e; }}
.container {{ max-width: 1200px; margin: 0 auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
.summary {{ display: flex; gap: 20px; margin: 20px 0; flex-wrap: wrap; }}
.card {{ background: #e8ecf4; padding: 12px 20px; border-radius: 6px; min-width: 140px; }}
.card .num {{ font-size: 24px; font-weight: bold; color: #1a1a2e; }}
.card .label {{ font-size: 12px; color: #666; }}
table {{ width: 100%%; border-collapse: collapse; margin-top: 16px; }}
th {{ background: #2c3e50; color: #fff; padding: 10px 8px; text-align: left; font-size: 13px; }}
td {{ padding: 8px; border-bottom: 1px solid #eee; font-size: 13px; }}
tr:hover {{ background: #f0f4ff; }}
tr.signal {{ background: #e8f5e9; }}
tr.pooled {{ background: #fff8e1; }}
.err {{ color: #999; font-size: 12px; }}
</style>
</head>
<body>
<div class="container">
<h1>QMT 策略端到端测试报告</h1>
<p>测试时间: {time}</p>
<p>股票池: {base} | 扫描: {total}只 | 触发选股: {pool_count}只 | 触发买点: {buy_count}只 | 异常: {err_count}只</p>

<div class="summary">
<div class="card"><div class="num">{total}</div><div class="label">扫描股票</div></div>
<div class="card"><div class="num">{pool_count}</div><div class="label">触发选股</div></div>
<div class="card"><div class="num">{buy_count}</div><div class="label">触发买点</div></div>
<div class="card"><div class="num">{avg_score:.1f}</div><div class="label">平均评分</div></div>
<div class="card"><div class="num">{pool_rate:.1f}%%</div><div class="label">选股通过率</div></div>
<div class="card"><div class="num">{buy_rate:.1f}%%</div><div class="label">买点触发率</div></div>
</div>

<table>
<tr><th>代码</th><th>名称</th><th>选股信号</th><th>买点</th><th>评分</th><th>评级</th><th>理由</th><th>异常</th></tr>
{rows}
</table>

<h2>汇总</h2>
<p>选股通过率: {pool_rate:.1f}% ({pool_count}/{total})</p>
<p>买点触发率: {buy_rate:.1f}% ({buy_count}/{total})</p>
<p>平均评分: {avg_score:.1f}</p>
<p>异常股票数: {err_count}</p>
</div>
</body>
</html>'''.format(
        time=now,
        base='沪深A股' if not os.path.exists(POOL_FILE) else POOL_FILE,
        total=len(results),
        pool_count=len(triggered_pool),
        buy_count=len(triggered_buy),
        err_count=len(errored),
        pool_rate=pool_rate,
        buy_rate=buy_rate,
        avg_score=avg_score,
        rows=rows_html,
    )

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)

    return REPORT_PATH


# ============================================================
#  主流程
# ============================================================

def main():
    if not preflight_checks():
        sys.exit(0)  # 不崩溃，友好退出

    # 阶段1: 配置和股票池
    print("\n[阶段1] 加载配置和股票池")
    config = load_config()
    print("  策略: %s" % config.get('strategy', {}).get('name', 'unknown'))

    stock_pool = load_stock_pool()
    if not stock_pool:
        print("  股票池为空，无法继续。")
        sys.exit(0)

    # 大盘数据
    print("\n[大盘] 获取指数数据 ...")
    idx_close, idx_ma20, idx_ma60 = get_index_data()
    if idx_close:
        print("  上证指数: %.2f  MA20: %.2f  MA60: %.2f" % (idx_close, idx_ma20, idx_ma60))
    else:
        print("  无法获取指数数据，使用默认市场系数")

    # 阶段2: 分析
    print("\n[阶段2] 逐只分析股票 (共 %d 只)" % len(stock_pool))

    from core.signal_main_rise import ScoreCalculator8D
    scorer = ScoreCalculator8D()

    # 尝试加载板块热度
    if os.path.exists(SECTOR_HEAT_FILE):
        scorer.load_sector_heat_from_file(SECTOR_HEAT_FILE)

    results = []
    for i, code in enumerate(stock_pool):
        sys.stdout.write("\r  分析中 [%d/%d] %s ... " % (i + 1, len(stock_pool), code))
        sys.stdout.flush()
        result = analyze_stock(code, scorer, idx_close, idx_ma20, idx_ma60)
        results.append(result)

    print("\n  完成!")

    # 额外卖出信号检测
    print("\n[卖出检测] 对触发信号的股票 ...")
    triggered = [r for r in results if r.get('buy_signal') or r.get('pool_signal')]
    for r in triggered:
        sell_info = check_sell_signals(r['code'])
        r['sell_info'] = sell_info
        if triggered:
            print("  %s: %s" % (r['code'], sell_info))

    # 阶段3: 报告
    print("\n[阶段3] 生成 HTML 报告 ...")
    report_path = generate_report(results, len(stock_pool))
    print("  报告已生成: %s" % report_path)

    # 控制台摘要
    triggered_pool = [r for r in results if r.get('pool_signal')]
    triggered_buy = [r for r in results if r.get('buy_signal')]
    errored = [r for r in results if r.get('error')]
    print("\n" + "=" * 60)
    print("测试完成")
    print("  扫描: %d 只" % len(results))
    print("  触发选股: %d 只" % len(triggered_pool))
    print("  触发买点: %d 只" % len(triggered_buy))
    print("  异常: %d 只" % len(errored))
    if triggered_buy:
        print("\n买点触发股票:")
        for r in triggered_buy:
            print("  %s %s | 评分: %.1f | 评级: %s | %s" % (
                r['code'], r.get('name', ''), r.get('final_score', 0),
                r.get('rating', 'D'), r.get('buy_reason', '')))
    if errored:
        print("\n异常股票:")
        for r in errored:
            print("  %s: %s" % (r['code'], r['error']))

    print("\n报告文件: %s" % report_path)


if __name__ == '__main__':
    main()
