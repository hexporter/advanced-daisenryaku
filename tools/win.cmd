@echo off
rem Windows entry point for the bash tools: tools\win build --rom tr (see tools\win_tool.ps1).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0win_tool.ps1" %*
exit /b %ERRORLEVEL%
