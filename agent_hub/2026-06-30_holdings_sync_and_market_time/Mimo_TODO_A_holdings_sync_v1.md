# 工单A：清仓票当天赖在持仓表 — 成交确认即移除并立即释放名额

**日期**: 2026-06-30
**作者**: CC
**目的**: 修复"QMT 清仓成交后，票当天仍留在 holdings 文件、占着名额，第二天才消失"的 bug。根因是 `_finish_pending_sell` 成交确认后 `_g_my_codes.pop` 依赖 QMT position 缓存（刷新有延迟），且全程未调 `write_holdings_file`。
**预计工时**: ≤ 40 分钟

---

## 〇、背景与根因（必读，不要改这段）

诚哥授权修复，非冻结期违规。今日 0630 实盘 600641 已因此链路问题产生异常卖出。

**根因代码**（`D:/QMT_STRATEGIES/adapters/qmt_wrapper.py` line ~2457 `_finish_pending_sell`）：

```python
_g_pending_sells.pop(code, None)
pos = _g_trader.get_position(code) if _g_trader else None
if pos is None or pos.get('volume', 0) <= 0:
    _g_my_codes.pop(code, None)
```

问题：
1. `get_position` 读 QMT 端持仓缓存快照（`get_trade_detail_data('position')`），卖出成交后缓存刷新有延迟（秒级~分钟级），当天 `m_nVolume` 还显示旧值 → 条件不满足 → **不 pop**。
2. 全程**没有 `write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)` 调用** → 即使内存 pop 了，holdings 文件也不更新。
3. 结果：清仓票当天赖在 `_g_my_codes` 和 holdings 文件里，占着 `MAX_HOLD` 名额，第二天 QMT 结算后缓存归零才被 `_sync_holdings_from_account` 清掉。

诚哥拍板的方案：**成交确认即移除，立即释放名额**（最激进选项）。

---

## 一、必做（4 项）

### TASK-1. 改 `_finish_pending_sell` 成交确认后立即 pop + 写文件

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`（`_finish_pending_sell` 函数，约 line 2457）

**内容/做法**:

把函数末尾的：

```python
    _g_pending_sells.pop(code, None)
    pos = _g_trader.get_position(code) if _g_trader else None
    if pos is None or pos.get('volume', 0) <= 0:
        _g_my_codes.pop(code, None)
```

改为：

```python
    _g_pending_sells.pop(code, None)
    # 成交确认即移除：以策略侧成交判定为准，不等 QMT position 缓存刷新
    # （QMT 缓存刷新有延迟，当天 m_nVolume 还显示旧值会导致清仓票赖着占名额）
    pos = _g_trader.get_position(code) if _g_trader else None
    qmt_vol = pos.get('volume', 0) if pos else 0
    if qmt_vol > 0:
        # QMT 缓存未刷新但仍判定成交：以策略侧为准 pop，打 warning 留痕便于事后核
        print("  [持仓清理] %s 成交确认但 QMT 缓存仍显示 %d 股，按策略侧成交移除" % (code, qmt_vol))
    _g_my_codes.pop(code, None)
    # 立即写 holdings 文件，释放名额（原 bug：此处未写文件）
    try:
        write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)
    except Exception as e:
        print("  [持仓清理] 写 holdings 文件失败: %s" % e)
    # 同步卖出引擎状态
    if _g_sell_engine is not None:
        try:
            _g_sell_engine.save_state()
        except Exception:
            pass
```

**关键**：
- `_g_my_codes.pop(code, None)` 现在**无条件执行**（不再被 QMT 缓存 volume 卡住）。
- 必须调 `write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)` —— 这是本次修复的核心动作。
- 保留 `get_position` 调用仅为打 warning 留痕，不作为 pop 的判断条件。

### TASK-2. 排查另一处成交路径是否同样漏写文件

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:

grep 所有调 `_g_my_codes.pop` 的位置（约 line 682/2299/2476/2498 及本工单 TASK-1 改的 2457），逐处确认：**pop 之后是否在合理时机调了 `write_holdings_file`**。

重点看：
- line ~2299 `_check_pending_sells` 里"订单号无效"分支的 `_g_my_codes.pop` —— 该分支 pop 后是否写文件？若否，补 `write_holdings_file(INTRADAY_HOLD_FILE, _g_my_codes)`。
- line ~2476 / ~2498 的 pop（换仓路径）—— 同样确认并补写文件。

**注意**：`_sync_holdings_from_account`（line ~693）已有 `write_holdings_file`，不用改。只补**成交确认路径上漏写的**。每处补写都要 try/except 包住，失败只打 print，不抛异常中断主流程。

### TASK-3. 不要动反查成交判定逻辑

**严禁改动**以下区域（它们是 commit b0e0fca 的领域，动它们要另开工单）：
- `_check_pending_sells` 里 `found_order` 的查找与成交/部分成交/未成交判定逻辑（line ~2284-2340）
- `_g_trader.cancel_order` / `_retry_pending_sell` 的调用时机
- `_lookup_order` / remark 过滤逻辑

本工单**只改 pop 之后的动作**（pop 时机 + 写文件），不改"何时判定成交"。

### TASK-4. 验证（不跑实盘/模拟）

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:

1. `python scripts/validate_qmt_file.py strategy_main.py` —— 6 项 ALL PASS（构建后必跑，见 CLAUDE.md）。
   - 若 strategy_main.py 不存在或需先构建：`python scripts/build_strategy.py` 生成后再 validate。
2. 用 Read 工具把改后的 `_finish_pending_sell` 完整函数体贴到回执里，CC 要核对 TASK-1 改动准确。
3. grep 确认：`_g_my_codes.pop` 的所有位置之后，要么本函数内已写文件，要么在调用链下游有写文件覆盖。把 grep 结果贴回执。

---

## 二、严禁

1. 禁止 git add / commit / push（本工单不授权 git）
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. 禁止改动反查成交判定逻辑（见 TASK-3）
5. 禁止动 `get_position` / `get_trade_detail_data` 内部实现
6. 禁止跑实盘 / 模拟盘交易验证（只做 validate + 静态检查）
7. **文件编码 GBK，`# coding=gbk` 文件头保持；禁止用 patch 工具直接编辑，用 Read+Edit；Python 3.6.8 语法（禁 f-string / dict[str,..] / walrus / match-case）**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿，禁止 placeholder>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] TASK-1: _finish_pending_sell 已改为无条件 pop + write_holdings_file + warning 留痕
- [ ] TASK-2: 已 grep 所有 _g_my_codes.pop 位置并补齐漏写的 write_holdings_file
- [ ] TASK-3: 未改动反查成交判定逻辑（_check_pending_sells 判定分支/cancel_order/retry/remark 过滤原样）
- [ ] TASK-4: validate_qmt_file.py 6 项 ALL PASS（贴输出）
- [ ] 回执贴了改后的 _finish_pending_sell 完整函数体
- [ ] 回执贴了 _g_my_codes.pop 的 grep 结果
- [ ] 仅末尾追加，未改动工单上方
- [ ] 无 git 操作 / 无实盘模拟交易
```
