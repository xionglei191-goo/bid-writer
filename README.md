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

- `docs/handoffs/DELIVERY_RECOVERY_20260908.md`：2026-09-08 恢复、交付操作和真实项目验收记录。
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

管理员可在“知识工程 → 全库收口”创建并控制全量任务。对应接口为
`POST /api/knowledge/corpus-runs`、`GET /api/knowledge/corpus-runs/{id}`、
`POST /api/knowledge/corpus-runs/{id}/pause|resume|cancel`、
`GET /api/knowledge/completion`以及`GET /api/knowledge/manual-tasks`。
技术复核由系统以`actor_type=ai`记录；只有版权、保密、法律责任、密码或替换文件事项进入人工队列。

## 送审与正式交付

在项目工作台中先填写“项目资料”，再解析要求、生成目录和章节。章节已有草稿后禁止重新解析或重建目录，以免删除已有成果。长章节按要求分包生成，进度会显示当前部分；模型失败或缺少正文响应的部分保留待确认事项，不能视为已完成技术响应。

“质量与交付”显示送审阻塞项、已签审条款覆盖、整本预览和历史下载。正式版还要求真实投标单位、实际专业复核人、章节签审、合规确认及整本定稿。签审绑定当前正文；修改章节或项目资料后，相关确认失效并需重新审核。旧交付文件保留原始版本，重复导出不会覆盖。

DOCX 可独立导出；PDF 和含 PDF 的交付包使用 Docker 镜像内的 LibreOffice 与 Python UNO 更新目录并分页。普通 Windows Python 环境如果没有 UNO，请使用 Compose 部署执行 PDF 导出。生成后应人工检查页码、图表、签章和投标文件要求。

## 测试

```powershell
$env:PYTHONPATH = "backend"
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m unittest discover -s backend\tests_v2 -v
cd frontend
npm run build
```
