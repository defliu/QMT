# MIMO 工单：黄氏 zhongjun + 6+2 + V1.1 聚宽 Part-JQ-B 盘中版

## 目的

基于 Part-JQ-A 尾盘版 (commit `126c1eb`) 复刻盘中版聚宽脚本.

**唯一差异**: 决策 + 撮合时点从 14:55 改 10:00. 其他全等价 (zhongjun / 6+2 / V1.1 / 中小盘股池 / 滑点 / 手续费 …).

聚宽实际语义:
- 14:55 (尾盘版): 接近收盘前 5 分钟, 当日全部 OHLCV 已完整成形, 撮合价 ≈ T 日 close
- 10:00 (盘中版): 开盘后 30 分钟, T 日只见 09:30~10:00 部分行情, 撮合价 ≈ T 日 10:00 实时价

**前置 commit**: `126c1eb`
**预计工时**: 20-30 分钟 (小工单)

---

## 一、必做（6 步）

### TASK-0. 时间戳

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"
```

### TASK-1. 预检

```bash
cd D:/QMT_STRATEGIES
git log -1 --oneline
ls huang_main_uptrend_combo/jq_strategies/
```

期望:
- HEAD = `126c1eb` (Part-JQ-A 已 commit)
- jq_strategies/ 含 huang_zhongjun_jq_close.py + README + USAGE + MIGRATION_REPORT (共 4 个文件)

**任一异常 → 停**.

### TASK-2. 复制并修改成盘中版

```bash
cp huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py \
   huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_open.py
```

然后在 `huang_zhongjun_jq_open.py` 里做以下精确修改:

#### 2a. 改文件头注释

定位 (精确字符串):

```python
"""黄氏 zhongjun + 6+2 评分 + V1.1 风控 聚宽尾盘版.

策略逻辑 (实盘等价):
  - 每日 14:55:
```

替换为:

```python
"""黄氏 zhongjun + 6+2 评分 + V1.1 风控 聚宽盘中版.

策略逻辑 (实盘等价):
  - 每日 10:00 (开盘后 30 分钟):
```

#### 2b. 改 initialize 里的 log 标题

定位:

```python
    log.info("黄氏 zhongjun + 6+2 + V1.1 聚宽尾盘版")
```

替换为:

```python
    log.info("黄氏 zhongjun + 6+2 + V1.1 聚宽盘中版")
```

#### 2c. 改 run_daily 时间

定位 (精确字符串):

```python
    # 14:55 尾盘决策 (实盘 14:40-14:57 窗口的代表时点)
    run_daily(handle_market_close, time='14:55', reference_security='000001.XSHG')
```

替换为:

```python
    # 10:00 盘中决策 (开盘后 30 分钟, 实盘 10:00-10:30 窗口的代表时点)
    run_daily(handle_market_intraday, time='10:00', reference_security='000001.XSHG')
```

#### 2d. 重命名主决策函数

定位 (精确字符串, only 1 处):

```python
def handle_market_close(context):
    """14:55 尾盘决策入口."""
    today = context.current_dt.strftime('%Y-%m-%d')
    log.info('[%s] === 14:55 尾盘决策 ===' % today)
```

替换为:

```python
def handle_market_intraday(context):
    """10:00 盘中决策入口."""
    today = context.current_dt.strftime('%Y-%m-%d')
    log.info('[%s] === 10:00 盘中决策 ===' % today)
```

### TASK-3. 静态检查

```bash
cd D:/QMT_STRATEGIES
py -3.10 -c "
import ast
with open('huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_open.py', encoding='utf-8') as f:
    src = f.read()
