# MIMO 工单：黄氏 combo Part 6 — 双中军单独回测对比

## 目的

诚哥拍板回到 Hermes 汇总建议（90_hermes_summary.md §一）：**只用 double_zhongjun_XG 作为最终选股**，丢掉箱体突破初选。

Hermes 4 个 profile 中 3 个把双中军单独评为第一候选（DeepSeek Quant / Doubao CIO / 平均推荐），理由：
- 唯一同时覆盖趋势 + 动能 + 突破 + 大盘环境的完整公式
- 不依赖 COST / SCR / WINNER 等难复现指标
- 最像"主升浪确认型"教科书定义

Part 5 v1.2 combo_XG 跑 119 信号、胜率 25-27% 全面跑输大盘。本工单跑双中军单独版本对比。

**前置 commit**: `b97a1dc`
**预计工时**: 30 分钟

---

## 一、必做（7 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git log -1 --oneline
git status --short huang_main_uptrend_combo/
```

期望：HEAD = `b97a1dc`，工作区干净（除 __pycache__）。**有 dirty 立刻停下报告**。

### TASK-2. 修改 `huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py`

加 `--signal-source` 参数，支持选择信号源字段。默认值 `combo_XG` 保持向后兼容（Part 5 v1.2 用法不变）。

#### 2a. 在 `parse_args()` 加参数

定位（精确字符串）：

```python
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2023-06-01')
    p.add_argument('--end', default='2026-04-03')
    p.add_argument('--universe', default='D:/QMT_STRATEGIES/backtest/data/universe/core_100.csv')
    p.add_argument('--benchmark', default='000001.SH')
    p.add_argument('--out-root', default='F:/backtest_workspace')
    p.add_argument('--hold-periods', default='5,10,20')
    return p.parse_args()
```

替换为：

```python
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2023-06-01')
    p.add_argument('--end', default='2026-04-03')
    p.add_argument('--universe', default='D:/QMT_STRATEGIES/backtest/data/universe/core_100.csv')
    p.add_argument('--benchmark', default='000001.SH')
    p.add_argument('--out-root', default='F:/backtest_workspace')
    p.add_argument('--hold-periods', default='5,10,20')
    p.add_argument('--signal-source', default='combo_XG',
                   choices=['combo_XG', 'double_zhongjun_XG', 'box_breakout_XG'],
                   help='信号源字段; 默认 combo_XG (SPEC v1.2 窗口语义)')
    return p.parse_args()
```

#### 2b. 把信号筛选改成走 `--signal-source`

定位（精确字符串）：

```python
    # 5. 信号统计 (SPEC v1.2: combo_XG 已是 box_window_hit AND zhongjun, 不再是同日 AND)
    sig = result[result['combo_XG'] == True].copy()
    n_box = int(result['box_breakout_XG'].sum())
    n_zj = int(result['double_zhongjun_XG'].sum())
    n_window_hit = int(result['box_window_hit'].sum())
    n_combo = len(sig)
    print('[step] box_breakout_XG signals:', n_box)
    print('[step] double_zhongjun_XG signals:', n_zj)
    print('[step] box_window_hit (any day in last 120 trading days):', n_window_hit)
    print('[step] combo_XG (window_hit AND zhongjun):', n_combo,
          '(across', sig['code'].nunique() if len(sig) else 0, 'stocks,',
          sig['date'].nunique() if len(sig) else 0, 'trading days)')
```

替换为：

```python
    # 5. 信号统计 (SPEC v1.2: combo_XG 已是 box_window_hit AND zhongjun, 不再是同日 AND)
    signal_source = args.signal_source
    if signal_source not in result.columns:
        raise ValueError('signal_source=%s 不在 selector 输出字段中; 可用: %s'
                         % (signal_source, list(result.columns)))
    sig = result[result[signal_source] == True].copy()
    n_box = int(result['box_breakout_XG'].sum())
    n_zj = int(result['double_zhongjun_XG'].sum())
    n_window_hit = int(result['box_window_hit'].sum())
    n_combo = int(result['combo_XG'].sum())
    print('[step] box_breakout_XG signals:', n_box)
    print('[step] double_zhongjun_XG signals:', n_zj)
    print('[step] box_window_hit (any day in last 120 trading days):', n_window_hit)
    print('[step] combo_XG (window_hit AND zhongjun):', n_combo)
    print('[step] using signal_source=%s -> %d signals' % (signal_source, len(sig)),
          '(across', sig['code'].nunique() if len(sig) else 0, 'stocks,',
          sig['date'].nunique() if len(sig) else 0, 'trading days)')
