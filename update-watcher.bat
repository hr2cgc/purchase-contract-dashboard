@echo off
rem Downloads the latest watcher files from GitHub (run once after an update)
cd /d "%~dp0"
echo [1/2] Downloading latest files...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $b='https://raw.githubusercontent.com/hr2cgc/purchase-contract-dashboard/main/'; Invoke-WebRequest -UseBasicParsing -Uri ($b+'scripts/build_data.py') -OutFile 'scripts\build_data.py'; Invoke-WebRequest -UseBasicParsing -Uri ($b+'watcher/watcher.py') -OutFile 'watcher\watcher.py'" || goto :fail
echo [2/2] Done.
echo.
echo Now CLOSE the black start-watcher window (if open) and run start-watcher.bat again.
pause
exit /b 0
:fail
echo.
echo Download failed. Take a screenshot of this window.
pause
exit /b 1
