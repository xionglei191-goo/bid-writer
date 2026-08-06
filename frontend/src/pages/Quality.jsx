import React, { useEffect, useState } from "react";
import { ArrowRight, ShieldAlert } from "lucide-react";
import { api } from "../api";
import { Empty, PageHeader, Status } from "../components";

export default function Quality() {
  const [projects, setProjects] = useState([]); const [reports, setReports] = useState({});
  async function load() { const items = await api("/api/projects"); setProjects(items); const results = await Promise.all(items.map(async (item) => { try { return [item.id, await api(`/api/projects/${item.id}/quality`)]; } catch { return [item.id, null]; } })); setReports(Object.fromEntries(results)); }
  useEffect(() => { load().catch(() => {}); }, []);
  return <><PageHeader eyebrow="质量与交付中心" title="项目质量门禁" description="正式导出前统一检查章节、条款证据、待确认项、占位符和知识引用。" /><section className="panel"><div className="quality-list">{projects.map((project) => { const report = reports[project.id]; return <a href={`#/projects/${project.id}`} key={project.id}><div className="quality-icon"><ShieldAlert size={19} /></div><div><strong>{project.name}</strong><span>{report ? `${report.metrics.drafts}/${report.metrics.sections}章 · 覆盖${report.metrics.coverage}% · ${report.blockers.length}项阻断` : "等待检查"}</span></div>{report && <span className={report.ready ? "score score-good" : "score"}>{report.score}</span>}<Status value={report?.ready ? "approved" : "review_required"} /><ArrowRight size={16} /></a>})}{!projects.length && <Empty title="暂无待检查项目" />}</div></section></>;
}
