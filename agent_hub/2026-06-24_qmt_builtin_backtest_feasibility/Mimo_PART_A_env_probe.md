# MIMO 工单 — PART-A 环境探活

任务：T-20260624-004 PART-A
SPEC：`D:/QMT_STRATEGIES/specs/SPEC_QMT_BUILTIN_BACKTEST_FEASIBILITY.md` 模块 1
Brief：`./00_brief.md`
派单时间：2026-06-24
模式：CC 自动派单（[[cc-mimo-dispatch-mode]]）

---

## 0. 任务范围（**不许超出**）

只做一件事：在两种 MiniQMT 状态下，用 QMT 自带 Python 调用 `xtquant.qmttools.stgentry.run_file()`，记录返回与报错。

**禁止动作**（违反任一项 → 立即停手回报）：
- 不修改 `strategy_main.py`、`strategy_allday.py`、`release/` 任何文件
- 不调用 `passorder`
- 不动 `D:/QMT_POOL/` 任何运行时文件
- 不 commit（PART-A 还没到落地阶段）
- 不许"判定异常无关"自行继续 — 遇异常立刻停（[[mimo-must-stop-on-any-failure]]）

---

## 1. 准备步骤

### 1.1 建目录

```bash
mkdir -p D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/data
mkdir -p D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/reports
mkdir -p D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts
```

### 1.2 写最小探针策略

文件路径：`D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/_qmt_probe_strategy.py`

内容**必须严格如下**（UTF-8 编码，不要加任何额外逻辑）：

```python
# coding=utf-8
"""QMT 内置回测探针策略 — PART-A 用，最小可执行版。

只做三件事：
1. init 打印生命周期标记
2. handlebar 累计 bar 数
3. stop 把 bar 数写入文件，让外部知道 handlebar 跑过几次

不下单、不调 passorder、不写 D:/QMT_POOL。
"""

import json
import os
import time

PROBE_LOG = r'D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/data/_probe_a_log.json'

_state = {
    'init_called': False,
    'after_init_called': False,
    'handlebar_count': 0,
    'stop_called': False,
    'first_bar_time': None,
    'last_bar_time': None,
    'error': None,
}


def init(C):
    _state['init_called'] = True
    _state['init_ts'] = time.time()
    # 注意：start_time/end_time 在 _param 里，stgframe 没自动赋值到 C
    C.start_time = C._param.get('start_time', '')
    C.end_time = C._param.get('end_time', '')


def after_init(C):
    _state['after_init_called'] = True


def handlebar(C):
    try:
        _state['handlebar_count'] += 1
        bar_time = C.timelist[C.barpos] if C.barpos >= 0 and C.barpos < len(C.timelist) else None
        if _state['first_bar_time'] is None:
            _state['first_bar_time'] = bar_time
        _state['last_bar_time'] = bar_time
    except Exception as e:
        _state['error'] = repr(e)


def stop(C):
    _state['stop_called'] = True
    _state['stop_ts'] = time.time()
    try:
        os.makedirs(os.path.dirname(PROBE_LOG), exist_ok=True)
        with open(PROBE_LOG, 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        # stop 阶段写不进去就静默，外层会用 stderr 兜底
        pass
```

### 1.3 写驱动脚本

文件路径：`D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/run_probe_a.py`

内容**必须严格如下**：

```python
# coding=utf-8
"""PART-A 驱动 — 用 QMT 自带 Python 跑探针。

输出：
  stdout / stderr → run_probe_a_<state>.log
  探针自己写       → data/_probe_a_log.json
"""

import json
import os
import sys
import time
import traceback

PROBE = r'D:/QMT_STRATEGIES/agent_hub/2026-06-24_qmt_builtin_backtest_feasibility/scripts/_qmt_probe_strategy.py'

PARAM = {
    'stock_code': '000001.SZ',
    'period': '1d',
    'start_time': '20240101',
    'end_time': '20240331',
    'trade_mode': 'backtest',
    'quote_mode': 'history',
    'asset': 1000000,
    'dividend_type': 'front',
    'title': 'probe_a_minimal',
}

def main():
    print('[probe_a] python:', sys.executable)
    print('[probe_a] cwd   :', os.getcwd())
    print('[probe_a] probe :', PROBE)
    print('[probe_a] param :', json.dumps(PARAM, ensure_ascii=False))

    t0 = time.time()
    try:
        from xtquant.qmttools import stgentry
        print('[probe_a] stgentry imported:', stgentry.__file__)
    except Exception:
        print('[probe_a] FAIL: import stgentry')
        traceback.print_exc()
        return 10

    try:
        ret = stgentry.run_file(PROBE, PARAM)
        print('[probe_a] run_file returned:', repr(ret))
        print('[probe_a] elapsed (s)      :', round(time.time() - t0, 2))
    except Exception:
        print('[probe_a] FAIL: run_file raised')
        print('[probe_a] elapsed (s)      :', round(time.time() - t0, 2))
        traceback.print_exc()
        return 20

    return 0


if __name__ == '__main__':
    sys.exit(main())
```

