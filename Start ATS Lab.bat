@echo off
rem 1000Jobs ATS Lab: one-click start (the app with the Admin page and the User page). If the Lab is already
rem running, only the browser page is opened. Works from any folder: it starts where this file is.
cd /d "%~dp0"
set PORT=8501

netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if %errorlevel%==0 goto open

rem the Lab runs in its own minimized window (its title is how "Stop ATS Lab" finds it); only this computer can open it
start "1000Jobs ATS Lab (running)" /min cmd /c "py -3.12 run_app.py --server.port %PORT% --server.headless true --server.address 127.0.0.1 || pause"

rem wait until the page answers (60 seconds at most), then open it
for /l %%i in (1,1,60) do (
    netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul && goto open
    timeout /t 1 /nobreak >nul
)
echo The Lab did not start in 60 seconds. Look at the minimized window "1000Jobs ATS Lab (running)".
pause
exit /b 1

:open
rem the Admin page (the User page for job seekers is http://localhost:%PORT%/user)
start "" http://localhost:%PORT%/admin
exit /b 0
