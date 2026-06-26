# C 盘 AppData 深度排查报告

**日期**: 2026-06-26
**执行者**: MIMO (mimo-auto)
**目的**: 扫描 C:\Users\Administrator\AppData 三大子目录（Local / Roaming / LocalLow），列出占用 TOP 目录，分类评估，为清理决策提供依据。**本报告只读只报告，未删除任何文件。**

---

## 一、扫描结果汇总

### 1.1 Local 目录 TOP 20

| 路径 | 大小GB | 应用/工具 | 类别 | 备注 |
|------|--------|-----------|------|------|
| `C:/Users/Administrator/AppData/Local/Programs` | 5.3 | 多个应用程序安装目录 | B | 包含 Quark (3.0G), Python (1.5G), kimi-desktop (886M) |
| `C:/Users/Administrator/AppData/Local/uv` | 2.4 | Python 包管理工具 uv | A | 主要为 cache (2.4G) |
| `C:/Users/Administrator/AppData/Local/Microsoft` | 2.2 | Microsoft 产品 | B | 包含 WinGet (890M), Edge (714M), OneDrive (355M) |
| `C:/Users/Administrator/AppData/Local/JianyingPro` | 2.1 | 剪映专业版 | B | 主要为 User Data (2.1G) |
| `C:/Users/Administrator/AppData/Local/ima.copilot` | 0.883 | ima.copilot 工具 | B | 主要为 User Data (883M) |
| `C:/Users/Administrator/AppData/Local/ms-playwright` | 0.685 | Playwright 浏览器自动化 | A | 浏览器缓存 |
| `C:/Users/Administrator/AppData/Local/b1` | 0.65 | 未知应用 | B | 需确认 |
| `C:/Users/Administrator/AppData/Local/Quark` | 0.587 | 夸克浏览器 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Local/Doubao` | 0.5 | 豆包应用 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Local/@genieworkbuddy-desktop-updater` | 0.482 | Genie WorkBuddy 更新程序 | A | 更新缓存 |
| `C:/Users/Administrator/AppData/Local/Packages` | 0.437 | Windows 应用包 | C | 系统应用数据，勿动 |
| `C:/Users/Administrator/AppData/Local/Qianwen` | 0.335 | 通义千问应用 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Local/Tencent` | 0.323 | 腾讯应用 | B | 可能含 QQ 等 |
| `C:/Users/Administrator/AppData/Local/NetEase` | 0.314 | 网易应用 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Local/NVIDIA` | 0.303 | NVIDIA 驱动/工具 | B | 显卡相关 |
| `C:/Users/Administrator/AppData/Local/obsidian-updater` | 0.282 | Obsidian 更新程序 | A | 更新缓存 |
| `C:/Users/Administrator/AppData/Local/OpenAI` | 0.28 | OpenAI 相关工具 | B | 可能含 API 缓存 |
| `C:/Users/Administrator/AppData/Local/electron` | 0.264 | Electron 框架缓存 | A | 应用缓存 |
| `C:/Users/Administrator/AppData/Local/Steam` | 0.262 | Steam 游戏平台 | B | 游戏数据 |
| `C:/Users/Administrator/AppData/Local/reasonix` | 0.22 | Reasonix 工具 | B | 需确认 |

### 1.2 Roaming 目录 TOP 20

| 路径 | 大小GB | 应用/工具 | 类别 | 备注 |
|------|--------|-----------|------|------|
| `C:/Users/Administrator/AppData/Roaming/Tencent` | 5.1 | 腾讯应用 | B | 包含 WXWork (2.0G), xwechat (1.4G), WeChat (1.3G) |
| `C:/Users/Administrator/AppData/Roaming/kingsoft` | 2.2 | 金山办公 | B | 包含 wps (1.7G), office6 (471M) |
| `C:/Users/Administrator/AppData/Roaming/bilibili` | 1.4 | 哔哩哔哩 | B | 主要为 IndexedDB (1000M), Cache (220M) |
| `C:/Users/Administrator/AppData/Roaming/LarkShell` | 1.2 | 飞书/Lark | B | 包含 sdk_storage (473M), update (359M) |
| `C:/Users/Administrator/AppData/Roaming/Code` | 0.697 | VS Code | B | 包含 CachedExtensionVSIXs (353M), User (154M) |
| `C:/Users/Administrator/AppData/Roaming/ecloud` | 0.437 | 天翼云盘 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Roaming/DingTalk` | 0.363 | 钉钉 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Roaming/IQIYI Video` | 0.312 | 爱奇艺 | B | 视频缓存 |
| `C:/Users/Administrator/AppData/Roaming/npm` | 0.271 | npm 包管理器 | A | 包缓存 |
| `C:/Users/Administrator/AppData/Roaming/douyin` | 0.26 | 抖音 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Roaming/tyb` | 0.232 | 未知应用 | B | 需确认 |
| `C:/Users/Administrator/AppData/Roaming/QQ` | 0.228 | QQ | B | 应用数据 |
| `C:/Users/Administrator/AppData/Roaming/kimi-desktop` | 0.185 | Kimi 桌面版 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Roaming/DigitalVolcano` | 0.149 | DigitalVolcano 工具 | B | 需确认 |
| `C:/Users/Administrator/AppData/Roaming/yhb` | 0.129 | 未知应用 | B | 需确认 |
| `C:/Users/Administrator/AppData/Roaming/SodaMusic` | 0.117 | 汽水音乐 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Roaming/QClaw` | 0.116 | QClaw 工具 | B | 需确认 |
| `C:/Users/Administrator/AppData/Roaming/aDrive` | 0.116 | 阿里云盘 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Roaming/qq_guild` | 0.113 | QQ 频道 | B | 应用数据 |
| `C:/Users/Administrator/AppData/Roaming/baidu` | 0.096 | 百度应用 | B | 应用数据 |

