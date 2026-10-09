param([int]$Port = 8202)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { $pythonPath = Join-Path (Split-Path $projectRoot -Parent) '.venv/Scripts/python.exe' }
if (!(Test-Path -LiteralPath $pythonPath)) { throw 'Create a Python .venv and install requirements.txt first.' }
& $pythonPath (Join-Path $projectRoot 'start.py') $Port
