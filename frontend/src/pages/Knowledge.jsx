import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Award, BookCheck, BrainCircuit, Check, Eye, FileSearch, FlaskConical, Play, RefreshCw, ScanSearch, Search, Send, ShieldCheck, WandSparkles, X } from "lucide-react";
import { api, post, waitForJob } from "../api";
import { BusyButton, Empty, Metric, Notice, PageHeader, Status, Tabs } from "../components";

const tabItems = [
  { key: "corpus", label: "全库收口" }, { key: "sources", label: "原始资料" }, { key: "jobs", label: "处理队列" }, { key: "documents", label: "标准文档" }, { key: "ai-pipeline", label: "AI加工" },
  { key: "units", label: "知识单元" }, { key: "reviews", label: "审核发布" }, { key: "publications", label: "正式知识" }, { key: "search", label: "检索测试" }, { key: "evaluation", label: "评测集" },
];

export default function Knowledge({ initialTab, onChanged }) {
  const [tab, setTab] = useState(initialTab || "sources");
  const [metrics, setMetrics] = useState({});
  function selectTab(key) { setTab(key); location.hash = `#/knowledge/${key}`; }
  async function loadMetrics() { setMetrics(await api("/api/knowledge/metrics")); }
  useEffect(() => { setTab(initialTab || "sources"); }, [initialTab]);
  useEffect(() => { loadMetrics().catch(() => {}); }, [tab]);
  return <>
    <PageHeader eyebrow="知识工程中心" title="本地知识资产" description="只有审核并发布的内容可以进入技术标生成链路。" />
    <section className="metric-grid five"><Metric label="已扫描" value={metrics.sources} /><Metric label="重复文件" value={metrics.duplicates} /><Metric label="标准文档" value={metrics.documents} /><Metric label="待审核" value={metrics.review_pending} tone="warning" /><Metric label="已发布" value={metrics.published} tone="success" /></section>
    <Tabs items={tabItems} active={tab} onChange={selectTab} />
    {tab === "corpus" && <CorpusCompletion onChanged={() => { loadMetrics(); onChanged?.(); }} />}
    {tab === "sources" && <Sources onChanged={() => { loadMetrics(); onChanged?.(); }} />}
    {tab === "jobs" && <Jobs onChanged={() => { loadMetrics(); onChanged?.(); }} />}
    {tab === "documents" && <Documents />}
    {tab === "ai-pipeline" && <AiKnowledgePipeline onChanged={loadMetrics} />}
    {tab === "units" && <Units mode="all" onChanged={loadMetrics} />}
    {tab === "reviews" && <Units mode="review" onChanged={loadMetrics} />}
    {tab === "publications" && <Publications onChanged={loadMetrics} />}
    {tab === "search" && <KnowledgeSearch />}
    {tab === "evaluation" && <RetrievalEvaluationWorkspace />}
  </>;
}

