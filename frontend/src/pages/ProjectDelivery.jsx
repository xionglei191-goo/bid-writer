import React, { useEffect, useState } from "react";
import { BookOpenText, CheckCheck, Download, History, ShieldCheck } from "lucide-react";
import { api, apiUrl, post, waitForJob } from "../api";
import { BusyButton, Empty, Metric, Notice } from "../components";

const formats = [["docx", "Word"], ["pdf", "PDF"], ["package", "交付包"]];
const profileIssues = new Set(["bidder_identity", "professional_reviewer", "seal_requirements", "delivery_deadline"]);

function IssueList({ items = [], onNavigate }) {
  return items.map((item) => <article key={`${item.key}-${item.detail}`}>
    <strong>{item.title}</strong><span>{item.detail}</span>
    {profileIssues.has(item.key) && <button className="secondary" onClick={() => onNavigate("overview")}>补充项目资料</button>}
    {["missing_sections", "unreviewed_drafts", "confirmations", "unsupported_high_claims", "coverage", "invalid_citations", "artifact_audit"].includes(item.key) && <button className="secondary" onClick={() => onNavigate("editor")}>核对章节与证据</button>}
  </article>);
}

function FileLink({ item, label }) {
  if (!item?.download_url || item.available === false) return <span className="form-help">文件暂不可下载</span>;
  return <a className="delivery-download" href={apiUrl(item.download_url)}><Download size={16} />{label || item.file_name || "下载文件"}</a>;
}

