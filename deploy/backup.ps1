$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $Root "backups"
$Target = Join-Path $BackupRoot $Stamp
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$ResolvedTarget = (Resolve-Path $Target).Path
$AllowedPrefix = $BackupRoot.TrimEnd("\") + "\"
if (-not $ResolvedTarget.StartsWith($AllowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup target is outside the backups directory"
}

docker image inspect alpine:3.21 *> $null
if ($LASTEXITCODE -ne 0) {
    docker pull alpine:3.21
    if ($LASTEXITCODE -ne 0) { throw "Unable to download the backup helper image" }
}
docker compose exec -T postgres pg_dump -U bid_writer -d bid_writer -Fc -f /tmp/bid-writer.dump
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed" }
$PostgresContainer = docker compose ps -q postgres
docker cp "${PostgresContainer}:/tmp/bid-writer.dump" (Join-Path $ResolvedTarget "postgres.dump")
if ($LASTEXITCODE -ne 0) { throw "Unable to copy the PostgreSQL backup" }

docker compose stop app worker qdrant minio
try {
    docker run --rm --volume "bid-writer_qdrant_data:/source:ro" --volume "${ResolvedTarget}:/backup" alpine:3.21 tar -czf /backup/qdrant.tar.gz -C /source .
    if ($LASTEXITCODE -ne 0) { throw "Qdrant backup failed" }
    docker run --rm --volume "bid-writer_minio_data:/source:ro" --volume "${ResolvedTarget}:/backup" alpine:3.21 tar -czf /backup/minio.tar.gz -C /source .
    if ($LASTEXITCODE -ne 0) { throw "MinIO backup failed" }
} finally {
    docker compose start qdrant minio app worker
}

Copy-Item -LiteralPath ".env" -Destination (Join-Path $ResolvedTarget "env.backup")
$PayloadFiles = Get-ChildItem -LiteralPath $ResolvedTarget -File
$PayloadFiles |
    Get-FileHash -Algorithm SHA256 |
    Select-Object Algorithm, Hash, Path |
    ConvertTo-Json |
    Set-Content -Encoding UTF8 -LiteralPath (Join-Path $ResolvedTarget "checksums.json")
Write-Host "Backup completed: $ResolvedTarget"
