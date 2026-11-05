@echo off
chcp 65001 >nul
if exist "%~dp0待办清单.exe" (
    start "" "%~dp0待办清单.exe"
    exit
)
start "" pyw -3 "%~dp0todo.py"
exit