---

## 2. 执行步骤（两轮）

> **2026-06-24 CC 补充执行顺序**：
> 派单时 QMT 已启动（XtMiniQmt.exe PID 76524），happy path 优先，所以**先做轮次 2（QMT 已启动），跑通后再回执**。
> 轮次 1（QMT 未启动）是否还需要补做，等 CC 看完轮次 2 结果再定 — **不要为了凑两轮主动关 QMT**。
> 如果轮次 2 失败，整单 STOP，**不要**再去尝试轮次 1。

### 轮次 1：MiniQMT **未启动**（**本次先跳过，等 CC 指示**）

1. 用 `tasklist | findstr /I XtMiniQmt` 确认确实没在跑
2. 执行（在普通 PowerShell / cmd 里）：

```cmd
& "D:\国金证券QMT交易端\bin.x64\pythonw.exe" "D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\scripts\run_probe_a.py" 1> "D:\QMT_STRATEGIES\agent_hub\2026-06-24_qmt_builtin_backtest_feasibility\data\run_probe_a_qmt_off.log" 2>&1
```

3. **设 90 秒超时**（用 PowerShell `Start-Process -Wait` + 计时；或 cmd 用 `timeout /t 90` 包一层）；超时强杀进程
4. 把 stdout/stderr 完整保存到 `data/run_probe_a_qmt_off.log`
5. 即使 `_probe_a_log.json` 没生成也要记录（这本身就是结论）

### 轮次 2：MiniQMT **已启动**（**先做这一轮**）

1. 双击启动 QMT（实盘端：`D:\国金证券QMT交易端\XtMiniQmt.exe` 或正常运营版），登录任意账号
2. `tasklist | findstr /I XtMiniQmt` 确认进程在
3. 同样命令，输出文件名直接用 `run_probe_a_qmt_on.log`（不需要先重命名前一轮的 json，因为轮次 1 跳过了）
4. 设 180 秒超时（要拉历史数据，给宽一点）

---

## 3. 验收回执（**回到这个文件夹下** `Mimo_PART_A_REPLY.md`）

必须包含：

### 3.1 轮次 1（MiniQMT 未启动）— **本次跳过**

- [ ] 标注「本轮按 CC 指示跳过，QMT 派单时已在运行（PID 76524）」即可，不需要 log/json

### 3.2 轮次 2（MiniQMT 已启动）

- [ ] tasklist 输出
- [ ] `run_probe_a_qmt_on.log` 全文（同上规则）
- [ ] `_probe_a_log.json` 内容（必须有，否则结论是 callback 未跑）
- [ ] 总耗时（秒）

### 3.3 三个事实判断（**必答**）

填以下表格（`是 / 否 / 不确定 + 证据行号`）：

| 问题 | 答 | 证据（log 行号或 json 字段） |
|------|----|---|
| MiniQMT 未启动时 `run_file()` 是否报错？ | 本次跳过 | — |
| 报错信息是什么（关键词）？ | 本次跳过 | — |
| MiniQMT 启动后 `init/after_init/handlebar/stop` 是否都被调过？ |  |  |
| `handlebar_count` 是几（预期 ≈ 60 个交易日）？ |  |  |
| `run_file()` 返回值是什么？ |  |  |

### 3.4 自检（必须全勾，否则 REJECT）

- [ ] 我没改任何生产文件（`git status` 输出贴一段证明）
- [ ] 我没 commit
- [ ] 我没动 `D:/QMT_POOL/`
- [ ] 我没"判定异常无关"自行继续 — 报错就停了，回报了
- [ ] 两个 log 文件 + 两个 json 文件（或显式说明哪个没生成）都在 `data/` 下
- [ ] 探针脚本完全照抄上文 1.2，没加私货

---

## 4. 异常处理（[[mimo-must-stop-on-any-failure]]）

任何下列情况立即停手，把现象写进回执，**不要自己改脚本继续往下尝试**：
- import stgentry 报错
- `run_file()` 抛任何异常
- 进程卡住超时被强杀
- 探针 json 没生成
- QMT 启动失败 / 登录失败

CC 收到回执判完情况再决定下一步（修脚本？等诚哥/恢复 QMT？换探针策略？）。

---

## 5. 完成判据

- 两轮各自的 log + json 齐全
- 回执 3.3 表全部填完
- 自检 3.4 全勾
- 没产生任何 commit
- 没碰生产文件

满足以上 = PART-A 完成，CC 验收后挂 PART-B 工单。
