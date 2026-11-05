@echo off
chcp 65001 >nul
set "DIR=%~dp0"
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $p=Join-Path ([Environment]::GetFolderPath('Startup')) '待办清单.lnk'; $s=$ws.CreateShortcut($p); $exe=Join-Path '%DIR%' '待办清单.exe'; if (Test-Path $exe) { $s.TargetPath=$exe } else { $s.TargetPath=(Get-Command pyw.exe).Source; $s.Arguments='-3 ""%DIR%todo.py""' }; $s.WorkingDirectory='%DIR%'; $s.IconLocation='%DIR%icon.ico'; $s.Save(); Write-Host '已设置为开机自动启动'"
pause
