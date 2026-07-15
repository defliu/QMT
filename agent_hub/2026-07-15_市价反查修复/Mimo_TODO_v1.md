# TASK: 修反查失败(方案A, 诚哥已拍板) + 加卖出评估心跳日志

**日期**: 2026-07-15
**作者**: CC
**目的**: 修复"从没见过市价委托"+"卖出只在10点"同根问题(反查失败断链)
**预计工时**: 实际 ~30 分钟(MIMO执行+CC验收)
**状态**: ✅ 已完成, commit 42cd130, 待诚哥部署模拟端验证

---

## 背景
诚哥审查发现: ① 卖出"只在10点触发"是日志静默假象(_g_sell_skip_printed每票每天首次去重打印) ② 从没见过市价委托, 根因是 _lookup_recent_order_id 反查失败导致 sell()返回None, 不登记 _g_pending_sells, _check_pending_sells 的撤单/市价重试分支(_retry_pending_sell retries>=1 use_market=True price_type=5)永不触发。铁证: D:/QMT_POOL/lookup_diag_20260715.csv 显示 605208 反查失败时 orders 里是 status=50待报单(未申报), m_nOrderVolume空, m_strInsertTime=095959<100000, 4×0.2s=0.8s轮询不够等新单入列。

诚哥拍板方案A: 放宽vol匹配(待报单字段空不continue) + 加长轮询0.8s->3s + 修dump按code过滤。心跳日志无争议直接做。

## 源文件
adapters/qmt_wrapper.py (UTF-8编码, 用Edit工具可)
禁止改 build产物 strategy_main.py(它是 build_strategy.py 生成的GBK产物, 改了下次build白改, 教训见 mimo-v1-claimed-done-unchanged)。
改完源文件后跑 build 重新生成 strategy_main.py, 再 validate。

## ⚠️ TASK-1 dirty守卫(开工必做)
`git -C D:/QMT_STRATEGIES diff -- adapters/qmt_wrapper.py`
看当前未commit改动。若有与反查/心跳无关的改动, 保留不动, commit只stage本任务改动行。
(教训: YEN_FIX把200+行dirty带进commit 0979226)

## 改动1: 修 _lookup_recent_order_id 反查失败 (方案A)

### 1a. vol匹配放宽 (qmt_wrapper.py 约489-491行, _lookup_recent_order_id 内)
当前:
```
                vol = getattr(o, 'm_nOrderVolume', 0)
                if vol != expected_vol:
                    continue
```
改为:
```
                vol = getattr(o, 'm_nOrderVolume', 0)
                # BUG5根因: 待报单status=50时m_nOrderVolume为空, 被 vol!=expected_vol 误continue
                # 改: vol空/0时不continue, 继续走 code/direction/time/remark 校验(防误匹配他票)
                if vol and vol != expected_vol:
                    continue
```
防误匹配说明(场景推演必答): vol空时仍受 条件1(code==stock_code) + 条件4(direction m_strOptName含卖/买) + 条件5(time>=t_before-1) + remark优先级 约束, 不会误匹配他票或旧单。

### 1b. 加长反查轮询 0.8s->3s (qmt_wrapper.py 约277-281行)
- SELL_LOOKUP_RETRIES = 4  ->  15  (15×0.2=3s, 待报单status=50变已报需时间, 原0.8s不够)
- BUY_LOOKUP_RETRIES = 4   ->  15
- SELL_LOOKUP_INTERVAL / BUY_LOOKUP_INTERVAL 保持 0.2 不变
- 更新行尾注释说明原因

### 1c. 修诊断dump按code过滤 (qmt_wrapper.py 约530行)
当前: `                        for _diag_o in orders[:5]:`
(不按code过滤, 688710反查dump里混入605208委托, 污染排查)
改为:
```
                        _diag_mine = [o for o in orders if ("%s.%s" % (getattr(o, 'm_strInstrumentID', ''), getattr(o, 'm_strExchangeID', '')) == stock_code)]
                        for _diag_o in _diag_mine[:5]:
```

## 改动2: 加卖出评估心跳日志 (qmt_wrapper.py)

目的: _check_and_execute_sell(约2356行)加每5分钟心跳, 解决"卖出只在10点"可观测性假象。当前[卖出评估]每票每天首次去重打印(_g_sell_skip_printed 约2390行), 10:01-14:57静默, 诚哥误以为没在跑。

### 2a. 模块级变量 (约240行 _g_phase_printed 附近)
加: `_g_last_heartbeat_min = -1`

### 2b. _check_and_execute_sell 开头加心跳 (约2357行, 在 `_g_sell_engine is None` 检查之后加)
```
    # 心跳: 每5分钟打印卖出评估摘要, 让全天评估可观测(解决"只在10点"假象)
    global _g_last_heartbeat_min
    try:
        _hb_dt = _get_qmt_time(C)
        _hb_now = _hb_dt.strftime('%H%M')
        _hb_min = int(_hb_now[:2]) * 60 + int(_hb_now[2:4])
        if _hb_min - _g_last_heartbeat_min >= 5 or _g_last_heartbeat_min < 0:
            _g_last_heartbeat_min = _hb_min
            _hb_codes = ','.join(sorted(_g_my_codes.keys())) if _g_my_codes else ''
            print("  [心跳] %s 卖出评估运行中 持仓%d只[%s]" % (_hb_now, len(_g_my_codes), _hb_codes))
    except Exception:
        pass  # 心跳不影响主流程
```

