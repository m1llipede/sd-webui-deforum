@echo off
title Deforum Compare (Portable) - KEEP THIS WINDOW OPEN
echo ============================================================
echo  Deforum Compare (Portable)
echo.
echo  A small local server is starting so the folder picker works.
echo  KEEP THIS WINDOW OPEN while you use the tool.
echo  Close it when you are finished.
echo ============================================================
echo.

REM Serve from THIS folder, wherever it happens to live
cd /d "%~dp0"

REM Pick the port
set PORT=48217

REM Start a tiny static web server in the background (needs Python)
start "DeforumCompareServer" /min python -m http.server %PORT%
if errorlevel 1 (
  echo.
  echo Python was not found. Trying py launcher...
  start "DeforumCompareServer" /min py -m http.server %PORT%
)

REM Give the server a second to come up, then open the browser
timeout /t 2 >nul
start "" chrome "http://localhost:%PORT%/Deforum_Compare_Portable.html"
if errorlevel 1 start "" "http://localhost:%PORT%/Deforum_Compare_Portable.html"

echo.
echo Opened in your browser:  http://localhost:%PORT%/Deforum_Compare_Portable.html
echo If nothing opened, paste that address into Chrome or Edge.
echo.
pause
