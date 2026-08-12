# 技术标生产与知识工程系统

本项目是AI优先的技术标生产与知识工程系统，覆盖资料加工、发布知识、混合检索、证据生成、质量门禁和冻结交付。

## 启动

开发模式可双击 `run_server.cmd`，浏览器访问 `http://127.0.0.1:8876`。

私有化部署复制`.env.example`为`.env`并填写密码、会话密钥和挂载目录，然后运行：

```powershell
.\deploy\install.ps1
```

详细步骤见`docs/private-deployment.md`。

首次安装依赖：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m pip install -r backend\requirements.txt
cd frontend
npm ci
npm run build
```

## 模块

- `backend/bid_writer_v2/knowledge`：扫描、去重、解析/OCR、知识拆解、重构、审核、发布和检索。
- `backend/bid_writer_v2/production`：项目、要求、目录、Claim证据、质量门禁和DOCX/PDF冻结交付。
- `backend/bid_writer_v2/retrieval.py`：BM25、BGE-M3、Qdrant、RRF和reranker。
- `backend/bid_writer_v2/auth.py`、`jobs.py`、`audit.py`：身份权限、后台任务和哈希审计。
- `frontend/src`：React模块化工作台。
- `docs`：架构、模块边界、研发工作流和技术决策。

## 当前研发计划

- `docs/ai-first-solo-development-plan.md`：单人开发条件下的 AI 优先实施计划、阶段验收和优先级。
- `docs/private-deployment.md`：Compose安装、升级、监控和故障处理。
- `docs/data-migration-and-backup.md`：SQLite迁移及备份恢复。

## 数据边界

原始资料以只读方式挂载；只有已发布且有效的知识进入检索。生产数据存入PostgreSQL，文件和索引存入MinIO，正式文件镜像到`04_交付与报告`。客户资料、数据库、模型缓存、备份和真实密钥不会提交到GitHub。

## 批量管理

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py scan
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py queue-all
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py work --limit 20
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py metrics
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py ai-process-document --document-id 10 --max-candidates 12
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py ai-accept-ready --reviewer "技术负责人"
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py eval-gold --top-k 10
```

`ai-process-document` 会把标准文档发送给当前配置的模型。首次试运行应只选择一份代表性、允许送入该模型的数据，检查候选和异常待办后再扩大范围。

HTTP耗时操作返回`202 + job_id`；前端任务中心显示进度、取消、失败和重试。旧CLI仍保留一个兼容周期。

## 测试

```powershell
$env:PYTHONPATH = "backend"
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m unittest discover -s backend\tests_v2 -v
cd frontend
npm run build
```
