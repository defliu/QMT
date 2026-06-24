# 02 单标的回测报告

日期：2026-06-24
状态：**BLOCKED — passorder 签名不匹配**

## 执行概况

- **区间**：2024-09-01 ~ 2024-12-31（4 个月）
- **标的**：000001.SZ
- **初始资金**：1,000,000
- **实测耗时**：1.2 秒

## 迭代经过

### v1（PART-B 首次）

探针通过 QMT 内置回测引擎加载，但 `timelist` 裁剪逻辑有误，handlebar 未触发，全部产物为空。

### v2（第二次重跑）

修复 timelist 裁剪，handlebar 触发 80 次。但使用了两个错误 API：
- `C.get_market_data`（回测模式返回结构与提取逻辑不匹配，close 全 0.0）
- `C.get_trade_detail_data`（不是 C 的方法，80 条 AttributeError）

结果：buy=0 / deal=0，nav 无变化。

### v3（第三次重跑）

针对 v2 两个根因修复：
1. 删 `get_trade_detail_data`，自维护 `_book = {cash, shares}`
2. `after_init` 一次性 `get_market_data_ex` 全区间 close 缓存到 `_price_by_date`

**新问题**：`C.passorder()` 传入 11 个参数，QMT backtest 模式只接受 8 个位置参数，4 次 BUY 全部 TypeError。

## 关键诊断对照表

| 字段 | v2 实测 | v3 实测 | v3 期望 |
|---|---|---|---|
| timelist_after_clip | 80 | 80 | 80 |
| handlebar_count | 80 | 80 | 80 |
| price_cache_size | — | 80 | 80 |
| cache_miss_dates 数量 | — | 0 | 0 |
| buy_signals | 0 | 0 | 4 |
| sell_signals | 0 | 0 | 4 |
| deal_callback_count | 0 | 0 | ≥8 |
| order_callback_count | 0 | 0 | ≥8 |
| acc_errors | 80 条 | 不存在 | 不存在 |
| handlebar_errors | — | 空 | 空 |
| passorder_errors | — | 4 条 TypeError | 空 |
| orderError_count | 0 | 0 | 0 |
| nav 末值 == init_nav？ | 是 | 是（1000000.0） | **否** |

## v3 改进评价

### 已生效的 workaround

1. **after_init timelist 截断**：426 → 80，正确裁剪到目标区间
2. **全区间 price 缓存**：`get_market_data_ex` 一次性拉取，80 个日期全覆盖，cache_miss=0
3. **自维护 book**：`_book = {cash, shares}`，nav = cash + shares × close，逻辑正确

### 新阻塞点

`passorder()` 签名不匹配。工单 v3 代码传入 11 个参数（opType, orderType, account, stockcode, prType, price, volume, strategyname, quicktrade, strtag），但 QMT backtest 模式下 passorder 只接受 8 个位置参数。

需要调查 QMT backtest 模式 passorder 的实际签名，或改用其他下单方式。

## 局限性

1. **m_strOptName 字段**：trades 为空无法验证，即使 passorder 修好后 side 可能全 unknown（QMT 回测 m_strOptName 可能为空），需补 PART-E 调研
2. **backtest passorder 签名**：工单 v3 给出的 11 参数版本不兼容，需确认实际签名

## QMT 进程验证

- **验证时间**：2026-06-24 22:39
- **验证命令**：`wmic process where "name='pythonw.exe'" get CommandLine,ProcessId`
- **验证结果**：pythonw.exe PID 16472 确认运行

## 自检

- [x] 没改任何生产文件
- [x] 没 commit
- [x] 没动 `D:/QMT_POOL/`
- [x] 异常按工单 §6 处理（STOP 条件已触发，已贴全部诊断）
- [x] 探针文件**整体覆盖**写入，不是 patch
- [x] 驱动文件**一字未动**
