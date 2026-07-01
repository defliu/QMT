# 工单：累计盈亏 CSV 重建 + 多策略统计接口 + 策略名更换

**日期**: 2026-07-01
**作者**: CC
**目的**: 诚哥发现策略启动日志"策略本金=100000 累计盈亏=+0 当前净值=..."累计盈亏一直为0。根因：`_g_cumulative_pnl` 机制只是单点累计（启动读 `endofday_nav_beat.txt`，卖出累加写回），文件丢了/不可靠就归零，没有从历史重建能力。本次：①策略名 config 化（去掉"双带主升浪_尾盘_外部池_beat四层版"，换"主升浪6+2"）；②多策略统计接口（按 STRATEGY_KEY 分文件）；③累计盈亏从 Hermes 持仓明细 CSV 重建。
**预计工时**: ≤ 60 分钟

---

## 〇、背景（必读，不要改这段）

### 诚哥已拍板的三个决策
1. **数据源**：仅 Hermes CSV（`D:\qmt_pool\`，0630 起，之前不补）
2. **新策略名**：`主升浪6+2`
3. **盈亏口径**：持仓明细 CSV 的"持仓盈亏"列（拥股=0 累加，券商端权威值）。**不要用成交明细 FIFO**（600641 买入在 0630 前无记录，配对失败 2280 永久丢失）。

### 关键约束
- 账户总资产千万级（资金概况 CSV 实测 10031185.73），策略本金 10 万，`总资产-本金` 口径完全不可用
- 模拟端不存历史：清仓股隔日从持仓明细消失 → 重建必须**扫所有历史持仓明细 CSV 文件、按代码去重**，不能只取最新快照
- `adapters/qmt_wrapper.py` 实测 **UTF-8 编码**（文件头 `# coding=gbk` 是历史遗留错误标注，不要改文件头）。build_strategy.py 的 `read_source` 用 UTF-8 读取源文件、`_force_gbk` 转 GBK 产物。用 Edit 工具改此文件没问题（它实际是 UTF-8）。
- Python 3.6.8 语法兼容（禁 f-string / dict[str,..] / walrus `:=` / match-case / `str|None`）

### 实测数据（D:\qmt_pool\持仓明细_20260630.csv，GBK）
字段 header：`资金账号,交易所,证券代码,证券名称,当前拥股,可用数量,冻结数量,成本价,最新价,持仓盈亏,浮动盈亏,盈亏比例,...`
0630 关键行：
- 600641 先导基电，当前拥股=0，持仓盈亏=2280.41 ← 已清仓，重建目标值
- 603283 赛腾股份，当前拥股=300，持仓盈亏=240.99 ← 持仓中，不取
- 688396 华润微，当前拥股=900，持仓盈亏=3240.90 ← 持仓中，不取
- 600397 江钨装备，当前拥股=800，持仓盈亏=1810.00 ← 持仓中，不取

重建期望：0630 只有 600641 拥股=0 → 重建值 = 2280.41

---

## 一、必做（8 项）

### TASK-1. config 加 display_name

**目标路径**: `D:/QMT_STRATEGIES/config/global_config.yaml`

**内容/做法**:
在 `strategy:` 段（现有 `name: "DUAL_BAND"` 那行下方）加一行 `display_name: "主升浪6+2"`。改完 strategy 段应为：
```yaml
strategy:
  name: "DUAL_BAND"
  display_name: "主升浪6+2"
  capital_base: 100000
  max_hold: 5
  ...
```
其他段不动。

### TASK-2. qmt_wrapper.py 常量区：策略名 config 化 + CUMULATIVE_PNL_FILE

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:

**(a) `_DEFAULT_CONFIG`（line 42 附近）的 strategy 段补 name/display_name**：
找到 `_DEFAULT_CONFIG` 里 strategy 段（含 capital_base 等），补 `name` 和 `display_name` 键。例如：
```python
'strategy': {
    'name': 'DUAL_BAND',
    'display_name': '主升浪6+2',
    'capital_base': 100000,
    ...原有键...
},
```

**(b) line 138-140 区域**：
现有：
```python
ACCOUNT_ID = '67014907'
STRATEGY_NAME = '双带主升浪_尾盘_外部池_beat四层版'
STRATEGY_VERSION = 'v2026.06.30-f1f5-lookup'
```
改为：
```python
ACCOUNT_ID = '67014907'
STRATEGY_KEY = _strategy_config.get('name', 'DUAL_BAND')
STRATEGY_NAME = _strategy_config.get('display_name', STRATEGY_KEY)
STRATEGY_VERSION = 'v2026.06.30-f1f5-lookup'
```
（删除硬编码旧名，STRATEGY_KEY 用于文件名/统计隔离，STRATEGY_NAME 用于日志/remark）

