@echo off
chcp 936 >nul
setlocal enabledelayedexpansion

:: ===== 权限自检：非管理员则请求 UAC 提权（隐藏窗口，不弹控制台） =====
net session >nul 2>&1
if %errorLevel% neq 0 (
    powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs -WindowStyle Hidden"
    goto :eof
)

:: ===== 参数解析 =====
set "KEEP=0"
set "SILENT=0"
if /i "%~1"=="keepdata" set "KEEP=1"
if /i "%~1"=="nouserdata" set "KEEP=1"
if /i "%~1"=="silent" set "SILENT=1"
if /i "%~2"=="keepdata" set "KEEP=1"
if /i "%~2"=="nouserdata" set "KEEP=1"
if /i "%~2"=="silent" set "SILENT=1"

if "%SILENT%"=="0" (
    cls
    echo ============================================================
    echo            AT小PP 一键彻底卸载工具  (v1.0)
    echo ============================================================
    echo 本工具将执行以下操作：
    echo   1. 关闭正在运行的 AT小PP 程序
    echo   2. 运行官方卸载程序（若存在）
    echo   3. 强制删除安装目录 C:\Program Files\AT小PP
    echo   4. 清除开始菜单 / 桌面快捷方式
    echo   5. 清除注册表中的卸载信息
    if "%KEEP%"=="0" (
        echo   6. 删除用户数据 %%APPDATA%%\AT小PP （音乐库等，不可恢复）
    ) else (
        echo   6. 保留用户数据 %%APPDATA%%\AT小PP
    )
    echo.
    echo [警告] 操作不可逆！若需保留音乐库，请以参数 keepdata 运行：
    echo         uninstall_at_xiaopp.bat keepdata
    echo.
    echo 5 秒后自动开始，按 Ctrl+C 可取消。
    timeout /t 5 /nobreak >nul
)

:: ===== 1. 关闭进程 =====
taskkill /f /im "AT小PP.exe" >nul 2>&1
taskkill /f /im "AT小PP-version-1.0-setup.exe" >nul 2>&1
ping -n 2 127.0.0.1 >nul

:: ===== 2. 官方卸载 =====
set "INSTALL=C:\Program Files\AT小PP"
if exist "%INSTALL%\unins000.exe" (
    "%INSTALL%\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
    timeout /t 4 /nobreak >nul
)

:: ===== 3. 强制删除安装目录（最高权限接管） =====
if exist "%INSTALL%" (
    takeown /f "%INSTALL%" /r /d y >nul 2>&1
    icacls "%INSTALL%" /grant "*S-1-5-32-544:F" /t >nul 2>&1
    rd /s /q "%INSTALL%" >nul 2>&1
)
if exist "%INSTALL%" (
    rd /s /q "%INSTALL%" >nul 2>&1
)
if exist "%INSTALL%" ( echo [!] 无法完全删除，请手动检查：%INSTALL% ) else ( echo [ok] 安装目录已清除 )

:: ===== 4. 快捷方式 =====
del /f /q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\AT小PP.lnk" >nul 2>&1
rd /s /q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\AT小PP" >nul 2>&1
del /f /q "%PUBLIC%\Desktop\AT小PP.lnk" >nul 2>&1
del /f /q "%USERPROFILE%\Desktop\AT小PP.lnk" >nul 2>&1
echo [ok] 快捷方式清理完成

:: ===== 5. 注册表 =====
set "APPID={8F689211-D13C-45E4-9D9E-5A1A0F9A1000}"
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\%APPID%" /f >nul 2>&1
reg delete "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\%APPID%" /f >nul 2>&1
reg delete "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\%APPID%" /f >nul 2>&1
for /f "tokens=*" %%k in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" 2^>nul ^| findstr /i "AT小PP"') do reg delete "%%k" /f >nul 2>&1
for /f "tokens=*" %%k in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" 2^>nul ^| findstr /i "AT小PP"') do reg delete "%%k" /f >nul 2>&1
echo [ok] 注册表清理完成

:: ===== 6. 用户数据 =====
if "%KEEP%"=="0" (
    set "DATA=%APPDATA%\AT小PP"
    if exist "!DATA!" (
        rd /s /q "!DATA!" >nul 2>&1
        if exist "!DATA!" ( echo [!] 用户数据删除失败：!DATA! ) else ( echo [ok] 用户数据已删除 )
    ) else (
        echo [ok] 未找到用户数据，跳过
    )
) else (
    echo [ok] 按参数保留用户数据：%APPDATA%\AT小PP
)

:: ===== 自删：跑完后由独立进程删除本脚本（程序关闭并永久删除自己） =====
set "_SELF=%~f0"
start "" /min cmd /c "ping -n 2 127.0.0.1 >nul & del /f /q "%_SELF%" >nul 2>&1"
goto :eof