### 2c. 换日重置 (约3860行 _g_sell_skip_printed.clear() 附近)
加: `        _g_last_heartbeat_min = -1`

## 验收(逐条贴证据, 不贴不算完成)
1. `git -C D:/QMT_STRATEGIES diff -- adapters/qmt_wrapper.py` 贴改动, 确认只动反查/心跳相关, 未碰TASK-1的dirty行
2. grep作证(贴命中行):
   - `grep -n "if vol and vol != expected_vol" adapters/qmt_wrapper.py` -> 命中1处(1a)
   - `grep -n "SELL_LOOKUP_RETRIES = 15" adapters/qmt_wrapper.py` -> 命中(1b)
   - `grep -n "BUY_LOOKUP_RETRIES = 15" adapters/qmt_wrapper.py` -> 命中(1b)
   - `grep -n "_diag_mine" adapters/qmt_wrapper.py` -> 命中(1c)
   - `grep -n "_g_last_heartbeat_min" adapters/qmt_wrapper.py` -> 命中>=3处(2a声明+2b使用+2c重置)
3. `python scripts/build_strategy.py` (重新build生成strategy_main.py, 确认无报错, 贴Size行)
4. `python scripts/validate_qmt_file.py strategy_main.py` -> 6项ALL PASS (贴结果)
5. 场景推演(文字答):
   - 待报单status=50 m_nOrderVolume空: 改后1a能否匹配?(答:能,vol空跳过vol检查,走code/direction/time)
   - 605208新委托10:00:01下0.8s未入列: 改后1b轮询3s能否等到?(答:能,3s足够入列+字段填全)
   - 心跳: 0930首次打印, 之后0935/0940...每5分钟一次, 全天可观测

## 严禁段(违反必返工)
- 遇任何异常/报错/不确定必停, 不得自判"无关"继续(教训: TM_FIX_20260623)
- 不得改build产物strategy_main.py, 只改源adapters/qmt_wrapper.py
- 不得用patch工具
- Python3.6.8语法: 禁 dict[str,]、str|None、walrus :=、match-case、f-string
- commit: 单commit, 回执staged进主commit, 不补chore commit(教训: TASK-5)
- 不得声称完成但源文件没改(教训: v1工单改了build产物源没动)。验收grep源文件作证。

---

## 完成回执(MIMO 执行 + CC 独立验收)

**执行时间**: 2026-07-15 (mimo run 完成, exit 0)
**MIMO 模型**: mimo-auto (build agent)
**commit**: 42cd130 (CC commit, MIMO 漏 commit 由 CC 补)

### MIMO 验收证据
1. **git diff**: 仅反查/心跳相关改动, 未碰其他行
2. **grep 作证**:
   - `if vol and vol != expected_vol` -> 命中 1 处 (line 493)
   - `SELL_LOOKUP_RETRIES = 15` -> 命中 (line 278)
   - `BUY_LOOKUP_RETRIES = 15` -> 命中 (line 282)
   - `_diag_mine` -> 命中 2 处 (line 533-534)
   - `_g_last_heartbeat_min` -> 命中 6 处 (line 241 声明 + 2362/2372/2373 使用 + 3865/3885 重置)
3. **build**: `strategy_main.py` 298840 bytes, GBK 编码
4. **validate**: 6/6 ALL PASS
   - [1/6] 文件存在 PASS / [2/6] 编码 GBK PASS / [3/6] 文件头 # coding=gbk PASS
   - [4/6] Python 3.6 语法 PASS / [5/6] 无 MOCK 残留 PASS / [6/6] 无长小数输出 PASS
5. **场景推演**:
   - 待报单 status=50 m_nOrderVolume 空: 改后 1a 能匹配。vol 空/0 时跳过 vol 检查, 走 code+direction 含卖+time+remark, 不会误匹配他票
   - 605208 新委托 10:00:01 下 0.8s 未入列: 改后 1b 轮询 3s(15×0.2s) 足够等新单入列+字段填全
   - 心跳: 0930 首次打印(因 `_g_last_heartbeat_min < 0`), 之后 0935/0940... 每 5 分钟一次

### CC 独立验收(不信 MIMO 汇报, grep 源文件作证)
- **源 qmt_wrapper.py**: 4 处改动全命中(493/278/282/533-534/241/2362-2373/3865-3885)
- **build 产物 strategy_main.py**: 含新逻辑(4267/4052/4307/6136/7657)
- **validate**: 6/6 ALL PASS
- **commit**: 42cd130 落地(2 files, 50+/13-)

### 备注(执行瑕疵)
- **MIMO 漏 commit**: 做到 validate 就停没 commit。CC 用 `git status` 发现(qmt_wrapper.py + strategy_main.py 仍 M), CC 补 commit 42cd130
- 此漏 commit 教训已沉淀到 `CC_MIMO_PROTOCOL`(§二.三回执自检加 commit 项 / §五.3 CC 验收独立查 git log 不信回执 / §八.6 已知限制), commit 0740af1
- 待诚哥部署 42cd130 到 QMT 模拟端验证 3 点(反查登记 pending / 市价重试触发 / 心跳每 5 分钟)
