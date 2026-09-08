import React, { useEffect, useState } from "react";
import { BookOpenText, CheckCheck, Link2, WandSparkles } from "lucide-react";
import { api, post } from "../api";
import { BusyButton, Empty, Notice } from "../components";

const categories = { technical: "技术要求", qualification: "资格资料", commercial: "商务条款", contract: "合同条款", reference: "参考信息", unclassified: "待分类" };
const kinds = { technical: "技术要求", veto: "限制与否决条款", scoring: "评分点", qualification: "资格要求", commitment: "履约承诺", parameter: "参数要求", deliverable: "交付资料", confirmation: "待确认要求" };
const reviewLabels = { pending: "分类待人工确认", confirmed: "分类已人工确认", stale: "原文或条款已变化，需重新确认" };
const reviewLabel = (item) => item?.classification?.status !== "confirmed" && item?.classification?.status !== "stale" && item?.planning_category === "technical" ? "技术范围建议，待章节核对" : reviewLabels[item?.classification?.status || "pending"];

export default function ProjectRequirements({ project, onParse, busy: parsing, reload, focus }) {
  const [workflow, setWorkflow] = useState(null);
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState(focus?.requirementId || null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const [category, setCategory] = useState("unclassified");
  const [reason, setReason] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [applicability, setApplicability] = useState("applicable");
  const [response, setResponse] = useState("");
  const [basis, setBasis] = useState("");
  const [sectionIds, setSectionIds] = useState([]);
  const [responseSectionId, setResponseSectionId] = useState("");
  const [evidenceText, setEvidenceText] = useState("");
  const root = `/api/projects/${project.id}/requirements`;
  const hasDrafts = project.sections.some((section) => section.draft);
  async function refresh() { const result = await api(`${root}/workflow`); setWorkflow(result); return result; }
  useEffect(() => { refresh().catch((error) => { setFailed(true); setMessage(error.message); }); }, [project]);
  useEffect(() => { if (focus?.requirementId) { setSelectedId(focus.requirementId); setFilter("all"); } }, [focus]);
  const items = workflow?.items || project.requirements;
  const pendingIds = workflow?.metrics?.scope_pending_ids || [];
  const visible = items.filter((item) => filter === "all" || (filter === "scope_pending" ? pendingIds.includes(item.id) : (item.planning_category || item.classification?.suggested_category || "unclassified") === filter));
  const selected = visible.find((item) => item.id === selectedId) || visible[0];
  useEffect(() => {
    const record = selected?.classification || {};
    setCategory(record.category || record.suggested_category || "unclassified");
    setReason(record.review_reason || ""); setReviewer("");
    setApplicability(record.applicability || "applicable"); setResponse(record.response_text || ""); setBasis(record.basis_text || "");
    setSectionIds(selected?.section_ids || []);
    setResponseSectionId(String((selected?.section_ids || []).find((id) => project.sections.some((section) => section.id === id && section.draft)) || "")); setEvidenceText("");
  }, [selected?.id, selected?.requirement_fingerprint]);
  async function run(name, action) {
    setBusy(name); setFailed(false); setMessage("");
    try { const result = await action(); setWorkflow(result); setReviewer(""); await reload(); setMessage(name === "response" ? "已记录本条对应的正文片段，章节内容已保留；请重新核对并签审本章。" : name === "reload" ? "已重新载入当前条款，请按最新原文重新核对。" : name === "mapping" ? "章节映射已保存，现有正文已保留；相关章节需要重新核对签审。" : name === "suggestions" ? "分类建议已刷新，请由实际复核人逐条确认。" : "本条复核记录已保存。资料未齐备的条款仍保留为待处理。"); }
    catch (error) { setFailed(true); setMessage(error.message); }
    finally { setBusy(""); }
  }
  async function review(event) {
    event.preventDefault();
    await run("review", () => post(`${root}/review`, { reviewer: reviewer.trim(), expected_project_hash: workflow.project_hash, items: [{ requirement_id: selected.id, expected_fingerprint: selected.requirement_fingerprint, category, reason: reason.trim(), applicability, response_text: response.trim(), basis_text: basis.trim() }] }));
  }
  const classification = selected?.classification || {};
  const nontechnical = ["qualification", "commercial", "contract"].includes(category);
  const responseStatusLabel = classification.category === "reference" ? "作为参考信息保留原文" : classification.category === "technical" ? "技术响应与签审在章节中处理" : classification.response_status === "responded" ? "已登记资料响应" : classification.response_status === "not_applicable" ? "已说明不适用依据" : "资料响应仍待补充";
  const disabled = Boolean(busy) || parsing || !workflow;
  const responseSection = project.sections.find((section) => String(section.id) === responseSectionId);
  return <section className="panel requirements-panel">
    <div className="panel-title"><div><BookOpenText size={18} /><h2>要求与评分点</h2></div><div className="actions"><BusyButton busy={busy === "suggestions"} disabled={disabled} className="secondary" onClick={() => run("suggestions", () => post(`${root}/suggestions`, {}))}>刷新分类建议</BusyButton><BusyButton busy={parsing} disabled={hasDrafts || Boolean(busy)} onClick={onParse}><WandSparkles size={16} />重新解析</BusyButton></div></div>
    <p className="form-help">系统分类只是建议。请结合原文确认技术、资格、商务、合同和参考范围，再补正文或真实资料。{hasDrafts ? "已有章节正文，重新解析已锁定；分类与章节映射仍可补充，现有草稿会保留。" : ""}</p>
    {message && <Notice type={failed ? "danger" : "info"}>{message}{failed && <button type="button" className="secondary inline-reload" onClick={() => run("reload", refresh)}>重新载入条款</button>}</Notice>}
    <div className="scope-filters" aria-label="条款分类筛选">{Object.entries({ all: "全部条款", ...categories, ...(workflow?.metrics?.scope_pending_ids ? { scope_pending: "需确认范围" } : {}) }).map(([key, label]) => <button key={key} type="button" aria-pressed={filter === key} className={filter === key ? "active" : "secondary"} onClick={() => { setFilter(key); setSelectedId(null); }}>{label}<span>{key === "all" ? items.length : key === "scope_pending" ? pendingIds.length : items.filter((item) => (item.planning_category || item.classification?.suggested_category || "unclassified") === key).length}</span></button>)}</div>
    {visible.length ? <div className="requirements-workspace"><div className="requirement-selector" aria-label="条款列表">{visible.map((item) => <button key={item.id} type="button" className={selected?.id === item.id ? "active" : ""} onClick={() => setSelectedId(item.id)}><span className="requirement-key">{item.requirement_key}</span><strong>{item.content}</strong><small>{categories[item.planning_category || item.classification?.suggested_category || "unclassified"]} · {reviewLabel(item)}</small></button>)}</div>
      {selected && <article className="requirement-detail">
        <div className="detail-title"><div><span className="requirement-key">{selected.requirement_key}</span><h3>条款原文与响应</h3></div><span className={`status status-${classification.status === "confirmed" ? "success" : "warning"}`}>{reviewLabel(selected)}</span></div>
        <div className="requirement-meta"><span>{kinds[selected.kind] || selected.kind}</span><span>{selected.source_page ? `原文件第 ${selected.source_page} 页` : "来源页码待核对"}</span><span>{selected.priority === "high" ? "高优先级" : "普通优先级"}</span></div>
        <p>{selected.content}</p>
        <div className="source-excerpt"><strong>本项目招标原文摘录</strong><blockquote>{classification.suggestion_excerpt || selected.content}</blockquote></div>
        <p className="classification-reason"><strong>系统建议：{categories[classification.suggested_category || "unclassified"]}</strong><span>{classification.suggestion_reason || "尚无分类理由，请结合原文人工判断。"}</span></p>
        {selected.planning_category === "technical" && classification.status === "pending" && <p className="form-help">本条按技术要求编制，可在章节中核对和签审；若要移出技术范围，需在此由实际复核人确认分类。</p>}
        {classification.reviewer && <p className="form-help">上次复核：{classification.reviewer}{classification.reviewed_at ? ` · ${classification.reviewed_at}` : ""}。{responseStatusLabel}。</p>}
        <form className="requirement-review" onSubmit={review}>
          <div className="form-grid"><label>人工确认分类<select value={category} onChange={(event) => { setCategory(event.target.value); if (event.target.value === "technical") setApplicability("applicable"); }}>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>本次条款复核人<input value={reviewer} placeholder="填写实际复核人姓名" onChange={(event) => setReviewer(event.target.value)} /></label></div>
          <label>分类核对理由<textarea rows="2" minLength={6} value={reason} placeholder="说明本条为何属于该范围，请结合原文，至少6字" onChange={(event) => setReason(event.target.value)} /></label>
          {category === "reference" && <p className="form-help">参考信息保留原文。请说明为何作为参考范围，保存前不会自动移出技术响应检查。</p>}
          {nontechnical && <><label>适用情况<select value={applicability} onChange={(event) => setApplicability(event.target.value)}><option value="applicable">适用，需要回应或资料</option><option value="not_applicable">不适用，需要说明依据</option></select></label><label>实际响应或资料说明<textarea rows="3" value={response} placeholder="填写已核对的资格、商务或合同响应，未取得资料请保持待处理" onChange={(event) => setResponse(event.target.value)} /></label><label>资料出处或不适用依据<textarea rows="2" value={basis} placeholder="填写真实文件、证照、原文页码或不适用依据" onChange={(event) => setBasis(event.target.value)} /></label><p className="form-help">只确认分类不会自动认定资料已齐备。资料响应和依据必须由实际责任人核实。</p></>}
          <BusyButton type="submit" busy={busy === "review"} disabled={disabled || !reviewer.trim() || !reason.trim() || category === "unclassified" || (applicability === "not_applicable" && !basis.trim())}><CheckCheck size={16} />保存本条人工复核</BusyButton>
        </form>
        {["technical", "unclassified"].includes(selected.planning_category || "unclassified") && <>
          <div className="mapping-panel"><h3>补充章节映射</h3><p className="form-help">勾选本条应回应的章节。保存映射保留现有正文，已有签审须重新核对。</p><div className="mapping-options">{project.sections.map((section) => <label className="confirmation-check" key={section.id}><input type="checkbox" checked={sectionIds.includes(section.id)} onChange={(event) => setSectionIds(event.target.checked ? [...sectionIds, section.id] : sectionIds.filter((id) => id !== section.id))} /><span>第 {section.order_no} 章 · {section.title}</span></label>)}</div><BusyButton type="button" className="secondary" busy={busy === "mapping"} disabled={disabled || !reviewer.trim() || !selected.requirement_fingerprint || !project.sections.length} onClick={() => run("mapping", () => api(`${root}/${selected.id}/mapping`, { method: "PUT", body: JSON.stringify({ reviewer: reviewer.trim(), expected_fingerprint: selected.requirement_fingerprint, section_ids: sectionIds }) }))}><Link2 size={16} />保存章节映射</BusyButton><p className="form-help">使用上方“本次条款复核人”记录实际操作人。</p></div>
          <form className="mapping-panel requirement-review" onSubmit={(event) => { event.preventDefault(); run("response", () => post(`${root}/${selected.id}/response`, { draft_id: responseSection.draft.id, reviewer: reviewer.trim(), target_hash: responseSection.draft.content_hash, requirement_fingerprint: selected.requirement_fingerprint, evidence_text: evidenceText.trim() })); }}>
            <h3>从现有正文补充响应定位</h3><p className="form-help">正文已经回应本条但尚未被定位时，可选取当前正文中的逐字片段，保留已有内容；记录后仍需章节签审。</p>
            <label>对应的已映射章节<select value={responseSectionId} onChange={(event) => { setResponseSectionId(event.target.value); setEvidenceText(""); }}><option value="">请选择已有正文的章节</option>{project.sections.filter((section) => selected.section_ids?.includes(section.id) && section.draft).map((section) => <option key={section.id} value={section.id}>第 {section.order_no} 章 · {section.title}</option>)}</select></label>
            {responseSection?.draft && <details className="book-preview"><summary>查看该章当前正文</summary><pre>{responseSection.draft.content}</pre></details>}
            <label>回应本条的正文原句<textarea rows="3" maxLength={500} placeholder="粘贴当前正文中的逐字片段，12至500字" value={evidenceText} onChange={(event) => setEvidenceText(event.target.value)} /></label>
            <BusyButton type="submit" className="secondary" busy={busy === "response"} disabled={disabled || !reviewer.trim() || !responseSection?.draft || evidenceText.trim().length < 12 || !selected.requirement_fingerprint}>记录正文响应片段</BusyButton><p className="form-help">使用上方“本次条款复核人”，并绑定当前正文和条款版本。</p>
          </form>
        </>}
      </article>}
    </div> : <Empty title={items.length ? "此分类暂无条款" : "尚未提取要求"} detail={items.length ? "可选择其他分类继续核对。" : "保存招标文本后执行解析。"} />}
  </section>;
}
