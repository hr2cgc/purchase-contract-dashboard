@echo off
where py >nul 2>nul && (py -m pip install openpyxl) || (python -m pip install openpyxl)
pause