```

#### 2c. 间隔分布只在 combo_XG 下打印（zhongjun 单独跑没有 box_days_since 含义）

定位（精确字符串）：

```python
    # 信号间隔分布 (SPEC v1.2 §E 第 3 条)
    if len(sig):
        gaps = sig['box_days_since_last_signal'].dropna()
        if len(gaps):
            print('[step] box→zhongjun 间隔天数: min=%.0f median=%.0f mean=%.1f max=%.0f' %
                  (gaps.min(), gaps.median(), gaps.mean(), gaps.max()))
```

替换为：

```python
    # 信号间隔分布 (仅 combo_XG 信号有 box_days_since_last_signal 含义)
    if len(sig) and signal_source == 'combo_XG':
        gaps = sig['box_days_since_last_signal'].dropna()
        if len(gaps):
            print('[step] box→zhongjun 间隔天数: min=%.0f median=%.0f mean=%.1f max=%.0f' %
                  (gaps.min(), gaps.median(), gaps.mean(), gaps.max()))
```

#### 2d. summary.json 加 signal_source 字段

定位（精确字符串）：

```python
        'spec_version': 'v1.2',
        'box_window_N': 120,
        'box_breakout_signals': n_box,
        'double_zhongjun_signals': n_zj,
        'box_window_hit_signals': n_window_hit,
        'signal_rows': int(len(sig)),
```

替换为：

```python
        'spec_version': 'v1.2',
        'box_window_N': 120,
        'signal_source': signal_source,
        'box_breakout_signals': n_box,
        'double_zhongjun_signals': n_zj,
        'box_window_hit_signals': n_window_hit,
        'combo_xg_signals': n_combo,
        'signal_rows': int(len(sig)),
```

#### 2e. run_id 加 signal_source 区分

定位（精确字符串）：

```python
def _make_run_id(start, end, n_codes, n_trade_days):
    h = hashlib.md5(('%s|%s|%d|%d' % (start, end, n_codes, n_trade_days)).encode()).hexdigest()[:8]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return 'huang_combo_%s_%s' % (ts, h)
```

替换为：

```python
def _make_run_id(start, end, n_codes, n_trade_days, signal_source='combo_XG'):
    key = '%s|%s|%d|%d|%s' % (start, end, n_codes, n_trade_days, signal_source)
    h = hashlib.md5(key.encode()).hexdigest()[:8]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    src_short = signal_source.replace('_XG', '').replace('double_', 'zj_')
    return 'huang_combo_%s_%s_%s' % (src_short, ts, h)
```

定位 `_make_run_id` 调用（精确字符串）：

```python
    run_id = _make_run_id(args.start, args.end, len(codes), len(bench))
```

替换为：

```python
    run_id = _make_run_id(args.start, args.end, len(codes), len(bench), signal_source)
```

### TASK-3. 跑 backtest 单测确认不破

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m unittest huang_main_uptrend_combo.backtest.tests.test_huice_loader huang_main_uptrend_combo.backtest.tests.test_run_backtest_minimum -v
```

期望 6 PASS（包括 smoke 测试默认 combo_XG）。**FAIL 停**。把最后 5 行贴回执。

### TASK-4. 跑 3 年 double_zhongjun 单独回测

```bash
cd D:/QMT_STRATEGIES
py -3.10 -m huang_main_uptrend_combo.backtest.run_backtest_huang_combo \
  --start 2023-06-01 --end 2026-04-03 \
  --universe D:/QMT_STRATEGIES/backtest/data/universe/huang_small_mid_20260403.csv \
  --benchmark 000001.SH \
  --hold-periods 5,10,20 \
  --signal-source double_zhongjun_XG
```

**期望**：
- `using signal_source=double_zhongjun_XG -> ~6899 signals`（与 Part 5 报告 zhongjun 信号数一致）
- stats / bench_compare 表非空
- run 目录名含 `zj_zhongjun` 前缀

**如果信号数为 0 或与 Part 5 报告差距巨大（< 1000 或 > 10000）→ 停下报告**。
**如果跑超 15 分钟未完成 → 停**。

把完整 stdout 贴回执。

### TASK-5. 写对比报告 `huang_main_uptrend_combo/backtest/reports/backtest_report_double_zhongjun_only.md`

**编码 utf-8**。结构：

