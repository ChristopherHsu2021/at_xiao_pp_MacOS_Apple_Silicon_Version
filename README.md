# AT小PP · macOS 版（Apple Silicon · 原生 arm64）

基于 PyQt6 的桌面宠物应用：陪伴互动 + 音乐播放器 + 待办 / 闹钟 / 计时器 + 场景玩法。
本仓库是 **Apple Silicon（M 系列）原生 arm64 发行线**，产物为 `AT小PP-macos-arm64.dmg`，
挂载后把 `AT小PP.app` 拖进「应用程序」即可使用，卸载就是拖进废纸篓。

- 架构：`arm64`（M1 / M2 / M3 / M4 及后续 Apple Silicon **原生运行，不依赖 Rosetta 2**）
- 系统：macOS 11.0+（arm64 Mac 的实际最低版本）
- 运行时：Python 3.13 + PyQt6 6.7.1
- 版本：1.0 · Copyright © 2026 Christopher Hsu

> 使用 **Intel 芯片 Mac** 或 **macOS 10.15** 的用户，请移步兼容性发行线
> [at_xiao_pp_macOS_Intel_Version](https://github.com/ChristopherHsu2021/at_xiao_pp_macOS_Intel_Version)（x86_64 包，在 M 系列上经 Rosetta 2 亦可运行）。

近期构建已修复 macOS 半透明窗口的残留重影、以及点击其他软件时桌面宠物 / 歌词浮窗被隐藏的问题。

---

## 下载与安装

1. 到本仓库 [Releases](../../releases) 下载 `AT小PP-macos-arm64.dmg`。
2. 双击挂载镜像，把里面的 **AT小PP.app** 拖进 `Applications`（或 `~/Applications`）。
3. 首次启动会被 macOS Gatekeeper 拦一次（未公证包的正常现象，详见下方「关于签名」与「常见问题」）。
   按 [常见问题](#常见问题) 里的步骤放行一次即可，之后不再拦截。
4. **卸载**：把 `AT小PP.app` 拖进废纸篓即可，没有卸载向导、不写系统目录。

关于签名的说明：本包使用免费的 **ad-hoc 自签名**（`codesign --sign -`），未经 Apple 付费公证，
因此从网络下载后首次打开会提示拦截。这是未公证包的预期行为，**并非文件损坏**，按下面的步骤处理一次即可。

用户数据（设置、待办、闹钟、曲库等）存放在
`~/Library/Application Support/AT小PP`，重装 / 升级不会丢失。

---

## 功能一览

| 模块 | 说明 |
| --- | --- |
| 桌面宠物 | 透明无边框、可拖拽、右键菜单；服装 / 工作 / 休息 / 睡觉状态自动切换，闲置超过 15 分钟进入休息并语音播报 |
| 音乐播放器 | 本地曲库 + 在线缓存 + 在线搜索，歌词滚动、专辑封面、拖拽上传、托盘播放控制条 |
| 待办清单 | 增删改与勾选划线，本地持久化，每周一自动清理 |
| 闹钟 | 时间 / 重复 / 铃声模糊搜索 / 自定义语音播报 |
| 计时器 | 时:分:秒 输入、倒计时、暂停与取消，结束语音提醒 |
| 场景玩法 | 工作·歌手（随机完整播放一首）、居家·听歌（打开播放器随机播放） |
| 语音播报 | 优先播放预生成语音，缺失时回退 macOS 系统 `say` 合成 |
| 设置 | 开机自启、语言（简体 / 繁體 / English）、音量、画面大小、工作时间段、版权信息 |
| 系统托盘 | 常驻托盘、隐身恢复、气泡通知；播放器开启时菜单顶部显示播放控制条 |

---

## macOS 适配要点

Windows 原版移植到 macOS 时处理的关键差异，修改代码前建议先读一遍：

- **PyQt6 锁定 6.7.1**：Qt 6.8+ 在 macOS 上因 `qdarwinpermission` 的全局静态初始化器调用
  `CFBundleCopyBundleURL` 拿到 NULL，`import` 阶段即 SIGSEGV。
- **音频后端改为 AVFoundation**：通过 PyObjC 桥接系统原生 `AVAudioPlayer`
  （见 `app/core/audio_backend.py`），绕开打包后 QtMultimedia 的 `darwinmedia` 后端
  因 `@rpath` 解析失败而「无声」的问题；非 macOS 平台仍走 `QMediaPlayer`。
- **显式写入 `qt.conf`**：强制 Qt 用文件系统路径解析库与插件，绕开 Qt 静态初始化期的
  `CFBundleCopyBundleURL(NULL)` 崩溃。
- **物化 Python 共享库**：`Contents/Frameworks/Python` 必须是真实的 libpython dylib；
  若被打包成符号链接并在拷贝时丢失，应用会在启动阶段报 `[PYI-xxx] Failed to load Python shared library`。
- **证书与字体**：冻结包无系统 CA 路径，https（在线搜索）依赖 `certifi` 显式指定证书；
  QSS 字体按平台切换为 `PingFang SC`，避免 macOS 上缺失 `Microsoft YaHei` 的告警。
- **语音**：Windows SAPI5 在 macOS 上替换为系统 `say` 命令。
- **窗口渲染（近期修复）**：半透明无边框窗口的残留重影根因在 macOS 窗口阴影缓存，已通过
  `NoDropShadowWindowHint` 治本；点击其他软件时被隐藏，根因是 `Qt::Tool` 在 macOS 映射为
  `NSPanel` 默认 `hidesOnDeactivate`，已通过底层 `setHidesOnDeactivate_(False)` 修正。

---

## 从源码运行

需要在 **macOS（Apple Silicon 或 Intel）** 上执行（PyInstaller 无法跨平台编译 `.app` / `.dmg`）。

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-macos.txt
python main.py
```

`requirements-macos.txt` 是 macOS 专用依赖清单：去掉仅 Windows 可用的 `comtypes`，
补上 `audioop-lts`（Python 3.13 已移除标准库 `audioop`）、`certifi`（https 证书）
与 `pyobjc-framework-AVFoundation`（音频后端）。

---

## 打包 .dmg

```bash
# arm64（本仓库默认，Apple Silicon 原生，不经过 Rosetta）
ATPP_TARGET_ARCH=arm64 python scripts/package_macos.py --clean

# 可选：尝试 universal2（需宿主机 Python 与依赖均为通用二进制，否则自动回退）
python scripts/package_macos.py --clean --universal
```

产物：`release/AT小PP-macos-arm64.dmg`。

脚本 `scripts/package_macos.py` 依次完成：生成 `app_icon.icns` → PyInstaller 打出
`dist/AT小PP.app` → 裁剪无用 Qt 翻译与 QtPdf → 物化 libpython、写入 `qt.conf`、
校验 QtMultimedia 插件与动态库 → ad-hoc 自签名 → `hdiutil` 打成 `.dmg`（含 Applications 快捷方式）。
其中「多媒体插件 / QtMultimedia 动态库 / Python 共享库」缺失会**直接判定构建失败**，避免发出无声或打不开的废包。

### 持续集成

`.github/workflows/build-macos.yml` 在 `macos-15`（Apple Silicon runner）上**原生**构建 arm64 包
（`ATPP_TARGET_ARCH=arm64`，不经过 Rosetta 2），触发方式为推送 `main` / `v*` tag 或手动 `workflow_dispatch`，
产物作为 Actions artifact `AT小PP-macos-arm64` 上传。

> 注意：本仓库直接产出 arm64 二进制，无需交叉编译；请在 Apple Silicon 宿主机或 macos-15 runner 上构建，
> 在纯 x86_64 环境会编译失败。

---

## 目录结构

```
app/core/     配置、状态、待办、闹钟、音频后端、语音、歌词、路径等核心逻辑
app/ui/       宠物窗、播放器、待办 / 闹钟 / 计时器 / 设置 / 场景等界面
assets/       图片与静态素材
data/         源码模式下的运行数据（打包后写入 ~/Library/Application Support/AT小PP）
scripts/      打包与发布脚本（package_macos.py 等）
build.spec    PyInstaller 配置（供 macOS .app 构建）
installer/    Windows 侧的 Inno Setup 脚本（macOS 不使用）
```

Windows 打包说明另见 [PACKAGE_WINDOWS.md](PACKAGE_WINDOWS.md)。

---

## 常见问题

**打不开 / 提示「App 已损坏」或「无法确认开发者」**
未公证包的正常拦截，按以下顺序处理：
1. 打开「系统设置 → 隐私与安全性」，滚到最底部点「仍要打开」；
2. 或在终端执行 `xattr -dr com.apple.quarantine /Applications/AT小PP.app`；
3. 若提示「已损坏，移到废纸篓」，改用 `xattr -cr /Applications/AT小PP.app`
   （`-r` 递归清除 App 内部所有动态库的隔离标记）；
4. 仍不行则本地 ad-hoc 重签：`sudo codesign --force --deep -s - /Applications/AT小PP.app`。
（macOS Sequoia 15+ 已移除「右键 → 打开」的绕过方式，优先用系统设置法。）

**在 Intel Mac 上启动报 `bad CPU type in executable`**
说明拿到的是 arm64 包。本仓库仅提供 arm64 包，请改用
[at_xiao_pp_macOS_Intel_Version](https://github.com/ChristopherHsu2021/at_xiao_pp_macOS_Intel_Version) 的 x86_64 包。

**能启动但播放没有声音**
构建期已校验 `plugins/multimedia` 与 QtMultimedia 动态库；若仍无声，
检查日志中是否出现 `No QtMultimedia backends found` 或 AVAudioPlayer 初始化错误。

**在线搜索 / 联网功能全部失败**
冻结包需 `certifi` 提供证书路径，确认 `requirements-macos.txt` 已安装且未被裁剪。

---

## 版权

Copyright © 2026 Christopher Hsu. All rights reserved.
