# 模块说明

## 后端

- `database`：SQLite开发兼容层、PostgreSQL连接和Alembic迁移。
- `auth`：本地账号、Argon2id、会话、OIDC PKCE和四类角色。
- `audit`：敏感字段清洗、操作记录和哈希链校验。
- `jobs`：持久任务、阶段事件、取消、重试及Dramatiq worker。
- `storage`：MinIO与本地文件系统对象存储适配。
- `knowledge.pipeline`：长文档切片、抽取、复核、规则、裁决、去重、抽检和回滚。
- `retrieval`：中文BM25、BGE-M3、Qdrant、RRF、reranker、版本索引和反馈。
- `evaluation`：白银/黄金问题、Recall、MRR、NDCG、负样本和基线提升。
- `evidence`：Claim分类、来源支持度、EvidenceLink和处理状态。
- `production`：要求分类、覆盖矩阵、生成快照、质量台账、DOCX/PDF预检和交付冻结。

## 前端

- 登录：本地账号与可选企业OIDC。
- 知识工程：处理任务、切片状态、AI候选、异常、抽检、发布和检索评测。
- 项目生产：要求、覆盖矩阵、后台生成、Claim证据侧栏和逐项签审。
- 质量交付：硬门禁、警告、证据指标、DOCX及正式交付包。
- 系统设置：运行组件、后台任务、AI调用和数据边界。

## 公共接口

- `/api/auth/*`：会话、OIDC和用户角色。
- `/api/jobs/*`：持久任务、取消、重试与SSE事件。
- `/api/search/hybrid`：带分数解释和索引版本的混合检索。
- `/api/projects/{id}/coverage`：要求到章节覆盖矩阵。
- `/api/projects/drafts/{id}/claims`：Claim及来源证据。
- `/api/projects/{id}/quality`：门禁和统一问题台账。
- `/api/projects/{id}/manifests`：冻结交付清单。
- `/api/audit/*`：审计查询与链校验。
