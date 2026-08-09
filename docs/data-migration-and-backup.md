# 数据迁移与备份恢复

## SQLite迁移

1. 停止旧服务并复制`data/bid_writer_v2.sqlite3`。
2. 启动空的PostgreSQL并确认Alembic已到head。
3. 执行：

```powershell
$env:PYTHONPATH = "backend"
python backend/scripts_v2/migrate_sqlite_to_postgres.py `
  --sqlite data/bid_writer_v2.sqlite3 `
  --database-url $env:BID_WRITER_DATABASE_URL `
  --report data/migration-report.json
```

迁移器要求目标业务表为空；允许Alembic预置的组织、角色和提示词存在。组织与角色按ID和业务字段核对，提示词在确认目标没有AI运行引用后由旧库版本完整替换，以保留历史外键。自引用字段采用先写主体、再补关系的两阶段方式。每表校验行数、主键范围和规范化SHA-256，任一表不一致时整个PostgreSQL事务回滚，原SQLite始终只读。

## 备份

`.\deploy\backup.ps1`在`backups/<时间>/`保存PostgreSQL、自托管Qdrant、MinIO、环境配置和校验和。备份目录已加入`.gitignore`。

脚本会在停止服务前确认备份工具镜像可用，并检查每个Docker命令的退出码。只有PostgreSQL、Qdrant和MinIO归档全部成功后才写校验清单。

## 恢复

```powershell
.\deploy\restore.ps1 -BackupPath .\backups\20260808-120000
```

脚本只接受项目`backups`目录内的已解析路径，恢复前停止app和worker。恢复后必须检查ready、审计链、active索引、两套演练项目和最近交付清单。

2026-08-09已将完整备份恢复到临时空数据库，核对11664条资料、256条知识、37次AI运行、任务及对象记录后删除临时库；Qdrant、MinIO归档和所有SHA-256同时通过检查。
