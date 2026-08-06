import React, { useEffect, useState } from "react";
import { ArrowRight, FolderPlus, Plus, Search } from "lucide-react";
import { api, post } from "../api";
import { Empty, PageHeader, Status } from "../components";

const emptyForm = { name: "", industry: "医院", project_type: "房屋建筑", region: "", source_text: "", profile: {} };

export default function Projects() {
  const [items, setItems] = useState([]); const [query, setQuery] = useState(""); const [creating, setCreating] = useState(false); const [form, setForm] = useState(emptyForm); const [message, setMessage] = useState("");
  async function load() { setItems(await api("/api/projects")); }
  async function create(event) { event.preventDefault(); try { const project = await post("/api/projects", form); location.hash = `#/projects/${project.id}`; } catch (error) { setMessage(error.message); } }
  useEffect(() => { load().catch(() => {}); }, []);
  const filtered = items.filter((item) => !query || item.name.includes(query) || item.industry?.includes(query));
  return <>
    <PageHeader eyebrow="技术标生产中心" title="项目生产" description="每个项目沿招标解析、目录策略、章节编制、质量审查和正式交付推进。" actions={<button onClick={() => setCreating(true)}><Plus size={16} />新建项目</button>} />
    <section className="panel"><div className="toolbar"><div className="filters"><div className="input-icon"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目" /></div></div><span>共 {items.length} 个项目</span></div><div className="project-grid">{filtered.map((item) => <a className="project-card" href={`#/projects/${item.id}`} key={item.id}><div className="project-card-head"><div className="project-icon"><FolderPlus size={19} /></div><Status value={item.status} /></div><h2>{item.name}</h2><p>{item.industry || "通用"} · {item.project_type || "未设置类型"} · {item.region || "未设置地区"}</p><div className="project-stats"><span><strong>{item.requirement_count}</strong>要求</span><span><strong>{item.section_count}</strong>章节</span><span><strong>{item.draft_count}</strong>草稿</span></div><footer>打开生产工作区<ArrowRight size={16} /></footer></a>)}{!filtered.length && <Empty title="暂无项目" detail="创建项目后录入招标文件内容。" />}</div></section>
    {creating && <div className="modal-backdrop" onMouseDown={() => setCreating(false)}><form className="modal" onMouseDown={(event) => event.stopPropagation()} onSubmit={create}><div className="modal-head"><div><span className="eyebrow">新建生产任务</span><h2>创建技术标项目</h2></div><button type="button" className="secondary" onClick={() => setCreating(false)}>关闭</button></div>{message && <div className="global-error">{message}</div>}<div className="form-grid"><label className="wide">项目名称<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label>行业<select value={form.industry} onChange={(event) => setForm({ ...form, industry: event.target.value })}>{["医院", "学校", "市政", "厂房", "水利", "通用"].map((value) => <option key={value}>{value}</option>)}</select></label><label>项目类型<input value={form.project_type} onChange={(event) => setForm({ ...form, project_type: event.target.value })} /></label><label className="wide">地区<input value={form.region} onChange={(event) => setForm({ ...form, region: event.target.value })} /></label><label className="wide">招标文件文本<textarea rows="10" value={form.source_text} onChange={(event) => setForm({ ...form, source_text: event.target.value })} placeholder="粘贴招标文件中的技术要求、评分点和项目概况" /></label></div><div className="modal-actions"><button type="button" className="secondary" onClick={() => setCreating(false)}>取消</button><button type="submit">创建并进入项目</button></div></form></div>}
  </>;
}
