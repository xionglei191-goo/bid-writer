import React, { useEffect, useState } from "react";
import { CheckCheck, ClipboardList, RefreshCw } from "lucide-react";
import { api, post, waitForJob } from "../api";
import { BusyButton, Empty, Metric, Notice } from "../components";

const taskKinds = { all: "全部待办", generation: "生成待处理", response: "缺正文响应", evidence: "需要原文核验", information: "需实际资料", scope: "条款分类待确认" };

export function CoverageMetrics({ metrics }) {
  if (!metrics) return null;
  return <><div className="metric-grid three coverage-metrics">
    <Metric label="已映射技术条款" value={`${metrics.mapped}/${metrics.technical_total}`} hint="已经关联到章节" />
    <Metric label="已回应技术条款" value={`${metrics.responded}/${metrics.technical_total}`} hint="已有正文响应，仍需核验" />
    <Metric label="已签审技术条款" value={`${metrics.signed}/${metrics.technical_total}`} hint="由实际责任人确认当前版本" />
  </div><p className="form-help">已映射、已回应、已签审是三个不同阶段。已签审为 0，不代表正文没有编写。非技术建议经人工确认前，仍保留在当前核验分母内；确认后在招标解析中单独核对资料。</p></>;
}

export function generationMessage(draft, prefix = "本章") {
  const status = draft?.generation?.status || draft?.generation_status;
  if (status === "ai") return `${prefix}已生成 AI 草稿。正文、原文依据和实际资料仍需逐项核验，尚未自动签审。`;
  if (status === "fallback") return `${prefix}未取得完整 AI 结果，当前为回退草稿，请处理失败部分后核对正文。`;
  if (status === "manual_edit") return `${prefix}已人工修改，正文响应与来源依据仍需重新核验。`;
  if (["incomplete", "ai_incomplete", "partial", "partial_fallback"].includes(status)) return `${prefix}仍有生成失败或漏回应的部分，可继续补写；其余正文已保留。`;
  return `${prefix}处理已完成，请根据生成状态和待办逐项核对正文与证据。`;
}

export default function ProjectRemediation({ project, reload, onNavigate }) {
  const [workbench, setWorkbench] = useState(null);
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const root = `/api/projects/${project.id}`;
  async function refresh() { setWorkbench(await api(`${root}/workbench`)); }
  useEffect(() => { refresh().catch((error) => { setFailed(true); setMessage(error.message); }); }, [project]);
  async function run(name, action) {
    setBusy(name); setFailed(false); setMessage("");
    try { await action(); }
    catch (error) { setFailed(true); setMessage(error.message); }
    finally { setBusy(""); }
  }
  async function recheck() {
    await run("recheck", async () => {
      await waitForJob(await post(`${root}/evidence/recheck`, { background: true }), { onProgress: (job) => setMessage(`正在复核原文证据 · ${job.progress}%`) });
      await reload(); await refresh();
      setMessage("当前原文证据已重新检查，请处理仍缺依据或资料的事项。此操作不会替代人工签审。");
    });
  }
  async function repair(task) {
    const section = project.sections.find((item) => item.id === task.section_id);
    if (!section) return;
    const partial = task.action === "repair";
    await run(task.id, async () => {
      const result = await waitForJob(await post(`${root}/sections/${section.id}/${partial ? "repair" : "generate"}`, { background: true, ...(partial ? { target_hash: section.draft?.content_hash } : {}) }), { onProgress: (job) => setMessage(`${partial ? "正在补写失败部分" : "正在重试本章"} · ${job.progress}%`) });
      const updated = await reload(); await refresh();
      const draft = updated?.sections?.find((item) => item.id === section.id)?.draft || result.draft || result;
      setMessage(generationMessage(draft));
    });
  }
  const tasks = workbench?.tasks || [];
  const visible = tasks.filter((item) => filter === "all" || item.kind === filter);
  return <section className="panel remediation-panel">
    <div className="panel-title"><div><ClipboardList size={18} /><h2>按原因处理待办</h2></div><div className="actions"><BusyButton className="secondary" busy={busy === "refresh"} disabled={Boolean(busy)} onClick={() => run("refresh", refresh)}><RefreshCw size={16} />刷新待办</BusyButton><BusyButton busy={busy === "recheck"} disabled={Boolean(busy)} onClick={recheck}><CheckCheck size={16} />重新核对原文证据</BusyButton></div></div>
    {message && <Notice type={failed ? "danger" : "info"}>{message}</Notice>}
    <CoverageMetrics metrics={workbench?.metrics} />
    <p className="form-help">补写只处理本章记录的失败或漏回应部分。旧草稿没有分段记录时，可重试本章；其他章节保持原样。证据核验与实际资料需要人工处理。</p>
    <div className="scope-filters" aria-label="待办类型筛选">{Object.entries(taskKinds).map(([key, label]) => <button type="button" key={key} className={filter === key ? "active" : "secondary"} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}<span>{key === "all" ? tasks.length : tasks.filter((item) => item.kind === key).length}</span></button>)}</div>
    {!workbench ? <Empty title="正在载入待办" /> : visible.length ? <div className="remediation-list">{visible.map((task) => <article key={task.id} data-task-id={task.id}>
      <div className="remediation-title"><span className={`task-kind task-${task.kind}`}>{taskKinds[task.kind] || "待核对"}</span><strong>{task.title}</strong></div>
      <p>{task.kind === "generation" && project.sections.find((section) => section.id === task.section_id)?.draft?.generation?.repair_blocked ? project.sections.find((section) => section.id === task.section_id).draft.generation.repair_blocked_reason || task.detail : task.detail}</p>
      {task.source_page && <small>原文件第 {task.source_page} 页</small>}
      <div className="actions">
        {["repair", "regenerate"].includes(task.action) && !project.sections.find((section) => section.id === task.section_id)?.draft?.generation?.repair_blocked && <BusyButton busy={busy === task.id} disabled={Boolean(busy)} onClick={() => repair(task)}>{task.action === "repair" ? "仅补写失败部分" : "重试本章"}</BusyButton>}
        {task.action === "recheck" && <BusyButton className="secondary" busy={busy === "recheck"} disabled={Boolean(busy)} onClick={recheck}>重新核对原文证据</BusyButton>}
        {task.kind === "response" && task.requirement_id && <button type="button" className="secondary" onClick={() => onNavigate("requirements", { requirementId: task.requirement_id })}>定位现有正文响应</button>}
        {task.requirement_id && ["scope", "information"].includes(task.kind) ? <button type="button" className="secondary" onClick={() => onNavigate("requirements", { requirementId: task.requirement_id })}>打开条款与资料</button> : task.section_id ? <button type="button" className="secondary" onClick={() => onNavigate("editor", { sectionId: task.section_id, claimId: task.claim_id })}>打开本章处理</button> : task.kind === "information" && <button type="button" className="secondary" onClick={() => onNavigate("overview")}>核对项目资料</button>}
      </div>
    </article>)}</div> : <Empty title={filter === "all" ? "当前没有可处理待办" : "此类暂无待办"} detail="正式交付仍以质量页的检查结果和人工签审为准。" />}
  </section>;
}
