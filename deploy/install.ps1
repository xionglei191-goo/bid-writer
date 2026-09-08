$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker Desktop or Docker Engine is not installed" }
docker compose version | Out-Null

function New-SecureValue([int]$ByteCount = 32) {
    $bytes = New-Object byte[] $ByteCount
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

if (-not (Test-Path ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    $content = Get-Content -LiteralPath ".env" -Raw -Encoding UTF8
    $content = $content.Replace("POSTGRES_PASSWORD=replace-with-a-long-random-password", "POSTGRES_PASSWORD=$(New-SecureValue)")
    $content = $content.Replace("MINIO_ROOT_PASSWORD=replace-with-a-long-random-password", "MINIO_ROOT_PASSWORD=$(New-SecureValue)")
    $content = $content.Replace("BID_WRITER_SESSION_SECRET=replace-with-at-least-32-random-characters", "BID_WRITER_SESSION_SECRET=$(New-SecureValue 48)")
    $content = $content.Replace("BID_WRITER_BOOTSTRAP_PASSWORD=replace-with-a-strong-admin-password", "BID_WRITER_BOOTSTRAP_PASSWORD=$(New-SecureValue 24)")
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $Root ".env"), $content, $utf8)
    Write-Host "Generated .env with random deployment secrets. The bootstrap password is stored in local .env."
}
New-Item -ItemType Directory -Force -Path "runtime/knowledge", "runtime/delivery", "sample-data/raw", "backups" | Out-Null
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
Write-Host "System started: http://127.0.0.1:$((Get-Content .env | Select-String '^BID_WRITER_PORT=').Line.Split('=')[-1])"
