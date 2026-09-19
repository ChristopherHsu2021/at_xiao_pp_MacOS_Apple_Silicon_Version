# AT小PP · macOS 版（Intel / x86_64）

基于 PyQt6 的桌面宠物应用：陪伴互动 + 音乐播放器 + 待办 / 闹钟 / 计时器 + 场景玩法。
本仓库是 **Intel（x86_64）发行线**，产物为 `.dmg`，挂载后把 `AT小PP.app` 拖进「应用程序」即可使用，卸载就是拖进废纸篓。

- 架构：`x86_64`（Intel Mac 原生运行；Apple Silicon Mac 经 Rosetta 2 运行）
- 系统：macOS 10.15+
- 运行时：Python 3.13 + PyQt6 6.7.1
- 版本：1.0 · Copyright © 2026 Christopher Hsu

> 使用 Apple Silicon（M 系列）且希望跑**原生 arm64** 包，请移步专用仓库
> [at_xiao_pp_MacOS_Apple_Silicon_Version](https://github.com/ChristopherHsu2021/at_xiao_pp_MacOS_Apple_Silicon_Version)。

---

## 下载与安装

1. 到本仓库 [Releases](../../releases) 下载 `AT小PP-macos.dmg`。
2. 双击挂载镜像，把里面的 **AT小PP.app** 拖进 `Applications`（或 `~/Applications`）。
3. 首次启动若被系统拦下，任选其一：
   - 在 Finder 中 **右键 → 打开**，弹窗里点「打开」；
   - 或先清除隔离属性：

     ```bash
     xattr -dr com.apple.quarantine /Applications/AT小PP.app
     ```

4. **卸载**：把 `AT小PP.app` 拖进废纸篓即可，没有卸载向导、不写系统目录。

关于签名的说明：本包使用免费的 **ad-hoc 自签名**（`codesign --sign -`），未经 Apple 付费公证，
因此从网络下载后首次打开可能提示「无法确认开发者」。这是未公证包的正常现象，按上面第 3 步处理一次即可。

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

---

## 从源码运行

需要在 **macOS** 上执行（PyInstaller 无法跨平台编译 `.app` / `.dmg`）。

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
# x86_64（默认，兼容性最强）
ATPP_TARGET_ARCH=x86_64 python scripts/package_macos.py --clean

# 可选：尝试 universal2（需宿主机 Python 与依赖均为通用二进制，否则自动回退）
python scripts/package_macos.py --clean --universal
```

产物：`release/AT小PP-macos.dmg`。

脚本 `scripts/package_macos.py` 依次完成：生成 `app_icon.icns` → PyInstaller 打出
`dist/AT小PP.app` → 裁剪无用 Qt 翻译与 QtPdf → 物化 libpython、写入 `qt.conf`、
校验 QtMultimedia 插件与动态库 → ad-hoc 自签名 → `hdiutil` 打成 `.dmg`（含 Applications 快捷方式）。
其中「多媒体插件 / QtMultimedia 动态库 / Python 共享库」缺失会**直接判定构建失败**，避免发出无声或打不开的废包。

### 持续集成

`.github/workflows/build-macos.yml` 在 `macos-15`（Apple Silicon runner）上
用 `arch -x86_64` 包裹整段构建并配合 Rosetta 2 交叉编译出 **x86_64** 包，
触发方式为推送 `main` / `v*` tag 或手动 `workflow_dispatch`，产物作为 Actions artifact 上传。

> 注意：`actions/setup-python` 的 `architecture: x64` 在 macOS 上是空操作，
> 必须显式用 `arch -x86_64` 包裹 venv、依赖安装与 PyInstaller，否则会产出 arm64 包
> （Intel 机运行时报 `bad CPU type`）。

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
未公证包的正常拦截，右键 → 打开，或执行一次
`xattr -dr com.apple.quarantine /Applications/AT小PP.app`。

**Intel Mac 上启动报 `bad CPU type in executable`**
说明拿到的是 arm64 包，请改用本仓库的 x86_64 构建。

**能启动但播放没有声音**
构建期已校验 `plugins/multimedia` 与 QtMultimedia 动态库；若仍无声，
检查日志中是否出现 `No QtMultimedia backends found` 或 AVAudioPlayer 初始化错误。

**在线搜索 / 联网功能全部失败**
冻结包需 `certifi` 提供证书路径，确认 `requirements-macos.txt` 已安装且未被裁剪。

---

## 版权

Copyright © 2026 Christopher Hsu. All rights reserved.
