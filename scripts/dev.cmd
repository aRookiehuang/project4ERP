@echo off
"%~dp0..\.venv\Scripts\python.exe" "%~dp0..\manage.py" run %*
exit /b %errorlevel%
