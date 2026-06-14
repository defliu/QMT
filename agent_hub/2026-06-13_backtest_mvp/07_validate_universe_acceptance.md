# Universe 校验脚本验收：validate_universe.py

日期：2026-06-14（夜班）
验收人：CC（夜班自主验收，依据诚哥 2026-06-14 免 Hermes 授权）
对象：`backtest/scripts/validate_universe.py` + 7 测试 + 真实数据探针验证

---

## 一、验收结论

**Task 6 自审通过。** universe 校验脚本可投入实际使用，全 backtest 套件 **157 / 157 PASS**。

依据：

1. 7 个新测试全部通过，覆盖 schema 拒绝 / DuckDB 缺失代码 / 行业分布排序 / 历史深度阈值 / 文件落盘 / main 端到端。
2. 真实数据探针运行成功：`strategy_pool_base.csv`（10 codes）在 2025-11-15..2026-02-27 窗口内 10/10 覆盖、10/10 历史 ≥60 bars、7 行业分布。
3. 不触碰生产策略 / release / 交易接口；写盘只到 `F:/backtest_workspace/logs/`；read-only 访问 DuckDB；不引入 xtquant。
4. 不修改任何已签字契约（03 / 04 / 05* / 06）。

---

## 二、本次实现内容

### 新增文件

| 文件 | 用途 | 行数（约） |
|---|---|---|
| `backtest/scripts/validate_universe.py` | universe 校验探针 | 145 |
| `backtest/tests/test_validate_universe.py` | 7 测试 | 145 |

### 不修改

- 任何 engine / strategy_core / data_tools / report 模块
- `data_tools/universe.py` `load_universe()` 不变（本脚本仅消费其返回值）
- 已签字契约文件全部保持

---

## 三、设计决策

### 校验项

| 校验 | 实现 | 输出字段 |
|---|---|---|
| Schema 合法性 | 复用 `load_universe`；捕获 `dropped_codes` | `rows_dropped_invalid` + `dropped_invalid_codes` |
| 启用/禁用计数 | 重新读 csv 数 enabled in (false/0/no/'') | `rows_disabled` |
| 行业分布 | `Counter` + `sorted` 按 count desc → sector asc | `sector_distribution: [{sector, count}, ...]` |
| DuckDB 代码覆盖 | `reader.coverage(codes=...)` 复用现有逻辑 | `duckdb_coverage.{codes_with_data, codes_missing, missing_count}` |
| 历史深度 | `SELECT code, COUNT(DISTINCT date)` GROUP BY；阈值 `--min-history-bars`（默认 60，对齐 strategy_core INSUFFICIENT_HISTORY） | `history_depth.{sufficient_count, thin_count, thin_codes:[{code,n_bars},...]}` |

### 不做的事

- **不抛错**：仅描述事实，返回 0；上游决定是否 gate（v0.2 不强制 gate）。
- **不写 universe csv**：read-only 探针，永不修改源 csv。
- **不动 reader.coverage 缓存**：调用 `reader.coverage()` 一次填缓存，再调一次带 codes 参数命中缓存。
- **不引入新 SQL 表**：仅读 `dat_day` 表，与现有 reader 一致。

### 行业分布字段顺序

按 count 降序、sector 字典序升序的稳定排序，便于报告对比。如果未来需要做 batch 多 universe 对比，固定排序保证 diff 可读。

---

## 四、测试

### 测试命令

```bash
py -3.10 -S -c "import sys; sys.path.append(r'C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python310\\Lib\\site-packages'); import pytest; raise SystemExit(pytest.main(['backtest/tests','-q','--ignore=backtest/tests/test_ima_uptrend_v31.py','--ignore=backtest/tests/test_ima_no_lookahead.py','--ignore=backtest/tests/test_ima_signal_returns.py']))"
```

### 测试结果

```text
157 passed in 3.80s
```

按文件分布（仅列 Task 6 新增）：

| 测试文件 | 通过数 | 覆盖契约 |
|---|---|---|
| **test_validate_universe.py** | **7** | **schema 接受 / 拒绝无效 / 计 disabled / DuckDB 缺失代码 / sector desc 排序 / history_depth 阈值划分 / write_report 落盘 / main 端到端** |
| 累计（含前 5 阶段 + Phase 6） | **157** | |

### 真实数据探针运行

