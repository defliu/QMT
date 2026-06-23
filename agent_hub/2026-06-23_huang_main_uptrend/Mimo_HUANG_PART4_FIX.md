# MIMO 工单：黄氏 combo 回测 Part 4 — 修复股池 + 大盘指数 + 重跑

## 目的

Part 3 commit `16c15d5` 跑完出 **0 信号** —— CC 验收时定位 2 个根因，本工单修复：

1. **大盘指数数据缺失 1.5 年**：用的 `benchmark_index.duckdb` 只覆盖 2025-01 起，导致 2023-06~2024-12 段 `double_大盘_ok` 全 False
   - **修复**：改读 huicexitong `basic_data."板块指数"` 表（覆盖 2004 起，3 年完整）
2. **股池与策略不匹配**：core_100 全是大盘蓝筹（茅台/宁德等），日涨幅 >5% 全程只有 7 次；黄氏策略原本针对小盘高波动股
   - **修复**：构造中小盘股池（流通市值 <100 亿）≈ 3800 只

selector 代码**不改**（公式已 SPEC 锁定，PART 2 已 commit）。

**前置 commit**: `16c15d5`
**预计工时**: 30-45 分钟

---

## 一、必做（7 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/ adapters/ strategy_main.py
git log -1 --oneline
```

期望：HEAD = `16c15d5`，无 dirty 文件。**如果有 dirty 立刻停下报告**。

### TASK-2. 修改 `huang_main_uptrend_combo/backtest/huice_loader.py`

**只改 `load_benchmark_index`，不改 OHLCV 加载器**。

定位（精确字符串，整个 `load_benchmark_index` 函数 + `BENCH_DB` 常量）：

```python
BENCH_DB = 'F:/backtest_workspace/data/duckdb/benchmark_index.duckdb'
```

替换为：

```python
# BENCH_DB 原为 F:/backtest_workspace/data/duckdb/benchmark_index.duckdb (只覆盖 2025-01 起)
# Part 4 改用 huicexitong basic_data."板块指数" (000001.SH 覆盖 2004-01 起)
# 字段: 收盘价 (收盘价); 表: 板块指数
```

然后定位 `load_benchmark_index` 函数整体：

```python
def load_benchmark_index(code, start_date, end_date, db_path=BENCH_DB):
    """读大盘指数, 返回 DataFrame(index=date, columns=[close]).
    走 benchmark_index.duckdb (BenchmarkIndexReader 同一文件, 但本模块直接 sql 取 close).
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        # benchmark schema 见 sync_xtquant_index_to_duckdb.py: trade_date / code / close
        rows = con.execute(
            'SELECT trade_date, close FROM index_daily '
            'WHERE code = ? AND trade_date BETWEEN ? AND ? '
            'ORDER BY trade_date',
            [code, start_date, end_date]
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise ValueError('benchmark %s 无数据 (%s ~ %s)' % (code, start_date, end_date))
    df = pd.DataFrame(rows, columns=['date', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df
```

替换为：

```python
# huicexitong 板块指数表名 + 收盘价列名 (中文 via \u escape)
_T_INDEX = '板块指数'  # 板块指数
_C_INDEX_CLOSE = '收盘价'  # 收盘价


def load_benchmark_index(code, start_date, end_date, db_path=HUICE_DB):
    """读大盘指数, 返回 DataFrame(index=date, columns=[close]).

    Part 4: 改用 huicexitong basic_data."板块指数" 表 (000001.SH 覆盖 2004 起).
    旧 F:/backtest_workspace/data/duckdb/benchmark_index.duckdb 只覆盖 2025-01 起,
    用它会让 2023-06~2024-12 段 selector 的 double_大盘_ok 全 False.
    """
    con = duckdb.connect(db_path, read_only=True)
    try:
        q = (
            'SELECT "%s" AS date, "%s" AS close '
            'FROM basic_data."%s" '
            'WHERE "%s" = ? AND "%s" BETWEEN ? AND ? '
            'ORDER BY "%s"'
        ) % (
            C_DATE, _C_INDEX_CLOSE,
            _T_INDEX,
            C_CODE, C_DATE,
            C_DATE,
        )
        rows = con.execute(q, [code, start_date, end_date]).fetchall()
    finally:
        con.close()
    if not rows:
        raise ValueError('benchmark %s 无数据 (%s ~ %s)' % (code, start_date, end_date))
    df = pd.DataFrame(rows, columns=['date', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df
```

### TASK-3. 新增中小盘股池构造脚本 `huang_main_uptrend_combo/backtest/build_universe_small_mid.py`

**编码 utf-8**。

```python
# coding=utf-8
"""构造中小盘股池: 流通市值 < 100亿 (1,000,000 万元) 的活股.
取最近一日的市值快照, 过滤 ST/退市股, 写到 backtest/data/universe/huang_small_mid_<date>.csv.

