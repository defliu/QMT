# CC ↔ MIMO 自动协作协议 v1

**日期**: 2026-06-18
**作者**: CC（基于 v1-v5 握手测试沉淀）
**状态**: 已验证可用（彩色 + 中文 + 实时观察 三通道齐全）

---

## 一、机制总览

```
       ┌──────────────────────────────────────────────────┐
       │  CC (本窗口)                                     │
       │  Bash run_in_background=true:                    │
       │     mimo run "<msg>" 2>&1 | tee -a <live.log>    │
       │            │                       │             │
       │            ▼                       ▼             │
       │   后台执行（task-notification     写入观察日志    │
       │   通知 CC 完成）                                  │
       └────────────┬───────────────────────┬─────────────┘
                    │                       │
                    ▼                       ▼
           MIMO 执行工单            诚哥 split terminal
           （读写文件、git 等）     Get-Content -Wait 实时观察
```

**三方角色**：
- **CC**：写工单 → 调 mimo → task-notification 回来后验收 → 报告诚哥
- **MIMO**：读工单 → 执行 → 写回执 → 输出全程 tee 到 live log
- **诚哥**：split terminal 看 live log，不下指令，仅观察

---

## 二、工单格式

工单路径：`agent_hub/<YYYY-MM-DD>_<主题>/Mimo_TODO_v<N>.md` 或 `Mimo_TEST_v<N>.md`

**最小必备段**：