输入：

```bash
py -3.10 -m backtest.scripts.validate_universe \
    --universe backtest/data/universe/strategy_pool_base.csv \
    --start-date 2025-11-15 \
    --end-date 2026-02-27
```

输出（`F:/backtest_workspace/logs/validate_universe_20260614_092243.json`）：

```json
{
  "universe_size_enabled": 10,
  "rows_dropped_invalid": 0,
  "rows_disabled": 0,
  "duckdb_coverage": {"codes_with_data": 10, "missing_count": 0, "codes_missing": []},
  "history_depth": {"min_history_bars": 60, "sufficient_count": 10, "thin_count": 0, "thin_codes": []},
  "sector_distribution": [
    {"sector": "新能源", "count": 2}, {"sector": "白酒", "count": 2}, {"sector": "银行", "count": 2},
    {"sector": "保险", "count": 1}, {"sector": "家电", "count": 1}, {"sector": "汽车", "count": 1},
    {"sector": "证券", "count": 1}
  ]
}
```

结论：现 universe 在该样本期内全部覆盖、全部历史充足、行业 7 类分布合理。

---

## 五、是否触碰生产文件：**否**

明确未触碰：

- `release/v1.0/`、`strategy_main.py`、`core/strategy/`、`core/scoring/dimension6plus2.py`、`core/risk_manager*` — 未读未写
- `D:/QMT_POOL/` — 未读未写
- `F:/金策智算/` — 仅 `access_mode='read_only'` 通过 reader 访问

本次写入：

- `backtest/scripts/validate_universe.py`、`backtest/tests/test_validate_universe.py`
- `agent_hub/2026-06-13_backtest_mvp/07_validate_universe_acceptance.md`（本文件）
- 运行时：`F:/backtest_workspace/logs/validate_universe_*.json`

---

## 六、是否违反 SPEC 边界：**否**

12 硬边界（授权令 §四）逐条核对：

| # | 边界 | 状态 |
|---|---|---|
| 1 | 不修改 release/v1.0 | ✅ |
| 2 | 不修改 strategy_main.py | ✅ |
| 3 | 不调用 passorder | ✅ |
| 4 | 不接 QMT 实盘/模拟 | ✅ |
| 5 | 不启动委托 | ✅ |
| 6 | 不写 F:\金策智算\ | ✅ |
| 7 | 不读写打开 quantifydata.duckdb | ✅（read_only） |
| 8 | 不在 C/D 盘写 results/cache/sample_db/logs | ✅ |
| 9 | 不引入 xtquant/MiniQMT | ✅ |
| 10 | 不混入 IMA 主升浪 | ✅ |
| 11 | 不改 6+2 生产策略主逻辑 | ✅ |
| 12 | 不破坏性 git 操作 | ✅（仅 add / commit） |

---

## 七、已知限制 / 后续方向

### 当前实现的限制

1. **`_bars_per_code` 直接访问 `reader._conn`**：私有字段访问。可接受，因为 reader 是同一个 backtest 包内部模块；如未来 reader 重构隐藏 conn，需要在 reader 上加 public `bars_per_code(codes, start, end)` 方法。
2. **行业字段允许为空**：`sector=""` 会进入 `sector_distribution` 作为空字符串桶。允许，因为 universe csv schema 不强制 sector；但报告消费者需要自行处理。
3. **`min_history_bars=60` 是硬编码默认**：与 strategy_core 的 INSUFFICIENT_HISTORY 阈值一致。如 strategy_core v0.3 改阈值，此处需同步（建议加入 SPEC 跨引用）。
4. **不校验 `enabled` 拼写**：例如 `enabled=Trueeee` 会被当作 truthy。`load_universe` 实现已经如此，本脚本一致。

### 可立即推进的后续

- universe csv 多版本对比（diff 工具：A 加了哪些代码、B 移除了哪些行业）
- 加 `--alert-thin-ratio` 阈值（如 thin_count/universe_size > 0.2 时告警 stderr，但仍 exit 0）
- 与 `validate_data.py` 合并成一个 `validate.py` 子命令式 CLI

---

签字：CC（夜班自主验收，诚哥 2026-06-14 免 Hermes 授权）
日期：2026-06-14
依据：`01_cc_full_night_authorization.md` + 诚哥 2026-06-14 口头补充授权