ast.parse(src)
# 必须含的关键串
for must in ['handle_market_intraday', \"time='10:00'\", '盘中']:
    assert must in src, 'MISSING: %r' % must
# 必须不含的旧串 (确认替换干净)
for must_not in ['handle_market_close(', \"time='14:55'\", '尾盘']:
    if must_not in src:
        print('REMAIN STALE:', must_not)
        raise SystemExit(1)
print('syntax OK, all replacements done, LOC:', len(src.split(chr(10))))
"
```

期望:
- syntax OK
- all replacements done
- LOC 与 close 版相同 (~758)

**FAIL → 停**. 把输出贴回执.

### TASK-4. 更新 README.md

定位:

```markdown
## 文件

- `huang_zhongjun_jq_close.py`: 尾盘版 (14:55 决策 + 14:55 撮合)
- `huang_zhongjun_jq_open.py`: 盘中版 (10:00 决策 + 10:00 撮合) — Part-JQ-B 生成
```

替换为:

```markdown
## 文件

- `huang_zhongjun_jq_close.py`: 尾盘版 (14:55 决策 + 14:55 撮合)
- `huang_zhongjun_jq_open.py`: 盘中版 (10:00 决策 + 10:00 撮合)
```

(删除 "Part-JQ-B 生成" 标记)

### TASK-5. 精确 add + commit (3 文件)

```bash
cd D:/QMT_STRATEGIES
git add huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_open.py
git add huang_main_uptrend_combo/jq_strategies/README.md
git add agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART_JQ_B.md

git diff --cached --name-only
```

**期望 3 行**:
```
agent_hub/2026-06-23_huang_main_uptrend/Mimo_HUANG_PART_JQ_B.md
huang_main_uptrend_combo/jq_strategies/README.md
huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_open.py
```

**staged ≠ 3 → 停**.

```bash
git commit -m "$(cat <<'EOF'
feat(huang_combo): 聚宽移植 Part-JQ-B 盘中版

基于 Part-JQ-A (commit 126c1eb) 复刻盘中版.

唯一差异: run_daily time '14:55' → '10:00'.
其他全部等价 (zhongjun / 6+2 / V1.1 / 股池 / 滑点 / 手续费).

新增:
- huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_open.py
  * 完整盘中版聚宽策略 (~758 行)
  * 与尾盘版唯一区别: 决策点 10:00, 撮合点 10:00
- README.md 更新引用

不动 jq_close.py / 本地 selector / risk_manager / scoring.

平台对比: 跑完聚宽尾盘 vs 聚宽盘中 vs 本地 Part 8 v3 三方对比.

Refs:
- specs/SPEC_HUANG_MAIN_UPTREND_TDX_TO_QMT.md (v1.2)
- huang_main_uptrend_combo/jq_strategies/huang_zhongjun_jq_close.py (Part-JQ-A)
EOF
)"

git log -1 --stat HEAD
```

### TASK-6. 最终核查

```bash
cd D:/QMT_STRATEGIES
git status --short huang_main_uptrend_combo/jq_strategies/
ls -la huang_main_uptrend_combo/jq_strategies/
git log -2 --oneline
```

期望:
- `git status` 工作树干净
- jq_strategies/ 含 5 个文件 (close.py + open.py + 3 个 md)
- HEAD = 本次新 commit, 上一个是 `126c1eb`

---

## 二、严禁

1. **严禁** `git add .` / `git add -A`
2. **严禁** push / amend / --no-verify
3. **严禁** 改 jq_close.py 任何一行
4. **严禁** 改 selector.py / core/risk_manager.py / core/scoring / production / engine
5. **严禁** 引入 mock / passorder
6. **严禁** 用 placeholder 时间戳
7. **严禁** 修改 zhongjun / 6+2 / V1.1 任何参数或逻辑 (本工单只改时间字符串)
8. **遇任一异常必停**:
   - TASK-1 HEAD 不是 126c1eb → 停
   - TASK-2 任一定位字符串非唯一或匹配不到 → 停
   - TASK-3 syntax / 替换检查失败 → 停
   - staged ≠ 3 → 停
9. **回执只能在工单 EOF 追加**

---

## 三、完成回执 (在工单 EOF 追加)

```markdown

---

## 完成回执

**执行时间**: <真实 date -u 输出>
**MIMO 模型**: <实际名>

### TASK-0: 真实时间戳
### TASK-1: 预检
### TASK-2: 5 处修改
- [ ] 文件头注释
- [ ] log 标题
- [ ] run_daily 时间
- [ ] 主函数重命名 handle_market_close → handle_market_intraday
- [ ] (cp 文件本身)

### TASK-3: 静态检查
<贴>

### TASK-4: README 更新

### TASK-5: git diff --cached + commit
<贴 3 行 + git log -1 --stat>

### TASK-6: 最终核查

### 自检
- [ ] 时间戳真跑 date
- [ ] jq_close.py 未改
- [ ] selector.py / core/ 等未改
- [ ] huang_zhongjun_jq_open.py 含 'handle_market_intraday' 与 "time='10:00'"
- [ ] huang_zhongjun_jq_open.py 不含 'handle_market_close(' 或 "time='14:55'"
- [ ] LOC 与 close 版相同 (~758)
- [ ] staged 只有 3 个文件
- [ ] commit 成功
- [ ] 回执在 EOF 追加
```
