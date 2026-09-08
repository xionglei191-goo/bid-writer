# Pi 接手任务书：知识库全量整理与正式发布收口

版本：2026-08-24  
接手对象：Pi  
工作目录：`F:\1600 套技术标\03_生产系统\bid_writer_app`  
代码分支：`agent/ai-private-platform`  
当前提交：`ef9b4e5 isolate service health windows by stage`

## 1. 任务目标

接续现有知识库全量收口任务 `run_id=4`，完成剩余资料标准化、OCR、AI 拆解、独立复核、发布、索引构建、检索评测和最终验收报告。

最终目标不是把所有资料都发布，而是使每一条源记录都有可审计终态，并使全部具备正式复用资格的知识完成发布。重复、损坏、不支持、证据不足、不可复用或未获授权的资料应以明确原因终结，不得为追求发布数量降低门槛。

最终分别报告：

- `corpus_terminal_rate=100%`：11,664 条源记录全部闭环；
- `formal_eligible_publication_rate=100%`：全部正式可用知识均已复核并发布；
- `manual_legal_open`：只统计仍需用户处理的版权、保密、法律、密码或替换文件事项；
- `legal_clearance_ready`：仅当上述人工事项为 0 时为 `true`。

## 2. 接手时的持久化快照

最后有效快照时间：2026-08-13 23:43 左右（北京时间）。2026-08-13 之后服务一直停止，2026-08-24 检查时 Docker Desktop 也未运行，因此没有后台继续处理。

| 项目 | 数量或状态 |
|---|---:|
| 源记录总数 | 11,664 |
| 已终态 | 9,549 |
| 全资料闭环率 | 81.87% |
| 未终态 | 2,115 |
| AI 待处理 | 2,089 |
| AI 重试 | 21 |
| OCR 待处理 | 4 |
| OCR 重试 | 1 |
| 已发布知识 | 138 |
| 当前运行人工待办 | 49 |
| 当前运行已解决人工事项 | 240 |
| 运行状态 | `paused` |
| 暂停阶段 | `ai` |
| 暂停原因 | 外部模型接口连续 `ReadTimeout`，触发熔断 |

停止前 AI 最近 20 次服务结果失败率为 30%，连续超时 4 次；任务已按策略自动暂停。49 项人工待办主要为素材授权或合规事项，不应当由 AI 假冒用户作出授权。

旧运行 `run_id=1~3` 已因操作恢复被取消，仅用于审计。不得恢复旧运行，不得重复创建全库快照；应继续 `run_id=4`。

## 3. 已完成的系统能力

- PostgreSQL、Qdrant、MinIO 和知识库备份及恢复演练已完成；
- 全库运行、运行条目、结构化复核决策和治理待办模型已实现；
- DOC/DOCX/PDF、扫描 PDF、压缩包和素材治理路径已实现；
- 旧版 DOC 已加入 LibreOffice 与 antiword 回退；异常 DOCX 已加入原始 XML 回退；
- 精确/近似去重、数值冲突保护、来源回挂和可审计处置已实现；
- AI 抽取、独立复核、技术修订、高风险复核、最终裁决及 AI 身份审计已实现；
- OCR/AI 分阶段熔断、恢复探针、短任务链和阶段并发控制已实现；
- AI 实际流水线并发限制为 1，OCR 为 1，标准化为 2；
- 管理接口和“全库收口”页面已实现；
- 后端最后一次完整回归为 89 项全部通过；
- 最新代码已推送至远端分支。

## 4. 数据安全和不可突破的约束

1. 原始资料只读，不删除、不移动、不覆盖。
2. 不执行 `docker compose down -v`，不删除 Docker volume、数据库、MinIO 对象、Qdrant 集合、旧索引或历史审计记录。
3. 不对 `corpus_run_items`、`source_files`、`knowledge_publications` 等表执行未经精确条件验证的批量 `UPDATE` 或 `DELETE`。
4. 不手工把未处理条目改成 `terminal`，不手工把运行状态改成 `completed`，所有终态必须由流水线及审计记录产生。
5. 不新建全库任务替代 `run_id=4`，除非已完成新备份、查明现有运行不可恢复，并记录恢复理由与对账结果。
6. 不伪造人工签审、版权授权、保密解密、法律结论、密码或替换文件。
7. AI 决策必须记录 `actor_type=ai`、模型、提示词版本、置信度和运行 ID，不使用“技术负责人”等人工身份。
8. 未获授权的历史照片、AI 场景图和来源不明素材不得进入正式检索。
9. 不把失败、重试、待复核或未授权资料计入正式可用发布率。
10. 不将 `.env`、密码、API Key、数据库备份或客户资料提交到 Git。

