@echo off
cd /d "C:\Users\User1\giftdice\miniapp"
REM убьём залипшие pythonw, если вдруг
for /f "tokens=2" %%p in ('tasklist ^| find /I "pythonw.exe"') do taskkill /PID %%p /F >nul 2>&1
python miniapp_server.py 8081