```markdown
# <标题>

**日期**: YYYY-MM-DD
**作者**: CC
**目的**: <一句话说清楚为什么做>
**预计工时**: ≤ N 分钟

---

## 一、必做（M 项）

### TASK-1. <动作名>
**目标路径**: <绝对路径>
**内容/做法**: <具体到可执行>

### TASK-2. ...

---

## 二、严禁

1. 禁止 git add / commit / push（除非工单显式授权）
2. 禁止改动本工单上方
3. 禁止做工单外动作
4. 禁止读握手目录之外的项目文件（除非工单显式列出）
5. <其他场景特定红线>

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <ISO 8601 真实时刻，用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 拿>
**MIMO 模型**: <实际名，如 mimo-auto>
**自检**:
- [ ] 项 1
- [ ] 项 2
- [ ] 仅末尾追加，未改动上方
- [ ] 无工单外文件改动 / git 操作
- [ ] 若工单授权 commit：已 `git commit` 且 `git status --short` 无残留（commit hash：<填>）
```
```

**关键约束**：
- 时间戳必须用 `date` 命令真实拿，**禁止 placeholder**（v4 偷懒过 `2026-06-18T00:00:00Z`，v5 已纠正）
- 自检条目用 `[x]` 勾选，每条对应 §一 的一项必做
- 严禁段落要场景化，不要复制粘贴

---

## 三、CC 调用 MIMO 的标准命令

```bash
mimo run "请用 Read 工具读取 D:/QMT_STRATEGIES/agent_hub/<path>/Mimo_TODO_v<N>.md 并完整执行其中所有步骤" 2>&1 | tee -a /d/QMT_STRATEGIES/agent_hub/.mimo_live.log
```

调用参数：
- `run_in_background=true`
- timeout 默认即可（mimo 自己会跑到完）

**坑位**：
1. `mimo run -f <file>` **不能用** —— `-f` 是 array 类型，会把后面的 message 也吞成文件路径。把工单路径**嵌进 message** 里，让 MIMO 自己用 Read 工具打开。
2. 不要用 `NO_COLOR=1`，不要用 `sed 's/\x1b\[[0-9;]*m//g'` —— 那会剥光颜色。直接 `2>&1 | tee -a`。
3. 不要 `cd` 到子目录调用 —— 用绝对路径，避免工作目录漂移。
4. **mimo 0.1.0 不存在的 flag（2026-06-26 踩坑）**：`--sandbox workspace-write`、`--cwd` 都没有；`--model mimo-auto` 格式错（要 `provider/model`）。带了这些 mimo 直接打印 help 退出，**任务不跑、`.mimo_live.log` 不被覆盖**（旧内容残留是诊断信号）。正确派单就是最简 `mimo run "<msg>"`，默认 agent `build` 已全权限 allow，模型默认 mimo-auto。
5. **Claude Code auto mode classifier 临时挡 `mimo run`**：报 "auto mode cannot determine safety of Bash / glm-latest temporarily unavailable"。allowlist 无效（permission 已全 allow，挡点在 safety classifier 层）。解法：关 auto mode，或等 classifier 恢复重试。诊断：`mimo run` 报 classifier 错 ≠ mimo 本身问题，是 Claude Code 那层。

---

## 四、诚哥端：实时观察通道

VS Code split terminal（PowerShell）跑：

```powershell
Get-Content -Path D:\QMT_STRATEGIES\agent_hub\.mimo_live.log -Wait -Tail 50 -Encoding UTF8
```

**注意**：
- `-Encoding UTF8` 必须有，否则中文乱码（PowerShell 默认 GBK 读 UTF-8 文件）
- VS Code 内置 xterm.js 渲染 ANSI 颜色 OK；外部 PowerShell 5.1 窗口不渲染
- MIMO 跑小任务（读+写+追加）色码很少，正文几乎全白是正常的；跑 plan/edit 长流程时颜色才丰富

---

## 五、CC 验收 SOP

收到 `<task-notification>status=completed</task-notification>` 后，**强制三步**：

1. **读握手/产物文件**：用 Read 工具确认内容（行数、关键字段、时间戳真伪）
2. **读工单回执段**：确认 MIMO 在工单末尾追加了回执，自检全 [x]
3. **检查 git 干净度**：`git status --short` 看有无残留改动
   - 工单**未授权** git：应无 git 改动（MIMO 擅自 commit/push 要揪出）
   - 工单**授权** commit：`git log --oneline -1` 确认新 commit 落地 + hash 对得上 + working tree clean。**必须独立查 `git log`，不能信回执**（0715 反查工单 MIMO 做到 validate 6/6 PASS 就停，没 commit，回执也没勾 commit 项，CC 靠 `git status` 才发现）

**验收通过** → 报告诚哥成果摘要 + 下一步建议
**验收失败** → 诚实告诉诚哥哪一项没过，提议修正工单或重跑

---

## 六、并发与日志卫生

- **目前默认串行**：一个 mimo 任务跑完再发下一个。并发未测过，先不上。
- **live log 位置**：`D:/QMT_STRATEGIES/agent_hub/.mimo_live.log`（agent_hub 根，不要塞进子目录，方便诚哥 tail）
- **轮转策略**：单次任务前如果 log 太大（>5MB），CC 写一行清屏标记 `[live log cleared @ <ISO时刻>, waiting for v<N>]` 或截断；不要 `> /dev/null` 清光，保留前一次内容方便回看。
- **不要把 .mimo_live.log 提交进 git**（已是 hidden 文件，git 默认会跟踪；必要时加 .gitignore）

---

## 七、握手测试简史

| 版本 | 验证目标 | 结果 |
|------|---------|------|
| v1 | mimo CLI 能跑、能写文件 | ✓ |
| v2 | 切到 mimo-auto 模型 | ✓ |
| v3 | tee 到 live log + split terminal tail | ✓ |
| v4 | 修中文乱码（`-Encoding UTF8`）+ 暂时去色（`NO_COLOR + sed`） | ✓ 但全白 |
| v5 | 去掉 NO_COLOR/sed，确认 ANSI 渲染 | ✓ 颜色 + 中文同时 OK |

工单与回执留档：`agent_hub/2026-06-18_cc_mimo_handshake/`

---

## 八、已知限制

1. **MIMO 偶尔偷懒写 placeholder 时间戳** —— 工单里要明确"用 `date -u` 真实拿"
2. **MIMO 偶尔声称切换模型实际未切** —— 历史教训，回执里要带 `MIMO 模型` 字段供 CC 抽查
3. **MIMO 偶尔声称完成实际未完成** —— V1.1 阶段出过两次，CC 必须独立用 Read/git status 验
4. **没有重试机制** —— mimo run 失败需 CC 手动判断重发还是改工单
5. **远程仓库已配置**(0715) —— origin=git@github.com:defliu/QMT.git(私有,main分支), SSH密钥 ~/.ssh/id_ed25519(公钥已加GitHub)。git push 类工单可执行。首次push 0715含commit 42cd130(反查修复)+0740af1(协议)。注:历史含模拟账号67014907(私有仓库可接受);如改公开需先清理
6. **MIMO 偶尔漏 commit 步骤** -- 0715 反查工单做到 validate 6/6 PASS 就停，没 commit（工单 commit 写在严禁段仍漏）。根因：回执自检原写"无其它 git 操作"，MIMO 倾向解读为"别 commit"。对策：回执自检已加"若工单授权 commit"显式项（§二.三），CC 验收独立查 git log 不信回执（§五.3）

## 九、2026-06-26 派单失败诊断记录

派 T-20260625-006（持仓同步修复）时连续 4 次失败，根因分两层：

**层1：Claude Code auto mode classifier**
- 报错：`auto mode cannot determine the safety of Bash right now` / `glm-latest temporarily unavailable`
- 性质：Claude Code 给每个 Bash 命令送 glm-latest 判危险，分类器临时挂 → 所有非只读命令被拦
- 误判：以为是 MIMO 本身问题，实际 MIMO 没问题
- 解法：关 auto mode（命令不过 classifier）；allowlist 无效（permission 已全 allow，挡点在 classifier 层不在 permission 层）

**层2：mimo CLI 参数错误（关了 auto mode 后暴露）**
- 用了 `--model mimo-auto` → 格式错，要 `provider/model`；且 mimo-auto 是默认别名不用指定
- 用了 `--sandbox workspace-write`、`--cwd` → mimo 0.1.0 无此 flag
- 结果：mimo 打印 help 退出，任务不跑，`.mimo_live.log` 不被覆盖（旧 505 任务日志残留是诊断信号）
- 解法：最简 `mimo run "<msg>"`，默认 agent `build` 全权限

**诊断 SOP（下次派单失败按此排）**：
1. 看 `.mimo_live.log` 有没有被覆盖 → 没覆盖 = mimo 没启动
2. `.mimo_live.log` 内容是 mimo help 文本 → 参数 flag 错
3. 报 classifier 错 → Claude Code auto mode 挡，关 auto mode 或等恢复
4. mimo 跑了但任务没执行 → 看工单路径/内容是否正确

**接单测试通过**（2026-06-26）：`mimo run "MIMO 接单测试..."` → MIMO 回执 `> build · mimo-auto` + 执行 git log + 回报 HEAD。确认 mimo 0.1.0 链路正常。