```markdown
# 黄氏主升浪 double_zhongjun 单独 3 年回测报告 (Part 6 / Hermes 汇总首推)

执行日期: <填本工单 date 真实值>
SPEC: D:/QMT_STRATEGIES/specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md (v1.2)
依据: agent_hub/2026-06-23_huang_main_uptrend/90_hermes_summary.md (Hermes Top 1 推荐)
脚本: huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py --signal-source double_zhongjun_XG

## 背景

Hermes 汇总：4 个 profile 中 3 个把"双中军版"评为主升浪 Top 1（DeepSeek Quant / Doubao CIO / 平均推荐）。
理由：唯一同时覆盖趋势 + 动能 + 突破 + 大盘环境的完整公式；不依赖难复现指标。

Part 5 v1.2 combo_XG (= box_window_hit AND zhongjun) 跑 119 信号、胜率 25-27% 全面跑输大盘.
本报告把箱体突破初选丢掉，只用 double_zhongjun_XG 作为最终信号源。

## 一、回测参数

| 项 | 值 |
|---|---|
| 时间区间 | 2023-06-01 ~ 2026-04-03 |
| 实际交易日数 | <填> |
| 股票池 | huang_small_mid_20260403.csv (3633 只, 流通市值<100亿) |
| 实际可得股票数 | <填> |
| 大盘指数 | 000001.SH (huicexitong basic_data."板块指数") |
| 持有期 | 5 / 10 / 20 日 |
| **信号源** | **double_zhongjun_XG 单独** |

## 二、信号统计

| 字段 | Part 5 (combo_XG) | **Part 6 (double_zhongjun_XG)** |
|---|---:|---:|
| 信号总数 | 119 | **<填>** |
| 涉及股票数 | 74 | <填> |
| 涉及交易日数 | 87 | <填> |
| 空仓日 | 601 / 688 (87.4%) | <填> |

## 三、持有期收益对比

### Part 6 (double_zhongjun_XG)
<贴本次 stats markdown 表格>

### Part 5 对比 (combo_XG)
| hold_n | n_signals | win_rate | avg_return | max_drawdown |
|---:|---:|---:|---:|---:|
| 5 | 119 | 0.2689 | -0.0370 | -0.9946 |
| 10 | 119 | 0.2605 | -0.0487 | -0.9992 |
| 20 | 113 | 0.2566 | -0.0653 | -0.9998 |

## 四、与大盘对比

<贴本次 bench_compare>

| hold_n | bench_n | bench_avg_return | bench_win_rate |
|---:|---:|---:|---:|
| 5 | 87 | -0.0019 | 0.4253 |
| 10 | 87 | -0.0006 | 0.5287 |
| 20 | 83 | 0.0019 | 0.4819 |

(Part 5 大盘数据，便于对照基准)

## 五、结论

- 5 日胜率 Part 6 <X%> vs Part 5 26.9% vs 大盘 42.5%: <比较>
- 10 日胜率 Part 6 <X%> vs Part 5 26.1% vs 大盘 52.9%
- 20 日胜率 Part 6 <X%> vs Part 5 25.7% vs 大盘 48.2%
- 平均收益: Part 6 vs Part 5 vs 大盘
- 最大回撤: Part 6 vs Part 5
- 信号数量: Part 6 <N> vs Part 5 119 (~<倍> 倍)
- 空仓比例: Part 6 vs Part 5 87.4%

**判断**:
- 双中军单独是否优于 box+window 组合？<是/否/相当>
- Hermes 汇总"双中军条件偏严, 大盘条件可能导致熊市无票"是否成立？(看空仓比例 + 信号分布)
- 是否值得继续 (接 QMT / 调参数 / 加择时)?
- 主要风险点
```

报告必须**真实回填脚本输出**，禁止 placeholder 数字。

### TASK-6. 精确 add + commit（4 文件）

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
git add huang_main_uptrend_combo/backtest/reports/backtest_report_double_zhongjun_only.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART6_ZHONGJUN_ONLY.md

git diff --cached --name-only
```

**期望输出 3 行**（多一行少一行都不行）：
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART6_ZHONGJUN_ONLY.md
huang_main_uptrend_combo/backtest/reports/backtest_report_double_zhongjun_only.md
huang_main_uptrend_combo/backtest/run_backtest_huang_combo.py
```

**严禁** `git add .` / `git add -A` / 整目录 add。staged 不是 3 个立刻停下报告。

