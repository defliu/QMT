# MIMO 工单 — V1.0 Phase 4:astock reader + event_study stub + batch 续跑 + 尾债

**状态**: 草稿(待诚哥确认 V1.0 SPEC 后发出;可后置,可拆 V1.1)
**日期**: 2026-06-27
**作者**: CC
**对应 SPEC**: `specs/SPEC_BACKTEST_FACTORY_V1.0_REFACTOR.md` §9
**预计工时**: ≤ 3 小时(全部子任务)

---

## 背景

V1.0 Phase 4 收口 5 项可后置债务,不阻塞通用化主线。子任务彼此独立,可单独派单或拆 V1.1。

**前置**:Phase 1(06 freeze)已签字。Phase 2/3 不阻塞 Phase 4(文件不重叠)。

---

## 一、必做(5 个独立子任务)

### 4a. astock parquet reader(D5)
**目标路径**: `backtest/data_tools/astock_reader.py`(新建)
**内容/做法**:
- `AstockParquetReader` 类,鸭子类型 4 方法:
  - `load_window(codes, start, end)` → 返回 OHLCV(date/open/high/low/close/vol/amount,与 DuckDBDailyReader 输出列对齐)
  - `trading_calendar(start, end)` → 交易日列表
  - `coverage(codes, start, end)` → 覆盖率
  - `close(code, date)` → 单股单日收盘
- 属性:`db_path` / `data_source="astock"` / `wal_detected=False` / `wal_warning_message=""`
- 数据源 `E:\astock\`(1min 2009起 + 日线 `daily\stock_daily.parquet` + 财务)。**先只做日线 OHLCV 路径**
- `run_backtest.py` 按 `data.source` 分流:`if source=="astock": AstockParquetReader(...) else DuckDBDailyReader(...)`
- **不改 engine**(engine 只鸭子类型)
- 验收:astock reader 跑 `example_ma_cross.yaml`(data.source 改 astock)smoke 产出合法 summary

### 4b. event_study stub(D6)
**目标路径**: `backtest/paradigms/event_study/__init__.py` + `stub.py`(新建)
**内容/做法**:
- `run_event_study(reader, events, label_windows, **kwargs)` 抛 `NotImplementedError("event_study paradigm: V1.0 stub, see SPEC §12")`
- docstring 说明未来形态(events/label_windows 定义)
- 不接入 daily_engine 主循环
- 不定义完整 StrategyDecision
- 新建 `backtest/tests/test_event_study_stub.py`:断言调用抛 NotImplementedError 且 message 含 SPEC 引用

### 4c. batch 续跑(D7)
**目标路径**: `backtest/scripts/run_batch.py`
**内容/做法**:
- 每 leaf 跑完写 checkpoint(`batch_id`+`leaf_index`+`results_dir`)到 `F:/backtest_workspace/batch_summary/{batch_id}_checkpoint.json`
- 重跑 `--resume {batch_id}` 跳过已完成 leaf
- **不做并行**(V1.0 不引入并发复杂度)
- 验收:中断后 `--resume` 跳过已完成 leaf 续跑

### 4d. huang_zhongjun_combo 文档化(D9)
**目标路径**: `agent_hub/2026-06-23_backtest_generalization/06_interface_freeze_v10.md`(已在附录 C 提及,本任务补专节)
**内容/做法**:
- 在 06 freeze 补一节"reference coupling pattern":记录 huang_zhongjun_combo 的 `ss.pop("ima_uptrend_v31")` → `ss["huang_zhongjun_combo"]` namespace 改名模式
- **建议**:不正规化,记为反例,新策略不抄;复用 6+2 评分应直接 import `score_universe`/`make_decision` 在自己 namespace 下产出
- 仅文档,不改代码

### 4e. paths.py 占位符(D10)
**目标路径**: `backtest/paths.py` L28
**内容/做法**:
- `PROJECT_MARKET_DB_V03_PLACEHOLDER`(D盘)改为实际 F 盘路径或删除占位符
- 与 yaml 实际路径(`F:/backtest_workspace/data/duckdb/qmt_market_data.duckdb`)对齐
- OQ-1 收口
- 验收:grep 全仓无残留 D 盘占位符

---

## 二、严禁

1. 禁止改 engine 主循环(只加 reader,engine 鸭子类型)
2. 禁止改 evaluate_day 8参/6键
3. 禁止改 6+2 业务逻辑
4. 禁止实现 event_study 完整逻辑(只 stub)
5. 禁止引入并行/异步(batch 只做续跑,不做并发)
6. 禁止影响冻结期/模拟盘/实盘策略
7. 禁止 `git add .`,逐文件 add
8. 禁止 push

---

## 三、完成回执(MIMO 追加)

```markdown

---

## 完成回执

**执行时间**: <ISO 8601>
**MIMO 模型**: <实际名>
**自检**:
- [ ] 4a astock_reader.py 实现 + example_ma_cross smoke 通过
- [ ] 4b event_study stub + test_event_study_stub.py 通过
- [ ] 4c batch --resume 续跑实现 + 验证
- [ ] 4d huang_zhongjun_combo 文档化(06 freeze 补节)
- [ ] 4e paths.py 占位符修复(grep 无残留)
- [ ] 全量 pytest PASS
- [ ] 未改 engine 主循环/8参/6键/6+2业务
- [ ] 未 push
**一句话结论**: <5 项尾债收口;astock reader 接入,event_study stub,batch 续跑,huang 文档,paths 修复>
```
