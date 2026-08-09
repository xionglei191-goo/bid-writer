# 单租户私有化部署

## 安装

要求Docker Desktop或Docker Engine支持Compose v2，建议至少8核CPU、32GB内存和30GB可用空间；NVIDIA GPU为可选项。

```powershell
Copy-Item .env.example .env
# 编辑.env中的密码、会话密钥和三个宿主机目录
.\deploy\install.ps1
```

默认地址为`http://127.0.0.1:8765`。首次启动使用`.env`中的管理员账号；登录后应立即创建日常账号。监控通过`docker compose --profile monitoring up -d`启用。

## 自动验收与监控

技术回归、检索门槛、监控地址和人工签审边界见`docs/automated-acceptance.md`。当前监控栈会自动装载 `Bid Writer Overview` Grafana 面板；应用、Prometheus 和 Grafana 默认分别使用 8765、9090 和 3000 端口。

## 升级与回退

`.\deploy\upgrade.ps1`先生成完整备份，再拉取镜像、重建应用并运行Alembic。数据库迁移不自动降级；回退使用升级前备份和对应代码版本。

## 健康检查

- `/api/health/live`：Web进程存活。
- `/api/health/ready`：数据库和对象存储可用。
- `/api/search/status`：索引、embedding和Qdrant状态。
- `/api/audit/verify`：审计哈希链完整性。
- `/metrics`：Prometheus指标。

## 模型

`deploy/download-models.ps1`预下载BGE-M3和BGE reranker。无GPU时设置`BID_WRITER_EMBEDDING_DEVICE=cpu`并保持worker低并发；模型替换后必须重建索引并运行黄金评测，旧索引在新索引激活前继续服务。

默认`HF_ENDPOINT=https://huggingface.co`。网络无法稳定访问官方地址时，可只在本机`.env`改为可信镜像，例如`https://hf-mirror.com`；模型缓存保存在Docker卷中，镜像地址和缓存文件都不提交仓库。

## 端到端检查

应用运行后可使用系统Chrome执行：

```powershell
$env:BID_WRITER_E2E_USERNAME = "BID_WRITER_BOOTSTRAP_ADMIN 的值"
$env:BID_WRITER_E2E_PASSWORD = "BID_WRITER_BOOTSTRAP_PASSWORD 的值"
Set-Location frontend
npm run test:e2e
```

用例覆盖登录、管理员角色、设置页运行组件、后台任务、检索评测工作台以及390像素手机宽度。密码只从进程环境读取。

## 故障处理

- AI任务失败：在任务中心查看错误代码并重试，不会写入半成品知识。
- 模型显示“需检查”：核对`.env`中的模型地址、模型名、协议和API Key，重启app/worker后重试失败任务。401通常对应凭据无效；不得为了继续流程而手工改写候选状态或绕过独立裁决。
- 新索引失败：系统继续使用上一active索引。
- MinIO不可用：ready状态变为degraded，正式交付任务失败并可重试。
- 模型不可用：生成和索引任务失败；系统不生成无证据替代正文。
- 自动发布抽检失败：批次知识撤回，候选回到人工复核并触发索引重建。
