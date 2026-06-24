# QMT 内置回测调研

#已验证

> 任务编号：T-20260624-004
> 工程报告：`D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\reports\05_conclusion.md`
> SPEC：`D:\QMT_STRATEGIES\specs\SPEC_QMT_BUILTIN_BACKTEST_FEASIBILITY.md`

## 一句话结论

`xtquant.qmttools.stgentry.run_file()` 在外部 Python 模式下可以跑通 QMT 策略生命周期和历史行情驱动，但**不会启动可用撮合链路**：`passorder()` 不报错，却不产生 `deal/order/account` 回调，服务端 callback cache 也为空。

因此，外部 Python 调 `stgentry.run_file()` **不适合作为研究端批量回测工具**。研究端继续使用自建回测工厂；QMT 内置 GUI 回测最多作为人工辅助验证，不进入脚本化 Phase 2。

## 已验证事实

### 1. 生命周期可跑通

外部脚本调用 `stgentry.run_file()` 后，探针策略的生命周期完整执行：

- `init(C)`：触发
- `after_init(C)`：触发
- `handlebar(C)`：按裁剪后的日线 bar 触发
- `stop(C)`：触发
- `run_file()` 返回值：`None`

MiniQMT 必须在后台运行，因为 `stgframe.init()` 通过 `xtdata.get_client()` 与 MiniQMT 进程 RPC 通信。

## 2. 行情通路可用

在回测上下文里，`C.get_market_data_ex(fields=['close'], stock_code=[code], period='1d', ...)` 可以拿到历史日线数据。

本次验证中：

- `000001.SZ` 日线可正常返回；
- `C.timelist` 能加载本地 xtdata 历史；
- 价格序列正常，说明行情驱动链路没问题。

## 3. 时间区间不能直接靠 param 生效

`param['start_time'] / param['end_time']` 不会自动限制主图历史长度。源码里 `stgframe.load_main_history()` 对主图历史使用 `start_time=''`、`end_time=''`、`count=-1`。

可用 workaround：在策略 `after_init(C)` 中手动裁剪 `C.timelist`。

```python
def after_init(C):
    start_ms = _to_ms(C._param.get('start_time'))
    end_ms = _to_ms(C._param.get('end_time'), end_of_day=True)
    C.timelist = [t for t in C.timelist
                  if (start_ms is None or t >= start_ms)
                  and (end_ms is None or t <= end_ms)]
```

本次实测可把全历史 timelist 裁剪到目标窗口。

## 4. 撮合链路不通

多轮验证均显示：

- `set_account(accountid)` 无改善；
- `set_auto_trade_callback(True)` 无改善；
- `C.do_back_test = True` 无改善；
- `prType=11` 指定价无改善；
- `passorder()` 7 参数签名修正后不再报错，但仍无成交；
- `deal_callback / order_callback / account_callback` 计数恒为 0；
- `C.get_callback_cache('deal') / ('order') / ('account')` 均返回 `{}`。

结论：外部 Python 路径下，`stgentry.run_file()` 更像是一个**策略脚本生命周期运行器 + 行情回放器**，不是完整撮合引擎。

## 5. 多标的和自建回测对比未继续

由于单标的撮合已经被验证为不可用，多标的循环和与自建回测对比没有继续推进。即使循环多标的，也只会得到空交易、平净值结果，无法形成有效对比。

## 建议

1. **不进入 Phase 2**：不要继续把外部 `stgentry.run_file()` 当研究端批量回测引擎集成。
2. **不修改 QMT 自带包源码**：不要改 `stgframe.py` 或绕过封装直接发 `callFormula`，维护风险高。
3. **研究端继续走自建回测工厂**：组合回测和 next_open 撮合继续放在自建回测体系中。
4. **如需补一锤定音**：可人工在 QMT GUI “我的策略”里加载同一探针，看 GUI 模式下 `deal_callback` 是否触发。但这只验证 GUI 手工回测能力，不解决脚本化批量回测需求。

## 交付物索引

- 任务大盘：`D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\00_brief.md`
- 终审报告：`D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\reports\05_conclusion.md`
- 探针策略：`D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\scripts\_qmt_probe_b_strategy.py`
- 运行驱动：`D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\scripts\run_probe_b.py`
- lifecycle 证据：`D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\data\_probe_b_lifecycle.json`
- 空交易证据：`D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\data\qmt_backtest_trades.json`
- 平净值证据：`D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\data\qmt_backtest_nav.csv`

## 相关链接

- [[QMT_Python_API速查]]
- [[QMT策略开发踩坑与验收清单]]
- [[QMT_passorder异步与反查订单号]]
- [[回测工厂不适合事件型策略]]
