@echo off
cd /d "%~dp0"
py -3.11 -m venv venv
if errorlevel 1 exit /b 1
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
echo Spike AI 3.0 installed. Run start.bat.
pause
