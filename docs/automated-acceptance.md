# 自动验收与运行检查

## 适用范围

本手册用于重复执行不依赖人工业务签审的技术验收。自动验收会修复可确定判定的错误负样本、运行混合检索评测、校验审计链并按阈值返回退出码；它不会把 AI 生成的数据提升为黄金数据，也不会代替高风险知识和正式交付签审。

## 一键检索验收

服务启动且模型配置可用后执行：

```powershell
docker compose exec -T app python /app/backend/scripts_v2/run_automated_acceptance.py `
  --dataset live-20260809-v2 `
  --skip-ai-review
```

新生成的白银集首次运行时去掉 `--skip-ai-review`。脚本依次执行 AI 独立复核、困难负样本探测与重建、混合检索评测和审计链校验。满足下列条件时退出码为 0：

- `Recall@10 >= 0.80`
- `NDCG@10 >= 0.75`
- 困难负样本拒绝率 `>= 0.80`
- 混合检索相对 FTS 在 Recall、MRR 或负样本拒绝率中至少一项有正向提升
- 审计哈希链有效

调试阶段可以追加 `--allow-below-target` 查看报告，但该参数不得用于验收放行。

## 完整技术回归

```powershell
docker compose exec -T app python -m unittest discover -s /app/backend/tests_v2 -v

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

端到端用例从进程环境读取凭据，不输出或提交密码。

## 监控

```powershell
docker compose --profile monitoring up -d
```

- 应用：`http://127.0.0.1:8876`
- Prometheus：`http://127.0.0.1:9090`
- Grafana：`http://127.0.0.1:3000`
- 指标端点：`http://127.0.0.1:8876/metrics`

Grafana 自动装载 `Bid Writer Overview` 面板，覆盖任务积压、AI 运行与 Token、模型耗时、检索延迟、已发布知识、存储健康和审计链状态。

## 备份恢复验收

```powershell
.\deploy\backup.ps1
.\deploy\restore.ps1 -BackupPath .\backups\YYYYMMDD-HHMMSS
```

恢复前必须确认目标为空环境。恢复后至少核对 Alembic 版本、知识数量、评测数据、审计事件、Qdrant 快照和 MinIO 对象；正式环境恢复需按 `docs/data-migration-and-backup.md` 执行停机和回滚检查。

## 人工边界

以下结论不能由自动验收替代：

- 中高风险知识、模型分歧、来源不匹配和冲突关系的业务裁决。
- 自动发布批次的来源忠实性与跨项目适用性抽检。
- 将白银问题提升为黄金问题。
- 真实项目的高风险 Claim、承诺、否决项以及 DOCX/PDF 最终签审。
