$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
& (Join-Path $PSScriptRoot "backup.ps1")
docker compose pull
docker compose build --pull
docker compose up -d --remove-orphans
docker compose ps