**(c) line 154-163 文件路径常量区**：
在现有路径常量区（`INTRADAY_NAV_FILE = ...` 那行附近）新增一行：
```python
CUMULATIVE_PNL_FILE = _path_config.get('cumulative_pnl_file', 'D:/QMT_POOL/cumulative_pnl_%s.txt' % STRATEGY_KEY)
```
（实际文件名 `cumulative_pnl_DUAL_BAND.txt`，未来多策略改 config name 即自动分文件）

**(d) line 170-178 DEBUG_MODE 分支**：
现有 DEBUG_MODE 分支里覆盖了 STRATEGY_NAME='全天测试版' 和各路径文件。**保留** STRATEGY_NAME='全天测试版' 覆盖，并在该分支内追加一行覆盖 CUMULATIVE_PNL_FILE：
```python
CUMULATIVE_PNL_FILE = 'D:/QMT_POOL/allday_nav.txt'
```
（与现有 allday 体系一致，避免与尾盘版串数据）

### TASK-3. qmt_wrapper.py 新增 rebuild_cumulative_pnl_from_csv() 函数

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:
在 `write_nav_file` 函数之后（line 793 后，与 read_nav_file/write_nav_file 并列）新增函数：

```python
def rebuild_cumulative_pnl_from_csv():
    """从 D:/qmt_pool/持仓明细_*.csv 重建累计已实现盈亏。

    扫所有历史持仓明细 CSV（日期<今日），按证券代码去重，
    取每只股票最新一次"拥股=0"（已清仓）的持仓盈亏，累加返回。
    清仓股隔日会从持仓明细消失，但历史 CSV 文件留存，所以不丢。
    """
    import glob
    csv_dir = 'D:/qmt_pool'
    today_str = datetime.now().strftime('%Y%m%d')
    files = []
    for fp in glob.glob(os.path.join(csv_dir, '持仓明细_*.csv')):
        fname = os.path.basename(fp)
        parts = fname.replace('.csv', '').split('_')
        if len(parts) >= 2:
            date_str = parts[-1]
            if len(date_str) == 8 and date_str.isdigit() and date_str < today_str:
                files.append((date_str, fp))
    if not files:
        return None
    files.sort()
    closed_pnl = {}
    for date_str, fp in files:
        try:
            with open(fp, 'r', encoding='gbk') as f:
                lines = f.readlines()
        except Exception as e:
            print("  [重建] 读取失败 %s: %s" % (fp, e))
            continue
        if len(lines) < 2:
            continue
        header = lines[0].strip().split(',')
        try:
            idx_code = header.index('证券代码')
            idx_vol = header.index('当前拥股')
            idx_pnl = header.index('持仓盈亏')
        except (ValueError, IndexError):
            print("  [重建] 表头未找到目标列: %s" % fp)
            continue
        for line in lines[1:]:
            row = line.strip().split(',')
            if len(row) <= max(idx_code, idx_vol, idx_pnl):
                continue
            code = row[idx_code].strip()
            vol_str = row[idx_vol].strip()
            pnl_str = row[idx_pnl].strip()
            if not code or not vol_str:
                continue
            try:
                volume = int(float(vol_str))
                pos_pnl = float(pnl_str) if pnl_str else 0.0
            except ValueError:
                continue
            if volume == 0:
                closed_pnl[code] = pos_pnl
    total = sum(closed_pnl.values())
    print("  [重建] 扫描 %d 个持仓明细CSV，清仓股 %d 只，累计已实现盈亏=%+.2f" % (
        len(files), len(closed_pnl), total))
    return total
```

**关键点**：
- 源文件 UTF-8，**中文字面量直接写**（`'持仓明细_*.csv'`、`'证券代码'`、`'当前拥股'`、`'持仓盈亏'`），**不要用 `.decode('gbk')`**。build 时 `_force_gbk` 转 GBK 产物，QMT 运行正常。
- `datetime` 已在文件顶部可用（line 3527 已用 `datetime.now()`）；`os` 已在顶部 import。
- `import glob` 放函数内（内聚，避免污染顶部 import）。
- 返回 `None` 表示无 CSV（让 init 走回退）；有 CSV 但无清仓股返回 `0.0`。
- 容错：解析失败的行/文件跳过 + 打印警告，不崩。

### TASK-4. qmt_wrapper.py 改 write_nav_file 调用路径（3处 realized + exit）

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:
grep `write_nav_file(INTRADAY_NAV_FILE` 找到所有调用点（应在 line 2384、2424、2528、3785 附近，共 4 处：3 处在卖出 realized 累加后，1 处在 exit）。
全部改为 `write_nav_file(CUMULATIVE_PNL_FILE, _g_cumulative_pnl)`。

**不要改** `read_nav_file` 的调用（init 里的 read 在 TASK-5 处理）。
**不要改** realized 累加逻辑（`_g_cumulative_pnl += realized` 保持不变）。

