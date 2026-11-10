@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py watcher\watcher.py) || (python watcher\watcher.py)
pause