function CorpusCompletion({ onChanged }) {
  const [run, setRun] = useState(null); const [completion, setCompletion] = useState(null); const [tasks, setTasks] = useState([]); const [busy, setBusy] = useState(""); const [message, setMessage] = useState("");
  async function load(runId) {
    const nextCompletion = await api(`/api/knowledge/completion${runId ? `?run_id=${runId}` : ""}`);
    setCompletion(nextCompletion);
    const id = runId || nextCompletion.run_id;
    if (id) setRun(await api(`/api/knowledge/corpus-runs/${id}`));
    setTasks(await api("/api/knowledge/manual-tasks?status=open&limit=500"));
  }
  async function start() { setBusy("start"); try { const next = await post("/api/knowledge/corpus-runs", {}); setRun(next); setMessage("全库收口任务已启动，原始库保持只读，加工结果按检查点持续写入。"); await load(next.id); onChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  async function control(action) { if (!run) return; setBusy(action); try { const next = await post(`/api/knowledge/corpus-runs/${run.id}/${action}`, {}); setRun(next); setMessage(action === "pause" ? "任务已暂停。" : action === "resume" ? "任务已恢复。" : "任务已取消。"); await load(run.id); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  async function resolve(task, action) { const resolution = window.prompt(action === "approve" ? "请输入授权、解密或法律确认依据；批准后相关内容才会进入后续流水线：" : "请输入排除依据；相关内容将保持不进入正式检索："); if (!resolution) return; setBusy(`task-${task.id}`); try { await post(`/api/knowledge/manual-tasks/${task.id}/resolve`, { action, resolution }); await load(run?.id); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  useEffect(() => { if (!run || run.status !== "running") return undefined; const timer = window.setInterval(() => load(run.id).catch(() => {}), 5000); return () => window.clearInterval(timer); }, [run?.id, run?.status]);
  const counters = run?.counters || {}; const reasons = Object.entries(counters.by_reason || {}).sort((left, right) => right[1] - left[1]);
  return <>
    <section className="metric-grid five"><Metric label="资料闭环率" value={`${Math.round((completion?.corpus_terminal_rate || 0) * 10000) / 100}%`} tone={completion?.corpus_terminal_rate === 1 ? "success" : "warning"} /><Metric label="正式发布率" value={`${Math.round((completion?.formal_eligible_publication_rate || 0) * 10000) / 100}%`} tone={completion?.formal_eligible_publication_rate === 1 ? "success" : "warning"} /><Metric label="剩余资料" value={counters.remaining ?? completion?.corpus_total ?? 0} /><Metric label="正式知识" value={completion?.published_total ?? 0} tone="success" /><Metric label="人工事项" value={completion?.manual_legal_open ?? 0} tone={completion?.manual_legal_open ? "warning" : "success"} /></section>
    <section className="panel"><div className="toolbar"><div><strong>全库收口运行</strong><span className="toolbar-note">标准化2路、OCR 1路、AI加工1路；服务失败率和磁盘空间自动熔断。</span></div><div className="actions"><button className="secondary icon-only" title="刷新" onClick={() => load(run?.id)}><RefreshCw size={17} /></button>{!run && <BusyButton busy={busy === "start"} onClick={start}><Play size={16} />启动全库收口</BusyButton>}{run?.status === "running" && <BusyButton busy={busy === "pause"} className="secondary" onClick={() => control("pause")}>暂停</BusyButton>}{run?.status === "paused" && <BusyButton busy={busy === "resume"} onClick={() => control("resume")}><Play size={16} />恢复</BusyButton>}</div></div>
      {message && <Notice type={message.includes("失败") || message.includes("无权") ? "danger" : "info"}>{message}</Notice>}
      {run ? <><div className="corpus-progress"><div><strong>运行 #{run.id} · {run.stage}</strong><Status value={run.status} /></div><div className="progress wide"><span style={{ width: `${run.progress || 0}%` }} /></div><small>{run.progress || 0}% · 剩余 {counters.remaining ?? 0} 项{run.pause_reason ? ` · 熔断/暂停原因：${run.pause_reason}` : ""}</small></div><div className="table-wrap"><table><thead><tr><th>终态原因</th><th>数量</th></tr></thead><tbody>{reasons.map(([reason, count]) => <tr key={reason}><td><Status value={reason} /></td><td>{count}</td></tr>)}</tbody></table>{!reasons.length && <Empty title="尚未形成终态统计" />}</div></> : <Empty title="尚未创建全库收口任务" detail="启动前应已完成数据库、向量库、对象存储和知识目录备份。" />}
    </section>
    <section className="panel"><div className="toolbar"><div><strong>必须人工处理</strong><span className="toolbar-note">仅保留版权授权、保密解密、法律责任和密码/替换文件事项。</span></div><span>{tasks.length} 项</span></div><div className="table-wrap"><table><thead><tr><th>类型</th><th>事项</th><th>来源</th><th>操作</th></tr></thead><tbody>{tasks.map((task) => <tr key={task.id}><td><Status value={task.task_type} /></td><td><strong>{task.title}</strong><small>{task.message}</small></td><td>{task.file_name || "批次事项"}<small>{task.relative_path || ""}</small></td><td><div className="row-actions"><BusyButton busy={busy === `task-${task.id}`} onClick={() => resolve(task, "approve")}>批准</BusyButton><BusyButton busy={busy === `task-${task.id}`} className="secondary" onClick={() => resolve(task, "exclude")}>排除</BusyButton></div></td></tr>)}</tbody></table>{!tasks.length && <Empty title="没有待人工处理事项" />}</div></section>
  </>;
}

function Sources({ onChanged }) {
  const [data, setData] = useState({ items: [], total: 0 });
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(300);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function load() { setData(await api(`/api/knowledge/sources?limit=100&status=${encodeURIComponent(status)}&query=${encodeURIComponent(query)}`)); }
  async function scan() { setBusy(true); try { const result = await post("/api/knowledge/sources/scan", { limit, expand_archives: true }); setMessage(`扫描${result.scanned}个文件，新增${result.created}个，识别重复${result.duplicates}个。`); await load(); onChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  useEffect(() => { load().catch(() => {}); }, [status]);
  return <section className="panel"><div className="toolbar"><div className="filters"><input placeholder="文件名或路径" value={query} onChange={(event) => setQuery(event.target.value)} /><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option><option value="discovered">待处理</option><option value="duplicate">重复</option><option value="asset">素材</option><option value="metadata_only">仅登记</option></select><button className="secondary icon-only" title="查询" onClick={load}><Search size={17} /></button></div><div className="actions"><label className="inline-field">本次扫描<input type="number" min="1" value={limit} onChange={(event) => setLimit(Number(event.target.value))} /></label><BusyButton busy={busy} onClick={scan}><ScanSearch size={16} />扫描原始库</BusyButton></div></div>{message && <Notice>{message}</Notice>}<div className="table-wrap"><table><thead><tr><th>文件</th><th>行业</th><th>格式</th><th>大小</th><th>状态</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}><td><strong>{item.file_name}</strong><small>{item.relative_path}</small></td><td>{item.industry}</td><td>{item.extension || "-"}</td><td>{(item.size_bytes / 1024 / 1024).toFixed(1)} MB</td><td><Status value={item.status} /></td></tr>)}</tbody></table>{!data.items.length && <Empty title="尚未扫描原始资料" />}</div><div className="table-footer">显示 {data.items.length} / {data.total}</div></section>;
}

function Jobs({ onChanged }) {
  const [jobs, setJobs] = useState([]); const [busyId, setBusyId] = useState(null); const [message, setMessage] = useState("");
  async function load() { setJobs(await api("/api/knowledge/jobs?limit=200")); }
  async function create() { const result = await post("/api/knowledge/jobs", { limit: 100 }); setMessage(`已创建${result.created}个任务。`); await load(); }
  async function runBatch() { setBusyId("batch"); try { const result = await post("/api/knowledge/jobs/run-batch", { limit: 20 }); setMessage(`批量处理${result.processed}项，完成${result.completed}项，等待OCR ${result.waiting_ocr}项，失败${result.failed}项。`); await load(); onChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusyId(null); } }
  async function run(job, action = "run") { setBusyId(job.id); try { const result = await post(`/api/knowledge/jobs/${job.id}/${action}`, {}); setMessage(result.status === "completed" ? `${job.file_name}处理完成。` : result.error || `任务状态：${result.status}`); await load(); onChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusyId(null); } }
  useEffect(() => { load().catch(() => {}); }, []);
  return <section className="panel"><div className="toolbar"><div><strong>标准化任务</strong><span className="toolbar-note">失败任务可重试，扫描PDF进入OCR队列。</span></div><div className="actions"><button className="secondary icon-only" title="刷新" onClick={load}><RefreshCw size={17} /></button><BusyButton busy={busyId === "batch"} className="secondary" onClick={runBatch}><Play size={16} />批量执行20项</BusyButton><button onClick={create}><FileSearch size={16} />创建任务</button></div></div>{message && <Notice>{message}</Notice>}<div className="table-wrap"><table><thead><tr><th>资料</th><th>步骤</th><th>进度</th><th>状态</th><th>操作</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.id}><td><strong>{job.file_name}</strong><small>{job.industry} · {job.extension}</small></td><td>{job.current_step || "queued"}</td><td><div className="progress"><span style={{ width: `${job.progress}%` }} /></div></td><td><Status value={job.status} />{job.error_message && <small className="error-text">{job.error_message}</small>}</td><td><div className="row-actions">{["pending", "failed"].includes(job.status) && <BusyButton busy={busyId === job.id} className="secondary" onClick={() => run(job, job.status === "failed" ? "retry" : "run")}><Play size={15} />{job.status === "failed" ? "重试" : "执行"}</BusyButton>}{job.status === "waiting_ocr" && <BusyButton busy={busyId === job.id} onClick={() => run(job, "ocr")}><ScanSearch size={15} />OCR</BusyButton>}{["pending", "failed", "waiting_ocr"].includes(job.status) && <button className="secondary" onClick={() => run(job, "pause")}>暂停</button>}{job.status === "paused" && <button className="secondary" onClick={() => run(job, "resume")}>恢复</button>}</div></td></tr>)}</tbody></table>{!jobs.length && <Empty title="暂无处理任务" />}</div></section>;
}

function Documents() {
  const [data, setData] = useState({ items: [], total: 0 });
  useEffect(() => { api("/api/knowledge/documents?limit=200").then(setData).catch(() => {}); }, []);
  return <section className="panel"><div className="table-wrap"><table><thead><tr><th>标准文档</th><th>行业</th><th>解析器</th><th>章节</th><th>字符</th><th>状态</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.id}><td><strong>{item.title}</strong><small>{item.relative_path}</small></td><td>{item.industry}</td><td>{item.parser}</td><td>{item.section_count}</td><td>{item.char_count.toLocaleString()}</td><td><Status value={item.status} /></td></tr>)}</tbody></table>{!data.items.length && <Empty title="暂无标准文档" detail="处理任务完成后会在这里形成统一Markdown。" />}</div></section>;
}

