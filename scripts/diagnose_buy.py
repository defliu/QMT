# coding=utf-8
"""
诊断脚本：逐条件检查买入链路，定位0交易根因。

用法:
    cd /mnt/d/QMT_STRATEGIES && python3 scripts/diagnose_buy.py 2>&1 | tail -60

对 selected.txt 股票池，取 2023-01-01~2024-06-01 之间10个随机交易日，
逐只股票检查策略执行时的每个买入条件是否通过。
"""

import os, sys, math, random
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _strip_suffix(code: str) -> str:
    """移除 .SH/.SZ/.BJ 后缀，返回6位纯代码。"""
    code = code.upper()
    for s in ['.SH', '.SZ', '.BJ']:
        if code.endswith(s):
            return code[:-3]
    return code


def read_pool(path: str) -> list[str]:
    """
    读取 stock pool，返回 6 位纯代码列表。
    支持格式：
      - "600027<tab>名称..."
      - "600027.SH"
      - "600027"
    """
    codes = []
    with open(path, encoding='gbk') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = line.split('\t')[0].strip()
            raw = _strip_suffix(raw)
            if raw.isdigit() and len(raw) == 6:
                codes.append(raw)
    return codes


def download_mootdx(stock_codes: list[str], req_bars: int = 800):
    """
    通过 mootdx 下载日K线数据。
    返回 (all_data: {code6: DataFrame}, stock_names: {code6: str})
    """
    from mootdx.quotes import Quotes
    client = Quotes.factory(market='std')

    all_data = {}
    stock_names = {}

    # 批量获取名称
    try:
        for i in range(0, len(stock_codes), 200):
            batch = stock_codes[i:i + 200]
            q = client.quotes(symbol=batch)
            if q is not None and not q.empty:
                for _, row in q.iterrows():
                    if 'code' in q.columns and 'name' in q.columns:
                        c = str(row['code'])
                        n = str(row['name']).strip()
                        if c in stock_codes and n:
                            stock_names[c] = n
    except Exception:
        pass

    for code6 in stock_codes:
        try:
            df = client.bars(symbol=code6, category=4, offset=req_bars)
        except Exception as e:
            print(f"  [下载失败] {code6}: {e}")
            continue

        if df is None or df.empty:
            print(f"  [空数据] {code6}")
            continue

        # 列名统一
        if 'vol' in df.columns and 'volume' not in df.columns:
            df = df.rename(columns={'vol': 'volume'})
        elif 'vol' in df.columns and 'volume' in df.columns:
            df = df.drop(columns=['vol'])

        # 日期解析
        if 'datetime' in df.columns:
            df['_date'] = pd.to_datetime(df['datetime'].str[:10], errors='coerce')
            df.set_index('_date', inplace=True)
            df.drop(columns=['datetime'], inplace=True)
            df.index = df.index.normalize()
        df.sort_index(inplace=True)
        df = df[df.index.notna()]
        df = df[df['close'] > 0]

        if df.empty:
            print(f"  [过滤后空] {code6}")
            continue

        all_data[code6] = df

    return all_data, stock_names


def calc_conditions(df: pd.DataFrame, bar_idx: int):
    """
    在 df 的第 bar_idx 根K线处，检查买入条件。

    Returns:
        dict with keys:
          - 多头排列   (bool)  MA5 > MA10 > MA20
          - MA60方向   (bool)  MA60 >= prev_MA60 (走平或向上)
          - MA5角度    (float) 度数
          - 阳线       (bool)  close > open
          - 突破60日高 (bool)  close > 前60日最高close
          - 8D评分     (float) 若无数据返回 -1
          - 失败条件   (str)   未通过的条件名，逗号分隔
    """
    result = {
        '多头排列': False,
        'MA60方向': False,
        'MA5角度': -1.0,
        '阳线': False,
        '突破60日高': False,
        '8D评分': -1.0,
        '失败条件': '',
    }

    sub = df.iloc[:bar_idx + 1].copy()
    if len(sub) < 60:
        result['失败条件'] = 'K线<60'
        return result

    close = sub['close'].astype(float)
    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    c = float(close.iloc[-1])
    o = float(sub['open'].astype(float).iloc[-1])

    m5 = float(ma5.iloc[-1]) if not pd.isna(ma5.iloc[-1]) else 0
    m10 = float(ma10.iloc[-1]) if not pd.isna(ma10.iloc[-1]) else 0
    m20 = float(ma20.iloc[-1]) if not pd.isna(ma20.iloc[-1]) else 0
    m60 = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else 0

    # 多头排列: MA5 > MA10 > MA20
    result['多头排列'] = (m5 > m10 > m20)

    # MA60方向: 走平或向上 (允许 0.5% 容差)
    if len(ma60) >= 2:
        m60_prev = float(ma60.iloc[-2]) if not pd.isna(ma60.iloc[-2]) else 0
        result['MA60方向'] = (m60 >= m60_prev * 0.995)
    else:
        result['MA60方向'] = False

    # MA5角度 (度数)
    if len(ma5) >= 6:
        m5_prev = float(ma5.iloc[-6])
        if m5_prev > 0:
            pct = (m5 - m5_prev) / m5_prev * 100
            result['MA5角度'] = round(float(np.degrees(np.arctan(pct))), 2)
        else:
            result['MA5角度'] = 0.0
    else:
        result['MA5角度'] = 0.0

    # 阳线
    result['阳线'] = (c > o)

    # 突破60日高: close > 前60日最高close, 且前一日 <= 前60日最高
    if len(close) >= 61:
        prev_60d_high = float(close.iloc[-(61):-1].max())
        prev_c = float(close.iloc[-2])
        result['突破60日高'] = (c > prev_60d_high and prev_c <= prev_60d_high)
    else:
        result['突破60日高'] = False

    # ---- 8D评分 ----
    try:
        from core.signal_main_rise import ScoreCalculator8D
        scorer = ScoreCalculator8D()
        score_result = scorer.total_score(df=sub, stock_code=None)
        result['8D评分'] = score_result.get('final_total', -1.0)
    except Exception:
        result['8D评分'] = -1.0

    # 收集失败条件
    failed = []
    if not result['多头排列']:
        failed.append(f"多头排列(MA5={m5:.2f} MA10={m10:.2f} MA20={m20:.2f})")
    if not result['MA60方向']:
        failed.append(f"MA60方向(当前{m60:.2f})")
    if result['MA5角度'] < 30:
        failed.append(f"MA5角度({result['MA5角度']:.1f}°<30°)")
    if not result['阳线']:
        failed.append(f"非阳线(C{c:.2f}<O{o:.2f})")
    if not result['突破60日高']:
        failed.append(f"未突破60日高")

    result['失败条件'] = ' | '.join(failed) if failed else '无'
    return result


