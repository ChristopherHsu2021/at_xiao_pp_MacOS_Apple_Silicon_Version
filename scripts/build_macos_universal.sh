#!/usr/bin/env bash
# ============================================================================
# AT小PP · macOS 通用版一键构建脚本（Intel + Apple Silicon 通吃）
# ----------------------------------------------------------------------------
# 使用场景：在 macOS 本机或 macOS 虚拟机（本项目用 VMware Workstation 里的
#           Intel macOS Ventura 13.6.5 验证）中运行本脚本，产出可被 Intel Mac
#           原生运行、Apple Silicon Mac 经 Rosetta 2（或 universal2 原生）运行的
#           单个 .dmg 安装包。
#
# 重要：本脚本【只能在 macOS 上运行】。PyInstaller 无法跨平台编译 .app/.dmg，
#       且脚本依赖 macOS 专属工具（sips / iconutil / hdiutil / codesign）。
#       Windows / Linux 上执行会直接报错退出。
#
# 产出：release/AT小PP-macos.dmg
#   - 挂载后把里面的 AT小PP.app 拖进 /Applications（或 ~/Applications）即安装；
#   - 卸载 = 把 AT小PP.app 拖进废纸篓，无需向导。
#
# 关于「Intel 兼容M系列 版」：
#   - 默认（宿主 Python 为 universal2 时）产出 universal2 单包：Intel 与
#     Apple Silicon 均原生运行，体验最佳。
#   - 若宿主 Python 仅为 Intel 单架构（Intel 虚拟机常见），脚本自动回退为
#     x86_64 包：Intel 原生、Apple Silicon 经 Rosetta 2 运行，单个 .dmg 仍
#     可覆盖几乎所有 Mac，满足「Intel 兼容 M 系列」需求。
# ============================================================================

set -euo pipefail

# 切到项目根目录（脚本位于 scripts/ 下，上一级即根）
cd "$(cd "$(dirname "$0")" && pwd)/.."

# 允许用 PY= 指定解释器，默认 python3
PY="${PY:-python3}"

echo "==> [1/4] 准备 Python 虚拟环境 (venv)"
if [ ! -x venv/bin/python3 ]; then
    "$PY" -m venv venv
fi

echo "==> [2/4] 安装/锁定 macOS 运行与打包依赖"
venv/bin/python3 -m pip install --upgrade pip
venv/bin/python3 -m pip install -r requirements-macos.txt

echo "==> [3/4] 构建 .app 并封盘为 .dmg（--universal 尝试 universal2）"
venv/bin/python3 scripts/package_macos.py --universal

echo "==> [4/4] 完成"
DMG="$(pwd)/release/AT小PP-macos.dmg"
if [ -f "$DMG" ]; then
    echo "已生成安装包：$DMG"
    echo "使用：挂载 .dmg 后把 AT小PP.app 拖进 /Applications（或 ~/Applications）即可；"
    echo "     卸载 = 把 AT小PP.app 拖进废纸篓。"
else
    echo "错误：未找到 $DMG，构建可能失败，请查看上方日志。" >&2
    exit 1
fi