function AiKnowledgePipeline({ onChanged }) {
  const [documents, setDocuments] = useState([]); const [metrics, setMetrics] = useState({}); const [candidates, setCandidates] = useState([]); const [tasks, setTasks] = useState([]); const [runs, setRuns] = useState([]); const [selectedDocumentId, setSelectedDocumentId] = useState(""); const [selectedCandidate, setSelectedCandidate] = useState(null); const [maxCandidates, setMaxCandidates] = useState(12); const [reviewer, setReviewer] = useState("技术负责人"); const [busy, setBusy] = useState(""); const [message, setMessage] = useState("");
  async function load() {
    const [documentData, nextMetrics, nextCandidates, nextTasks, nextRuns] = await Promise.all([
      api("/api/knowledge/documents?limit=200"), api("/api/knowledge-ai/metrics"), api("/api/knowledge-ai/candidates?limit=200"), api("/api/knowledge-ai/tasks?status=open&limit=200"), api("/api/knowledge-ai/runs?limit=30"),
    ]);
    setDocuments(documentData.items); setMetrics(nextMetrics); setCandidates(nextCandidates); setTasks(nextTasks); setRuns(nextRuns); setSelectedDocumentId((current) => current || String(documentData.items[0]?.id || ""));
  }
  async function processDocument() { if (!selectedDocumentId) return; setBusy("process"); try { const queued = await post("/api/knowledge-ai/runs", { document_id: Number(selectedDocumentId), max_candidates: maxCandidates, background: true }); const result = await waitForJob(queued, { onProgress: (job) => setMessage(`${job.stage} · ${job.progress}%`) }); setMessage(`AI加工完成：${result.candidate_count || 0}条候选，${result.ready_count || 0}条可接收，覆盖率${Math.round((result.coverage_rate || 1) * 100)}%。`); await load(); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  async function reviewCandidate(item, action) { setBusy(`candidate-${item.id}`); try { await post(`/api/knowledge-ai/candidates/${item.id}/review`, { action, reviewer, notes: action === "accept" ? "已核对来源与风险，接收为待审核知识" : "候选不适合进入知识库" }); setMessage(action === "accept" ? "候选已进入知识单元审核队列。" : "候选已退回，关联异常已关闭。"); await load(); onChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  async function acceptReady() { setBusy("accept-ready"); try { const result = await post("/api/knowledge-ai/candidates/accept-ready", { reviewer, limit: 100 }); setMessage(`已批量接收${result.accepted}条通过复核的候选，后续可在“审核发布”中签审。`); await load(); onChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  const riskLabels = { low: "低", medium: "中", high: "高" };
  const latestRun = runs[0];
  return <>
    <section className="metric-grid five"><Metric label="AI候选" value={metrics.candidates} /><Metric label="可批量接收" value={metrics.ready} tone="success" /><Metric label="异常候选" value={metrics.needs_review} tone="warning" /><Metric label="开放待办" value={metrics.open_tasks} tone="warning" /><Metric label="已接收" value={metrics.accepted} /></section>
    <section className="panel">
      <div className="toolbar"><div className="filters"><select value={selectedDocumentId} onChange={(event) => setSelectedDocumentId(event.target.value)}><option value="">选择标准文档</option>{documents.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select><label className="inline-field">最多候选<input type="number" min="1" max="20" value={maxCandidates} onChange={(event) => setMaxCandidates(Number(event.target.value))} /></label><label className="inline-field">审核人<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label></div><div className="actions"><BusyButton busy={busy === "process"} onClick={processDocument} disabled={!selectedDocumentId}><BrainCircuit size={16} />AI拆解并复核</BusyButton><BusyButton busy={busy === "accept-ready"} className="success" onClick={acceptReady} disabled={!metrics.ready}><ShieldCheck size={16} />批量接收可用候选</BusyButton></div></div>
      {message && <Notice type={message.includes("失败") ? "danger" : "info"}>{message}</Notice>}
      {latestRun && <div className="toolbar-note">最近运行：{latestRun.document_title} · 候选{latestRun.candidate_count}条 · 可接收{latestRun.ready_count}条 · 异常{latestRun.exception_count}项</div>}
      <div className="table-wrap"><table><thead><tr><th>候选知识</th><th>来源</th><th>风险</th><th>独立复核</th><th>状态</th><th>操作</th></tr></thead><tbody>{candidates.map((item) => <tr key={item.id}><td><strong>{item.title}</strong><small>{item.unit_type} · {item.applicability}</small></td><td>{item.source_heading}<small>{item.file_name}</small></td><td>{riskLabels[item.risk_level] || item.risk_level}</td><td><Status value={item.review_decision} /><small>置信度 {Math.round(item.review_confidence * 100)}%</small></td><td><Status value={item.status} />{item.rule_findings[0] && <small className="error-text">{item.rule_findings[0].message}</small>}</td><td><div className="row-actions"><button className="secondary icon-only" title="查看候选与来源" onClick={() => setSelectedCandidate(item)}><Eye size={15} /></button>{["ready", "needs_review"].includes(item.status) && <><BusyButton busy={busy === `candidate-${item.id}`} onClick={() => reviewCandidate(item, "accept")}><Check size={14} />接收</BusyButton><BusyButton busy={busy === `candidate-${item.id}`} className="danger-outline" onClick={() => reviewCandidate(item, "reject")}><X size={14} />退回</BusyButton></>}</div></td></tr>)}</tbody></table>{!candidates.length && <Empty title="尚未进行AI知识加工" detail="选择一份标准文档，系统将用两次模型调用完成拆解和独立复核。" />}</div>
    </section>
    {tasks.length > 0 && <section className="panel"><div className="toolbar"><div><strong>异常待办</strong><span className="toolbar-note">仅展示需要人工判断的模型分歧和规则风险。</span></div><AlertTriangle size={18} /></div><div className="table-wrap"><table><thead><tr><th>候选</th><th>级别</th><th>来源</th><th>问题</th></tr></thead><tbody>{tasks.map((item) => <tr key={item.id}><td><strong>{item.title}</strong></td><td>{riskLabels[item.severity] || item.severity}</td><td>{item.source === "rule" ? "确定性规则" : item.source === "risk_router" ? "风险路由" : "独立模型复核"}</td><td>{item.message}</td></tr>)}</tbody></table></div></section>}
    {selectedCandidate && <div className="modal-backdrop" onClick={() => setSelectedCandidate(null)}><section className="modal" onClick={(event) => event.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">候选知识 #{selectedCandidate.id}</span><h2>{selectedCandidate.title}</h2></div><button className="secondary icon-only" title="关闭" onClick={() => setSelectedCandidate(null)}><X size={17} /></button></div><div className="detail-title"><p>{selectedCandidate.unit_type} · {selectedCandidate.applicability}</p><Status value={selectedCandidate.status} /></div><div className="content-preview compact"><pre>{selectedCandidate.content}</pre></div><div className="source-box"><h3>逐字来源引文</h3><p>{selectedCandidate.source_quote}</p><span>{selectedCandidate.source_heading} · {selectedCandidate.file_name}</span></div>{[...selectedCandidate.review_issues, ...selectedCandidate.rule_findings].length > 0 && <div className="source-box"><h3>复核与规则发现</h3>{[...selectedCandidate.review_issues, ...selectedCandidate.rule_findings].map((finding, index) => <div key={`${finding.code}-${index}`}><strong>{riskLabels[finding.severity] || finding.severity} · {finding.code}</strong><span>{finding.message}</span></div>)}</div>}<div className="modal-actions"><button className="secondary" onClick={() => setSelectedCandidate(null)}>关闭</button></div></section></div>}
  </>;
}

function Units({ mode, onChanged }) {
  const [items, setItems] = useState([]); const [selected, setSelected] = useState(null); const [query, setQuery] = useState(""); const [reviewer, setReviewer] = useState("技术负责人"); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const status = mode === "review" ? "review_required" : "";
  async function load() { setItems(await api(`/api/knowledge/units?limit=200&status=${status}&query=${encodeURIComponent(query)}`)); }
  async function open(id) { setSelected(await api(`/api/knowledge/units/${id}`)); }
  async function rewrite() { setBusy(true); try { await post(`/api/knowledge/units/${selected.id}/rewrite`, { related_unit_ids: [] }); setMessage("知识重构草稿已生成，等待人工审核。"); await open(selected.id); await load(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function review(action) { const version = selected.versions[0]; setBusy(true); try { await post(`/api/knowledge/reviews/${selected.id}`, { version_id: version.id, action, reviewer, notes: "" }); setMessage(action === "approve" ? "版本已批准。" : "版本已退回。"); await open(selected.id); await load(); onChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function publish() { const version = selected.versions.find((item) => item.status === "approved"); if (!version) return; setBusy(true); try { await post(`/api/knowledge/publications/${selected.id}`, { version_id: version.id, publisher: reviewer }); setMessage("知识已发布并进入正式检索库。"); await open(selected.id); await load(); onChanged?.(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function cluster() { setBusy(true); try { const result = await post("/api/knowledge/units/cluster?limit=5000", {}); setMessage(`已将${result.units}个知识单元归入${result.clusters}个主题簇。`); await load(); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  useEffect(() => { load().catch(() => {}); }, [status]);
  const approvedVersion = selected?.versions?.find((item) => item.status === "approved");
  return <section className="split-view"><article className="panel list-pane"><div className="toolbar"><div className="filters"><input placeholder="标题或内容" value={query} onChange={(event) => setQuery(event.target.value)} /><button className="secondary icon-only" title="查询" onClick={load}><Search size={17} /></button></div><div className="actions"><BusyButton busy={busy} className="secondary" onClick={cluster}>自动聚类</BusyButton><span>{items.length}项</span></div></div><div className="unit-list">{items.map((item) => <button key={item.id} className={selected?.id === item.id ? "unit-item active" : "unit-item"} onClick={() => open(item.id)}><div><strong>{item.title}</strong><span>{item.industry} · {item.unit_type}</span></div><Status value={item.status} /></button>)}{!items.length && <Empty title={mode === "review" ? "没有待审核知识" : "暂无知识单元"} />}</div></article><article className="panel detail-pane">{selected ? <><div className="detail-title"><div><span className="eyebrow">{selected.unit_type}</span><h2>{selected.title}</h2><p>{selected.industry} · 来源{selected.sources.length}份 · 版本{selected.versions.length}个</p></div><Status value={selected.status} /></div>{message && <Notice>{message}</Notice>}<div className="reviewer-row"><label>审核人<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label><div className="actions"><BusyButton busy={busy} className="secondary" onClick={rewrite}><WandSparkles size={16} />重构草稿</BusyButton><BusyButton busy={busy} className="danger-outline" onClick={() => review("reject")} disabled={!selected.versions.length}>退回</BusyButton><BusyButton busy={busy} onClick={() => review("approve")} disabled={!selected.versions.length}><BookCheck size={16} />批准</BusyButton><BusyButton busy={busy} className="success" onClick={publish} disabled={!approvedVersion}><Send size={16} />发布</BusyButton></div></div><div className="content-preview"><pre>{selected.versions[0]?.content || selected.cleaned_content}</pre></div><div className="source-box"><h3>来源追溯</h3>{selected.sources.map((source) => <div key={source.id}><strong>{source.file_name}</strong><span>{source.heading || "正文"} · {source.relative_path}</span></div>)}</div></> : <Empty title="选择知识单元" detail="查看正文、来源、版本并执行审核发布。" />}</article></section>;
}

function Publications({ onChanged }) {
  const [items, setItems] = useState([]); const [reviewer, setReviewer] = useState("系统管理员");
  async function load() { setItems(await api("/api/knowledge/publications?limit=200")); }
  async function retire(item) { await post(`/api/knowledge/publications/${item.id}/retire`, { reviewer }); await load(); onChanged?.(); }
  async function restore(item) { await post(`/api/knowledge/publications/${item.id}/restore`, { reviewer }); await load(); onChanged?.(); }
  useEffect(() => { load().catch(() => {}); }, []);
  return <section className="panel"><div className="toolbar"><strong>正式知识库</strong><label className="inline-field">操作人<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label></div><div className="table-wrap"><table><thead><tr><th>知识</th><th>行业</th><th>类型</th><th>版本</th><th>来源</th><th>状态</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.title}</strong></td><td>{item.industry}</td><td>{item.unit_type}</td><td>v{item.publication_version}</td><td>{item.source_name || "可追溯"}</td><td><Status value={item.status} /></td><td>{item.status === "published" ? <button className="secondary" onClick={() => retire(item)}>停用</button> : <button className="secondary" onClick={() => restore(item)}>恢复</button>}</td></tr>)}</tbody></table>{!items.length && <Empty title="正式知识库为空" detail="知识单元必须经过人工批准后才能发布。" />}</div></section>;
}

function KnowledgeSearch() {
  const [query, setQuery] = useState("施工工艺"); const [industry, setIndustry] = useState(""); const [items, setItems] = useState([]); const [message, setMessage] = useState("");
  async function search() { try { const result = await post("/api/knowledge/search", { query, industry, limit: 20 }); setItems(result); setMessage(`命中${result.length}条已发布知识。`); } catch (error) { setMessage(error.message); } }
  return <section className="panel"><div className="search-bar"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入章节、工艺或管理要求" /><select value={industry} onChange={(event) => setIndustry(event.target.value)}><option value="">全部行业</option>{["医院", "学校", "市政", "厂房", "水利", "通用"].map((value) => <option key={value}>{value}</option>)}</select><button onClick={search}><Search size={17} />检索</button></div>{message && <Notice>{message}</Notice>}<div className="search-results">{items.map((item) => <article key={item.publication_id}><div><span className="eyebrow">{item.industry} · {item.unit_type}</span><h3>{item.title}</h3></div><p>{item.content.slice(0, 320)}...</p><footer><span>发布v{item.publication_version}</span><span>来源{item.sources.length}份</span></footer></article>)}{!items.length && <Empty title="等待检索" detail="检索范围只包含当前有效的已发布知识。" />}</div></section>;
}

function RetrievalEvaluation() {
  const [publications, setPublications] = useState([]); const [cases, setCases] = useState([]); const [runs, setRuns] = useState([]); const [selectedUnitId, setSelectedUnitId] = useState(""); const [reviewer, setReviewer] = useState("技术负责人"); const [busy, setBusy] = useState(""); const [message, setMessage] = useState("");
  const publishedUnits = useMemo(() => Array.from(new Map(publications.filter((item) => item.status === "published").map((item) => [item.unit_id, item])).values()), [publications]);
  async function load() { const [nextPublications, nextCases, nextRuns] = await Promise.all([api("/api/knowledge/publications?limit=500"), api("/api/evaluation/cases"), api("/api/evaluation/runs?limit=10")]); setPublications(nextPublications); setCases(nextCases); setRuns(nextRuns); setSelectedUnitId((current) => current || String(nextPublications.find((item) => item.status === "published")?.unit_id || "")); }
  async function generate() { if (!selectedUnitId) return; setBusy("generate"); try { const result = await post("/api/evaluation/cases/generate-silver", { unit_id: Number(selectedUnitId), count: 8, dataset_name: "default" }); setMessage(`已生成${result.created}条白银候选问题${result.cached ? "（使用缓存）" : ""}。`); await load(); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  async function review(item, action) { setBusy(`case-${item.id}`); try { await post(`/api/evaluation/cases/${item.id}/review`, { action, reviewer }); setMessage(action === "promote_gold" ? "样本已确认并升级为黄金数据。" : action === "approve" ? "白银样本已通过抽检。" : "样本已退回。"); await load(); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  async function run(sourceType) { setBusy(`run-${sourceType}`); try { const result = await post("/api/evaluation/runs", { dataset_name: "default", source_type: sourceType, top_k: 10 }); setMessage(`${sourceType === "gold" ? "黄金" : "白银"}评测完成，通过率${Math.round(result.metrics.pass_rate * 100)}%。`); await load(); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  const latest = runs[0];
  const approvedSilver = cases.filter((item) => item.source_type === "silver" && item.status === "approved").length;
  const approvedGold = cases.filter((item) => item.source_type === "gold" && item.status === "approved").length;
  const kindLabels = { direct: "直接问法", synonym: "同义改写", tender_clause: "招标条款", confusing_negative: "干扰负样本" };
  return <><section className="panel"><div className="toolbar"><div className="filters"><select value={selectedUnitId} onChange={(event) => setSelectedUnitId(event.target.value)}><option value="">选择已发布知识</option>{publishedUnits.map((item) => <option value={item.unit_id} key={item.unit_id}>{item.title}</option>)}</select><label className="inline-field">审核人<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label></div><div className="actions"><BusyButton busy={busy === "generate"} onClick={generate} disabled={!selectedUnitId}><WandSparkles size={16} />生成8条白银问题</BusyButton><BusyButton busy={busy === "run-silver"} className="secondary" onClick={() => run("silver")} disabled={!approvedSilver}><FlaskConical size={16} />运行白银评测</BusyButton><BusyButton busy={busy === "run-gold"} className="secondary" onClick={() => run("gold")} disabled={!approvedGold}><Award size={16} />运行黄金评测</BusyButton></div></div>{message && <Notice>{message}</Notice>}{latest && <div className="metric-grid four"><Metric label="最近样本" value={latest.case_count} /><Metric label={`Recall@${latest.top_k}`} value={latest.metrics.recall_at_k == null ? "-" : `${Math.round(latest.metrics.recall_at_k * 100)}%`} tone="success" /><Metric label="MRR" value={latest.metrics.mrr == null ? "-" : latest.metrics.mrr.toFixed(2)} /><Metric label="负样本拒绝" value={latest.metrics.negative_rejection_rate == null ? "-" : `${Math.round(latest.metrics.negative_rejection_rate * 100)}%`} /></div>}<div className="table-wrap"><table><thead><tr><th>问题</th><th>类型</th><th>数据级别</th><th>状态</th><th>操作</th></tr></thead><tbody>{cases.map((item) => <tr key={item.id}><td><strong>{item.query}</strong><small>知识单元 #{item.source_unit_id}</small></td><td>{kindLabels[item.query_kind] || item.query_kind}</td><td>{item.source_type === "gold" ? "黄金" : "白银"}</td><td><Status value={item.status} /></td><td><div className="row-actions">{item.status === "proposed" && <><BusyButton busy={busy === `case-${item.id}`} className="secondary" onClick={() => review(item, "approve")}><Check size={14} />通过</BusyButton><BusyButton busy={busy === `case-${item.id}`} onClick={() => review(item, "promote_gold")}><Award size={14} />升黄金</BusyButton><BusyButton busy={busy === `case-${item.id}`} className="danger-outline" onClick={() => review(item, "reject")}><X size={14} />退回</BusyButton></>}{item.source_type === "silver" && item.status === "approved" && <BusyButton busy={busy === `case-${item.id}`} onClick={() => review(item, "promote_gold")}><Award size={14} />升黄金</BusyButton>}</div></td></tr>)}</tbody></table>{!cases.length && <Empty title="暂无评测样本" detail={publishedUnits.length ? "选择一条已发布知识，由AI生成候选问题。" : "请先审核并发布知识，再生成评测问题。"} />}</div></section></>;
}

function RetrievalEvaluationWorkspace() {
  const [publications, setPublications] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [datasetName, setDatasetName] = useState("");
  const [cases, setCases] = useState([]);
  const [runs, setRuns] = useState([]);
  const [selectedUnitId, setSelectedUnitId] = useState("");
  const [selectedIds, setSelectedIds] = useState([]);
  const [reviewer, setReviewer] = useState("技术负责人");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const publishedUnits = useMemo(() => Array.from(new Map(publications.filter((item) => item.status === "published").map((item) => [item.unit_id, item])).values()), [publications]);

  async function load(preferredDataset = datasetName) {
    const [nextPublications, nextDatasets, nextRuns] = await Promise.all([
      api("/api/knowledge/publications?limit=500"),
      api("/api/evaluation/datasets"),
      api("/api/evaluation/runs?limit=50"),
    ]);
    const nextDataset = preferredDataset || nextDatasets[0]?.dataset_name || "default";
    const nextCases = await api(`/api/evaluation/cases?dataset_name=${encodeURIComponent(nextDataset)}`);
    setPublications(nextPublications);
    setDatasets(nextDatasets);
    setRuns(nextRuns);
    setDatasetName(nextDataset);
    setCases(nextCases);
    setSelectedIds((current) => current.filter((id) => nextCases.some((item) => item.id === id)));
    setSelectedUnitId((current) => current || String(nextPublications.find((item) => item.status === "published")?.unit_id || ""));
  }

  async function switchDataset(value) { setDatasetName(value); setSelectedIds([]); await load(value); }
  async function generate() {
    if (!selectedUnitId || !datasetName) return;
    setBusy("generate");
    try {
      const result = await post("/api/evaluation/cases/generate-silver", { unit_id: Number(selectedUnitId), count: 8, dataset_name: datasetName });
      setMessage(`已生成 ${result.created} 条白银候选问题。`);
      await load(datasetName);
    } catch (error) { setMessage(error.message); } finally { setBusy(""); }
  }
  async function aiReview() {
    if (!datasetName) return;
    setBusy("ai-review");
    try {
      const job = await post("/api/evaluation/cases/review-silver-ai", { dataset_name: datasetName, case_ids: selectedIds });
      const completed = await waitForJob(job.id);
      setMessage(`AI 复核完成：批准 ${completed.result.approved || 0}，淘汰 ${completed.result.rejected || 0}，待人工 ${completed.result.needs_review || 0}。`);
      await load(datasetName);
    } catch (error) { setMessage(error.message); } finally { setBusy(""); }
  }
  async function batchReview(action) {
    if (!selectedIds.length) return;
    setBusy(`batch-${action}`);
    try {
      const result = await post("/api/evaluation/cases/batch-review", { case_ids: selectedIds, action, reviewer });
      setMessage(`已处理 ${result.processed} 条评测问题。`);
      setSelectedIds([]);
      await load(datasetName);
    } catch (error) { setMessage(error.message); } finally { setBusy(""); }
  }
  async function run(sourceType) {
    setBusy(`run-${sourceType}`);
    try {
      const result = await post("/api/evaluation/runs", { dataset_name: datasetName, source_type: sourceType, top_k: 10 });
      setMessage(`${sourceType === "gold" ? "黄金" : "白银"}评测完成，通过率 ${Math.round(result.metrics.pass_rate * 100)}%。`);
      await load(datasetName);
    } catch (error) { setMessage(error.message); } finally { setBusy(""); }
  }
  function toggle(id) { setSelectedIds((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]); }
  function toggleAll() { setSelectedIds(selectedIds.length === cases.length ? [] : cases.map((item) => item.id)); }

  useEffect(() => { load().catch((error) => setMessage(error.message)); }, []);
  const latest = runs.find((item) => item.dataset_name === datasetName);
  const approvedSilver = cases.filter((item) => item.source_type === "silver" && item.status === "approved").length;
  const approvedGold = cases.filter((item) => item.source_type === "gold" && item.status === "approved").length;
  const proposed = cases.filter((item) => item.status === "proposed").length;
  const kindLabels = { direct: "直接问法", synonym: "同义改写", tender_clause: "招标条款", confusing_negative: "困难负样本" };
  const percent = (value) => value == null ? "-" : `${Math.round(value * 100)}%`;

  return <>
    <section className="panel">
      <div className="toolbar">
        <div className="filters">
          <select value={datasetName} onChange={(event) => switchDataset(event.target.value)}>{datasets.map((item) => <option key={item.dataset_name} value={item.dataset_name}>{item.dataset_name} · {item.case_count}</option>)}{!datasets.length && <option value="default">default</option>}</select>
          <select value={selectedUnitId} onChange={(event) => setSelectedUnitId(event.target.value)}><option value="">选择已发布知识</option>{publishedUnits.map((item) => <option value={item.unit_id} key={item.unit_id}>{item.title}</option>)}</select>
          <label className="inline-field">审核人<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
        </div>
        <div className="actions">
          <BusyButton busy={busy === "generate"} onClick={generate} disabled={!selectedUnitId}><WandSparkles size={16} />生成白银问题</BusyButton>
          <BusyButton busy={busy === "ai-review"} className="secondary" onClick={aiReview} disabled={!proposed}><BrainCircuit size={16} />AI 独立复核</BusyButton>
          <BusyButton busy={busy === "run-silver"} className="secondary" onClick={() => run("silver")} disabled={!approvedSilver}><FlaskConical size={16} />运行白银评测</BusyButton>
          <BusyButton busy={busy === "run-gold"} className="secondary" onClick={() => run("gold")} disabled={!approvedGold}><Award size={16} />运行黄金评测</BusyButton>
        </div>
      </div>
      {message && <Notice>{message}</Notice>}
      {latest && <div className="metric-grid five"><Metric label={`Recall@${latest.top_k}`} value={percent(latest.metrics.recall_at_k)} tone={latest.metrics.recall_at_k >= 0.8 ? "success" : "warning"} /><Metric label={`NDCG@${latest.top_k}`} value={percent(latest.metrics.ndcg_at_k)} tone={latest.metrics.ndcg_at_k >= 0.75 ? "success" : "warning"} /><Metric label="困难负样本拒绝" value={percent(latest.metrics.negative_rejection_rate)} tone={latest.metrics.negative_rejection_rate >= 0.8 ? "success" : "warning"} /><Metric label="FTS 负样本拒绝" value={percent(latest.metrics.baseline_negative_rejection_rate)} /><Metric label="负样本提升" value={latest.metrics.negative_rejection_lift == null ? "-" : `${latest.metrics.negative_rejection_lift >= 0 ? "+" : ""}${Math.round(latest.metrics.negative_rejection_lift * 100)}%`} /></div>}
      <div className="toolbar compact"><div className="actions"><button className="secondary" onClick={toggleAll}>{selectedIds.length === cases.length && cases.length ? "取消全选" : "全选"}</button><span>已选 {selectedIds.length}</span></div><div className="actions"><BusyButton busy={busy === "batch-approve"} className="secondary" disabled={!selectedIds.length} onClick={() => batchReview("approve")}><Check size={14} />批量通过</BusyButton><BusyButton busy={busy === "batch-promote_gold"} disabled={!selectedIds.length} onClick={() => batchReview("promote_gold")}><Award size={14} />批量升黄金</BusyButton><BusyButton busy={busy === "batch-reject"} className="danger-outline" disabled={!selectedIds.length} onClick={() => batchReview("reject")}><X size={14} />批量退回</BusyButton></div></div>
      <div className="table-wrap"><table><thead><tr><th></th><th>问题</th><th>类型</th><th>级别</th><th>AI 复核</th><th>状态</th></tr></thead><tbody>{cases.map((item) => <tr key={item.id}><td><input type="checkbox" checked={selectedIds.includes(item.id)} onChange={() => toggle(item.id)} aria-label={`选择问题 ${item.id}`} /></td><td><strong>{item.query}</strong><small>知识单元 #{item.source_unit_id}</small></td><td>{kindLabels[item.query_kind] || item.query_kind}</td><td>{item.source_type === "gold" ? "黄金" : "白银"}</td><td><Status value={item.ai_review_status || "pending"} />{item.ai_review_confidence ? <small>{Math.round(item.ai_review_confidence * 100)}%</small> : null}</td><td><Status value={item.status} /></td></tr>)}</tbody></table>{!cases.length && <Empty title="暂无评测样本" />}</div>
    </section>
  </>;
}