def sample_trading_days(all_dates: list, n: int = 10, seed: int = 42):
    """从交易日序列中随机取 n 个。"""
    if len(all_dates) <= n:
        return all_dates
    rng = np.random.default_rng(seed)
    indices = sorted(rng.choice(len(all_dates), n, replace=False))
    return [all_dates[i] for i in indices]


def main():
    POOL_PATH = 'D:/QMT_POOL/selected.txt'
    START = '2023-01-01'
    END = '2024-06-01'
    N_SAMPLES = 10
    REQ_BARS = 800

    print("=" * 70)
    print("  买入条件诊断 — 逐条件追踪")
    print(f"  周期: {START} ~ {END}  取样: {N_SAMPLES}个交易日")
    print("=" * 70)

    # 1. 读取股票池
    print(f"\n[1/4] 读取股票池: {POOL_PATH}")
    stock_codes = read_pool(POOL_PATH)
    print(f"  解析到 {len(stock_codes)} 只股票")

    # 2. 下载数据
    print(f"\n[2/4] 下载日K线 (mootdx, {REQ_BARS}根)")
    all_data, stock_names = download_mootdx(stock_codes, REQ_BARS)
    valid_codes = sorted(all_data.keys())
    print(f"  成功下载: {len(valid_codes)}/{len(stock_codes)} 只")

    if not valid_codes:
        print("  [致命] 无任何数据，退出")
        return 1

    # 3. 确定共同交易日范围
    print(f"\n[3/4] 确定取样交易日")
    # 找一只数据最全的股票作为交易日基准
    ref_code = max(valid_codes, key=lambda c: len(all_data[c]))
    all_dates = [d.strftime('%Y-%m-%d') for d in all_data[ref_code].index
                 if START <= d.strftime('%Y-%m-%d') <= END]
    print(f"  基准股票: {ref_code}, 周期内交易日: {len(all_dates)}")

    if len(all_dates) < N_SAMPLES:
        print(f"  [警告] 交易日不足{N_SAMPLES}个，改用全部")
        sample_dates = all_dates
    else:
        sample_dates = sample_trading_days(all_dates, N_SAMPLES)
    print(f"  取样交易日: {sample_dates}")

    # 4. 逐条件检查
    print(f"\n[4/4] 逐条件检查 ({len(valid_codes)}只 x {len(sample_dates)}天)")

    COND_KEYS = ['多头排列', 'MA60方向', 'MA5角度', '阳线', '突破60日高', '8D评分']

    # 统计累计
    total_checks = 0
    cond_fails = {k: 0 for k in COND_KEYS}
    all_pass_count = 0

    # 输出表头
    header = (f"{'股票':<8} {'日期':<11} {'多头排列':<8} {'MA60方向':<8} "
              f"{'MA5角度':<8} {'阳线':<8} {'突破60日高':<10} {'8D评分':<8} {'失败条件'}")
    sep = '-' * len(header)
    print(f"\n{header}")
    print(sep)

    # 逐只股票统计
    stock_stats = {}

    for code6 in valid_codes:
        df = all_data[code6]
        name = stock_names.get(code6, code6)
        stock_pass = 0
        stock_total = 0
        stock_fails = {}

        for date_str in sample_dates:
            # 找到该日期在 df 中的位置
            date_match = df.index[df.index.strftime('%Y-%m-%d') == date_str]
            if len(date_match) == 0:
                continue
            bar_idx = df.index.get_loc(date_match[0])

            conds = calc_conditions(df, bar_idx)

            total_checks += 1
            stock_total += 1

            all_pass = all(conds[k] for k in ['多头排列', 'MA60方向', '阳线', '突破60日高']
                           if k != 'MA5角度' and k != '8D评分') and conds['MA5角度'] >= 30

            # 更新条件级统计：仅对 boolean 条件统计
            for k in COND_KEYS:
                if k == 'MA5角度':
                    if conds[k] < 30:
                        cond_fails[k] = cond_fails.get(k, 0) + 1
                elif k == '8D评分':
                    if conds[k] < 60:
                        cond_fails[k] = cond_fails.get(k, 0) + 1
                else:
                    if not conds[k]:
                        cond_fails[k] = cond_fails.get(k, 0) + 1

            if all_pass:
                all_pass_count += 1
                stock_pass += 1
            else:
                # 记录首失败条件
                fail_reason = conds['失败条件']
                for fk in COND_KEYS:
                    if fk == 'MA5角度' and conds[fk] < 30:
                        stock_fails[fk] = stock_fails.get(fk, 0) + 1
                    elif fk == '8D评分' and conds[fk] < 60:
                        stock_fails[fk] = stock_fails.get(fk, 0) + 1
                    elif fk not in ('MA5角度', '8D评分') and not conds[fk]:
                        stock_fails[fk] = stock_fails.get(fk, 0) + 1

            # 输出行
            row = (f"{code6:<8} {date_str:<11} "
                   f"{'1' if conds['多头排列'] else '0':<8} "
                   f"{'1' if conds['MA60方向'] else '0':<8} "
                   f"{conds['MA5角度']:<8.1f} "
                   f"{'1' if conds['阳线'] else '0':<8} "
                   f"{'1' if conds['突破60日高'] else '0':<10} "
                   f"{conds['8D评分']:<8.1f} "
                   f"{conds['失败条件']}")
            if all_pass:
                # 标记通过的行为绿色 ✓ (不使用 emoji,用文本)
                row += "  PASS"
            print(row)

        stock_stats[code6] = {
            'name': name,
            'pass': stock_pass,
            'total': stock_total,
            'fails': stock_fails,
        }

    # ============ 统计汇总 ============
    print(f"\n{'=' * 70}")
    print("  统计汇总")
    print(f"{'=' * 70}")

    total = total_checks
    print(f"\n  总检查次数: {total}")
    print(f"  全部条件通过: {all_pass_count}/{total} = {all_pass_count / total * 100:.1f}%" if total > 0 else "  全部条件通过: 0")

    # 各条件失败率
    print(f"\n  {'条件':<14} {'失败率':>8} {'失败/总':>12}")
    print(f"  {'-' * 36}")
    for k in COND_KEYS:
        fail = cond_fails.get(k, 0)
        rate = fail / total * 100 if total > 0 else 0
        bar = '#' * max(1, int(rate / 4))
        print(f"  {k:<14} {rate:>7.1f}%  {fail:>4}/{total:<4}  {bar}")

    # 按股票汇总
    print(f"\n  {'代码':<8} {'名称':<8} {'通过/总':<10} {'通过率':<8} {'主要卡点'}")
    print(f"  {'-' * 50}")
    for code6 in valid_codes:
        s = stock_stats.get(code6, {})
        pt = f"{s.get('pass', 0)}/{s.get('total', 0)}"
        rate = s['pass'] / s['total'] * 100 if s.get('total', 0) > 0 else 0
        # 找出该股票最常见的失败条件 (top 2)
        fails = s.get('fails', {})
        top_fails = sorted(fails.items(), key=lambda x: -x[1])[:2]
        fail_str = ', '.join(f'{k}({v})' for k, v in top_fails) if top_fails else '-'
        print(f"  {code6:<8} {s.get('name', ''):<8} {pt:<10} {rate:>5.1f}%   {fail_str}")

    # 瓶颈排名
    print(f"\n  瓶颈排名 (按失败率):")
    bottlenecks = sorted(
        [(k, cond_fails.get(k, 0) / total) for k in COND_KEYS],
        key=lambda x: -x[1]
    )
    for k, rate in bottlenecks:
        if rate > 0.2:
            print(f"    ** {k}: {rate * 100:.1f}%")
    for k, rate in bottlenecks:
        if rate <= 0.2:
            print(f"       {k}: {rate * 100:.1f}%")

    print(f"\n  [注意] 诊断使用 mootdx 数据源, 可能与前复权实盘数据有偏差")
    print(f"         周期内{len(sample_dates)}个随机交易日，非连续回测")
    print(f"{'=' * 70}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
