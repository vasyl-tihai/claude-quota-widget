@echo off
rem Starts both widgets without a console window.
rem Keep this file pure ASCII: cmd.exe reads .bat files in the OEM code page.
cd /d "%~dp0"

set "PYW="
where pythonw >nul 2>nul && set "PYW=pythonw"
if not defined PYW where pyw >nul 2>nul && set "PYW=pyw -3"
if not defined PYW (
    echo Python 3 for Windows was not found.
    echo Install it from https://www.python.org/downloads/windows/ and run this file again.
    pause
    exit /b 1
)

start "" %PYW% "%~dp0quota_widget.py"
start "" %PYW% "%~dp0tasks_widget.py"
