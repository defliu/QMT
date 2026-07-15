# coding=utf-8
"""板块热度更新脚本 - QMT数据源版(运行设备自给,不依赖astock)

用 xtquant.xtdata 取QMT本地缓存行情, 计算三因子加权板块热度.
运行设备(模拟端/实盘端)有QMT即可跑, 不需要本机astock数据.

三因子加权:
  热度 = 40% * 5日涨幅排名百分位 + 40% * 资金净流入排名百分位 + 20% * 成交额占比排名百分位

用法(在QMT运行设备上):
  D:\\国金证券QMT交易端\\bin.x64\\pythonw.exe scripts\\update_sector_heat_qmt.py
  或(模拟端):
  D:\\国金QMT交易端模拟\\bin.x64\\pythonw.exe scripts\\update_sector_heat_qmt.py

前置:
  - QMT终端已启动(xtdata连接本地终端取缓存数据)
  - D:/QMT_POOL/sector/*.txt 板块定义文件(从开发机复制一次即可, 不常变)
  - pandas(策略已依赖, QMT自带python有)

输出: D:/QMT_POOL/sector_heat.json (格式与astock版一致, 策略直接读)
"""
import os
import sys
import json
import math
from datetime import datetime

# pandas(策略已依赖, QMT设备有)
try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("[警告] 无pandas, 用纯Python模式(较慢)")

# xtquant(QMT自带)
try:
    from xtquant import xtdata
    HAS_XTDATA = True
except ImportError:
    HAS_XTDATA = False
    print("[错误] 无xtquant! 需在QMT设备(有bin.x64/pythonw.exe)上运行")
    sys.exit(1)

OUTPUT = "D:/QMT_POOL/sector_heat.json"
SECTOR_DIR = "D:/QMT_POOL/sector"
DAYS = 10
BATCH_SIZE = 200  # 批量取数, 避免一次性5000+超时


def get_all_stock_codes():
    """获取全A股代码(沪深A股)."""
    try:
        codes = xtdata.get_stock_list_in_sector('沪深A股')
        if not codes:
            # 回退: 用板块定义里的股票
            codes = get_sector_stock_codes()
        codes = [c for c in codes if c.endswith(('.SH', '.SZ'))]
        print("[代码] 全A股: %d 只" % len(codes))
        return codes
    except Exception as e:
        print("[警告] get_stock_list_in_sector失败: %s, 用板块定义股票" % e)
        return get_sector_stock_codes()


def get_sector_stock_codes():
    """从板块定义文件获取所有股票代码(回退方案)."""
    codes = set()
    sector_path = SECTOR_DIR
    if os.path.exists(sector_path):
        for f in os.listdir(sector_path):
            if f.endswith('.txt') and not f.startswith('_'):
                try:
                    for line in open(os.path.join(sector_path, f), 'r', encoding='utf-8'):
                        code = line.strip()
                        if code and code.endswith(('.SZ', '.SH', '.BJ')):
                            codes.add(code)
                except Exception:
                    continue
    print("[代码] 板块定义股票: %d 只" % len(codes))
    return list(codes)