### TASK-5. qmt_wrapper.py 改 init 启动优先级

**目标路径**: `D:/QMT_STRATEGIES/adapters/qmt_wrapper.py`

**内容/做法**:
找到 init 里的（line 3532 附近）：
```python
_g_cumulative_pnl = read_nav_file(INTRADAY_NAV_FILE)
current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
```
改为：
```python
rebuilt = rebuild_cumulative_pnl_from_csv()
if rebuilt is not None:
    _g_cumulative_pnl = rebuilt
    write_nav_file(CUMULATIVE_PNL_FILE, _g_cumulative_pnl)
    print("  [重建] 从持仓明细CSV重建累计盈亏=%+.0f" % _g_cumulative_pnl)
else:
    _g_cumulative_pnl = read_nav_file(CUMULATIVE_PNL_FILE)
    if not os.path.exists('D:/QMT_POOL/cumulative_pnl_%s.txt' % STRATEGY_KEY) and os.path.exists(INTRADAY_NAV_FILE):
        _g_cumulative_pnl = read_nav_file(INTRADAY_NAV_FILE)
        print("  [迁移] 新累计文件不存在，从旧 %s 读取=%+.0f" % (os.path.basename(INTRADAY_NAV_FILE), _g_cumulative_pnl))
current_nav = STRATEGY_CAPITAL + _g_cumulative_pnl
```

exit（line 3779-3785 附近）里的 `read_nav_file(INTRADAY_NAV_FILE)` 和 `write_nav_file(INTRADAY_NAV_FILE, ...)`：read 改为读 `CUMULATIVE_PNL_FILE`（但 exit 里通常直接用内存 `_g_cumulative_pnl`，read 可能多余；保留现有逻辑结构，只把文件参数改 CUMULATIVE_PNL_FILE）。如果 exit 里 read 后又立即 write 同一文件，可简化为只 write，但**保守起见只改文件参数，不动结构**。

### TASK-6. tests/test_order_lookup.py 修硬编码策略名

**目标路径**: `D:/QMT_STRATEGIES/tests/test_order_lookup.py`

**内容/做法**:
grep `'双带主升浪_尾盘_外部池_beat四层版'` 或 `'双带主升浪'` 在本文件的所有出现（约 6 处）。
这些是 remark 匹配测试里硬编码的旧策略名。改为引用 `qmt.STRATEGY_NAME`（测试文件应已 `import adapters.qmt_wrapper as qmt` 或类似）。
若测试里是字符串字面量用于断言，改为 `qmt.STRATEGY_NAME` 或新名 `'主升浪6+2'`。保持测试逻辑不变，只换策略名来源。

如果某些断言依赖旧名的特定字符串结构，确保改后断言与 STRATEGY_NAME 一致。

### TASK-7. 新增 tests/test_rebuild_pnl.py

**目标路径**: `D:/QMT_STRATEGIES/tests/test_rebuild_pnl.py`（新建）

**内容/做法**:
参考 `tests/test_order_lookup.py`（FakeContext + monkey-patch 风格）和 `tests/test_config_fallback.py`（tempfile 手法）。

用例（pytest）：
1. `test_rebuild_closed_position`：用 tempfile + monkey-patch `rebuild_cumulative_pnl_from_csv` 的 csv_dir 和 datetime.now（返回 20260701），构造一个 `持仓明细_20260630.csv`（GBK，含 600641 拥股0/持仓盈亏2280.41 + 603283 拥股300/持仓盈亏240.99），断言返回 2280.41。
2. `test_rebuild_multi_csv_dedup`：两个日期 CSV（20260629、20260630），同 code 600641 拥股0 但持仓盈亏不同（如 2000、2280.41），断言取最新（2280.41）。
3. `test_rebuild_skip_today`：构造今日日期 CSV（datetime mock 返回 20260701，CSV 文件名 20260701），断言被跳过、返回 None（无历史 CSV）。
4. `test_rebuild_no_csv_fallback`：无 CSV 时返回 None。
5. `test_rebuild_holding_not_counted`：拥股>0 的持仓盈亏不计入（如 603283 拥股300 持仓盈亏240.99 不累加）。
6. `test_strategy_name_from_config`（归入策略名验证）：monkey-patch config 加载，断言 `qmt.STRATEGY_NAME == '主升浪6+2'` 且 `qmt.STRATEGY_KEY == 'DUAL_BAND'`。
7. `test_cumulative_pnl_file_naming`：断言 `qmt.CUMULATIVE_PNL_FILE` 包含 `DUAL_BAND`。

