# 工单：buy_order 即时反查撞 QMT 异步延迟误判失败 — 同步卖单短轮询

**日期**: 2026-06-30
**作者**: CC
**目的**: 在刚完成的卖单短轮询修复基础上，修复买入委托同源隐患：`buy` 方法 passorder 后立即 `_lookup_recent_order_id`，若撞上 QMT 异步分配 order_id 的 ~100ms 延迟，会误判"买入反查失败"并 return None，导致上游不登记 `_g_pending_buys`，后续成交回写(F1)够不着。
**预计工时**: ≤ 25 分钟

---

## 〇、背景与根因（必读，不要改这段）

诚哥授权"都处理"：卖单已由上个工单 `Mimo_TODO_sell_lookup_retry_v1.md` 修为短轮询；本工单只处理买单同源路径，不碰 C1 幽灵触发问题。

**根因代码**（`D:/QMT_STRATEGIES/adapters/qmt_wrapper.py` line 370-388 `buy` 方法）：

```python
t_before = time.time()
self._passorder(self.BUY_CODE, stock_code, vol, remark)
order_id = self._lookup_recent_order_id(stock_code, vol, 'buy', t_before)
if order_id is None:
    print("  [买入反查失败] %s %d股 委托可能未到达交易所" % (stock_code, vol))
    return None
return order_id
```

问题与 0630 600641 卖单相同：passorder 是异步的，QMT 分配 order_id 可能晚于即时反查；若 `buy` 方法 return None，上游不会登记 `_g_pending_buys`，那么今日 3c36743/F1 修的 `_check_pending_orders` 可达性也接不住（前提仍是 pending 已登记）。本工单补齐"登记前"这一步。

---

## 一、必做（3 项）

### TASK-1. 改 `buy` 方法：即时反查失败时短轮询重试

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`buy` 方法，line 370-388）

**当前代码**：
```python
        t_before = time.time()
        self._passorder(self.BUY_CODE, stock_code, vol, remark)
        order_id = self._lookup_recent_order_id(stock_code, vol, 'buy', t_before)
        if order_id is None:
            print("  [买入反查失败] %s %d股 委托可能未到达交易所" % (stock_code, vol))
            return None
        return order_id
```

**改为**：
```python
        t_before = time.time()
        self._passorder(self.BUY_CODE, stock_code, vol, remark)
        # passorder 已发出，QMT 异步分配 order_id 有 ~100ms 延迟；
        # 即时反查一次可能撞在分配窗口内查不到，短轮询几次再判失败
        order_id = None
        for _attempt in range(BUY_LOOKUP_RETRIES):
            order_id = self._lookup_recent_order_id(stock_code, vol, 'buy', t_before)
            if order_id is not None:
                break
            time.sleep(BUY_LOOKUP_INTERVAL)
        if order_id is None:
            print("  [买入反查失败] %s %d股 委托可能未到达交易所" % (stock_code, vol))
            return None
        return order_id
```

**关键**：
- 只改 `buy` 方法；不要动刚修好的 `sell` 方法。
- 保持上游契约不变：成功返回 order_id，失败仍 return None，原日志文本不变。
- `time` 模块顶部已 import，不要重复 import。

### TASK-2. 定义买入轮询参数常量

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

在刚新增的 `SELL_LOOKUP_RETRIES / SELL_LOOKUP_INTERVAL` 附近新增：

```python
# 买入委托 passorder 后反查 order_id 的短轮询参数（同卖出）
BUY_LOOKUP_RETRIES = 4
BUY_LOOKUP_INTERVAL = 0.2
```

**关键**：
- 不要改名或移动 `SELL_LOOKUP_RETRIES / SELL_LOOKUP_INTERVAL`，避免破坏上个工单验证。
- 数值与卖单保持一致，最多等 0.8s。

### TASK-3. 验证（不跑实盘/模拟）

1. `python scripts/build_strategy.py`
2. `python scripts/build_strategy.py --allday`
3. validate 两个产物：
   - `python scripts/validate_qmt_file.py strategy_main.py`
   - `python scripts/validate_qmt_file.py strategy_allday.py`
   - 必须 ALL PASS (6/6)