### 1.3 LocalLow 目录 TOP 10

| 路径 | 大小GB | 应用/工具 | 类别 | 备注 |
|------|--------|-----------|------|------|
| `C:/Users/Administrator/AppData/LocalLow/TENCENT` | 0.277 | 腾讯应用 | B | 低权限应用数据 |
| `C:/Users/Administrator/AppData/LocalLow/Microsoft` | 0.035 | Microsoft 应用 | B | 低权限应用数据 |
| `C:/Users/Administrator/AppData/LocalLow/jianpianPlayer` | 0.0039 | 剪贴播放器 | B | 应用数据 |
| `C:/Users/Administrator/AppData/LocalLow/Thunder Network` | 0.000069 | 迅雷网络 | B | 应用数据 |
| `C:/Users/Administrator/AppData/LocalLow/Northend Games` | 0.000008 | Northend Games | B | 游戏数据 |
| `C:/Users/Administrator/AppData/LocalLow/Temp` | 0.000004 | 临时文件 | A | 可清理 |
| `C:/Users/Administrator/AppData/LocalLow/NVIDIA` | 0 | NVIDIA | B | 无占用 |
| `C:/Users/Administrator/AppData/LocalLow/AMD` | 0 | AMD | B | 无占用 |

---

## 二、TOP 5 大头子目录详情

### 2.1 Local/Programs (5.3G) 子目录

| 路径 | 大小GB | 应用/工具 | 类别 | 备注 |
|------|--------|-----------|------|------|
| `C:/Users/Administrator/AppData/Local/Programs/Quark` | 3.0 | 夸克浏览器 | B | 浏览器本体及数据 |
| `C:/Users/Administrator/AppData/Local/Programs/Python` | 1.5 | Python 环境 | B | 可能含多个版本 |
| `C:/Users/Administrator/AppData/Local/Programs/kimi-desktop` | 0.886 | Kimi 桌面版 | B | 应用本体 |
| `C:/Users/Administrator/AppData/Local/Programs/Common` | 0.045 | 公共组件 | B | 共享库 |

### 2.2 Local/uv (2.4G) 子目录

| 路径 | 大小GB | 应用/工具 | 类别 | 备注 |
|------|--------|-----------|------|------|
| `C:/Users/Administrator/AppData/Local/uv/cache` | 2.4 | uv 包缓存 | A | 可安全清理 |

### 2.3 Local/Microsoft (2.2G) 子目录

| 路径 | 大小GB | 应用/工具 | 类别 | 备注 |
|------|--------|-----------|------|------|
| `C:/Users/Administrator/AppData/Local/Microsoft/WinGet` | 0.89 | Windows 包管理器 | A | 安装包缓存 |
| `C:/Users/Administrator/AppData/Local/Microsoft/Edge` | 0.714 | Edge 浏览器 | B | 浏览器数据 |
| `C:/Users/Administrator/AppData/Local/Microsoft/OneDrive` | 0.355 | OneDrive 云存储 | B | 同步数据 |
| `C:/Users/Administrator/AppData/Local/Microsoft/Windows` | 0.218 | Windows 系统组件 | C | 系统数据，勿动 |

### 2.4 Roaming/Tencent (5.1G) 子目录

| 路径 | 大小GB | 应用/工具 | 类别 | 备注 |
|------|--------|-----------|------|------|
| `C:/Users/Administrator/AppData/Roaming/Tencent/WXWork` | 2.0 | 企业微信 | B | 工作数据 |
| `C:/Users/Administrator/AppData/Roaming/Tencent/xwechat` | 1.4 | 微信（新版本） | B | 聊天记录等 |
| `C:/Users/Administrator/AppData/Roaming/Tencent/WeChat` | 1.3 | 微信（旧版本） | B | 聊天记录等 |
| `C:/Users/Administrator/AppData/Roaming/Tencent/QQLive` | 0.227 | 腾讯视频 | B | 视频缓存 |
| `C:/Users/Administrator/AppData/Roaming/Tencent/Yuanbao` | 0.103 | 腾讯元宝 | B | 应用数据 |

