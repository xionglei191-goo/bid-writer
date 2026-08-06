import React from "react";
import { Archive, BookOpenCheck, Boxes, ChevronRight, ClipboardCheck, FolderKanban, LayoutDashboard, LibraryBig, PanelLeftClose, Settings } from "lucide-react";

const navigation = [
  { key: "dashboard", label: "工作台", icon: LayoutDashboard, href: "#/dashboard" },
  { key: "knowledge", label: "知识工程", icon: LibraryBig, href: "#/knowledge" },
  { key: "projects", label: "项目生产", icon: FolderKanban, href: "#/projects" },
  { key: "assets", label: "模板资产", icon: Boxes, href: "#/assets" },
  { key: "quality", label: "质量交付", icon: ClipboardCheck, href: "#/quality" },
  { key: "settings", label: "系统设置", icon: Settings, href: "#/settings" },
];

export default function Shell({ route, status, children }) {
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark"><BookOpenCheck size={21} /></div><div><strong>标书生产系统</strong><span>Knowledge First</span></div></div><nav>{navigation.map(({ key, label, icon: Icon, href }) => <a key={key} href={href} className={route.section === key ? "active" : ""}><Icon size={18} /><span>{label}</span>{route.section === key && <ChevronRight size={15} />}</a>)}</nav><div className="sidebar-foot"><div className="runtime-state"><span className={status?.llm?.configured ? "dot online" : "dot"} /><div><strong>{status?.llm?.configured ? "模型已连接" : "模型未配置"}</strong><span>{status?.llm?.model || "本地模式"}</span></div></div><div className="version"><Archive size={14} /> v{status?.version || "2.0.0"}</div></div></aside><section className="workspace"><div className="topbar"><div><PanelLeftClose size={18} /><span>本地工作区</span></div><span>{status?.architecture === "knowledge-engineering-first" ? "知识工程优先架构" : "正在连接"}</span></div><main className="page-content">{children}</main></section></div>;
}
