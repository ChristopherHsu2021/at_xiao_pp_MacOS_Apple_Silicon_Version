# AT小PP Windows 打包流程

软件信息：

- 软件名称：AT小PP
- 版本号：beta version 1.0
- 开发者：Christopher Hsu
- 版权信息：Copyright © 2026 Christopher Hsu. All rights reserved.

## 1. 生成 PyInstaller 程序目录

```powershell
.\venv\Scripts\python.exe -m PyInstaller .\build.spec --clean --noconfirm
```

产物：

```text
dist\AT小PP\AT小PP.exe
```

## 2. 用 Inno Setup 生成内层静默安装包

安装 Inno Setup 后执行：

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\installer\AT小PP.iss
```

产物：

```text
release\AT小PP-beta-version-1.0-inner-setup.exe
```

这是给外层自定义安装器嵌入用的中间产物，不直接交付给用户。

## 3. 生成最终自定义安装器

```powershell
.\venv\Scripts\python.exe -m PyInstaller .\bootstrap.spec --clean --noconfirm --distpath .\release
```

最终交付给用户的安装包：

```text
release\AT小PP-beta-version-1.0-setup.exe
```

生成最终安装器后，可以删除 `release\AT小PP-beta-version-1.0-inner-setup.exe`，避免误点到 Inno 默认页面。

## 4. 安装/卸载接入

- 用户双击最终安装包后，先看到项目内自定义安装向导，不显示 Inno Setup 默认页面。
- 自定义安装向导负责语言、安装路径、桌面快捷方式、开机自启动、完成页和立即打开。
- 用户点击“安装”后，外层安装器会在后台静默运行内层 Inno Setup，把 PyInstaller 产物安装到 Program Files 或用户选择的目录。
- Windows 会自动写入卸载注册表，软件会出现在“设置 -> 应用 -> 已安装的应用”。
- 卸载开始前 Inno Setup 会调用 `AT小PP.exe --uninstall --inno-managed`，展示项目内自定义卸载向导；用户确认后才继续删除程序文件，选择“再留一下”会取消卸载。
- 主程序、外层安装器均使用 `console=False`；后台安装和卸载清理使用隐藏进程，不弹出 cmd 黑窗。

## 注意

当前版本不内置 GPT-SoVITS/语音模仿模型，只保留接口，避免打包体积过大和用户环境问题。
用户安装后不需要配置 Python、PyQt 或其它运行环境。
