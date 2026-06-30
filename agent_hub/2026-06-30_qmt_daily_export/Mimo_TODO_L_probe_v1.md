# 工单L：QMT 每日导出 — 探针脚本（ODM 第一步）

**日期**: 2026-06-30
**作者**: CC
**目的**: Hermes 团队需求(SPEC `D:/QMT_STRATEGIES/specs/qmt_daily_export_spec.md`)——每日导出成交/持仓/资金三张 CSV 到 `D:\qmt_pool\`。ODM 工作流第一步:写探针脚本,在 QMT 模拟端跑,确认 `get_trade_detail_data` 返回对象的实际属性名,再写正式脚本。
**预计工时**: ≤ 15 分钟

---

## 〇、背景（必读，不要改这段）

SPEC 给的属性名与生产代码 `adapters/qmt_wrapper.py` 已实测的有出入,必须用探针确认真实属性名:
- position 证券代码:SPEC 写 `m_strStockCode`,生产代码用 `m_strInstrumentID`+`m_strExchangeID` 拼接
- account 总资产:SPEC 写 `m_dTotalAssets`,生产代码实测 `m_dAssetBalance`(见 memory [[qmt-account-asset-fields]])
- position 当日盈亏:SPEC 写 `m_dTodayProfit`,生产代码用 `m_dTodayBSPnl`

`get_trade_detail_data` 是 QMT 内置 API,CC/MIMO 环境跑不了,**探针脚本必须由诚哥在 QMT 模拟端跑**。本工单只写脚本,不执行。

输出目录 `D:\qmt_pool\` 已确认可达。

---

## 一、必做（2 项）

### TASK-1. 写探针脚本

**目标路径**: `D:/QMT_STRATEGIES/scripts/qmt_probe.py`

**内容/做法**:

按 SPEC 5.1 模板写,关键调整:
- `OUTPUT_DIR = r'D:\qmt_pool'`（SPEC 5.1 写的 `D:\QMT_POOL` 改成 `D:\qmt_pool`，跟正式导出目标一致）
- 探针输出文件: `D:\qmt_pool\probe_output.txt`
- `init(ContextInfo)` 入口（QMT 策略研究里运行时调用）
- 三个数据类型 deal/position/account 都探,每个打印前 3 条记录的所有非下划线属性及值
- 编码 GBK,文件头 `# coding=gbk`
- Python 3.6.8 语法（禁 f-string / dict[str,..] / walrus / match-case）

脚本内容（MIMO 直接写这个）:

```python
# coding=gbk
"""
QMT 探针：打印 get_trade_detail_data 返回对象的属性和示例值
在 QMT 模拟端 Python 策略研究中运行，结果写入 D:\qmt_pool\probe_output.txt
诚哥跑完把 probe_output.txt 发给 CC，CC 据真实属性名写正式导出脚本
"""

import os

ACCOUNT_ID = '67014907'
OUTPUT_DIR = r'D:\qmt_pool'


def init(ContextInfo):
    lines = []

    for data_type in ['deal', 'position', 'account']:
        lines.append('=' * 60)
        lines.append('data_type: %s' % data_type)
        lines.append('=' * 60)

        try:
            data = get_trade_detail_data(ACCOUNT_ID, 'STOCK', data_type)
        except Exception as e:
            lines.append('get_trade_detail_data exception: %s' % e)
            lines.append('')
            continue

        lines.append('count: %d' % len(data))

        for i, obj in enumerate(data[:3]):
            lines.append('--- record %d ---' % i)
            for attr in dir(obj):
                if attr.startswith('_'):
                    continue
                try:
                    val = getattr(obj, attr)
                    if callable(val):
                        continue
                    lines.append('  %s = %r' % (attr, val))
                except Exception as e:
                    lines.append('  %s = <err %s>' % (attr, e))
        lines.append('')

    probe_path = os.path.join(OUTPUT_DIR, 'probe_output.txt')
    try:
        with open(probe_path, 'w', encoding='gbk') as f:
            f.write('\n'.join(lines))
        print('probe output written: %s' % probe_path)
    except Exception as e:
        print('write probe failed: %s' % e)
        print('\n'.join(lines))


def handlebar(ContextInfo):
    pass
```

**关键**:
- `handlebar` 空函数必须有,QMT 策略研究要求。
- `callable(val)` 跳过方法,只打印数据属性。
- `%r` 打印原始值,方便看类型。
- 异常都 try/except,不能让探针崩。

### TASK-2. validate + 给诚哥的运行说明

**内容/做法**:

1. `python scripts/validate_qmt_file.py scripts/qmt_probe.py` 必须 6 项 ALL PASS。
2. 在工单回执里写清楚诚哥怎么跑:
   - 把 `scripts/qmt_probe.py` 内容粘到 QMT 模拟端「Python策略研究」
   - 账号选 67014907
   - 运行,等打印 `probe output written: D:\qmt_pool\probe_output.txt`
   - 把 `D:\qmt_pool\probe_output.txt` 发给 CC

贴 validate 输出。

---

## 二、严禁

1. 禁止 git add / commit / push
2. 禁止改动本工单上方
3. 禁止写正式导出脚本（本工单只写探针，正式脚本等探针结果）
4. 禁止改 strategy_main.py / strategy_allday.py / qmt_wrapper.py
5. 禁止跑实盘交易（探针只读 get_trade_detail_data，不下单）
6. **文件编码 GBK，`# coding=gbk`；Python 3.6.8 语法（禁 f-string/dict[str,..]/walrus/match-case）**

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 真实拿>
**MIMO 模型**: <实际模型名>
**自检**:
- [ ] scripts/qmt_probe.py 已创建，内容如工单 TASK-1
- [ ] validate scripts/qmt_probe.py 6 项 ALL PASS，贴输出
- [ ] 回执含给诚哥的运行说明（粘到QMT策略研究、账号67014907、跑完发 probe_output.txt）
- [ ] 未写正式导出脚本 / 未改策略代码 / 未 git 操作
- [ ] 仅末尾追加，未改动工单上方
```

---

## 完成回执

**执行时间**: 2026-06-30T15:09:25Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] scripts/qmt_probe.py 已创建，内容如工单 TASK-1
- [x] validate scripts/qmt_probe.py 6 项 ALL PASS，贴输出
- [x] 回执含给诚哥的运行说明（粘到QMT策略研究、账号67014907、跑完发 probe_output.txt）
- [x] 未写正式导出脚本 / 未改策略代码 / 未 git 操作
- [x] 仅末尾追加，未改动工单上方

**validate 输出**:
```
Validating: qmt_probe.py
  [1/6] 文件存在         PASS
  [2/6] 编码 GBK         PASS
  [3/6] 文件头 # coding=gbk  PASS
  [4/6] Python 3.6 语法   PASS
  [5/6] 无 MOCK 残留      PASS
  [6/6] 无长小数输出      PASS  (所有评分值 %.2f)
  ------------------------
  Result: ALL PASS  (6/6)
```

**给诚哥的运行说明**:
1. 把 `D:/QMT_STRATEGIES/scripts/qmt_probe.py` 的全部内容复制
2. 打开 QMT 模拟端 →「Python策略研究」→ 粘贴内容
3. 账号选 `67014907`
4. 点击运行，等待打印 `probe output written: D:\qmt_pool\probe_output.txt`
5. 运行完成后，把 `D:\qmt_pool\probe_output.txt` 文件内容发给 CC