边界:
- read_only huicexitong
- 写到 D:/QMT_STRATEGIES/backtest/data/universe/ (源码区, 与现有 core_100.csv 同位)
- 不下单 / 不接 QMT
"""
import sys, os, argparse
from datetime import datetime
sys.path.insert(0, 'D:/QMT_STRATEGIES')

import duckdb
import pandas as pd

from backtest.data_tools._huicexitong_names import T_DAILY, C_CODE, C_DATE

HUICE_DB = 'E:/huicexitong/runtime/sj/gpsj.duckdb'
UNIVERSE_DIR = 'D:/QMT_STRATEGIES/backtest/data/universe'

# 中文字段名 (via \u escape)
_C_MV_FLOAT = '流通市值(万元)'  # 流通市值(万元)
_C_ST = 'ST'


def build(mv_max_wan=1000000, snapshot_date=None):
    """mv_max_wan: 流通市值上限 (万元), 默认 100 亿 = 1,000,000 万元.
    snapshot_date: 取此日的市值快照, None = 用 daily 表最大日.
    """
    con = duckdb.connect(HUICE_DB, read_only=True)
    try:
        if snapshot_date is None:
            snapshot_date = con.execute(
                'SELECT MAX("%s") FROM daily_data."%s"' % (C_DATE, T_DAILY)
            ).fetchone()[0]
        print('snapshot date:', snapshot_date)
        q = (
            'SELECT "%s" AS code, "%s" AS mv '
            'FROM daily_data."%s" '
            'WHERE "%s" = ? AND "%s" > 0 AND "%s" < ? '
            '  AND ("%s" = 0 OR "%s" IS NULL) '
            'ORDER BY "%s"'
        ) % (
            C_CODE, _C_MV_FLOAT,
            T_DAILY,
            C_DATE, _C_MV_FLOAT, _C_MV_FLOAT,
            _C_ST, _C_ST,
            C_CODE,
        )
        rows = con.execute(q, [snapshot_date, mv_max_wan]).fetchall()
    finally:
        con.close()

    df = pd.DataFrame(rows, columns=['code', 'mv_wan'])
    df['name'] = ''
    df['sector'] = ''
    df['enabled'] = True
    df = df[['code', 'name', 'sector', 'enabled']]
    snap_str = snapshot_date.strftime('%Y%m%d') if hasattr(snapshot_date, 'strftime') else str(snapshot_date).replace('-', '')
    out_path = os.path.join(UNIVERSE_DIR, 'huang_small_mid_%s.csv' % snap_str)
    df.to_csv(out_path, index=False, encoding='utf-8')
    print('wrote', len(df), 'codes to', out_path)
    return out_path, len(df)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mv-max-wan', type=int, default=1000000,
                   help='流通市值上限 (万元), 默认 1,000,000 万 = 100 亿')
    args = p.parse_args()
    build(mv_max_wan=args.mv_max_wan)
```

跑一下生成股池：

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.build_universe_small_mid
```

期望：输出 "wrote ~3800 codes to D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_<date>.csv"。

把输出贴回执，记下实际文件名（含日期）。

### TASK-4. 单测：补 1 个新单测验证 huicexitong 大盘读取

修改 `huang_main_uptrend_combo/backtest/tests/test_huice_loader.py`，在 `test_load_benchmark_returns_close_only` 之后追加：

```python

    def test_load_benchmark_3year_coverage(self):
        """Part 4: 验证从 huicexitong 板块指数能读出 3 年完整数据 (修复前 benchmark_index.duckdb 只覆盖 2025-01 起)"""
        df = load_benchmark_index('000001.SH', '2023-06-01', '2024-12-31')
        # 1.5 年应有 ~360 个交易日
        self.assertGreater(len(df), 300, '应有至少 300 行 (2023-06~2024-12 约 365 交易日)')
        # 首日应早于 2023-06-30
        self.assertLess(df.index.min().date().isoformat(), '2023-06-30')
        # 末日应晚于 2024-12-01
        self.assertGreater(df.index.max().date().isoformat(), '2024-12-01')
```

跑全部单测：

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m unittest huang_main_uptrend_combo.backtest.tests.test_huice_loader huang_main_uptrend_combo.backtest.tests.test_run_backtest_minimum -v
```

期望：6 PASS（原 5 + 新 1）。**任一 FAIL 立刻停下报告**。把输出贴回执。

### TASK-5. 重跑 3 年回测（中小盘股池 + 修复后大盘）

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.run_backtest_huang_combo \
  --start 2023-06-01 --end 2026-04-03 \
  --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_<date>.csv \
  --benchmark 000001.SH \
  --hold-periods 5,10,20
```

**注意 universe 路径用 TASK-3 真实输出的文件名**。

**期望**：
- 读 OHLCV 慢一些（3800 只 × 3 年，估计 1-3 分钟）
- combo_XG=True 信号数 > 0（这次有效）
- 空仓日比例应显著 < 100%

**如果跑超过 15 分钟没结束，停下报告**。

把完整 stdout 贴回执（含 stats、bench_compare、empty days 完整数字，不要省略）。

### TASK-6. 重写回测报告 `huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md`

**整段覆盖**之前的报告（之前是 0 信号，已无效）。结构：

```markdown
# 黄氏主升浪 combo selector 3 年历史回测报告 (Part 4 修复版)

执行日期: <填本工单 date 真实值>
SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md
脚本: huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py

## Part 3 → Part 4 修复

Part 3 (commit `16c15d5`) 跑出 0 信号, CC 验收定位 2 个根因:

| # | 问题 | Part 3 现状 | Part 4 修复 |
|---|---|---|---|
| 1 | 大盘指数缺 1.5 年 | benchmark_index.duckdb 只覆盖 2025-01 起 | 改读 huicexitong basic_data."板块指数" (覆盖 2004 起) |
| 2 | 股池与策略不匹配 | core_100 全是大盘蓝筹, 日涨幅 >5% 全程仅 7 次 | 换中小盘股池 (流通市值 <100亿, ~3800 只) |

selector 代码本身**不改** (公式已 SPEC 锁定, PART 2 已 commit).

---

## 一、回测参数

| 项 | 值 |
|---|---|
| 时间区间 | 2023-06-01 ~ 2026-04-03 |
| 实际交易日数 | <填 summary.total_trading_days> |
| 股票池 | huang_small_mid_<date>.csv (<填 universe_size> 只) |
| 实际可得股票数 | <填 codes_with_data> |
| 大盘指数 | 000001.SH (from huicexitong) |
| 持有期 | 5 / 10 / 20 日 |

## 二、信号统计

| 指标 | 数值 |
|---|---:|
| 总信号数 | <填 signal_rows> |
| 涉及股票数 | <填 signal_unique_stocks> |
| 涉及交易日数 | <填 signal_unique_days> |
| 空仓日 (无信号) | <填 empty_days> / total (<empty_days_pct>%) |

## 三、持有期收益

<把 stats.csv 内容贴成 markdown 表格, 不要截断>

## 四、与大盘对比

<把 bench_compare.csv 贴成 markdown 表格>

## 五、结论

- 5 日胜率 <X%> vs 大盘 <Y%>: <selector +/-/持平>
- 10 日胜率 ...
- 20 日胜率 ...
- 空仓比例 <Z%>: <过严/适中/过松>
- 最大回撤 <W%>: <可接受/偏大>

**判断**:
- 是否值得继续 (走 B 方案接 daily_engine 或接入策略)?
- 主要风险点
- 待回测建议
```

报告内容必须**真实回填脚本输出**，禁止 placeholder 数字。

### TASK-7. 精确 add + commit (6 文件)

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/backtest/huice_loader.py
git add huang_main_uptrend_combo/backtest/build_universe_small_mid.py
git add huang_main_uptrend_combo/backtest/tests/test_huice_loader.py
git add huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md
git add backtest/data/universe/huang_small_mid_<date>.csv
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART4_FIX.md

git diff --cached --name-only
```

**期望输出 6 行**（多一行少一行都不行）：
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART4_FIX.md
backtest/data/universe/huang_small_mid_<date>.csv
huang_main_uptrend_combo/backtest/build_universe_small_mid.py
huang_main_uptrend_combo/backtest/huice_loader.py
huang_main_uptrend_combo/backtest/reports/backtest_report_3y.md
huang_main_uptrend_combo/backtest/tests/test_huice_loader.py
```

**严禁** `git add .` / `git add -A` / 整目录 add。staged 不是 6 个立刻停下报告。

```bash
git commit -m "$(cat <<'EOF'
fix(huang_combo): Part 4 修复 0 信号 - 大盘指数源 + 中小盘股池

Part 3 (commit 16c15d5) 跑出 0 combo_XG=True 信号, 2 个根因:

1. 大盘指数源错: 用的 benchmark_index.duckdb 只覆盖 2025-01 起,
   导致 2023-06~2024-12 段 selector double_大盘_ok 全 False.
   改读 huicexitong basic_data."板块指数" (000001.SH 覆盖 2004 起).

2. 股池与策略不匹配: core_100 全大盘蓝筹, 日涨幅 >5% 全程仅 7 次,
   而黄氏主升浪 SPEC 原设计针对小盘高波动股. 换 huang_small_mid
   (流通市值 <100亿 ~3800 只).

selector.py 不改 (公式 SPEC 锁定, PART 2 已 commit).

变更:
- huice_loader.py: load_benchmark_index 改读 huicexitong 板块指数
- build_universe_small_mid.py: 新增中小盘股池构造脚本
- huang_small_mid_<date>.csv: 中小盘股池快照
- test_huice_loader.py: +1 单测验证 3 年大盘数据可读
- backtest_report_3y.md: 整段重写, 真实回填 Part 4 结果
EOF
)"

git log -1 --stat HEAD
```

把 commit 完整输出贴回执。

---

## 二、严禁

1. **严禁** `git add .` / `git add -A` / 整目录 add
2. **严禁** push / amend / --no-verify / --force
3. **严禁** 改 `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py` 任何一行
4. **严禁** 改 `adapters/qmt_wrapper.py` / `strategy_*.py` / `core/` / `backtest/engine/*` / `backtest/data_tools/duckdb_reader.py` / `huicexitong_reader.py` / `benchmark_reader.py`
5. **严禁** 改 selector 默认参数（DEFAULT_PARAMS）—— SPEC §D 锁定
6. **严禁** 写文件到 D:/ 盘除了 `huang_main_uptrend_combo/backtest/` 和 `backtest/data/universe/`
7. **严禁** 引入 mock / passorder / xttrader / xtquant / 任何下单接口
8. **严禁** 用 placeholder 时间戳 / placeholder 数字（报告必须真实回填）
9. **严禁裸中文 SQL 字面量**（中文表名/列名走 `\u escape` 或 `_huicexitong_names.py`）
10. **遇任一异常必停**:
   - TASK-1 dirty 文件 → 停
   - TASK-2 定位字符串非唯一或匹配不到 → 停
   - TASK-3 输出股池数 < 1000 或 > 5000（说明市值过滤异常）→ 停
   - TASK-4 单测 FAIL → 停
   - TASK-5 仍然 0 信号 → **必停报告**（说明根因诊断错了，不要继续）
   - TASK-5 超 15 分钟未完成 → 停
   - staged 不是 6 个 → 停
   - **不得自判"无关"继续**
11. **回执只能在工单 EOF 追加**

---

## 三、完成回执（在工单 EOF 追加）

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
<贴 date 输出>

### TASK-1: 预检
<贴>

### TASK-2: huice_loader.py 修改
- [ ] BENCH_DB 常量删除/替换
- [ ] load_benchmark_index 改读 basic_data."板块指数"
- [ ] _T_INDEX / _C_INDEX_CLOSE \u escape 常量
- [ ] 仍然无裸中文 SQL 字面量

### TASK-3: build_universe_small_mid.py + 跑生成
- 实际输出文件名: <填 huang_small_mid_YYYYMMDD.csv>
- 股池大小: <填>

### TASK-4: 单测输出 (6 PASS)
<贴 unittest -v 完整输出>

### TASK-5: 3 年回测 stdout
<贴完整, 含 stats / bench_compare / empty days 完整数字>

### TASK-6: backtest_report_3y.md 内容
<贴完整报告>

### TASK-7: git diff --cached --name-only + commit
<贴 6 行 + git log -1 --stat HEAD>

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] huice_loader 仅改 load_benchmark_index (没改 OHLCV 加载器)
- [ ] selector.py 未改
- [ ] 中小盘股池 1000 ~ 5000 只
- [ ] 单测 6 PASS
- [ ] 3 年回测 combo_XG 信号数 > 0
- [ ] 报告含真实数字
- [ ] staged 只有 6 个文件
- [ ] commit 成功，未 push / amend / --no-verify
- [ ] 回执在工单 EOF 追加
```