现有恢复备份：

- 路径：`F:\1600 套技术标\03_生产系统\bid_writer_app\backups\operator-recovery-20260813-012643\postgres.dump`
- SHA-256：`DF551FE7CCB2463F456764B630FAA9608F983EDDE8A8729603EA754A7757F269`

该备份用于灾难恢复，不应直接覆盖当前持续更新后的生产库。恢复前必须另做最新备份，并在隔离环境验证。

## 5. 启动与恢复步骤

### 5.1 启动前检查

1. 启动 Docker Desktop，等待 Linux Engine 可用。
2. 进入工作目录并确认分支及工作树：

```powershell
Set-Location 'F:\1600 套技术标\03_生产系统\bid_writer_app'
git branch --show-current
git status --short
git log -1 --oneline
```

预期分支为 `agent/ai-private-platform`，最新提交为 `ef9b4e5`。若工作树有用户改动，先识别并保留，禁止清除或覆盖。

3. 检查 `.env` 存在，不输出任何密钥。当前本地运行模型应为 `gpt-5.6-terra`；此前 `gpt-5.6-luna` 在局域网模型代理返回 404。不要用 `.env.example` 覆盖 `.env`。
4. 检查磁盘剩余空间满足“至少 100 GB 且不少于 10%”的运行门槛。

### 5.2 启动基础服务

```powershell
docker compose up -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8876/api/health/ready | ConvertTo-Json -Depth 5
```

应确认 app、worker、postgres、redis、qdrant、minio、embedding 均健康。监控组件按需启动：

```powershell
docker compose --profile monitoring up -d
```

### 5.3 恢复前只读对账

启动后先查询，不立即恢复：

```powershell
$sql = @'
SELECT id,status,stage,progress,pause_reason,counters_json,checkpoint_json,updated_at
FROM corpus_runs WHERE id=4;
SELECT stage,status,count(*)
FROM corpus_run_items WHERE run_id=4
GROUP BY stage,status ORDER BY stage,status;
SELECT count(*) AS active_ai
FROM knowledge_ai_pipeline_runs WHERE status='running';
SELECT status,count(*)
FROM governance_tasks WHERE run_id=4 GROUP BY status ORDER BY status;
'@
docker compose exec -T postgres psql -U bid_writer -d bid_writer -c $sql
```

先确认总数仍为 11,664、终态数不回退、活动 AI 流水线没有异常堆积。若与本任务书快照不一致，以数据库为准并记录差异。

### 5.4 模型服务恢复确认

恢复任务前，通过系统现有最小生成探针或一条无客户敏感内容的最小请求确认 `gpt-5.6-terra` 能在超时限制内响应。不得将原始客户内容用于临时连通性测试。

若模型仍连续超时：

- 保持 `run_id=4` 暂停；
- 检查局域网代理 `http://192.168.31.246:8080` 的可达性和负载；
- 不提高 AI 并发；
- 不通过扩大超时无限占用 Worker；
- 服务恢复后再续跑。

### 5.5 恢复现有任务

使用管理员登录系统，在“知识工程 → 全库收口”选择 `run_id=4`，点击“恢复”；或以已认证管理员会话调用：

```text
POST /api/knowledge/corpus-runs/4/resume
```

不要调用 `POST /api/knowledge/corpus-runs`，因为这会创建新运行。

恢复后 5~15 分钟内确认：

- `corpus_runs.status=running`；
- 终态数持续增加；
- `knowledge_ai_pipeline_runs.status=running` 最多 1 条；
- AI/OCR 分阶段错误窗口正常；
- 没有相同来源被重复发布；
- Worker 无持续崩溃或内存异常。

## 6. 执行计划

### 阶段 A：恢复和稳定性观察

目标：安全恢复 `run_id=4`，证明检查点、短任务链、熔断和自动重试均有效。

验收：连续完成至少 3 个 AI 批次，终态数单调增加，AI 并发不超过 1，最近 20 次服务失败率不超过 20%，无连续 5 次服务错误。