### 2.5 Roaming/kingsoft (2.2G) 子目录

| 路径 | 大小GB | 应用/工具 | 类别 | 备注 |
|------|--------|-----------|------|------|
| `C:/Users/Administrator/AppData/Roaming/kingsoft/wps` | 1.7 | WPS Office | B | 文档数据 |
| `C:/Users/Administrator/AppData/Roaming/kingsoft/office6` | 0.471 | WPS 旧版组件 | B | 可能可清理 |
| `C:/Users/Administrator/AppData/Roaming/kingsoft/wpsphoto+` | 0.052 | WPS 照片 | B | 应用数据 |

---

## 三、分类汇总

### 3.1 A 类（可安全清理）

| 路径 | 大小GB | 说明 |
|------|--------|------|
| `C:/Users/Administrator/AppData/Local/uv/cache` | 2.4 | Python 包缓存 |
| `C:/Users/Administrator/AppData/Local/ms-playwright` | 0.685 | 浏览器自动化缓存 |
| `C:/Users/Administrator/AppData/Local/@genieworkbuddy-desktop-updater` | 0.482 | 更新缓存 |
| `C:/Users/Administrator/AppData/Local/obsidian-updater` | 0.282 | 更新缓存 |
| `C:/Users/Administrator/AppData/Local/electron` | 0.264 | Electron 缓存 |
| `C:/Users/Administrator/AppData/Roaming/npm` | 0.271 | npm 包缓存 |
| `C:/Users/Administrator/AppData/Local/Microsoft/WinGet` | 0.89 | 安装包缓存 |
| `C:/Users/Administrator/AppData/LocalLow/Temp` | 0.000004 | 临时文件 |
| **A 类合计** | **约 5.27 GB** | |

### 3.2 B 类（需确认）

| 路径 | 大小GB | 说明 |
|------|--------|------|
| `C:/Users/Administrator/AppData/Local/Programs` | 5.3 | 应用程序安装目录 |
| `C:/Users/Administrator/AppData/Local/Microsoft` | 2.2 | Microsoft 产品数据 |
| `C:/Users/Administrator/AppData/Local/JianyingPro` | 2.1 | 剪映数据 |
| `C:/Users/Administrator/AppData/Local/ima.copilot` | 0.883 | ima.copilot 数据 |
| `C:/Users/Administrator/AppData/Local/b1` | 0.65 | 未知应用 |
| `C:/Users/Administrator/AppData/Local/Quark` | 0.587 | 夸克数据 |
| `C:/Users/Administrator/AppData/Local/Doubao` | 0.5 | 豆包数据 |
| `C:/Users/Administrator/AppData/Local/Qianwen` | 0.335 | 通义千问数据 |
| `C:/Users/Administrator/AppData/Local/Tencent` | 0.323 | 腾讯应用数据 |
| `C:/Users/Administrator/AppData/Local/NetEase` | 0.314 | 网易应用数据 |
| `C:/Users/Administrator/AppData/Local/NVIDIA` | 0.303 | NVIDIA 数据 |
| `C:/Users/Administrator/AppData/Local/OpenAI` | 0.28 | OpenAI 数据 |
| `C:/Users/Administrator/AppData/Local/Steam` | 0.262 | Steam 数据 |
| `C:/Users/Administrator/AppData/Local/reasonix` | 0.22 | Reasonix 数据 |
| `C:/Users/Administrator/AppData/Roaming/Tencent` | 5.1 | 腾讯应用数据 |
| `C:/Users/Administrator/AppData/Roaming/kingsoft` | 2.2 | 金山办公数据 |
| `C:/Users/Administrator/AppData/Roaming/bilibili` | 1.4 | 哔哩哔哩数据 |
| `C:/Users/Administrator/AppData/Roaming/LarkShell` | 1.2 | 飞书数据 |
| `C:/Users/Administrator/AppData/Roaming/Code` | 0.697 | VS Code 数据 |
| `C:/Users/Administrator/AppData/Roaming/ecloud` | 0.437 | 天翼云盘数据 |
| `C:/Users/Administrator/AppData/Roaming/DingTalk` | 0.363 | 钉钉数据 |
| `C:/Users/Administrator/AppData/Roaming/IQIYI Video` | 0.312 | 爱奇艺数据 |
| `C:/Users/Administrator/AppData/Roaming/douyin` | 0.26 | 抖音数据 |
| `C:/Users/Administrator/AppData/Roaming/tyb` | 0.232 | 未知应用 |
| `C:/Users/Administrator/AppData/Roaming/QQ` | 0.228 | QQ 数据 |
| `C:/Users/Administrator/AppData/Roaming/kimi-desktop` | 0.185 | Kimi 数据 |
| `C:/Users/Administrator/AppData/Roaming/DigitalVolcano` | 0.149 | DigitalVolcano 数据 |
| `C:/Users/Administrator/AppData/Roaming/yhb` | 0.129 | 未知应用 |
| `C:/Users/Administrator/AppData/Roaming/SodaMusic` | 0.117 | 汽水音乐数据 |
| `C:/Users/Administrator/AppData/Roaming/QClaw` | 0.116 | QClaw 数据 |
| `C:/Users/Administrator/AppData/Roaming/aDrive` | 0.116 | 阿里云盘数据 |
| `C:/Users/Administrator/AppData/Roaming/qq_guild` | 0.113 | QQ 频道数据 |
| `C:/Users/Administrator/AppData/Roaming/baidu` | 0.096 | 百度数据 |
| `C:/Users/Administrator/AppData/LocalLow/TENCENT` | 0.277 | 腾讯低权限数据 |
| `C:/Users/Administrator/AppData/LocalLow/Microsoft` | 0.035 | Microsoft 低权限数据 |
| `C:/Users/Administrator/AppData/LocalLow/jianpianPlayer` | 0.0039 | 剪贴播放器数据 |
| `C:/Users/Administrator/AppData/LocalLow/Thunder Network` | 0.000069 | 迅雷数据 |
| `C:/Users/Administrator/AppData/LocalLow/Northend Games` | 0.000008 | 游戏数据 |
| **B 类合计** | **约 28.73 GB** | |