4. grep 验证：
   ```bash
   grep -n "BUY_LOOKUP_RETRIES\|SELL_LOOKUP_RETRIES\|短轮询" adapters/qmt_wrapper.py
   iconv -f GBK -t UTF-8 strategy_main.py | grep -c "BUY_LOOKUP_RETRIES"
   iconv -f GBK -t UTF-8 strategy_allday.py | grep -c "BUY_LOOKUP_RETRIES"
   ```
5. diff 范围自检：
   ```bash
   git diff --stat HEAD adapters/qmt_wrapper.py
   git diff HEAD adapters/qmt_wrapper.py | grep -n "def buy\|def sell\|BUY_LOOKUP\|SELL_LOOKUP\|短轮询"
   ```
   贴结果，确认本工单只在上个卖单改动基础上新增 buy 短轮询 + BUY 常量。

---

## 二、严禁

1. 禁止 git add / commit / push（commit 由 CC 后续统一处理）
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. 禁止改动 `sell` 方法（上个工单已完成）
5. 禁止改动 `_lookup_recent_order_id` 本体
6. 禁止改动 `_check_pending_orders` / `_check_pending_sells` / `_finish_pending_sell`
7. 禁止改动 C1 / risk_manager / 评分逻辑
8. 禁止跑实盘 / 模拟盘交易验证
9. **文件编码 GBK，`# coding=gbk` 文件头保持；禁止用 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string / dict[str,..] / walrus / match-case），用 % 格式化。**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿，禁止 placeholder>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] TASK-1: buy 方法已改为短轮询，贴改后 buy 方法体
- [ ] TASK-2: BUY_LOOKUP_RETRIES / BUY_LOOKUP_INTERVAL 常量已定义，贴上下文
- [ ] TASK-3: strategy_main.py + strategy_allday.py build + validate 6 项 ALL PASS，贴输出
- [ ] TASK-3: grep 验证结果贴出
- [ ] TASK-3: diff 范围自检贴出
- [ ] 未动 sell / _lookup_recent_order_id / pending 检查函数 / C1 风控评分
- [ ] 仅末尾追加，未改动工单上方
- [ ] 无 git 操作 / 无实盘模拟交易
```

---

## 完成回执

**执行时间**: 2026-06-30T13:55:46Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1: buy 方法已改为短轮询，改后 buy 方法体：
```python
    def buy(self, stock_code, volume, remark=''):
        ...
        t_before = time.time()
        self._passorder(self.BUY_CODE, stock_code, vol, remark)
        # passorder 已发出，QMT 异步分配 order_id 有 ~100ms 延迟；
        # 即时反查一次可能撞在分配窗口内查不到，短轮询几次再判失败
        order_id = None
        for _attempt in range(BUY_LOOKUP_RETRIES):
            order_id = self._lookup_recent_order_id(stock_code, vol, 'buy', t_before)
            if order_id is not None:
                break
            time.sleep(BUY_LOOKUP_INTERVAL)
        if order_id is None:
            print("  [买入反查失败] %s %d股 委托可能未到达交易所" % (stock_code, vol))
            return None
        return order_id
```
- [x] TASK-2: BUY_LOOKUP_RETRIES / BUY_LOOKUP_INTERVAL 常量已定义（line 247-248）：
```python
# 买入委托 passorder 后反查 order_id 的短轮询参数（同卖出）
BUY_LOOKUP_RETRIES = 4
BUY_LOOKUP_INTERVAL = 0.2
```
- [x] TASK-3: strategy_main.py build + validate ALL PASS (6/6)
- [x] TASK-3: strategy_allday.py build + validate ALL PASS (6/6)
- [x] TASK-3: grep 验证 — source 含 BUY_LOOKUP_RETRIES/SELL_LOOKUP_RETRIES/短轮询；两个产物各含 BUY_LOOKUP_RETRIES 2 次
- [x] TASK-3: diff 范围自检 — 仅 1 文件 +26/-2，改动集中在 buy 方法短轮询 + BUY 常量，sell/_lookup_recent_order_id/pending 检查函数/C1 风控评分均未动
- [x] 未动 sell / _lookup_recent_order_id / pending 检查函数 / C1 风控评分
- [x] 仅末尾追加，未改动工单上方
- [x] 无 git 操作 / 无实盘模拟交易
