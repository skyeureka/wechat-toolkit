# autostart

让「微信记录查看器」可用的启动方式。**默认没有开机自启** —— 按需求，只在点击快捷方式时才启动服务，避免影响系统启动时间。

## 日常用法（推荐）

桌面快捷方式 **`微信记录查看器`**（`T:\DeskTop\微信记录查看器.lnk`）：

双击 → 先确保服务在跑（没跑就拉起来）→ 再打开 `http://127.0.0.1:8714/`。

冷启动实测 **3.4 秒**（服务未运行时点开），无需任何后台常驻。

快捷方式由 `create-desktop-shortcut.ps1` 生成（换机器要重跑一次：`.lnk` 存的是绝对路径）。

## 文件

| 文件 | 作用 |
|---|---|
| `open-webui-hidden.vbs` | 快捷方式的目标：先调 `ensure-webui.ps1`，再开浏览器 |
| `ensure-webui.ps1` | 幂等启动：端口已在监听就退出 0，否则拉起服务并等端口就绪 |
| `run-webui-hidden.vbs` | 隐藏启动器（供计划任务用，见下） |
| `create-desktop-shortcut.ps1` | 生成桌面快捷方式 |
| `register-webui-task.ps1` | **可选**：注册开机/登录自启任务（当前未注册） |

## 可选：开机自启（当前未启用）

如果哪天希望登录后自动可用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File T:\wx4win\wechat-toolkit\autostart\register-webui-task.ps1
```

撤销：

```powershell
Unregister-ScheduledTask -TaskName "ChatTrace Web UI" -Confirm:$false
```

该任务用 `wscript.exe` + `run-webui-hidden.vbs`（`-WindowStyle Hidden` 的 powershell 动作仍会闪窗），
登录触发延迟 1m30s 避开开机 I/O 高峰，另加 30 分钟重复触发，`RestartCount=3`。

## 两个编码坑（都踩过）

- **含中文的 `.ps1` 必须存成 UTF-8 带 BOM。** PowerShell 5.1 对无 BOM 文件按 ANSI/GBK 解码，
  中文串会被解坏 —— 实测快捷方式名被解坏后 `CreateShortcut` 报「路径名称需以 .lnk 或 .url 结尾」。
- **`.vbs` 保持纯 ASCII**（不要 UTF-16 BOM），所以路径字面量都放在 `.ps1` 里。

另外：`.vbs` 里写日志前要确保父目录存在且包在 `On Error Resume Next` 里。
往不存在的目录写文件会抛运行时错误，未捕获时 WSH 会弹**模态对话框**卡在屏幕上等人点 —— 后台启动器绝不能这样。
