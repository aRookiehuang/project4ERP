$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectDir '.venv\Scripts\python.exe'
if (-not (Test-Path $PythonExe)) {
    throw 'Run py manage.py setup before starting the application.'
}
& $PythonExe (Join-Path $ProjectDir 'manage.py') run @args
exit $LASTEXITCODE
