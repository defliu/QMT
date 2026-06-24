# MIMO 工单：黄氏聚宽 Part-JQ-C v2 - 修 avoid_future_data (基于当前 HEAD)

## 背景

JQ-C v1 (工单文件 `Mimo_HUANG_PART_JQ_C.md`) 因 HEAD 漂移到 `78958e6` 停下报告. CC 验收: 4 个新 commit (MS-E/F/G/H) 都跟 `huang_main_uptrend_combo/jq_strategies/` **无关** (动的是 `backtest/strategies/research/example_ma_cross/` + `daily_engine.py` + PIT manifest 测试 + 工厂使用说明书), jq_strategies/ 仍干净.

本工单 = JQ-C v1 内容不变, **在当前 HEAD 直接做**.

**当前 HEAD**: `78958e6` ([MS-H] test(backtest/v0.4): PIT manifest 路径集成测试)
**前置参考**: `6d6280b` Part-JQ-B 盘中版 (jq_strategies/ 内容最后一次变更)
**预计工时**: 10 分钟

---

## 一、必做（5 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检 (只查目标文件区, 不查全局 HEAD)

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/jq_strategies/
git log -1 --oneline huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py
git log -1 --oneline huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_open.py
```

期望:
- `git status --short` jq_strategies/ 无输出（目录干净）
- 两个 .py 文件的最近 commit 分别是 `126c1eb` (close) 和 `6d6280b` (open)

**任一文件已被改动 (有 dirty 行) → 停**.
**全局 HEAD 是什么不管, 只要这俩文件没人动过**.

把输出贴回执.

### TASK-2. 改 `huang_zhongjun_jq_close.py`

定位 (精确字符串):

```python
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_slippage(FixedSlippage(0.02))
```

替换为:

```python
    set_option('use_real_price', True)
    # avoid_future_data=False: 14:55 决策需要看到当日 close (与实盘等价).
    # 聚宽默认 True 会把 14:55 取 close 视为未来数据拒绝, 导致 zhongjun 全程 0 触发.
    set_option('avoid_future_data', False)
    set_slippage(FixedSlippage(0.02))
```

### TASK-3. 改 `huang_zhongjun_jq_open.py`

定位完全相同的字符串:

```python
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_slippage(FixedSlippage(0.02))
```

替换为:

```python
    set_option('use_real_price', True)
    # avoid_future_data=False: 10:00 决策需要看到当日 open (与实盘等价).
    # 聚宽默认 True 会把盘中取价视为未来数据拒绝.
    # 注意盘中版本意上 10:00 时只应看 T 日 open + T-1 close, 不应看 T 日 close;
    # 但聚宽 get_price 频率='1d' 时返回的是日 K (含 close), avoid_future_data=False
    # 后 10:00 取的 close 实际值取决于聚宽行为, 不保证严格"盘中只见 open".
    # 平台对比仅供参考.
    set_option('avoid_future_data', False)
    set_slippage(FixedSlippage(0.02))
```

### TASK-4. 静态检查

```bash
cd D:/QMT_STRATEGIES
py -3.10 -c "
for fn in ['huang_zhongjun_jq_close.py', 'huang_zhongjun_jq_open.py']:
    with open('huang_main_uptrend_combo/jq_strategies/' + fn, encoding='utf-8') as f:
        src = f.read()
    import ast
    ast.parse(src)
    assert \"set_option('avoid_future_data', False)\" in src, fn + ' missing False'
    assert \"set_option('avoid_future_data', True)\" not in src, fn + ' still has True'
    print(fn, 'OK, LOC:', len(src.split(chr(10))))
"
```

期望: 两文件都 OK, LOC ≈ 760.

**FAIL → 停**. 把输出贴回执.

### TASK-5. 精确 add + commit (3 文件)

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py
git add huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_open.py
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART_JQ_C_V2.md

git diff --cached --name-only
```

**期望 3 行**, staged ≠ 3 → 停.

```bash
git commit -m "$(cat <<'EOF'
fix(huang_combo): 聚宽 Part-JQ-C v2 - 修 avoid_future_data 导致 0 交易

诚哥实测 jq_close 和 jq_open 两版都 0 交易. 日志根因:

  avoid_future_data=True, 盘中不能取当日的 {'close'} 字段数据,
  current_dt=2024-01-02 14:55:00, end_date=2024-01-02 14:55:00

set_option('avoid_future_data', True) 与 run_daily(time='14:55')
天然冲突: 聚宽认为 14:55 当日 close 还未收盘 = 未来数据,
get_price 直接拒绝, 大盘条件函数返回 None, zhongjun 全程 0 触发.

实盘 14:55 本就能看到 T 日 close (距收盘 5 分钟, lastPrice ≈ close),
聚宽放开此限制后才与实盘等价.

修改 (单行 × 2 文件):
- huang_zhongjun_jq_close.py: avoid_future_data True → False + 注释
- huang_zhongjun_jq_open.py: 同上 + 盘中版语义说明

不动 zhongjun / 6+2 / V1.1 任何逻辑.

JQ-C v1 (Mimo_HUANG_PART_JQ_C.md) 因预检守卫"全局 HEAD 漂移"误判停下.
JQ-C v2 = 内容相同, 改用"只查目标文件 dirty"守卫, 在当前 HEAD 78958e6 上执行.

Refs:
- Part-JQ-A commit 126c1eb (尾盘版基础)
- Part-JQ-B commit 6d6280b (盘中版基础)
- [[cc-ticket-must-check-dirty-target-file]] memory: 工单守卫应查目标文件而非全局 HEAD
EOF
)"

git log -1 --stat HEAD
```

---

## 二、严禁

1. **严禁** `git add .` / `git add -A`
2. **严禁** push / amend / --no-verify
3. **严禁** 改 zhongjun / 6+2 / V1.1 / 股池函数任何代码
4. **严禁** 改 selector / core / production / engine / backtest/strategies/research/example_ma_cross (后者是 MS-E 新加, 跟本工单无关, 别碰)
5. **严禁** 用 placeholder 时间戳
6. **遇任一异常必停**:
   - TASK-1 任一目标 .py 文件已被改动 → 停
   - TASK-2/3 定位字符串非唯一或匹配不到 → 停
   - TASK-4 syntax fail / assert fail → 停
   - staged ≠ 3 → 停
7. **回执只能在工单 EOF 追加**

---

## 三、完成回执

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
### TASK-1: 预检 (目标文件粒度)
<贴>

### TASK-2: jq_close.py 修改
### TASK-3: jq_open.py 修改
### TASK-4: 静态检查
<贴 stdout>

### TASK-5: git diff + commit
<贴 3 行 + git log -1 --stat>

### 自检
- [ ] 时间戳真跑 date
- [ ] 两文件 set_option 都改成 False
- [ ] 两文件无残留 True
- [ ] 未改 zhongjun / 6+2 / V1.1 / 股池任何代码
- [ ] selector / core / production / example_ma_cross 未改
- [ ] staged 只有 3 个文件
- [ ] commit 成功
- [ ] 回执在 EOF 追加
```
