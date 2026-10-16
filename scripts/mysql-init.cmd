@echo off
setlocal
set "PYTHONUTF8=1"
if not exist "%~dp0..\.venv\Scripts\python.exe" (
    echo Windows Python environment not found.
    echo Open a terminal in the project folder and run:
    echo   py -3.11 manage.py setup --skip-browser
    echo Then run this script again.
    pause
    exit /b 1
)
"%~dp0..\.venv\Scripts\python.exe" "%~dp0..\manage.py" mysql-init %*
set "ERP_INIT_EXIT=%errorlevel%"
echo.
pause
exit /b %ERP_INIT_EXIT%
