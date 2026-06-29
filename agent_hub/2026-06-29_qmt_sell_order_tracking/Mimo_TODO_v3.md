# MIMO_TODO_v3：恢复 qmt_wrapper.py 原 CRLF 行尾，避免巨大 diff

**日期**: 2026-06-29
**作者**: CC
**目的**: v2 将 `adapters/qmt_wrapper.py` 整文件 CRLF→LF，虽然 diff-check 无 error，但造成约 6998 行巨大 diff；本单只恢复该文件原有 CRLF 行尾，保留 v1 功能修复，不改逻辑。
**预计工时**: ≤ 20 分钟

---

## 一、背景

v2 回执称将 `adapters/qmt_wrapper.py` 行尾统一为 LF。CC 验收发现：

```text
adapters/qmt_wrapper.py | 6998 ++++++++++++++++++++++++-----------------------
```

这不适合提交。仓库 HEAD 中 `adapters/qmt_wrapper.py` 原本是 CRLF（`core.autocrlf=true`），需要恢复 CRLF，保持 diff 只显示 v1 的真实逻辑改动。

注意：v1 功能修复是正确的，必须保留：

- `Trader.buy()` 下单后反查订单；
- `_lookup_recent_order_id()` 不再硬过滤 remark；
- 多候选 `remark_match + ot_hms` 排序。

---

## 二、必做（4 项）

### TASK-1. 确认当前巨大 diff

执行：

```bash
git -C D:/QMT_STRATEGIES diff --stat -- adapters/qmt_wrapper.py
```

回执中记录当前是否仍是约 6998 行巨大 diff。

### TASK-2. 只恢复 `adapters/qmt_wrapper.py` 为 CRLF 行尾

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:
1. 仅转换行尾：LF → CRLF。
2. 必须保留文件内容和 v1 功能逻辑，不得改代码文本。
3. 不得编辑 `strategy_main.py` / `strategy_allday.py`，后面用 build 生成。
4. 可用 Python 二进制方式转换，例如读取 bytes，先规范为 LF，再写回 CRLF；不要改变编码内容。

转换后检查：

```bash
git -C D:/QMT_STRATEGIES diff --stat -- adapters/qmt_wrapper.py
git -C D:/QMT_STRATEGIES diff -- adapters/qmt_wrapper.py
```

要求：
- diff stat 回到小范围（约 34 行级别，而不是 6998 行）；
- diff 内容仍是 v1 功能改动；
- 不允许功能逻辑消失。

### TASK-3. 复跑最小验证

```bash
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" -m pytest tests/test_order_lookup.py -q
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/build_strategy.py
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/build_strategy.py --allday
"C:/Users/Administrator/AppData/Local/Programs/Python/Python310/python.exe" scripts/validate_qmt_file.py strategy_main.py
```

要求：
- 专项测试 9 passed；
- 生产版和全天版构建 OK；
- validate 6/6 PASS。

### TASK-4. 写回执

在本文件末尾追加完成回执，记录：

- 恢复前 diff stat；
- 恢复后 diff stat；
- 是否确认只恢复行尾、未改逻辑；
- 验证命令结果。

---

## 三、严禁

1. 禁止 git add / commit / push。
2. 禁止改 release、QMT 日志、`D:/QMT_POOL/`、QMT 安装目录。
3. 禁止扩大范围修历史失败测试。
4. 禁止改 v1 功能逻辑。
5. 禁止直接手改 `strategy_main.py` / `strategy_allday.py`。
6. 遇异常必须停下写明。

---

## 四、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <ISO 8601 真实时刻>
**MIMO 模型**: <实际名>
**恢复前 diff stat**: <摘要>
**恢复后 diff stat**: <摘要>
**改动文件**:
- `adapters/qmt_wrapper.py`: <摘要>
**验证命令与结果**:
- `<命令>` → PASS/FAIL，摘要
**自检**:
- [ ] 只恢复 CRLF 行尾，未改 v1 功能逻辑
- [ ] qmt_wrapper.py diff stat 已回到小范围
- [ ] tests/test_order_lookup.py 9 passed
- [ ] build_strategy.py / --allday OK
- [ ] validate_qmt_file.py strategy_main.py 6/6 PASS
- [ ] 未 git add/commit/push
```

---

## 完成回执

**执行时间**: 2026-06-29T15:30:00Z
**MIMO 模型**: mimo-auto
**恢复前 diff stat**: `adapters/qmt_wrapper.py | 6998 ++++++++++++++++++++++++-----------------------` (3505 insertions, 3493 deletions)
**恢复后 diff stat**: `adapters/qmt_wrapper.py | 34 +++++++++++++++++++++++-----------` (23 insertions, 11 deletions)
**改动文件**:
- `adapters/qmt_wrapper.py`: 仅将 LF 行尾恢复为 CRLF，v1 功能改动完整保留
**验证命令与结果**:
- `pytest tests/test_order_lookup.py -q` → PASS，9 passed
- `python scripts/build_strategy.py` → OK，strategy_main.py 构建成功 (234226 bytes, GBK)
- `python scripts/build_strategy.py --allday` → OK，strategy_allday.py 构建成功 (234195 bytes, GBK)
- `python scripts/validate_qmt_file.py strategy_main.py` → ALL PASS (6/6)
**自检**:
- [x] 只恢复 CRLF 行尾，未改 v1 功能逻辑
- [x] qmt_wrapper.py diff stat 已回到小范围 (34 行)
- [x] tests/test_order_lookup.py 9 passed
- [x] build_strategy.py / --allday OK
- [x] validate_qmt_file.py strategy_main.py 6/6 PASS
- [x] 未 git add/commit/push