### 阶段 B：清空 OCR 和非 AI 尾项

目标：将剩余 5 个 OCR 条目及其他非 AI 条目全部处理为成功、重复或有理由排除。

处理原则：

- OCR 任务提交队列满时按 1、5、15 分钟重试；
- SSL EOF、服务限流等外部错误不得直接判为资料损坏；
- 同一文件技术性重试 3 次仍无法读取，且已排除服务故障后，才可标记 `unreadable_excluded`；
- 加密资料只生成密码/替换文件人工事项，不破解、不伪造凭据。

验收：`ocr:pending|running|retrying=0`，`normalize:pending|running|retrying=0`，每条均有来源哈希、解析器版本和终态原因。

### 阶段 C：完成剩余 AI 加工与自动复核

目标：清空约 2,110 个 AI 待处理/重试条目，不遗留技术人工复核队列。

执行要求：

- 先去重、后调用模型；
- 每批最多按现有安全批量运行，不提高单路 AI 并发；
- 低风险两阶段置信度均不低于 0.92；
- 中风险两阶段置信度均不低于 0.95；
- 高风险两次非缓存独立复核及最终裁决均不低于 0.97；
- 数值、规范编号、适用条件和来源引文必须逐项一致；
- 未达门槛时自动修订一次，再失败则以 `insufficient_evidence` 或 `not_reusable` 终结；
- 项目名称、人员、电话、无依据参数、占位符、绝对承诺、测试内容和来源冲突一律禁止发布；
- 旧规则抽取知识保留审计，若被新知识覆盖则标记 `superseded`，不删除。

对 `ReadTimeout`、429、503 等外部服务问题，应让阶段熔断和恢复探针处理，不得把相关来源误判为不可复用。

验收：`ai:pending|running|retrying=0`，技术异常队列为 0；每条可复用知识具备原文锚点、版本、AI 复核和发布记录；每条排除均有明确、可审计原因。

### 阶段 D：索引构建与检索评测

目标：在全资料终态后构建候选 BM25/Qdrant 索引，通过评测后再激活；失败时保留上一活动索引。

正式验收使用本任务的严格阈值：

- Recall@10 不低于 90%；
- MRR 不低于 80%；
- NDCG@10 不低于 80%；
- 困难负样本拒绝率不低于 85%；
- 各主要行业和知识类型 Recall@10 不低于 85%；
- 每条已发布知识至少有直接问法和同义问法；
- 聚类补充困难负样本。

注意：`docs/automated-acceptance.md` 当前脚本说明中的 80%/75%/80% 是较低的通用技术门槛，不能代替本次正式验收阈值。必要时应补充配置或校验代码，使最终报告按上述严格门槛判断，不能用 `--allow-below-target` 放行。

验收：活动索引知识数量和内容哈希与发布表完全一致；未通过评测时不得激活候选索引，也不得将运行手工改为完成。

### 阶段 E：人工事项治理

目标：将 49 项人工事项按来源批次合并、去重并提供清晰清单。

Pi 可以完成：来源识别、重复合并、公开授权证据核对、风险说明和建议处置。Pi 不可以替用户完成：版权授权、保密解密、具有约束力的法律责任确认、密码提供或替换文件决定。

未获授权内容必须保持归档且不进入检索。即使人工事项未归零，只要相关内容已被隔离，仍可实现 `corpus_terminal_rate=100%` 和 `formal_eligible_publication_rate=100%`；但必须报告 `legal_clearance_ready=false`。

### 阶段 F：完整测试和最终交付

后端：

```powershell
docker compose exec -T app python -m unittest discover -s /app/backend/tests_v2 -v
```

前端：

```powershell
Set-Location frontend
npm ci
npm run build

$cfg = @{}
Get-Content ..\.env | ForEach-Object {
  if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
    $cfg[$matches[1].Trim()] = $matches[2].Trim().Trim('"')
  }
}
$env:BID_WRITER_E2E_USERNAME = $cfg['BID_WRITER_BOOTSTRAP_ADMIN']
$env:BID_WRITER_E2E_PASSWORD = $cfg['BID_WRITER_BOOTSTRAP_PASSWORD']
npm run test:e2e
```

测试输出不得打印或提交凭据。最终还要验证健康端点、OpenAPI 标题、Prometheus 指标、备份可恢复性、审计哈希链和活动索引一致性。

