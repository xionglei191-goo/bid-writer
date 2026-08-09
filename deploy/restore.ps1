param([Parameter(Mandatory = $true)][string]$BackupPath)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackupRoot = (Resolve-Path (Join-Path $Root "backups")).Path
$ResolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
$AllowedPrefix = $BackupRoot.TrimEnd("\") + "\"
if (-not $ResolvedBackup.StartsWith($AllowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Restore is only allowed from the project backups directory"
}
foreach ($Name in "postgres.dump", "qdrant.tar.gz", "minio.tar.gz") {
    if (-not (Test-Path -LiteralPath (Join-Path $ResolvedBackup $Name))) {
        throw "Backup is missing $Name"
    }
}

Set-Location $Root
& (Join-Path $PSScriptRoot "backup.ps1")
docker compose stop app worker qdrant minio
$PostgresContainer = docker compose ps -q postgres
docker cp (Join-Path $ResolvedBackup "postgres.dump") "${PostgresContainer}:/tmp/bid-writer-restore.dump"
if ($LASTEXITCODE -ne 0) { throw "Unable to copy the PostgreSQL restore file" }
docker compose exec -T postgres pg_restore -U bid_writer -d bid_writer --clean --if-exists /tmp/bid-writer-restore.dump
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore failed" }
docker run --rm --volume "bid-writer_qdrant_data:/target" --volume "${ResolvedBackup}:/backup:ro" alpine:3.21 sh -c "rm -rf /target/* && tar -xzf /backup/qdrant.tar.gz -C /target"
if ($LASTEXITCODE -ne 0) { throw "Qdrant restore failed" }
docker run --rm --volume "bid-writer_minio_data:/target" --volume "${ResolvedBackup}:/backup:ro" alpine:3.21 sh -c "rm -rf /target/* && tar -xzf /backup/minio.tar.gz -C /target"
if ($LASTEXITCODE -ne 0) { throw "MinIO restore failed" }
docker compose start qdrant minio app worker
Write-Host "Restore completed. Verify /api/health/ready and the audit chain."