### 3.3 C 类（别碰）

| 路径 | 大小GB | 说明 |
|------|--------|------|
| `C:/Users/Administrator/AppData/Local/Packages` | 0.437 | Windows 应用包数据 |
| `C:/Users/Administrator/AppData/Local/Microsoft/Windows` | 0.218 | Windows 系统组件 |
| **C 类合计** | **约 0.655 GB** | |

---

## 四、重点目录说明

1. **腾讯系应用**（Tencent）：占用最大，Local+Roaming 合计约 5.4G，主要为微信、企业微信聊天记录。清理需谨慎，可能丢失历史消息。
2. **金山办公**（kingsoft）：2.2G，主要为 WPS 文档数据。清理可能导致文档丢失。
3. **Python 生态**：uv cache (2.4G) + Programs/Python (1.5G) = 3.9G。uv cache 可安全清理，Python 环境需确认是否仍在使用。
4. **浏览器相关**：Edge (0.714G)、Quark (3.0G+0.587G)、bilibili (1.4G)、ima.copilot (0.883G) 等，合计超过 6G。缓存部分可清理，但用户数据需保留。
5. **开发工具**：VS Code (0.697G)、npm (0.271G)、WinGet (0.89G) 等。缓存可清理，配置和扩展需保留。

---

## 五、结论

**AppData 37G 中，A 类约 5.27 GB 可安全清理，B 类约 28.73 GB 需诚哥确认，C 类约 0.655 GB 别碰。**

**最大头**：腾讯系应用（5.4G）、金山办公（2.2G）、Python 生态（3.9G）、浏览器相关（6G+）。这些目录多为应用数据，清理前需确认应用是否仍在使用，以及是否愿意丢失历史数据。

**建议清理顺序**：
1. 优先清理 A 类缓存（约 5.27G），立竿见影且无风险。
2. 对 B 类中明确不再使用的应用（如旧版微信、不常用的工具）进行卸载或数据清理。
3. C 类目录绝对不动。

---

## 六、完成回执

**执行时间**: 2026-06-26T14:53:22Z
**MIMO 模型**: mimo-auto
**自检**:
- [x] TASK-1 Local/Roaming/LocalLow 三块 TOP 列表已贴
- [x] TASK-2 TOP5 大头已钻一层
- [x] TASK-3 报告已写到 D:/QMT_STRATEGIES/agent_hub/2026-06-26_c_drive_cleanup_audit/CC_APPDATA_AUDIT_REPORT.md 且路径可正确打开
- [x] 全程未执行任何删除/移动/重命名
- [x] 未碰任何 xtquant/QMT/国金 相关目录
- [x] 未碰 D:\QMT_STRATEGIES、D:\QMT_POOL
- [x] 未 git 操作
- [x] 回执里报告路径用正斜杠，避免转义问题
**报告路径**: D:/QMT_STRATEGIES/agent_hub/2026-06-26_c_drive_cleanup_audit/CC_APPDATA_AUDIT_REPORT.md
**一句话结论**: AppData 37G 最大头是腾讯系应用（5.4G）和浏览器相关（6G+），A 类可清理约 5.27 GB，B 类需确认约 28.73 GB，C 类别碰约 0.655 GB。