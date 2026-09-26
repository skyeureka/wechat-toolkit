# WeChat 聊天记录工具（Windows）

本地离线的微信 4.x 聊天记录读取 / 导出工具。**数据不出本机**：不联网、不上传、无遥测。

> 这个项目是把 macOS 版 `wechat-toolkit` 的思路搬到 Windows 的产物。
> 原仓库 `skyeureka/wechat-toolkit` 是空的（0 提交），Mac 源码没有上传，
> 因此这里基于本机实测重新打通了 Windows 的整条链路，并复用 MIT 许可的
> [ChatTrace](https://github.com/qiaodogbear/ChatTrace) 作为解密引擎。

## 已验证环境

| 项目 | 值 |
|---|---|
| 微信 | **4.1.15.12**（Windows） |
| 密钥锚点 | `entry=0x3567630` `mmv1_ref=0x3567669` `magic_check=0x74D4BA2` |
| 数据目录 | `<盘>:\xwechat_files\<wxid_xxx>\db_storage` |
| 加密 | SQLCipher 4（PBKDF2-HMAC-SHA512 / 256000 迭代 / reserve 80） |
| 实测结果 | 密钥抓取 ✅、20/20 数据库解密 ✅、导出 txt/json ✅ |

## 快速开始

```
setup.bat     # 首次运行：建 venv + 装依赖（需要 Python 3.11+）
start.bat     # 一键：定位锚点 → 抓密钥 → 解密 → 打开网页界面
```

浏览器会自动打开 `http://127.0.0.1:8714/`。

### 常用参数

```
start.bat --check                  # 只做环境自检，不改动任何东西
start.bat --capture                # 强制重新抓一次密钥
start.bat --no-ui                  # 只解密，不开界面
start.bat --export-format html --user wxid_xxx   # 导出单个聊天（含图片/语音）
```

## 密钥是怎么抓到的

微信 4.1.11 之后，旧工具「在内存里扫 32 字节十六进制字面量」的做法失效了。
本工具改为**在密钥送进加密引擎之前截住它**：

1. 静态分析 `Weixin.dll`，定位 codec 配置函数与 `MMV1` 魔数锚点；
2. 用 Frida **spawn** 微信（不是 attach），在开库前完成 hook；
3. 从 `rcx` 指向的结构前 32 字节取出主密钥候选；
4. **拿候选密钥对真实数据库页做 HMAC 校验**，通过才接受 —— 这能滤掉登录过程中的过渡态密钥。

## Windows 上踩掉的两个坑

这两处是本项目相对上游引擎修补的地方，都已修复并验证：

**1. 版本目录多份时会挂错 hook。**
安装根目录下可能同时存在多个版本（本机有 `4.1.13.12` 和 `4.1.15.12`）。
上游的 `save_anchor_cache` 是**整体覆盖**写缓存 —— 给新版本注册锚点时会把旧版本抹掉；
抓取时又挑「第一个已注册的版本」，于是按错误的 DLL 偏移挂 hook，一次都不会命中。
已改为**合并写入** + 按 DLL 修改时间**从新到旧排序、失败自动换下一个版本重试**。

**2. 点击账号选择页会点到别的窗口上。**
`frida.spawn` 出来的微信停在「进入微信」账号选择页，需要点一下才进库。
但 `SetCursorPos` + `mouse_event` 用的是**屏幕坐标**，微信窗口不在最前面时，
点击会落到上层窗口（实测打到了 Chrome）——看起来「点击成功」，实际什么都没发生。
已改为：先用 `SetWindowPos(HWND_TOPMOST)` 把窗口提到最前（不需要前台权限，
比 `SetForegroundWindow` 可靠），再用 `WindowFromPoint` **验证落点确实属于目标进程**
才发送点击，点完恢复原层级。

> 附带：`click_enter.ps1` 的参数不能叫 `$Pid` —— 那是 PowerShell 只读自动变量，会直接报错。

## 目录结构

```
wechat-toolkit\
  setup.bat              首次安装
  start.bat              一键启动
  run.py                 流程编排（自检 / 抓密钥 / 解密 / 开界面）
  scripts\
    capture_win.py       抓密钥（含自动点击账号选择页、版本回退重试）
    click_enter.ps1      点击账号选择页的「进入微信」按钮
  engine\ChatTrace\      解密引擎（MIT，已打上述补丁）
```

## 数据在哪

| 内容 | 位置 |
|---|---|
| 密钥（DPAPI 加密，仅当前用户可解） | `%LOCALAPPDATA%\ChatTrace\keys\` |
| 解密后的数据库 | `%LOCALAPPDATA%\ChatTrace\accounts\<账号>\decrypted\` |
| 导出文件 | `%LOCALAPPDATA%\ChatTrace\accounts\<账号>\exports\` |

⚠️ `decrypted\` 和 `exports\` 里是**明文聊天记录**，别同步到网盘/仓库。

## 已知限制

- 微信**升级后锚点会漂移**，需重跑 `start.bat --check`（会自动重新定位）或 `--capture`。
- 抓密钥时要微信**完全退出**（含托盘）；工具会自动关，但正在用的会话会被中断。
- 微信登录态过期（长期没开）时，spawn 出来的实例可能要求扫码 —— 正常登录一次即可。
- 群聊里「我发的消息」发送者解析依赖分片内 `Name2Id`，跨分片同名 rowid 会错位（引擎已按分片处理）。

## 许可

`engine/ChatTrace` 为 MIT，版权归原作者；本目录下的补丁与脚本同样以 MIT 提供。
仅限导出**自己的**账号数据。