export default function ProjectDelivery({ project, reload, onNavigate }) {
  const [report, setReport] = useState(null);
  const [deliveries, setDeliveries] = useState([]);
  const [latest, setLatest] = useState(null);
  const [preview, setPreview] = useState(null);
  const [reviewer, setReviewer] = useState("");
  const [compliance, setCompliance] = useState(false);
  const [finalized, setFinalized] = useState(false);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const root = `/api/projects/${project.id}`;

  function clearConfirmation() { setPreview(null); setReviewer(""); setCompliance(false); setFinalized(false); }
  async function refresh() {
    const [quality, history] = await Promise.all([api(`${root}/quality`), api(`${root}/deliveries`)]);
    setReport(quality); setDeliveries(history);
  }
  async function run(name, action) {
    setBusy(name); setFailed(false); setMessage("");
    try { await action(); }
    catch (error) { setFailed(true); setMessage(error.message); }
    finally { setBusy(""); }
  }
  async function check() {
    clearConfirmation(); setReport(null);
    await run("check", refresh);
  }
  useEffect(() => { setLatest(null); check(); }, [project.id]);

  async function openPreview() {
    clearConfirmation();
    await run("preview", async () => {
      setPreview(await api(`${root}/preview`));
      setMessage("已载入整本正文。请核对章节、参数和评分点；Word / PDF 的实际分页请下载送审文件查看。");
    });
  }
  async function confirmFinal() {
    if (!preview || !reviewer.trim() || !compliance || !finalized) return;
    await run("confirm", async () => {
      const result = await post(`${root}/final-review`, {
        project_hash: preview.project_hash, professional_reviewer: reviewer.trim(),
        compliance_confirmed: compliance, manual_finalized: finalized,
      });
      setPreview(result); setCompliance(false); setFinalized(false); setReviewer("");
      await reload(); await refresh();
      setMessage("整本复核和定稿已记录，已重新检查正式交付条件。");
    });
  }
  async function exportFile(format, mode) {
    await run(`${mode}-${format}`, async () => {
      const job = await post(`${root}/export`, { format, mode, background: true });
      const result = await waitForJob(job, { onProgress: (current) => setMessage(`正在生成${mode === "review" ? "送审" : "正式"}文件 · ${current.progress}%`) });
      setLatest(result); await refresh();
      setMessage(`${mode === "review" ? "送审" : "正式"}文件已生成，可从下方下载。`);
    });
  }

  return <div className="project-delivery">
    <section className="panel">
      <div className="panel-title"><div><ShieldCheck size={18} /><h2>质量检查与交付</h2></div><BusyButton busy={busy === "check"} disabled={Boolean(busy)} className="secondary" onClick={check}><CheckCheck size={16} />重新检查</BusyButton></div>
      {message && <Notice type={failed ? "danger" : "info"}>{message}</Notice>}
      {latest && <div className="delivery-latest"><strong>本次导出：{latest.mode === "review" ? "送审版" : "正式版"}</strong><FileLink item={latest} /></div>}
      {report ? <>
        <div className="metric-grid four">
          <Metric label="章节草稿" value={`${report.metrics.drafts}/${report.metrics.sections}`} />
          <Metric label="已签审条款覆盖" value={`${report.metrics.coverage}%`} />
          <Metric label="证据支持" value={`${report.metrics.claims.support_rate}%`} tone={report.metrics.claims.high_unsupported ? "danger" : "success"} />
          <Metric label="未签审章节" value={report.metrics.unreviewed_drafts} tone={report.metrics.unreviewed_drafts ? "warning" : "success"} />
        </div>
        <div className="delivery-modes">
          {["review", "formal"].map((mode) => {
            const reviewMode = mode === "review";
            const ready = Boolean(report[`${mode}_ready`]);
            const label = reviewMode ? "送审" : "正式";
            return <section className="delivery-mode" key={mode} aria-label={`${label}交付`}>
              <h3>{reviewMode ? "专业送审" : "正式交付"}</h3>
              <p>{reviewMode ? "供专业人员复核。正式投标前仍需完成单位资料、签审和整本定稿。" : "完成送审检查，并由实际责任人完成章节签审、合规确认及整本定稿。"}</p>
              <div className={`gate-badge ${ready ? "ready" : "blocked"}`}>{ready ? `可导出${label}版` : `${label}条件未齐备`}</div>
              <div className="actions">{formats.map(([format, name]) => <BusyButton key={format} busy={busy === `${mode}-${format}`} disabled={Boolean(busy) || !ready} className={format === "package" ? "" : "secondary"} onClick={() => exportFile(format, mode)}><Download size={15} />{label}{name}</BusyButton>)}</div>
              <div className="gate-result"><IssueList items={reviewMode ? report.review_blockers : report.formal_blockers} onNavigate={onNavigate} />{!reviewMode && report.review_blockers?.length > 0 && <p className="form-help">还需先处理送审检查问题。</p>}</div>
            </section>;
          })}
        </div>
        {report.warnings?.length > 0 && <div className="gate-result"><h3>需留意的问题</h3><IssueList items={report.warnings} onNavigate={onNavigate} /></div>}
      </> : <Empty title={busy ? "正在检查交付条件" : "交付检查未完成"} detail="以服务器检查结果为准，完成检查后开放相应导出。" />}
    </section>

    <section className="panel">
      <div className="panel-title"><div><BookOpenText size={18} /><h2>整本预览与人工定稿</h2></div><BusyButton className="secondary" busy={busy === "preview"} disabled={Boolean(busy)} onClick={openPreview}>打开当前整本预览</BusyButton></div>
      <p className="form-help">先在项目资料页登记真实投标信息，再由实际复核人核对整本内容。这里的确认仅对所预览的版本生效，修改后须重新复核。</p>
      {preview ? <>
        {preview.confirmation?.valid && <Notice type="success">当前版本已由 {preview.confirmation.professional_reviewer} 完成整本复核与定稿{preview.confirmation.confirmed_at ? `（${preview.confirmation.confirmed_at}）` : ""}。</Notice>}
        <details className="book-preview" open><summary>整本正文 · {project.sections.length} 章</summary><pre aria-label="整本正文">{preview.markdown || "尚无正文"}</pre></details>
        <form className="final-review-form" onSubmit={(event) => { event.preventDefault(); confirmFinal(); }}>
          <label>本次整本复核人<input required value={reviewer} placeholder="由实际复核人填写姓名" onChange={(event) => setReviewer(event.target.value)} /></label>
          <label className="confirmation-check"><input type="checkbox" checked={compliance} onChange={(event) => setCompliance(event.target.checked)} /><span>我已核对招标要求、工程参数、单位资料和签字盖章要求，确认合规清单已完成。</span></label>
          <label className="confirmation-check"><input type="checkbox" checked={finalized} onChange={(event) => setFinalized(event.target.checked)} /><span>我已审阅当前整本内容及送审文件的排版，确认本版本可以定稿。</span></label>
          <BusyButton type="submit" busy={busy === "confirm"} disabled={Boolean(busy) || !report?.review_ready || !reviewer.trim() || !compliance || !finalized}><CheckCheck size={16} />确认合规并完成定稿</BusyButton>
          {!report?.review_ready && <p className="form-help">请先处理送审检查问题，再完成整本定稿。</p>}
        </form>
      </> : <Empty title="尚未打开当前整本预览" detail="打开预览后，可填写复核姓名并逐项确认。" />}
    </section>

    <section className="panel">
      <div className="panel-title"><div><History size={18} /><h2>历史交付文件</h2></div></div>
      {deliveries.length ? <div className="delivery-history">{deliveries.map((item) => <article key={item.delivery_id}>
        <div><strong>{item.mode === "review" ? "送审版" : "正式版"} · {item.file_name}</strong><small>{item.created_at} · {item.current ? "对应当前项目版本" : "历史版本，项目内容可能已有变化"}</small></div>
        <FileLink item={item} label="下载此版本" />
      </article>)}</div> : <Empty title="尚无交付文件" detail="通过检查并导出后，文件将保留在这里。" />}
    </section>
  </div>;
}
