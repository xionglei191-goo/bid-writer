import React, { useEffect, useState } from "react";
import { ArrowRight, CircleAlert, FileClock, FolderOpen, LibraryBig, RefreshCw } from "lucide-react";
import { api } from "../api";
import { Empty, Metric, PageHeader, Status } from "../components";

export default function Dashboard({ status }) {
  const [jobs, setJobs] = useState([]);
  const [projects, setProjects] = useState([]);

  async function load() {
    const [nextJobs, nextProjects] = await Promise.all([api("/api/knowledge/jobs?limit=6"), api("/api/projects")]);
    setJobs(nextJobs);
    setProjects(nextProjects);
  }
  useEffect(() => { load().catch(() => {}); }, []);
  const metrics = status?.knowledge || {};
  return <>
    <PageHeader eyebrow="总览" title="生产工作台" description="知识资产、项目生产和质量风险集中视图。" actions={<button className="icon-text" onClick={() => load()}><RefreshCw size={16} />刷新</button>} />
    <section className="metric-grid five"><Metric label="原始资料" value={metrics.sources} hint="已扫描" /><Metric label="标准文档" value={metrics.documents} /><Metric label="待审核知识" value={metrics.review_pending} tone="warning" /><Metric label="已发布知识" value={metrics.published} tone="success" /><Metric label="生产项目" value={status?.projects} /></section>
    <section className="two-column">
      <article className="panel"><div className="panel-title"><div><FileClock size={18} /><h2>处理队列</h2></div><a href="#/knowledge/jobs">查看全部<ArrowRight size={15} /></a></div>{jobs.length ? <div className="list">{jobs.map((job) => <div className="list-row" key={job.id}><div><strong>{job.file_name}</strong><span>{job.current_step || "等待处理"} · {job.progress}%</span></div><Status value={job.status} /></div>)}</div> : <Empty title="暂无处理任务" detail="扫描原始资料后创建标准化任务。" />}</article>
      <article className="panel"><div className="panel-title"><div><FolderOpen size={18} /><h2>最近项目</h2></div><a href="#/projects">项目列表<ArrowRight size={15} /></a></div>{projects.length ? <div className="list">{projects.slice(0, 6).map((project) => <a className="list-row row-link" href={`#/projects/${project.id}`} key={project.id}><div><strong>{project.name}</strong><span>{project.industry || "通用"} · {project.draft_count}/{project.section_count}章</span></div><Status value={project.status} /></a>)}</div> : <Empty title="暂无生产项目" detail="创建项目并录入招标要求后开始编制。" />}</article>
    </section>
    <section className="three-column compact-panels"><a className="quick-link" href="#/knowledge"><LibraryBig size={20} /><div><strong>建设知识库</strong><span>扫描、拆解、审核与发布</span></div><ArrowRight size={16} /></a><a className="quick-link" href="#/projects"><FolderOpen size={20} /><div><strong>创建技术标</strong><span>解析、目录、章节与成稿</span></div><ArrowRight size={16} /></a><a className="quick-link" href="#/quality"><CircleAlert size={20} /><div><strong>检查交付风险</strong><span>条款、引用、占位符与导出门禁</span></div><ArrowRight size={16} /></a></section>
  </>;
}
