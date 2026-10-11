@echo off
setlocal
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  py -3.11 -m venv venv
  if errorlevel 1 goto python_missing
)
venv\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
venv\Scripts\python.exe -m PyInstaller --noconfirm --workpath "%TEMP%\SpikeAI-build" --distpath "%TEMP%\SpikeAI-dist" SpikeAI.spec
if errorlevel 1 goto failed
robocopy "%TEMP%\SpikeAI-dist\Spike AI" "dist\Spike AI" /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS
if errorlevel 8 goto failed
echo.
echo Build complete: dist\Spike AI\Spike AI.exe
pause
exit /b 0
:python_missing
echo Python 3.11 was not found. Install it from python.org with the py launcher, then run build.bat again.
pause
exit /b 1
:failed
echo Build failed. See the messages above.
pause
exit /b 1
