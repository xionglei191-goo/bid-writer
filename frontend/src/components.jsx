import React from "react";
import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";

export function PageHeader({ eyebrow, title, description, actions }) {
  return <header className="page-header"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="header-actions">{actions}</div>}</header>;
}

export function Metric({ label, value, tone = "default", hint }) {
  return <article className={`metric metric-${tone}`}><span>{label}</span><strong>{value ?? 0}</strong>{hint && <small>{hint}</small>}</article>;
}

export function Status({ value }) {
  const normalized = String(value || "pending").toLowerCase();
  const labels = { discovered: "待处理", pending: "等待中", paused: "已暂停", running: "处理中", waiting_ocr: "等待OCR", completed: "已完成", processed: "已处理", failed: "失败", duplicate: "重复", skipped: "已跳过", review_required: "待审核", approved: "已批准", rejected: "已退回", published: "已发布", retired: "已停用", draft: "草稿", drafted: "已生成", reviewed: "已确认", asset: "素材", archive: "压缩包", metadata_only: "仅登记" };
  const tone = ["completed", "processed", "approved", "published"].includes(normalized) ? "success" : ["failed", "rejected"].includes(normalized) ? "danger" : ["running", "waiting_ocr", "review_required"].includes(normalized) ? "warning" : "neutral";
  return <span className={`status status-${tone}`}>{labels[normalized] || value || "待处理"}</span>;
}

export function Empty({ title = "暂无数据", detail = "" }) {
  return <div className="empty-state"><div className="empty-icon" /><strong>{title}</strong>{detail && <p>{detail}</p>}</div>;
}

export function Notice({ type = "info", children }) {
  const Icon = type === "success" ? CheckCircle2 : type === "danger" ? AlertTriangle : LoaderCircle;
  return <div className={`notice notice-${type}`}><Icon size={17} /><span>{children}</span></div>;
}

export function Tabs({ items, active, onChange }) {
  return <div className="tabs" role="tablist">{items.map((item) => <button key={item.key} type="button" className={active === item.key ? "active" : ""} onClick={() => onChange(item.key)}>{item.label}</button>)}</div>;
}

export function BusyButton({ busy, children, ...props }) {
  return <button {...props} disabled={busy || props.disabled}>{busy && <LoaderCircle size={16} className="spin" />}{children}</button>;
}