def fetch_data_batch(codes):
    """批量取N天日线数据. 返回 {code: {close:[], open:[], vol:[], amount:[]}}."""
    all_data = {}
    total = len(codes)
    for i in range(0, total, BATCH_SIZE):
        batch = codes[i:i + BATCH_SIZE]
        try:
            # xtdata.get_market_data_ex(field_list, stock_list, period, count)
            # 返回格式: {code: DataFrame} 或 {field: {code: DataFrame}}
            result = xtdata.get_market_data_ex(
                ['close', 'open', 'vol', 'amount'],
                batch,
                period='1d',
                count=DAYS
            )
            if not result:
                continue
            # 解析返回格式
            if HAS_PANDAS and result:
                first_key = list(result.keys())[0]
                val = result[first_key]
                # 格式1: {code: DataFrame} (DataFrame有close/open/vol/amount列)
                if hasattr(val, 'columns') and 'close' in val.columns:
                    for code, df in result.items():
                        if df is not None and len(df) > 0:
                            all_data[code] = {
                                'close': df['close'].tolist() if 'close' in df else [],
                                'open': df['open'].tolist() if 'open' in df else [],
                                'vol': df['vol'].tolist() if 'vol' in df else [],
                                'amount': df['amount'].tolist() if 'amount' in df else [],
                            }
                # 格式2: {field: {code: DataFrame}} -> 转换
                elif isinstance(val, dict):
                    for code in batch:
                        try:
                            closes = result.get('close', {}).get(code)
                            opens = result.get('open', {}).get(code)
                            vols = result.get('vol', {}).get(code)
                            amounts = result.get('amount', {}).get(code)
                            if closes is not None and len(closes) > 0:
                                all_data[code] = {
                                    'close': list(closes.values) if hasattr(closes, 'values') else list(closes),
                                    'open': list(opens.values) if hasattr(opens, 'values') else (list(opens) if opens is not None else []),
                                    'vol': list(vols.values) if hasattr(vols, 'values') else (list(vols) if vols is not None else []),
                                    'amount': list(amounts.values) if hasattr(amounts, 'values') else (list(amounts) if amounts is not None else []),
                                }
                        except Exception:
                            continue
        except Exception as e:
            print("  批次 %d-%d 异常: %s" % (i, i + BATCH_SIZE, e))
            continue
        if (i // BATCH_SIZE) % 10 == 0:
            print("  数据加载: %d/%d (有效 %d)" % (min(i + BATCH_SIZE, total), total, len(all_data)))
    print("[数据] 有效股票: %d / %d" % (len(all_data), total))
    return all_data


def compute_5d_return(data):
    """5日涨幅(%)."""
    result = {}
    for code, d in data.items():
        closes = d['close']
        if len(closes) < 2:
            continue
        close_now = closes[-1]
        close_5d = closes[-min(6, len(closes))]
        if close_5d and close_5d > 0:
            result[code] = (close_now / close_5d - 1) * 100.0
    return result


def compute_net_inflow(data):
    """资金净流入(近似: vol * (close - open), 近5日累计)."""
    result = {}
    for code, d in data.items():
        closes = d['close']
        opens = d['open']
        vols = d['vol']
        if not closes or not opens or not vols:
            continue
        n = min(5, len(closes))
        inflow = 0.0
        for i in range(-n, 0):
            if abs(i) <= len(closes) and abs(i) <= len(opens) and abs(i) <= len(vols):
                if opens[i] and opens[i] > 0:
                    inflow += vols[i] * (closes[i] - opens[i])
        result[code] = inflow
    return result


def compute_amount_ratio(data):
    """成交额占比(%)."""
    totals = {}
    grand_total = 0.0
    for code, d in data.items():
        amounts = d['amount']
        if not amounts:
            continue
        s = sum(amounts)
        totals[code] = s
        grand_total += s
    if grand_total <= 0:
        return {}
    return {code: s / grand_total * 100.0 for code, s in totals.items()}


def rank_percentile(values):
    """值映射到0-100百分位(降序, 最高=100)."""
    if not values:
        return {}
    sorted_codes = sorted(values.keys(), key=lambda x: values[x])
    n = len(sorted_codes)
    result = {}
    for i, code in enumerate(sorted_codes):
        result[code] = (n - 1 - i) / (n - 1) * 100.0 if n > 1 else 50.0
    return result


def load_sector_defs():
    """加载板块定义 {板块名: [股票代码]}."""
    sectors = {}
    if not os.path.exists(SECTOR_DIR):
        print("[警告] 板块定义目录不存在: %s" % SECTOR_DIR)
        return sectors
    for f in os.listdir(SECTOR_DIR):
        if not f.endswith('.txt') or f.startswith('_'):
            continue
        try:
            codes = []
            for line in open(os.path.join(SECTOR_DIR, f), 'r', encoding='utf-8'):
                code = line.strip()
                if code and code.endswith(('.SZ', '.SH', '.BJ')):
                    codes.append(code)
            if len(codes) >= 5:
                sectors[f.replace('.txt', '')] = codes
        except Exception:
            continue
    print("[板块] 加载 %d 个板块定义" % len(sectors))
    return sectors


def main():
    print("=" * 60)
    print("  板块热度更新(QMT数据源版)")
    print("  %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    # 1. 连接QMT
    print("[连接] xtdata...")
    try:
        xtdata.connect()
        print("[连接] 成功")
    except Exception as e:
        print("[连接] 失败(可能已连或无需显式连接): %s" % e)

    # 2. 获取股票代码
    codes = get_all_stock_codes()
    if not codes:
        print("[错误] 无股票代码, 退出")
        sys.exit(1)

    # 3. 批量取数据
    print("[取数] 取最近%d天日线..." % DAYS)
    data = fetch_data_batch(codes)
    if not data:
        print("[错误] 无有效数据, 退出")
        sys.exit(1)

    # 4. 三因子计算
    print("[计算] 三因子加权...")
    ret_5d = compute_5d_return(data)
    net_inflow = compute_net_inflow(data)
    amount_ratio = compute_amount_ratio(data)
    print("  5日涨幅: %d 只" % len(ret_5d))
    print("  资金净流入: %d 只" % len(net_inflow))
    print("  成交额占比: %d 只" % len(amount_ratio))

    ret_rank = rank_percentile(ret_5d)
    inflow_rank = rank_percentile(net_inflow)
    amount_rank = rank_percentile(amount_ratio)

    all_codes = set(ret_5d.keys()) | set(net_inflow.keys()) | set(amount_ratio.keys())
    stock_heat = {}
    for code in all_codes:
        r = ret_rank.get(code, 50.0)
        i = inflow_rank.get(code, 50.0)
        a = amount_rank.get(code, 50.0)
        heat = 0.4 * r + 0.4 * i + 0.2 * a
        stock_heat[code] = round(heat, 2)

    # 5. 板块统计
    sectors = load_sector_defs()
    sector_heat = {}
    for name, sec_codes in sectors.items():
        heats = [stock_heat.get(c, 50.0) for c in sec_codes]
        if heats:
            sector_heat[name] = round(float(np.mean(heats)) if HAS_PANDAS else round(sum(heats) / len(heats), 2), 2)

    # 6. 验证分布
    values = list(stock_heat.values())
    if values:
        if HAS_PANDAS:
            arr = np.array(values)
            stats = {
                'median': round(float(np.median(arr)), 2),
                'mean': round(float(np.mean(arr)), 2),
                'min': round(float(np.min(arr)), 2),
                'max': round(float(np.max(arr)), 2),
                'std': round(float(np.std(arr)), 2),
                'total_count': len(values),
            }
        else:
            sv = sorted(values)
            n = len(sv)
            stats = {
                'median': round(sv[n // 2], 2),
                'mean': round(sum(sv) / n, 2),
                'min': round(sv[0], 2),
                'max': round(sv[-1], 2),
                'total_count': n,
            }
        print("\n[验证] 中位数: %.2f  均值: %.2f  股票数: %d" % (
            stats['median'], stats['mean'], stats['total_count']))

    # 7. 输出
    today = datetime.now().strftime("%Y%m%d")
    output = {
        "update_date": today,
        "stock_heat": stock_heat,
        "sector_stats": stats if values else {},
        "top_sectors": dict(sorted(sector_heat.items(), key=lambda x: -x[1])[:10]),
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("  更新完成(QMT数据源)!")
    print("  日期: %s" % today)
    print("  股票数: %d" % len(stock_heat))
    print("  板块数: %d" % len(sector_heat))
    print("  输出: %s" % OUTPUT)
    print("=" * 60)

    if sector_heat:
        print("\n  热门板块 Top-10:")
        for i, (name, heat) in enumerate(sorted(sector_heat.items(), key=lambda x: -x[1])[:10]):
            print("    %d. %-20s 热度: %.2f" % (i + 1, name, heat))


if __name__ == "__main__":
    main()
