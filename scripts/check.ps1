$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path -LiteralPath 'backend/.venv/Scripts/python.exe')) {
    throw 'Backend virtual environment is missing. Run .\scripts\setup.ps1 first.'
}

if (-not (Test-Path -LiteralPath 'frontend/node_modules')) {
    throw 'Frontend dependencies are missing. Run .\scripts\setup.ps1 first.'
}

Push-Location backend
try {
    & '.\.venv\Scripts\python.exe' -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed.' }
    & '.\.venv\Scripts\python.exe' -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
} finally {
    Pop-Location
}

Push-Location frontend
try {
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Frontend typecheck failed.' }
    npm test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}

Write-Host 'All checks passed.'