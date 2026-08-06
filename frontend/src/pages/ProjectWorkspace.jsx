import React, { useEffect, useState } from "react";
import { ArrowLeft, BookOpenText, CheckCheck, Download, FileInput, ListTree, Save, ShieldCheck, WandSparkles } from "lucide-react";
import { api, patch, post } from "../api";
import { BusyButton, Empty, Metric, Notice, PageHeader, Status, Tabs } from "../components";

const tabs = [{ key: "overview", label: "项目资料" }, { key: "requirements", label: "招标解析" }, { key: "outline", label: "目录策略" }, { key: "editor", label: "章节编制" }, { key: "quality", label: "质量交付" }];

export default function ProjectWorkspace({ projectId }) {
  const [project, setProject] = useState(null); const [tab, setTab] = useState("overview"); const [message, setMessage] = useState(""); const [busy, setBusy] = useState("");
  async function load() { setProject(await api(`/api/projects/${projectId}`)); }
  async function action(name, fn) { setBusy(name); try { await fn(); await load(); setMessage("操作已完成。"); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
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
    {tab === "quality" && <ProjectQuality project={project} />}
  </>;
}

function ProjectProfile({ project, onSave, busy }) {
  const [form, setForm] = useState({ name: project.name, industry: project.industry, project_type: project.project_type, region: project.region, source_text: project.source_text || "", profile: project.profile || {} });
  const setProfile = (key, value) => setForm({ ...form, profile: { ...form.profile, [key]: value } });
  return <section className="panel"><div className="panel-title"><div><FileInput size={18} /><h2>项目资料</h2></div><BusyButton busy={busy} onClick={() => onSave(form)}><Save size={16} />保存资料</BusyButton></div><div className="form-grid"><label className="wide">项目名称<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label>行业<select value={form.industry} onChange={(event) => setForm({ ...form, industry: event.target.value })}>{["医院", "学校", "市政", "厂房", "水利", "通用"].map((value) => <option key={value}>{value}</option>)}</select></label><label>项目类型<input value={form.project_type} onChange={(event) => setForm({ ...form, project_type: event.target.value })} /></label><label>地区<input value={form.region} onChange={(event) => setForm({ ...form, region: event.target.value })} /></label><label>结构形式<input value={form.profile.structure_type || ""} onChange={(event) => setProfile("structure_type", event.target.value)} /></label><label>计划工期<input value={form.profile.duration || ""} onChange={(event) => setProfile("duration", event.target.value)} /></label><label>质量目标<input value={form.profile.quality_target || ""} onChange={(event) => setProfile("quality_target", event.target.value)} /></label><label>安全目标<input value={form.profile.safety_target || ""} onChange={(event) => setProfile("safety_target", event.target.value)} /></label><label className="wide">招标文件与技术要求<textarea rows="18" value={form.source_text} onChange={(event) => setForm({ ...form, source_text: event.target.value })} /></label></div></section>;
}

function Requirements({ project, onParse, busy }) {
  return <section className="panel"><div className="panel-title"><div><BookOpenText size={18} /><h2>要求与评分点</h2></div><BusyButton busy={busy} onClick={onParse}><WandSparkles size={16} />重新解析</BusyButton></div>{project.requirements.length ? <div className="requirement-list">{project.requirements.map((item) => <article key={item.id}><div><span className="requirement-key">{item.requirement_key}</span><Status value={item.status} /></div><p>{item.content}</p><footer><span>{item.kind}</span><span className={item.priority === "high" ? "priority-high" : ""}>{item.priority === "high" ? "高优先级" : "普通"}</span></footer></article>)}</div> : <Empty title="尚未提取要求" detail="保存招标文本后执行解析。" />}</section>;
}

function Outline({ project, onBuild, busy }) {
  return <section className="panel"><div className="panel-title"><div><ListTree size={18} /><h2>技术标目录</h2></div><BusyButton busy={busy} onClick={onBuild}><WandSparkles size={16} />生成目录</BusyButton></div>{project.sections.length ? <div className="outline-list">{project.sections.map((item) => <article key={item.id}><span>{String(item.order_no).padStart(2, "0")}</span><div><strong>{item.title}</strong><small>关联{item.requirement_ids.length}项要求</small></div><Status value={item.status} /></article>)}</div> : <Empty title="目录尚未生成" detail="完成招标解析后生成11类标准章节。" />}</section>;
}

function Editor({ project, reload, setMessage }) {
  const [selectedId, setSelectedId] = useState(project.sections[0]?.id || null); const [content, setContent] = useState(""); const [busy, setBusy] = useState(false); const [reviewer, setReviewer] = useState("技术负责人");
  const selected = project.sections.find((item) => item.id === selectedId);
  useEffect(() => { setContent(selected?.draft?.content || ""); }, [selectedId, selected?.draft?.id]);
  async function generate() { if (!selected) return; setBusy(true); try { await post(`/api/projects/${project.id}/sections/${selected.id}/generate`, {}); await reload(); setMessage("章节草稿已生成，并记录正式知识来源。"); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function save() { if (!selected?.draft) return; setBusy(true); try { await patch(`/api/projects/drafts/${selected.draft.id}`, { content }); await reload(); setMessage("章节已保存，旧质量确认已失效。"); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function confirm() { if (!selected?.draft) return; setBusy(true); try { await post(`/api/projects/drafts/${selected.draft.id}/confirm`, { reviewer }); await reload(); setMessage("本章待确认项已由人工确认。"); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function generateAll() { setBusy(true); try { const result = await post(`/api/projects/${project.id}/generate-all`, {}); await reload(); setMessage(`批量生成完成：成功${result.generated}章，失败${result.failed}章。`); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  if (!project.sections.length) return <section className="panel"><Empty title="请先生成目录" /></section>;
  return <section className="editor-layout"><aside className="chapter-list"><div className="chapter-tools"><BusyButton busy={busy} onClick={generateAll}><WandSparkles size={16} />生成全部章节</BusyButton></div>{project.sections.map((item) => <button key={item.id} className={selectedId === item.id ? "active" : ""} onClick={() => setSelectedId(item.id)}><span>{item.order_no}</span><div><strong>{item.title}</strong><small>{item.requirement_ids.length}项要求</small></div><Status value={item.status} /></button>)}</aside><article className="panel editor-main"><div className="editor-head"><div><span className="eyebrow">第{selected?.order_no}章</span><h2>{selected?.title}</h2></div><div className="actions"><BusyButton busy={busy} className="secondary" onClick={generate}><WandSparkles size={16} />生成本章</BusyButton><BusyButton busy={busy} className="secondary" onClick={confirm} disabled={!selected?.draft || !selected.draft.confirmations.length}>人工确认</BusyButton><BusyButton busy={busy} onClick={save} disabled={!selected?.draft}><Save size={16} />保存</BusyButton></div></div>{selected?.draft ? <><div className="reviewer-inline"><label>确认人<input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label></div><textarea className="chapter-editor" value={content} onChange={(event) => setContent(event.target.value)} /><div className="citation-strip"><strong>知识来源</strong><span>{selected.draft.citations.length}项正式知识</span><span>{selected.draft.confirmations.length}项待确认</span></div></> : <Empty title="本章尚未生成" detail="生成前必须确保正式知识库已有匹配内容。" />}</article></section>;
}

function ProjectQuality({ project }) {
  const [report, setReport] = useState(null); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  async function check() { setBusy(true); try { setReport(await api(`/api/projects/${project.id}/quality`)); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  async function exportFile(format) { setBusy(true); try { const result = await post(`/api/projects/${project.id}/export`, { format }); setMessage(`已导出：${result.file_path}`); } catch (error) { setMessage(error.message); } finally { setBusy(false); } }
  useEffect(() => { check(); }, [project.id]);
  return <section className="panel"><div className="panel-title"><div><ShieldCheck size={18} /><h2>正式交付门禁</h2></div><div className="actions"><BusyButton busy={busy} className="secondary" onClick={check}><CheckCheck size={16} />重新检查</BusyButton><BusyButton busy={busy} onClick={() => exportFile("docx")} disabled={!report?.ready}><Download size={16} />导出DOCX</BusyButton></div></div>{message && <Notice>{message}</Notice>}{report && <><div className="metric-grid four"><Metric label="质量分" value={report.score} tone={report.ready ? "success" : "warning"} /><Metric label="章节草稿" value={`${report.metrics.drafts}/${report.metrics.sections}`} /><Metric label="条款覆盖" value={`${report.metrics.coverage}%`} /><Metric label="失效引用" value={report.metrics.invalid_citations} tone={report.metrics.invalid_citations ? "danger" : "success"} /></div><div className="gate-result"><div className={report.ready ? "gate-badge ready" : "gate-badge blocked"}>{report.ready ? "可正式交付" : "尚未通过门禁"}</div>{report.blockers.map((item) => <article key={item.key}><strong>{item.title}</strong><span>{item.detail}</span></article>)}</div></>}</section>;
}
