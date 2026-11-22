$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host 'Created .env from .env.example'
}

if (-not (Test-Path -LiteralPath 'backend/.env')) {
    Copy-Item -LiteralPath 'backend/.env.example' -Destination 'backend/.env'
    Write-Host 'Created backend/.env from backend/.env.example'
}

$authEnvPath = Join-Path $root 'backend/.env'
$authEnv = [System.IO.File]::ReadAllText($authEnvPath)
$keyPattern = '(?m)^CREATORMIND_AUTH_SECRET_KEY=[ \t]*\r?$'
if ($authEnv -notmatch '(?m)^CREATORMIND_AUTH_SECRET_KEY=.+$' -or $authEnv -match $keyPattern) {
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $line = 'CREATORMIND_AUTH_SECRET_KEY=' + [Convert]::ToBase64String($bytes)
    if ($authEnv -match $keyPattern) {
        $authEnv = [regex]::Replace($authEnv, $keyPattern, $line)
    } else {
        $authEnv = $authEnv.TrimEnd() + "`n" + $line + "`n"
    }
    [System.IO.File]::WriteAllText($authEnvPath, $authEnv, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Generated a server-only authentication key (not displayed).'
}

if (-not (Test-Path -LiteralPath 'backend/.venv')) {
    py -m venv backend/.venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

& '.\backend\.venv\Scripts\python.exe' -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& '.\backend\.venv\Scripts\python.exe' -m pip install -e '.\backend[dev,agent]'
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }

Push-Location frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
} finally {
    Pop-Location
}

Write-Host ''
Write-Host 'CreatorMind dependencies are ready.'
Write-Host 'Start infrastructure: docker compose up -d postgres redis minio'
Write-Host 'Migrate database:     cd backend; .\.venv\Scripts\python.exe -m alembic upgrade head'
Write-Host 'Initialize account:   .\.venv\Scripts\python.exe -m app.cli.auth init-user --username creator'
Write-Host 'Start API:            .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --no-proxy-headers'
Write-Host 'Start web:            cd frontend; npm run dev'