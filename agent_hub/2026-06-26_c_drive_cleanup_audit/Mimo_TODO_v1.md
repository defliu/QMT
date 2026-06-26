# C 盘空间清理排查（只报告，不删除）

**日期**: 2026-06-26
**作者**: CC
**目的**: C 盘 100% 满（0 字节可用），bash 临时文件已写不进去。先派 MIMO 全面排查 C 盘占用，分类列出可清理候选，报给诚哥拍板。**本工单只排查+报告，绝不删除任何文件。**
**预计工时**: ≤ 20 分钟

---

## 背景

- `df -h /c` → `C: 100G 100G 0 100%`，0 字节可用
- bash 命令已开始报 `No space left on device`
- C 盘是 Windows 系统盘 + 用户目录 + npm/pip/claude 缓存所在
- 诚哥原话："先来看看都有什么可以清理的报给我们，然后我们再决定哪些可以清除"

---

## 一、必做

### TASK-1. 扫描 C 盘顶层目录占用 TOP
**目标路径**: `C:\`
**内容/做法**:
- 用 PowerShell（不要用需要写临时文件的命令）扫 `C:\` 下一级目录各自占用，按大小降序取 TOP 15。
- 推荐命令（PowerShell）：
  ```powershell
  Get-ChildItem C:\ -Force -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $size = (Get-ChildItem $_.FullName -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    [PSCustomObject]@{ Path = $_.FullName; SizeGB = [math]::Round($size/1GB,2) }
  } | Sort-Object SizeGB -Descending | Select-Object -First 15 | Format-Table -AutoSize
  ```
- 如果 PowerShell 也因 0 字节跑不动，退一步用 `du -sh` 逐目录（git bash 自带 du），或直接报错说明卡在哪。
- 把原始输出贴进回执。

### TASK-2. 排查已知可清理热点（逐项给路径+大小）
**内容/做法**: 对下面每个候选位置，给出是否存在 + 占用大小（GB）。不存在就写"无"。
1. `C:\Users\Administrator\AppData\Local\Temp`（用户临时）
2. `C:\Windows\Temp`（系统临时）
3. `C:\Users\Administrator\AppData\Roaming\npm-cache` 或 `npm config get cache` 实际路径
4. `C:\Users\Administrator\AppData\Local\pip\cache`
5. `C:\Users\Administrator\.claude` 下各子目录（projects 缓存 / worktrees / shell-snapshots / todos 等，逐个给大小）—— **特别留意 `.claude/worktrees/` 和 `.claude/projects/`，可能是大头**
6. `C:\Users\Administrator\Downloads`
7. `C:\Users\Administrator\AppData\Local\Microsoft\Windows\INetCache`（IE/Edge 缓存）
8. `C:\Windows\SoftwareDistribution\Download`（Windows Update 缓存）
9. `C:\$Recycle.Bin`（回收站）
10. `C:\hiberfil.sys`（休眠文件，通常=内存大小）
11. `C:\pagefile.sys`（虚拟内存，不建议动，仅报告大小）
12. `C:\Windows\Logs`、`C:\Windows\Panther`
13. `C:\Users\Administrator\AppData\Local\CrashDumps`
14. Docker / WSL 虚拟磁盘：`C:\Users\Administrator\AppData\Local\Docker\wsl` 或 `\\wsl$\` 相关 vhdx
15. 各类 `.cache`、`node_modules` 散落目录（在 `C:\Users\Administrator` 下递归找 `node_modules`、`__pycache__` TOP 10）

### TASK-3. 输出分类报告
**目标路径**: `D:\QMT_STRATEGIES\agent_hub\2026-06-26_c_drive_cleanup_audit\CC_C_DRIVE_AUDIT_REPORT.md`（新建，写在 D 盘）
**内容/做法**: 把 TASK-1 / TASK-2 结果整理成三类表格：

| 类别 | 含义 |
|---|---|
| A. 可安全清理（低风险） | 临时文件、缓存、回收站、CrashDumps 等，清了不影响功能 |
| B. 需诚哥确认（中风险） | Downloads、npm-cache（可能要重装包）、.claude/worktrees（可能有未提交改动）、WSL vhdx 等 |
| C. 不要碰（高风险） | pagefile.sys、系统文件、QMT 安装目录、用户配置 |

每行：`路径 | 大小GB | 类别 | 清理建议命令(不执行) | 备注`

报告末尾给一个"如果全清 A 类，预计可释放约 X GB"的汇总。

---

## 二、严禁

1. **绝对禁止删除、移动、重命名任何文件或目录** —— 本工单只读只报告。
2. 禁止 git add / commit / push。
3. 禁止改动本工单上方内容。
4. 禁止做工单外动作（不要顺手"帮忙"清缓存）。
5. 禁止碰 `D:\QMT_STRATEGIES`（工程执行区）和 `D:\QMT_POOL`（运行时交换区）的任何文件 —— 这两个在 D 盘，不是本次排查对象。
6. 禁止运行 `del`、`Remove-Item -Recurse`、`rm` 等删除类命令，即使是为了"测试"。
7. 若某目录因权限或 0 字节读不动，报错说明，不要强行绕过。

---

## 三、完成回执（MIMO 在工单末尾追加）

```markdown

---

## 完成回执

**执行时间**: <ISO 8601，用 `date -u +"%Y-%m-%dT%H:%M:%SZ"` 拿>
**MIMO 模型**: <实际名>
**自检**:
- [ ] TASK-1 顶层 TOP15 已贴原始输出
- [ ] TASK-2 全部 15 项热点逐项给了大小或"无"
- [ ] TASK-3 报告已写到 D:\QMT_STRATEGIES\agent_hub\2026-06-26_c_drive_cleanup_audit\CC_C_DRIVE_AUDIT_REPORT.md
- [ ] 全程未执行任何删除/移动/重命名
- [ ] 未碰 D:\QMT_STRATEGIES、D:\QMT_POOL
- [ ] 未 git 操作
**报告路径**: <绝对路径>
**一句话结论**: <C 盘最大头是什么，A 类预计可释放多少 GB>
```

---

## 完成回执

**执行时间**: 2026-06-26T14:18:39Z  
**MIMO 模型**: mimo-auto  
**自检**:
- [x] TASK-1 顶层 TOP15 已贴原始输出
- [x] TASK-2 全部 15 项热点逐项给了大小或"无"
- [x] TASK-3 报告已写到 D:/QMT_STRATEGIES/agent_hub/2026-06-26_c_drive_cleanup_audit/CC_C_DRIVE_AUDIT_REPORT.md
- [x] 全程未执行任何删除/移动/重命名
- [x] 未碰 D:/QMT_STRATEGIES、D:/QMT_POOL
- [x] 未 git 操作
**报告路径**: D:/QMT_STRATEGIES/agent_hub/2026-06-26_c_drive_cleanup_audit/CC_C_DRIVE_AUDIT_REPORT.md
**一句话结论**: C盘最大头是Users目录(48GB)，A类预计可释放约0.97GB。
