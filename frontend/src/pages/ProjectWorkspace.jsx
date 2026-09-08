import React, { useEffect, useState } from "react";
import { ArrowLeft, CheckCheck, ListTree, Save, WandSparkles } from "lucide-react";
import { api, patch, post, waitForJob } from "../api";
import { BusyButton, Empty, Notice, PageHeader, Status, Tabs } from "../components";
import ProjectDelivery from "./ProjectDelivery";
import ProjectProfile from "./ProjectProfile";
import ProjectRequirements from "./ProjectRequirements";
import ProjectRemediation, { generationMessage } from "./ProjectRemediation";

const tabs = [{ key: "overview", label: "项目资料" }, { key: "requirements", label: "招标解析" }, { key: "outline", label: "目录策略" }, { key: "editor", label: "章节编制" }, { key: "remediation", label: "处理待办" }, { key: "quality", label: "质量交付" }];

export default function ProjectWorkspace({ projectId }) {
  const [focus, setFocus] = useState(null);
  const [project, setProject] = useState(null); const [tab, setTab] = useState("overview"); const [message, setMessage] = useState(""); const [busy, setBusy] = useState("");
  async function load() { const result = await api(`/api/projects/${projectId}`); setProject(result); return result; }
  function navigate(nextTab, target) { setFocus(target || null); setTab(nextTab); }
  async function action(name, fn) { setBusy(name); try { const result = await fn(); await waitForJob(result, { onProgress: (job) => setMessage(`正在处理 · ${job.progress}%`) }); await load(); setMessage("操作已完成。"); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, [projectId]);
  if (!project) return <Empty title="正在加载项目" />;
  return <>
    <a className="back-link" href="#/projects"><ArrowLeft size={15} />返回项目列表</a>
    <PageHeader eyebrow={`${project.industry || "通用"} · ${project.project_type || "技术标"}`} title={project.name} description={`${project.region || "未设置地区"} · ${project.requirements.length}项要求 · ${project.sections.length}个章节`} actions={<Status value={project.status} />} />
    <Tabs items={tabs} active={tab} onChange={navigate} />
    {message && <Notice type={/失败|不能|没有|已变化|已失效|不一致/.test(message) ? "danger" : "info"}>{message}{/变化|版本|重新载入|重新加载|不一致/.test(message) && <button type="button" className="secondary inline-reload" onClick={() => load().then(() => setMessage("已重新载入当前项目，请重新核对后操作。")).catch((error) => setMessage(error.message))}>重新载入项目</button>}</Notice>}
    {tab === "overview" && <ProjectProfile project={project} onSave={(payload) => action("save", () => patch(`/api/projects/${projectId}`, payload))} busy={busy === "save"} />}
    {tab === "requirements" && <ProjectRequirements project={project} reload={load} focus={focus} onParse={() => action("parse", () => post(`/api/projects/${projectId}/requirements/parse`, {}))} busy={busy === "parse"} />}
    {tab === "outline" && <Outline project={project} onBuild={() => action("outline", () => post(`/api/projects/${projectId}/outline`, {}))} busy={busy === "outline"} />}
    {tab === "editor" && <Editor project={project} reload={load} setMessage={setMessage} focus={focus} onNavigate={navigate} />}
    {tab === "remediation" && <ProjectRemediation project={project} reload={load} onNavigate={navigate} />}
    {tab === "quality" && <ProjectDelivery project={project} reload={load} onNavigate={navigate} />}
  </>;
}

function Outline({ project, onBuild, busy }) {
  const hasDrafts = project.sections.some((section) => section.draft);
  return <section className="panel"><div className="panel-title"><div><ListTree size={18} /><h2>技术标目录</h2></div><BusyButton busy={busy} disabled={hasDrafts} onClick={onBuild}><WandSparkles size={16} />生成目录</BusyButton></div>{hasDrafts && <p className="form-help">已有章节正文，目录重建已锁定，保留当前草稿和签审记录。</p>}{project.sections.length ? <div className="outline-list">{project.sections.map((item) => <article key={item.id}><span>{String(item.order_no).padStart(2, "0")}</span><div><strong>{item.title}</strong><small>关联{item.requirement_ids.length}项要求</small></div><Status value={item.status} /></article>)}</div> : <Empty title="目录尚未生成" detail="完成招标解析后生成11类标准章节。" />}</section>;
}

function Editor({ project, reload, setMessage, focus, onNavigate }) {
  const [selectedId, setSelectedId] = useState(focus?.sectionId || project.sections[0]?.id || null);
  const [content, setContent] = useState(""); const [busy, setBusy] = useState(""); const [reviewer, setReviewer] = useState(""); const [resolutions, setResolutions] = useState([]);
  const selected = project.sections.find((item) => item.id === selectedId) || project.sections[0];
  useEffect(() => { if (focus?.sectionId) setSelectedId(focus.sectionId); }, [focus]);
  useEffect(() => {
    setContent(selected?.draft?.content || ""); setReviewer("");
    const existing = Object.fromEntries((selected?.draft?.confirmation_resolutions || []).map((item) => [item.confirmation_index, item.resolution]));
    setResolutions((selected?.draft?.confirmations || []).map((_, index) => existing[index] || ""));
  }, [selected?.id, selected?.draft?.id, selected?.draft?.content_hash, JSON.stringify(selected?.draft?.confirmations || []), JSON.stringify(selected?.draft?.confirmation_required_indices)]);
  async function run(name, action) { setBusy(name); try { await action(); } catch (error) { setMessage(error.message); } finally { setBusy(""); } }
  async function generate(repair = false) {
    if (!selected) return;
    await run(repair ? "repair" : "generate", async () => {
      const result = await waitForJob(await post(`/api/projects/${project.id}/sections/${selected.id}/${repair ? "repair" : "generate"}`, { background: true, ...(repair ? { target_hash: selected.draft.content_hash } : {}) }), { onProgress: (job) => setMessage(`${job.stage} · ${job.progress}%`) });
      const updated = await reload();
      setMessage(generationMessage(updated.sections.find((item) => item.id === selected.id)?.draft || result.draft || result));
    });
  }
  async function save() { if (!selected?.draft) return; await run("save", async () => { await patch(`/api/projects/drafts/${selected.draft.id}`, { content }); await reload(); setMessage("章节已保存，旧质量确认已失效。请重新核对证据后签审。"); }); }
  async function confirm() { if (!selected?.draft) return; await run("confirm", async () => { await post(`/api/projects/drafts/${selected.draft.id}/confirm`, { reviewer: reviewer.trim(), target_hash: selected.draft.content_hash, resolutions: requiredIndices.map((index) => ({ index, resolution: resolutions[index] })) }); await reload(); setReviewer(""); setMessage("本章已逐项处理待确认事项，并绑定当前正文完成签审。"); }); }
  async function generateMissing() {
    await run("missing", async () => {
      let generated = 0; let failed = 0;
      for (const section of project.sections.filter((item) => !item.draft)) {
        try { await waitForJob(await post(`/api/projects/${project.id}/sections/${section.id}/generate`, { background: true }), { onProgress: (job) => setMessage(`第 ${section.order_no} 章 · ${job.progress}%`) }); generated += 1; }
        catch { failed += 1; }
      }
      await reload(); setMessage(`未编制章节处理完成：返回草稿 ${generated} 章，任务失败 ${failed} 章。已有章节已保留，请到处理待办核对草稿完整性与证据。`);
    });
  }
  if (!project.sections.length) return <section className="panel"><Empty title="请先生成目录" /></section>;
  const draft = selected?.draft;
  const hasUnsavedChanges = Boolean(draft && content !== draft.content);
  const requiredIndices = draft?.confirmation_required_indices ?? (draft?.confirmations || []).map((_, index) => index);
  const resolutionsComplete = requiredIndices.every((index) => resolutions[index]?.trim());
  const resolvedIndices = new Set((draft?.confirmation_resolutions || []).map((item) => item.confirmation_index));
  const unresolvedCount = requiredIndices.filter((index) => !resolvedIndices.has(index)).length;
  const generationStatus = draft?.generation?.status || draft?.generation_status;
  const generationLabels = { ai: "AI 草稿已生成，待核验", fallback: "回退草稿，需补写核对", incomplete: "部分生成失败或漏回应", ai_incomplete: "部分生成失败或漏回应", partial: "部分生成失败或漏回应", partial_fallback: "部分内容使用回退草稿，需补写核对", legacy: "旧版草稿，生成过程尚无分段记录", manual_edit: "人工修改后，待核验" };
  const sourceStale = project.evidence_source?.stale_draft_ids?.includes(draft?.id) || draft?.claims?.some((claim) => claim.source_stale);
  const missingResponseIds = draft?.missing_response_requirement_ids || [];
  const machineBlocked = Boolean(missingResponseIds.length || draft?.generation?.can_repair || ["fallback", "incomplete", "ai_incomplete", "partial", "partial_fallback"].includes(generationStatus) || draft?.claims?.some((claim) => claim.risk_level === "high" && ["unsupported", "invalidated"].includes(claim.support_status)));
  return <section className="editor-layout"><aside className="chapter-list"><div className="chapter-tools"><BusyButton busy={busy === "missing"} disabled={Boolean(busy) || project.sections.every((item) => item.draft)} onClick={generateMissing}><WandSparkles size={16} />生成未编制章节</BusyButton><button type="button" className="secondary" onClick={() => onNavigate("remediation")}>打开处理待办</button></div>{project.sections.map((item) => <button key={item.id} className={selected?.id === item.id ? "active" : ""} onClick={() => setSelectedId(item.id)}><span>{item.order_no}</span><div><strong>{item.title}</strong><small>{item.requirement_ids.length}项要求{item.draft?.generation?.can_repair ? " · 可补写" : ""}</small></div><Status value={item.status} /></button>)}</aside>
    <article className="panel editor-main"><div className="editor-head"><div><span className="eyebrow">第{selected?.order_no}章</span><h2>{selected?.title}</h2></div><div className="actions">
      {draft?.generation?.can_repair && <BusyButton busy={busy === "repair"} disabled={Boolean(busy) || hasUnsavedChanges} onClick={() => generate(true)}>仅补写失败部分</BusyButton>}
      {draft?.generation?.repair_blocked ? <button type="button" className="secondary" onClick={() => { const editor = document.querySelector(".chapter-editor"); editor?.scrollIntoView({ block: "center", behavior: "smooth" }); editor?.focus(); }}>继续人工补写</button> : <BusyButton busy={busy === "generate"} disabled={Boolean(busy) || hasUnsavedChanges} className="secondary" onClick={() => generate(false)}><WandSparkles size={16} />{draft ? "重试本章" : "生成本章"}</BusyButton>}
      <BusyButton busy={busy === "confirm"} className="secondary" onClick={confirm} disabled={Boolean(busy) || !draft || hasUnsavedChanges || !resolutionsComplete || !reviewer.trim() || sourceStale || machineBlocked}><CheckCheck size={16} />{draft?.status === "reviewed" ? "重新签审" : "签审本章"}</BusyButton>
      <BusyButton busy={busy === "save"} onClick={save} disabled={Boolean(busy) || !draft || !hasUnsavedChanges}><Save size={16} />保存</BusyButton>
    </div></div>
    {draft ? <>
      {generationStatus && <Notice type={["ai", "legacy", "manual_edit"].includes(generationStatus) ? "info" : "danger"}>{generationLabels[generationStatus] || "生成情况需核对"}。生成草稿不会自动认定证据成立或完成签审。</Notice>}
      {draft.generation?.repair_blocked && <Notice>{draft.generation.repair_blocked_reason || "已记录的人工响应需要保留，请继续人工补写或定位现有正文响应。"}</Notice>}
      {machineBlocked && <p className="form-help">请先处理生成失败、正文响应未定位或高风险表述缺少依据的问题，再签审本章。这些问题在待办与证据核验中处理，无需重复填写资料确认。</p>}
      {missingResponseIds.length > 0 && <details className="response-gaps"><summary>{missingResponseIds.length} 条要求尚未定位正文响应</summary><p className="form-help">正文已回应时，可记录现有正文片段；尚未回应时，请先补写并保存。</p><div>{missingResponseIds.map((id) => { const requirement = project.requirements.find((item) => item.id === id); return <button key={id} type="button" className="secondary" disabled={hasUnsavedChanges} onClick={() => onNavigate("requirements", { requirementId: id })}>{requirement?.requirement_key || `条款 ${id}`} · 定位正文响应<span>{requirement?.content}</span></button>; })}</div></details>}
      {sourceStale && <Notice type="danger">招标原文或项目依据已变化，旧证据已失效。请到处理待办重新核对原文证据，再由实际责任人签审。<button type="button" className="secondary inline-reload" onClick={() => onNavigate("remediation")}>打开处理待办</button></Notice>}
      <div className="reviewer-inline"><label>本章签审人<input placeholder="填写实际签审人姓名" value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label></div>
      <textarea aria-label="本章正文" className="chapter-editor" value={content} onChange={(event) => setContent(event.target.value)} />
      {requiredIndices.length > 0 && <div className="confirmation-panel"><h3>实际资料与方案确认</h3>{requiredIndices.map((index) => <label key={`${draft.id}-${index}`}><span>{index + 1}. {draft.confirmations[index]}</span><textarea rows="2" placeholder="填写核实结果或处理结论" value={resolutions[index] || ""} onChange={(event) => setResolutions(resolutions.map((value, itemIndex) => itemIndex === index ? event.target.value : value))} /></label>)}</div>}
      {hasUnsavedChanges && <Notice type="danger">正文有未保存修改，请先保存再签审或重试。</Notice>}
      <div className="citation-strip"><strong>来源与人工处理</strong><span>{draft.citations?.length || 0}项知识库引用</span><span>{unresolvedCount}项待处理</span><span>{requiredIndices.length - unresolvedCount}项已处理</span><Status value={sourceStale ? "invalidated" : draft.evidence_status} /></div>
      <EvidencePanel project={project} draft={draft} claims={draft.claims || []} focus={focus} disabled={hasUnsavedChanges} onChanged={reload} setMessage={setMessage} />
    </> : <Empty title="本章尚未生成" detail="生成后仍需核对本项目原文、正文完整性与真实资料。" />}</article>
  </section>;
}

function EvidencePanel({ project, draft, claims, focus, disabled, onChanged, setMessage }) {
  const [selectedId, setSelectedId] = useState(focus?.claimId || claims[0]?.id || null);
  const [reviewer, setReviewer] = useState(""); const [resolution, setResolution] = useState(""); const [busy, setBusy] = useState(false);
  const selected = claims.find((item) => item.id === selectedId) || claims[0];
  useEffect(() => { if (focus?.claimId) setSelectedId(focus.claimId); }, [focus]);
  useEffect(() => { setReviewer(""); setResolution(""); }, [selected?.id, draft.content_hash, selected?.current_project_source_hash]);
  async function resolve(action) {
    if (!selected) return; setBusy(true);
    try { await post(`/api/projects/claims/${selected.id}/resolve`, { action, resolution: resolution.trim(), reviewer: reviewer.trim(), target_hash: selected.draft_content_hash || draft.content_hash, project_source_hash: selected.current_project_source_hash || project.evidence_source?.current_project_source_hash }); await onChanged(); setReviewer(""); setResolution(""); setMessage("表述核验结论已绑定当前正文与项目原文记录。"); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  if (!claims.length) return null;
  return <section className="evidence-panel"><div className="evidence-list">{claims.map((claim) => <button type="button" key={claim.id} className={selected?.id === claim.id ? "active" : ""} onClick={() => setSelectedId(claim.id)}><span className={`risk-dot risk-${claim.risk_level}`} /><span>{claim.text}</span><Status value={claim.source_stale ? "invalidated" : claim.support_status} /></button>)}</div>
    {selected && <aside className="evidence-source"><div className="detail-title"><div><span className="eyebrow">{selected.risk_level === "high" ? "高风险表述" : selected.risk_level === "medium" ? "需核对表述" : "一般表述"}</span><h2>证据核验</h2></div><Status value={selected.source_stale ? "invalidated" : selected.support_status} /></div><p>{selected.text}</p>
      <p className="form-help">原文匹配和检索相似度只帮助定位依据，不代表专业人员已认可。请同时核对对象、数值和适用条件。</p>
      {selected.analysis?.reason && <p className="analysis-reason"><strong>本条核验说明：</strong>{selected.analysis.reason}</p>}
      {selected.analysis?.assertions?.length > 0 && <div className="assertion-list">{selected.analysis.assertions.map((item, index) => <article key={index}><strong>{item.text}</strong><span className={item.supported ? "assertion-supported" : "assertion-missing"}>{item.supported ? "已匹配依据" : "仍缺依据"} · {item.reason}</span></article>)}</div>}
      {selected.source_stale && <Notice type="danger">{selected.source_stale_reason || "来源已变化，请重新核对原文证据。"}</Notice>}
      {!selected.evidence?.length && <p className="form-help">尚无匹配依据，需要补充真实资料或修改正文。</p>}
      {selected.evidence?.map((item) => <article key={item.id}><span className="evidence-origin">{item.source_kind === "project_tender" ? "本项目招标原文" : ["knowledge_publication", "knowledge_reference"].includes(item.source_kind) ? "知识库参考来源" : "来源类型待核对"}</span><strong>{item.source_title || item.unit_title || item.file_name || "项目输入"}</strong><small>{item.file_name || ""}{item.source_page ? ` · 第 ${item.source_page} 页` : " · 页码待核对"}</small><blockquote>{item.source_excerpt || item.excerpt}</blockquote><span>匹配原因：{item.match_reason || item.source_meta?.match_reason || "需结合原文人工核验"}</span>{item.source_meta?.supported === false && <span className="assertion-missing">此来源尚未满足本条核验条件</span>}{typeof item.score === "number" && <span>检索匹配度 {Math.round(item.score * 100)}%（辅助定位）</span>}</article>)}
      <form className="evidence-review" onSubmit={(event) => { event.preventDefault(); resolve("confirm"); }}><label>本次证据核验人<input placeholder="填写实际核验人姓名" value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label><label>核验依据与结论<textarea rows="3" placeholder="填写核对的原文页码、实际资料及结论" value={resolution} onChange={(event) => setResolution(event.target.value)} /></label><div className="actions"><BusyButton type="submit" busy={busy} disabled={disabled || selected.source_stale || !(selected.current_project_source_hash || project.evidence_source?.current_project_source_hash) || !reviewer.trim() || !resolution.trim()}>确认本条依据</BusyButton>{selected.support_status === "confirmed" && <BusyButton type="button" className="secondary" busy={busy} disabled={disabled || !reviewer.trim() || !resolution.trim()} onClick={() => resolve("reopen")}>撤回本条核验</BusyButton>}<button type="button" className="secondary" onClick={() => { const editor = document.querySelector(".chapter-editor"); editor?.scrollIntoView({ block: "center", behavior: "smooth" }); editor?.focus(); }}>修改正文</button></div></form>
    </aside>}
  </section>;
}
