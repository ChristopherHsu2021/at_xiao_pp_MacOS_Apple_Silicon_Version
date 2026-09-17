# AT小PP

AT小PP 是一个基于 PyQt6 的桌面宠物项目，带有音乐播放器、待办、闹钟、计时器、设置、自定义安装/卸载向导等功能。

## 项目特性

- 桌面宠物主界面与托盘常驻
- 音乐播放器、歌词、专辑图
- 待办事项与闹钟提醒
- 计时器与系统播报
- 自定义安装向导与自定义卸载向导
- Windows 打包发布链路

## 运行环境

- Python 3.10+（建议）
- PyQt6
- comtypes
- pycryptodome
- opencc-python-reimplemented

安装依赖：

```powershell
pip install -r requirements.txt
```

## 本地运行

从项目根目录启动：

```powershell
python main.py
```

## 打包流程

Windows 打包说明见 [PACKAGE_WINDOWS.md](PACKAGE_WINDOWS.md)。

简要流程：

1. 使用 PyInstaller 生成程序目录
2. 用 Inno Setup 生成内层安装包
3. 再用外层 bootstrap 打出最终自定义安装器

## 目录说明

- `app/`：主程序代码
- `assets/`：静态资源
- `data/`：本地配置、状态、任务、闹钟等运行数据
- `installer/`：Inno Setup 脚本
- `scripts/`：打包与发布脚本
- `build.spec` / `bootstrap.spec`：PyInstaller 配置

## 说明

- 运行时生成的缓存、状态、语音媒体和打包产物不建议提交仓库
- 当前版本不内置语音模仿模型，只保留接口
- 用户安装后不需要额外配置 Python 环境

## 版权

Copyright © 2026 Christopher Hsu. All rights reserved.