**关键**：
- monkey-patch `qmt_wrapper` 模块里的 `datetime`（或 `datetime.now`）来固定"今日"，避免测试依赖真实日期。注意 `datetime` 是 `from datetime import datetime` 还是 `import datetime`，看 qmt_wrapper.py 顶部 import 方式，monkey-patch 对应的引用。
- tempfile 造 CSV 时用 GBK 写中文表头。
- 测试要能独立跑（不依赖 D:\qmt_pool 真实文件）。

### TASK-8. build + validate + pytest

**内容/做法**:

```bash
cd D:/QMT_STRATEGIES
python scripts/build_strategy.py
python scripts/build_strategy.py --allday
python scripts/validate_qmt_file.py strategy_main.py
python -m pytest tests/test_rebuild_pnl.py tests/test_order_lookup.py -q
```

贴全部输出。要求：
- build 无报错（GBK 编码不失败）
- validate strategy_main.py 6/6 ALL PASS
- pytest 全绿

若 pytest 有失败，修到全绿（不准跳过）。

---

## 二、严禁

1. 禁止 git add / commit / push（本次只改代码，commit 等诚哥验完另出工单）
2. 禁止改动本工单上方
3. 禁止用成交明细 CSV 做 FIFO（诚哥已否决，必须用持仓明细的持仓盈亏列）
4. 禁止改 `strategy_main.py` / `strategy_dev.py` / `strategy_allday.py`（build 产物，build 自动更新）
5. 禁止改 `scripts/qmt_daily_export.py` / `scripts/build_strategy.py`（不在本次范围）
6. 禁止改其他 `_beat` 文件名（holdings/trade_log/score_history/sell_state 保持向后兼容）
7. 禁止改 realized 累加逻辑（`_g_cumulative_pnl += realized` 不变，只改 write_nav_file 的文件参数）
8. 禁止改"累计盈亏"口径（保持"已实现"语义，浮动盈亏 line 2902 单独算，不变）
9. 禁止用 f-string / dict[str,..] / walrus / match-case（Python 3.6.8 兼容）
10. 禁止改 qmt_wrapper.py 文件头 `# coding=gbk`（虽然实际是 UTF-8，但文件头保持原样，build 的 strip_coding_header 会处理）

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] TASK-1 config 加 display_name="主升浪6+2"
- [ ] TASK-2 qmt_wrapper.py 常量区：STRATEGY_KEY/STRATEGY_NAME config化 + CUMULATIVE_PNL_FILE + DEBUG_MODE覆盖
- [ ] TASK-3 rebuild_cumulative_pnl_from_csv() 函数（扫历史持仓明细CSV，拥股=0去重累加）
- [ ] TASK-4 write_nav_file 4处调用改 CUMULATIVE_PNL_FILE
- [ ] TASK-5 init 启动优先级（CSV重建优先→新文件→旧文件兼容迁移）
- [ ] TASK-6 test_order_lookup.py 硬编码策略名改 qmt.STRATEGY_NAME
- [ ] TASK-7 新增 tests/test_rebuild_pnl.py 7用例
- [ ] TASK-8 build + validate 6/6 PASS + pytest 全绿，贴输出
- [ ] 未 commit / 未改 build 产物 / 未改 qmt_daily_export.py
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-07-01T06:47:07Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1 config 加 display_name="主升浪6+2"
- [x] TASK-2 qmt_wrapper.py 常量区：STRATEGY_KEY/STRATEGY_NAME config化 + CUMULATIVE_PNL_FILE + DEBUG_MODE覆盖
- [x] TASK-3 rebuild_cumulative_pnl_from_csv() 函数（扫历史持仓明细CSV，拥股=0去重累加）
- [x] TASK-4 write_nav_file 4处调用改 CUMULATIVE_PNL_FILE
- [x] TASK-5 init 启动优先级（CSV重建优先→新文件→旧文件兼容迁移）
- [x] TASK-6 test_order_lookup.py 硬编码策略名改 qmt.STRATEGY_NAME
- [x] TASK-7 新增 tests/test_rebuild_pnl.py 7用例
- [x] TASK-8 build + validate 6/6 PASS + pytest 全绿，贴输出
- [x] 未 commit / 未改 build 产物 / 未改 qmt_daily_export.py
- [x] 仅末尾追加，未改动工单上方

### TASK-8 输出

```
Building strategy_main.py ...
OK: strategy_main.py (生产版, 不含MOCK)
Size: 248414 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.

Building strategy_allday.py ...
  [allday] 硬编码 DEBUG_MODE = True
OK: strategy_allday.py (全天调试版, 不含MOCK)
Size: 248383 bytes
First line: # coding=gbk
Encoding: GBK (verified by reading with gbk)
Validating... OK
Done.

Validating: strategy_main.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS  (所有评分值 %.2f)
  ------------------------
  Result: ALL PASS  (6/6)

tests/test_rebuild_pnl.py + tests/test_order_lookup.py:
................ 16 passed in 1.07s
```
