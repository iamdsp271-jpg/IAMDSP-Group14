@echo off
REM Double-click this file to install everything and start IAMDSP on Windows.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed or not added to PATH. Please install Python from python.org and tick "Add python.exe to PATH".
  pause
  exit /b
)
if not exist venv (
  echo Creating a private Python environment... this happens only once.
  python -m venv venv
)
call venv\Scripts\activate
echo Installing the needed packages (needs internet the first time)...
pip install -r requirements.txt
echo.
echo Starting IAMDSP. Open your browser and go to  http://127.0.0.1:5000
python app.py
pause
