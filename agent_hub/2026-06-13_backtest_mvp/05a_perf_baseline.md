# Phase 1A 验收 + DuckDB Reader 性能基线

日期：2026-06-13
作者：CC
对应 SPEC：v0.2 §1.2 / 附录 D.1（建议 #7）

## Phase 1A 验收

- 累计 commits：`fa93e07` → `668d89b`（共 7 个 commit）
  - `fa93e07` feat(backtest): paths constants + init_workspace (decision J)
  - `eb32d4a` test(backtest): sample db fixture with dedup+suspension injections
  - `387debb` feat(backtest): DuckDBDailyReader read-only with dedup+coverage (SPEC §1)
  - `7878f45` test(backtest): wal concurrent-sync detection
  - `125b368` feat(backtest): universe loader with schema validation (建议 #3)
  - `afc1408` test(backtest): disk partition + clean_results isolation (constraints #4 #6)
  - `668d89b` feat(backtest): data_hash 9-field formula (decision F)
- 累计 pytest：30/30 全绿（`py -3.10 -m pytest backtest/tests -v`，1.17 s）
- 关键文件（对照 plan §5.1 完整产出清单）：
  - `backtest/__init__.py`
  - `backtest/paths.py`（含 `JINCE_DB_PATH` + v0.3 OPEN_QUESTION 占位）
  - `backtest/scripts/init_workspace.py`
  - `backtest/scripts/clean_results.py`（独立链路，未被任何主路径模块 import）
  - `backtest/data_tools/__init__.py`
  - `backtest/data_tools/duckdb_reader.py`（read_only / dedup / coverage / calendar）
  - `backtest/data_tools/universe.py`（CSV schema 校验 + 去重告警）
  - `backtest/engine/__init__.py`
  - `backtest/engine/hashing.py`（9 字段 data_hash）
  - `backtest/data/universe/`（universe CSV 目录）
  - `backtest/tests/`（30 项测试 + conftest + fixtures）
- 决策 J 验证：`D:\QMT_STRATEGIES\backtest\` 下不存在 `results/`、`cache/`、`sample_db/`、`logs/`、`batch_summary/`、`results_archive/`；`F:\backtest_workspace\` 已自动建好（含上述 6 个子目录 + `README.txt`）。
- 决策 I 验证：`F:\金策智算\_internal\databases\duckdb\` 跑性能基线前后 `ls -la` + `stat` 完全一致：
  - 文件列表：`duckdb.exe`、`quantifydata.duckdb`（无新增、无 `.wal`、无 tmp 文件）
  - `quantifydata.duckdb` size = 5,435,830,272 bytes（前后一致）
  - mtime = `2026-05-06 23:59:58.049680800 +0800`（前后一致）
  - inode = `562949953483225`（前后一致）
  - atime 略有更新（只读访问的预期表现，无写操作）
- 硬约束 #6 验证：`backtest/scripts/clean_results.py` 不在 `duckdb_reader / universe / paths / init_workspace / hashing / engine` 任何模块的 import 链中（`test_clean_results_isolation.py` 通过）。

## DuckDB 读性能基线（真库 5.4 GB / 5197 只 / 2025-08-01..2026-02-27）

环境：`py -3.10`，Windows 11，F 盘 NVMe。
执行方式：单一 `DuckDBDailyReader` 实例顺序跑三档。
真库：`F:/金策智算/_internal/databases/duckdb/quantifydata.duckdb`
coverage 信息：
```
{'min_date': '2025-08-01', 'max_date': '2026-02-27',
 'n_codes': 5197, 'n_rows_after_dedup': 701352,
 'dedup_count': 18620, 'db_mtime': '2026-05-06T23:59:58'}
```

| 场景                          | 实测耗时   | 行数      | 目标     | 是否达标 |
|-------------------------------|-----------|----------|----------|--------|
| 5 只 × 1 个月                 | 0.020 秒  | 110      | < 1 秒   | OK (远优) |
| 200 只 × 6 个月               | 0.107 秒  | 23,105   | < 5 秒   | OK (远优) |
| 5197 只 × 7 个月（全表）       | 2.395 秒  | 701,352  | < 30 秒  | OK (远优) |

三档全部达标，且全部 **远低于** 目标阈值：
- 5×1m：实测 0.02 s（目标的 2%）
- 200×6m：实测 0.107 s（目标的 2.1%）
- 全表 7m：实测 2.395 s（目标的 8%）

## 不达标项的原因 & 建议

无不达标项。性能已远超 SPEC 附录 D.1 的最低目标，目前无需任何性能优化（如分页、attach 副本建索引、仅加载 universe codes 等手段）。

后续若进入 Phase 4 性能 budget 验证或全市场长周期回测时，再视实际场景重新基线。当前 v0.2 MVP 阶段无需提前优化。

## 硬约束 6 项核对

| #   | 约束                                                  | 状态 |
|-----|-------------------------------------------------------|------|
| 1   | Phase 2.0 接口冻结门禁                                 | 待 Task 2.0.1 |
| 2   | Phase 3 前输出 schema 冻结门禁                         | 待 Task 2.5.1 |
| 3   | DuckDB 只读 / 去重 / coverage / 短样本警告             | OK Task 1.3 + 1.4 已落地 read_only / dedup / coverage / calendar；短样本警告留 Phase 4 评分上下文 |
| 4   | D / F / C 盘写入边界                                  | OK Task 1.6 4 项测试通过（test_paths_disk_partition.py） |
| 5   | v0.3 OPEN_QUESTION 标记                               | OK paths.py 留有占位 + plan §OPEN_QUESTIONS 段落 |
| 6   | clean_results.py 独立链路                             | OK Task 1.6 isolation 测试通过 |

## 下一步

进入 Phase 2.0 GATE：写 `agent_hub/2026-06-13_backtest_mvp/03_interface_freeze.md`，等 Hermes 签字「确认」后开 Task 2.1（strategy_core 接口实现）。