```bash
git commit -m "$(cat <<'EOF'
feat(huang_combo): Part 6 - double_zhongjun 单独 3 年回测 (Hermes 汇总首推)

诚哥拍板回到 Hermes 90_hermes_summary.md §一推荐方案: 只用 double_zhongjun_XG.

依据: 4 个 profile 中 3 个把双中军评为主升浪 Top 1
(DeepSeek Quant / Doubao CIO / 平均推荐).
Part 5 v1.2 combo_XG (= box_window_hit AND zhongjun) 119 信号 胜率 25-27%
全面跑输大盘, 本工单丢掉 box 初选, 只用 double_zhongjun_XG 作为信号源.

变更:
- run_backtest_huang_combo.py 加 --signal-source 参数:
  * combo_XG (默认, SPEC v1.2 窗口语义, 向后兼容 Part 5)
  * double_zhongjun_XG (本工单使用)
  * box_breakout_XG (预留)
- run_id 加 signal_source 前缀, 区分多次跑结果
- summary.json 加 signal_source / combo_xg_signals 字段

3 年回测结果 (double_zhongjun_XG 单独, 3633 只中小盘):
- 信号数: <填>
- 胜率 (5/10/20 日): <填>
- 平均收益: <填>
- vs Part 5 combo_XG: <填>
- vs 大盘: <填>
- 详见 backtest/reports/backtest_report_double_zhongjun_only.md

6 backtest 单测全 PASS.
不动 selector.py (公式 SPEC v1.2 锁定) / adapters / strategy_*.py / engine /
backtest/strategies/.

Refs: agent_hub/2026-06-23_huang_main_uptrend/90_hermes_summary.md
EOF
)"

git log -1 --stat HEAD
```

把 commit 完整输出贴回执（含上面 `<填>` 替换为真实数字版本）。

### TASK-7. 最终核查

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/
ls F:/backtest_workspace/ | grep huang_combo | tail -3
git log -2 --oneline
```

期望：
- `git status` 工作树干净
- F:/ 下有 `huang_combo_zj_zhongjun_*` 目录
- master HEAD 是新 commit, 上一个是 `b97a1dc`

---

## 二、严禁

1. **严禁** `git add .` / `git add -A` / 整目录 add
2. **严禁** push / amend / --no-verify / --force
3. **严禁** 改 `huang_main_uptrend_combo/huang_main_uptrend_combo_selector.py`（selector 公式 SPEC v1.2 已锁定）
4. **严禁** 改 SPEC 文件
5. **严禁** 改 `adapters/qmt_wrapper.py` / `strategy_*.py` / `core/` / `backtest/engine/*` / `backtest/strategies/*` / `huicexitong_reader.py`
6. **严禁** 写文件到 D:/ 盘除了既定的 3 个源文件路径
7. **严禁** 引入 mock / passorder / xttrader / xtquant
8. **严禁** 用 placeholder 时间戳 / placeholder 数字（报告 + commit message 必须真实回填）
9. **严禁段加死**: `--signal-source` 参数必须在函数体引用
10. **遇任一异常必停**:
    - TASK-1 有 dirty → 停
    - TASK-2 定位字符串非唯一或匹配不到 → 停
    - TASK-3 backtest 单测 FAIL → 停
    - TASK-4 信号数 = 0 或与预期差距巨大 (<1000 或 >10000) → **必停**
    - TASK-4 超 15 分钟未完成 → 停
    - staged 不是 3 个 → 停
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
### TASK-1: 预检
### TASK-2: run_backtest 改动
- [ ] parse_args 加 --signal-source
- [ ] 信号筛选改 result[result[signal_source]]
- [ ] 间隔分布只在 combo_XG 打印
- [ ] summary.json 加 signal_source / combo_xg_signals
- [ ] _make_run_id 加 signal_source 前缀

### TASK-3: backtest 单测
<贴最后 5 行>

### TASK-4: double_zhongjun 3 年回测 stdout
<贴完整>

### TASK-5: backtest_report_double_zhongjun_only.md
<贴完整报告>

### TASK-6: git diff --cached + commit
<贴 3 行 + git log -1 --stat HEAD>

### TASK-7: 最终核查
<贴>

### 自检
- [ ] 时间戳真跑 date 命令
- [ ] selector.py 未改
- [ ] run_backtest 默认行为不变 (默认 combo_XG)
- [ ] backtest 单测 6 PASS
- [ ] double_zhongjun 跑出预期信号数
- [ ] 报告含真实数字 + 与 Part 5 对比表
- [ ] commit message 含真实回测数字
- [ ] staged 只有 3 个文件
- [ ] commit 成功, 未 push / amend
- [ ] F: 下有 zj_zhongjun 前缀目录
- [ ] 回执在工单 EOF 追加
```
