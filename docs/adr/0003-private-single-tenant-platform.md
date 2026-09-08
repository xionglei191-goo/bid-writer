# ADR 0003：单组织私有化平台

状态：已采纳

## 决策

生产环境使用Docker Compose、PostgreSQL、Redis/Dramatiq、Qdrant和MinIO。SQLite只用于开发测试和旧数据导入。身份采用本地账号加可选OIDC，首版不实现多租户。

## 原因

单人维护条件下继续采用模块化单体，避免微服务治理成本；将长任务、向量和二进制对象从Web进程及SQLite中分离，获得可恢复任务、权限审计和可验证备份。

## 后果

部署需要Docker和更多内存；所有schema变更必须追加Alembic迁移；升级前必须备份。Kubernetes、多区域和高可用不在本阶段范围。