## 7. 最终交付物

必须生成：

- `F:\1600 套技术标\04_交付与报告\质量验收\knowledge\knowledge_completion.json`
- `F:\1600 套技术标\04_交付与报告\质量验收\knowledge\knowledge_completion.md`
- 全量来源处置清单；
- 正式发布清单；
- 排除清单及原因；
- 人工事项清单；
- 交付文件 SHA-256 清单；
- 索引版本、发布表数量/哈希一致性结果；
- 检索评测数据集、指标和各主要分段结果；
- 后端测试、前端构建和 Playwright 回归结果。

报告必须如实显示：

- `corpus_terminal_rate`；
- `formal_eligible_publication_rate`；
- `manual_legal_open`；
- `legal_clearance_ready`；
- 正式发布知识数量；
- 各终态原因数量；
- 索引一致性和评测结果；
- 未处理技术异常数量。

## 8. 完成判定

只有同时满足以下条件，Pi 才能宣布“知识库整理和正式可用内容达到 100%”：

1. 11,664 条源记录全部对账，`corpus_terminal_rate=100%`；
2. 所有正文资料均已标准化、判定重复或有理由排除；
3. 全部素材完成治理；
4. 全部可复用知识均有来源锚点、版本、AI 复核和发布记录；
5. `formal_eligible_publication_rate=100%`；
6. 未处理技术异常和技术人工复核任务均为 0；
7. 已发布内容中的占位符、个人信息、测试内容、无依据承诺和未批准视觉素材均为 0；
8. 活动索引与发布表数量和内容哈希一致；
9. 检索评测全部达到本任务严格阈值；
10. 最终报告、清单和文件哈希全部生成且可读取；
11. 后端、前端构建和 Playwright 回归通过。

人工授权事项可以保持未解决，但必须隔离相关内容并单列；此时应报告 `legal_clearance_ready=false`，不得伪造授权归零。

## 9. 异常处理与升级规则

| 情况 | 处理方式 |
|---|---|
| AI/OCR 连续 5 次服务错误或最近 20 次失败率超过 20% | 保持阶段暂停，执行最小恢复探针，服务恢复后续跑 |
| 磁盘低于 100 GB 或低于 10% | 立即暂停，不删除原始资料、备份或生产数据；先扩容或安全迁移缓存 |
| 同一来源反复重开 | 检查来源处置、流水线和发布审计的幂等条件，不直接改终态 |
| 模型结构化输出失败 | 使用现有兼容解析与自动修订；仍失败则按证据不足终结，不进入技术人工队列 |
| 索引评测不达标 | 保留旧活动索引，修复评测覆盖、知识质量或检索配置后重建 |
| 数据总数、终态数或发布数异常回退 | 立即停止 Worker，做最新备份，进行只读对账，不执行批量修复 SQL |
| 需要版权、保密、法律责任、密码或替换文件 | 生成或保留人工事项，相关内容不发布，提交用户决定 |

## 10. Pi 的阶段汇报格式

每次阶段汇报至少包含：

```text
运行ID：4
运行状态/阶段：
终态数 / 11,664：
corpus_terminal_rate：
剩余 normalize / OCR / AI：
正式发布知识数：
formal_eligible_publication_rate：
技术异常未处理数：
manual_legal_open：
活动索引版本及一致性：
Recall@10 / MRR / NDCG@10 / 困难负样本拒绝率：
本阶段新增排除原因：
当前阻塞及下一步：
```

不得只汇报 `corpus_runs.progress`。该字段是阶段进度；全资料完成率必须以终态数除以 11,664 计算。

## 11. 给 Pi 的直接执行指令

> 从 `F:\1600 套技术标\03_生产系统\bid_writer_app` 的 `agent/ai-private-platform` 分支接手现有知识库全量收口。先启动 Docker Desktop和服务，做只读对账并确认模型恢复，再通过管理员界面恢复 `run_id=4`。不得新建运行、删除数据、绕过评测门槛或伪造授权。持续处理剩余 2,115 条资料，直到 11,664 条全部具有可审计终态；完成严格检索评测、索引一致性验证、完整测试和最终报告。法律/版权/密码事项只整理证据并保留人工待办，相关内容不得进入正式检索。只有本任务书第 8 节全部满足时，才能宣布正式可用内容达到 100%。
