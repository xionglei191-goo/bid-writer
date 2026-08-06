@echo off
set "APP_ROOT=%~dp0"
for %%I in ("%APP_ROOT%..\..") do set "BID_WRITER_WORKSPACE=%%~fI"
set "BID_WRITER_DB=%APP_ROOT%data\bid_writer_v2.sqlite3"
set "BID_WRITER_ENABLE_OPERATIONS=0"
set "PYTHONPATH=%APP_ROOT%backend"
if exist "%APP_ROOT%.venv\Scripts\python.exe" (set "PYTHON=%APP_ROOT%.venv\Scripts\python.exe") else if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe") else (set "PYTHON=python")
cd /d "%APP_ROOT%"
"%PYTHON%" "backend\scripts_v2\manage.py" scan
"%PYTHON%" "backend\scripts_v2\manage.py" queue-all
