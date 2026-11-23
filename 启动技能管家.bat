@echo off
chcp 65001 >nul
title WorkBuddy Skill Manager
cd /d "%~dp0"
echo.
echo   WorkBuddy Skill Manager 启动中...
echo   使用说明见 README.md，配置见 config.json
echo   浏览器会自动打开 http://127.0.0.1:17823/
echo   关闭本窗口即可停止服务
echo.
python server.py
if errorlevel 1 (
  echo.
  echo [错误] 启动失败：检查 Python 是否安装、config.json 的 WorkBuddy 路径是否正确、端口 17823 是否被占用。
  pause
)
