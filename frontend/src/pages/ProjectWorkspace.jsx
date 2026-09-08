import React, { useEffect, useState } from "react";
import { ArrowLeft, BookOpenText, CheckCheck, ListTree, Save, WandSparkles } from "lucide-react";
import { api, patch, post, waitForJob } from "../api";
import { BusyButton, Empty, Notice, PageHeader, Status, Tabs } from "../components";
import ProjectDelivery from "./ProjectDelivery";
import ProjectProfile from "./ProjectProfile";

const tabs = [{ key: "overview", label: "项目资料" }, { key: "requirements", label: "招标解析" }, { key: "outline", label: "目录策略" }, { key: "editor", label: "章节编制" }, { key: "quality", label: "质量交付" }];

export default function ProjectWorkspace({ projectId }) {
  const [project, setProject] = useState(null); const [tab, setTab] = useState("overview"); const [message, setMessage] = useState(""); const [busy, setBusy] = useState("");
  async function load() { setProject(await api(`/api/projects/${projectId}`)); }
  async function action(name, fn) { setBusy(name); try { const result = await fn(); await waitForJob(result, { onProgress: (job) => setMessage(`正在处理 · ${job.progress}%`) }); await load(); setMessage("操作已完成。"); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, [projectId]);
  if (!project) return <Empty title="正在加载项目" />;
  return <>
    <a className="back-link" href="#/projects"><ArrowLeft size={15} />返回项目列表</a>
    <PageHeader eyebrow={`${project.industry || "通用"} · ${project.project_type || "技术标"}`} title={project.name} description={`${project.region || "未设置地区"} · ${project.requirements.length}项要求 · ${project.sections.length}个章节`} actions={<Status value={project.status} />} />
    <Tabs items={tabs} active={tab} onChange={setTab} />
    {message && <Notice type={message.includes("失败") || message.includes("不能") || message.includes("没有") ? "danger" : "info"}>{message}</Notice>}
    {tab === "overview" && <ProjectProfile project={project} onSave={(payload) => action("save", () => patch(`/api/projects/${projectId}`, payload))} busy={busy === "save"} />}
    {tab === "requirements" && <Requirements project={project} onParse={() => action("parse", () => post(`/api/projects/${projectId}/requirements/parse`, {}))} busy={busy === "parse"} />}
    {tab === "outline" && <Outline project={project} onBuild={() => action("outline", () => post(`/api/projects/${projectId}/outline`, {}))} busy={busy === "outline"} />}
    {tab === "editor" && <Editor project={project} reload={load} setMessage={setMessage} />}
    {tab === "quality" && <ProjectDelivery project={project} reload={load} onNavigate={setTab} />}
  </>;
}

function Requirements({ project, onParse, busy }) {
  const hasDrafts = project.sections.some((section) => section.draft);
  const kinds = { technical: "技术要求", veto: "限制与否决条款", scoring: "评分点", qualification: "资格要求", commitment: "履约承诺", parameter: "参数要求", deliverable: "交付资料", confirmation: "待确认要求" };
  return <section className="panel">
    <div className="panel-title"><div><BookOpenText size={18} /><h2>要求与评分点</h2></div><BusyButton busy={busy} disabled={hasDrafts} onClick={onParse}><WandSparkles size={16} />重新解析</BusyButton></div>
    <p className="form-help">解析结果供逐条核对，请结合原招标文件检查适用范围、评分规则及资格条件。{hasDrafts ? "已有章节正文，重新解析已锁定，避免清除原有条款和签审依据。" : ""}</p>
    {project.requirements.length ? <div className="requirement-list">{project.requirements.map((item) => <article key={item.id}><div><span className="requirement-key">{item.requirement_key}</span><Status value={item.status} /></div><p>{item.content}</p><footer><span>{kinds[item.kind] || item.kind}</span><span>{item.source_page ? `原文件第 ${item.source_page} 页` : "来源页码待核对"}</span><span className={item.priority === "high" ? "priority-high" : ""}>{item.priority === "high" ? "高优先级" : "普通"}</span></footer></article>)}</div> : <Empty title="尚未提取要求" detail="保存招标文本后执行解析。" />}
  </section>;
}

function Outline({ project, onBuild, busy }) {
  const hasDrafts = project.sections.some((section) => section.draft);
  return <section className="panel"><div className="panel-title"><div><ListTree size={18} /><h2>技术标目录</h2></div><BusyButton busy={busy} disabled={hasDrafts} onClick={onBuild}><WandSparkles size={16} />生成目录</BusyButton></div>{hasDrafts && <p className="form-help">已有章节正文，目录重建已锁定，保留当前草稿和签审记录。</p>}{project.sections.length ? <div className="outline-list">{project.sections.map((item) => <article key={item.id}><span>{String(item.order_no).padStart(2, "0")}</span><div><strong>{item.title}</strong><small>关联{item.requirement_ids.length}项要求</small></div><Status value={item.status} /></article>)}</div> : <Empty title="目录尚未生成" detail="完成招标解析后生成11类标准章节。" />}</section>;
}

function Editor({ project, reload, setMessage }) {
  const [selectedId, setSelectedId] = useState(project.sections[0]?.id || null); const [content, setContent] = useState(""); const [busy, setBusy] = useState(false); const [reviewer, setReviewer] = useState(""); const [resolutions, setResolutions] = useState([]);
  const selected = project.sections.find((item) => item.id === selectedId);
  useEffect(() => {
    setContent(selected?.draft?.content || "");
    const existing = Object.fromEntries((selected?.draft?.confirmation_resolutions || []).map((item) => [item.confirmation_index, item.resolution]));
    setResolutions((selected?.draft?.confirmations || []).map((_, index) => existing[index] || ""));
  }, [selectedId, selected?.draft?.id, selected?.draft?.content_hash]);
  async function generate() { if (!selected) return; setBusy(true); try { const queued = await post(`/api/projects/${project.id}/sections/${selected.id}/generate`, { background: true }); await waitForJob(queued, { onProgress: (job) => setMessage(`${job.stage} · ${job.progress}%`) }); await reload(); setMessage("章节草稿已生成，关键表述与来源证据已经建立。"); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function save() { if (!selected?.draft) return; setBusy(true); try { await patch(`/api/projects/drafts/${selected.draft.id}`, { content }); await reload(); setMessage("章节已保存，旧质量确认已失效。"); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function confirm() { if (!selected?.draft) return; setBusy(true); try { await post(`/api/projects/drafts/${selected.draft.id}/confirm`, { reviewer, target_hash: selected.draft.content_hash, resolutions: resolutions.map((resolution, index) => ({ index, resolution })) }); await reload(); setMessage("本章已逐项处理待确认事项，并绑定当前正文完成签审。"); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function generateAll() { setBusy(true); try { const queued = await post(`/api/projects/${project.id}/generate-all`, { background: true }); const result = await waitForJob(queued, { onProgress: (job) => setMessage(`${job.stage} · ${job.progress}%`) }); await reload(); setMessage(`批量生成完成：成功${result.generated}章，失败${result.failed}章。`); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  if (!project.sections.length) return <section className="panel"><Empty title="请先生成目录" /></section>;
  const hasUnsavedChanges = Boolean(selected?.draft && content !== selected.draft.content);
  const resolutionsComplete = resolutions.every((item) => item.trim());
  const unresolvedCount = Math.max(0, (selected?.draft?.confirmations.length || 0) - (selected?.draft?.confirmation_resolutions.length || 0));
  return <section className="editor-layout"><aside className="chapter-list"><div className="chapter-tools"><BusyButton busy={busy} onClick={generateAll}><WandSparkles size={16} />生成全部章节</BusyButton></div>{project.sections.map((item) => <button key={item.id} className={selectedId === item.id ? "active" : ""} onClick={() => setSelectedId(item.id)}><span>{item.order_no}</span><div><strong>{item.title}</strong><small>{item.requirement_ids.length}项要求</small></div><Status value={item.status} /></button>)}</aside><article className="panel editor-main"><div className="editor-head"><div><span className="eyebrow">第{selected?.order_no}章</span><h2>{selected?.title}</h2></div><div className="actions"><BusyButton busy={busy} className="secondary" onClick={generate}><WandSparkles size={16} />生成本章</BusyButton><BusyButton busy={busy} className="secondary" onClick={confirm} disabled={!selected?.draft || hasUnsavedChanges || !resolutionsComplete || !reviewer.trim()}><CheckCheck size={16} />{selected?.draft?.status === "reviewed" ? "重新签审" : "签审本章"}</BusyButton><BusyButton busy={busy} onClick={save} disabled={!selected?.draft || !hasUnsavedChanges}><Save size={16} />保存</BusyButton></div></div>{selected?.draft ? <><div className="reviewer-inline"><label>本章签审人<input placeholder="填写实际签审人姓名" value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label></div><textarea className="chapter-editor" value={content} onChange={(event) => setContent(event.target.value)} />{selected.draft.confirmations.length > 0 && <div className="confirmation-panel"><h3>待确认事项</h3>{selected.draft.confirmations.map((item, index) => <label key={`${selected.draft.id}-${index}`}><span>{index + 1}. {item}</span><textarea rows="2" placeholder="填写核实结果或处理结论" value={resolutions[index] || ""} onChange={(event) => setResolutions(resolutions.map((value, itemIndex) => itemIndex === index ? event.target.value : value))} /></label>)}</div>} {hasUnsavedChanges && <Notice type="danger">正文有未保存修改，请先保存再签审。</Notice>}<div className="citation-strip"><strong>知识来源</strong><span>{selected.draft.citations.length}项正式知识</span><span>{unresolvedCount}项待处理</span><span>{selected.draft.confirmation_resolutions.length}项已处理</span><Status value={selected.draft.evidence_status} /></div><EvidencePanel claims={selected.draft.claims || []} onChanged={reload} setMessage={setMessage} /></> : <Empty title="本章尚未生成" detail="生成前必须确保正式知识库已有匹配内容。" />}</article></section>;
}

function EvidencePanel({ claims, onChanged, setMessage }) {
  const [selectedId, setSelectedId] = useState(claims[0]?.id || null);
  const selected = claims.find((item) => item.id === selectedId) || claims[0];
  useEffect(() => { if (!claims.some((item) => item.id === selectedId)) setSelectedId(claims[0]?.id || null); }, [claims, selectedId]);
  async function resolve(action) {
    if (!selected) return;
    const resolution = window.prompt(action === "confirm" ? "填写核验依据" : "填写处理结论");
    if (!resolution) return;
    try { await post(`/api/projects/claims/${selected.id}/resolve`, { action, resolution }); await onChanged(); setMessage("表述核验结论已记录。"); }
    catch (error) { setMessage(error.message); }
  }
  if (!claims.length) return null;
  return <section className="evidence-panel"><div className="evidence-list">{claims.map((claim) => <button type="button" key={claim.id} className={selected?.id === claim.id ? "active" : ""} onClick={() => setSelectedId(claim.id)}><span className={`risk-dot risk-${claim.risk_level}`} /><span>{claim.text}</span><Status value={claim.support_status} /></button>)}</div>{selected && <aside className="evidence-source"><div className="detail-title"><div><span className="eyebrow">{selected.claim_type} · {selected.risk_level}</span><h2>证据核验</h2></div><Status value={selected.support_status} /></div><p>{selected.text}</p>{selected.evidence?.map((item) => <article key={item.id}><strong>{item.unit_title || "招标要求"}</strong><small>{item.file_name || "项目输入"}{item.source_page ? ` · 第${item.source_page}页` : ""}</small><blockquote>{item.source_excerpt}</blockquote><span>支持度 {Math.round(item.score * 100)}%</span></article>)}{selected.support_status === "unsupported" && <div className="actions"><button className="secondary" onClick={() => resolve("weaken")}>降级表述</button><button onClick={() => resolve("confirm")}>确认依据</button></div>}</aside>}</section>;
}
