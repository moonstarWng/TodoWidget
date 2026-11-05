@echo off
chcp 65001 >nul
powershell -NoProfile -Command "$p=Join-Path ([Environment]::GetFolderPath('Startup')) '待办清单.lnk'; if (Test-Path $p) { Remove-Item $p; Write-Host '已取消开机自启' } else { Write-Host '本来就没有开机自启' }"
pause
