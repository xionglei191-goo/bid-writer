import React, { useEffect, useState } from "react";
import { FileInput, Save } from "lucide-react";
import { BusyButton, Notice } from "../components";

const engineeringFields = [["structure_type", "结构形式"], ["duration", "计划工期"], ["quality_target", "质量目标"], ["safety_target", "安全目标"]];
const deliveryFields = [
  ["bidder_name", "真实投标单位"], ["bidder_credit_code", "统一社会信用代码"],
  ["authorized_signatory", "授权签字人"], ["professional_reviewer", "专业复核人"],
  ["customer_name", "委托方 / 接收方"], ["delivery_deadline", "交付期限"],
];

function initialForm(project) {
  const saved = project.profile || {};
  const profile = { ...saved, bidder_name: saved.bidder_name || saved.tenderer_name || saved.bidder || "", professional_reviewer: saved.professional_reviewer || saved.reviewed_by || "" };
  // Only business fields belong in this form. Version-bound signoff is a separate action.
  const keys = [...engineeringFields, ...deliveryFields, ["seal_requirements"]].map(([key]) => key);
  return {
    name: project.name || "", industry: project.industry || "通用", project_type: project.project_type || "",
    region: project.region || "", source_text: project.source_text || "",
    profile: Object.fromEntries(keys.map((key) => [key, profile[key] || ""])),
  };
}

export default function ProjectProfile({ project, onSave, busy }) {
  const [form, setForm] = useState(() => initialForm(project));
  useEffect(() => { setForm(initialForm(project)); }, [project.id, project.updated_at]);
  const setField = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const setProfile = (key, value) => setForm((current) => ({ ...current, profile: { ...current.profile, [key]: value } }));
  return <form className="panel project-profile" onSubmit={(event) => { event.preventDefault(); onSave(form); }}>
    <div className="panel-title"><div><FileInput size={18} /><h2>项目资料</h2></div><BusyButton type="submit" busy={busy} disabled={!form.name.trim()}><Save size={16} />保存资料</BusyButton></div>
    <div className="form-grid">
      <label className="wide">项目名称<input required value={form.name} onChange={(event) => setField("name", event.target.value)} /></label>
      <label>行业<select value={form.industry} onChange={(event) => setField("industry", event.target.value)}>{[...new Set([form.industry, "医院", "学校", "市政", "厂房", "水利", "通用"])].map((value) => <option key={value}>{value}</option>)}</select></label>
      <label>项目类型<input value={form.project_type} onChange={(event) => setField("project_type", event.target.value)} /></label>
      <label>地区<input value={form.region} onChange={(event) => setField("region", event.target.value)} /></label>
      {engineeringFields.map(([key, label]) => <label key={key}>{label}<input value={form.profile[key]} onChange={(event) => setProfile(key, event.target.value)} /></label>)}
    </div>
    <h3 className="form-section-title">投标与交付资料</h3>
    <p className="form-help">按真实项目资料填写。登记姓名不代表完成签审；请在质量交付页核对整本内容并明确确认。</p>
    <div className="form-grid">
      {deliveryFields.map(([key, label]) => <label key={key}>{label}<input value={form.profile[key]} placeholder={key === "delivery_deadline" ? "例如：2026-09-30 18:00" : ""} onChange={(event) => setProfile(key, event.target.value)} /></label>)}
      <label className="wide">签字盖章要求<textarea rows="3" placeholder="填写招标文件要求的签字人、盖章位置及办理情况" value={form.profile.seal_requirements} onChange={(event) => setProfile("seal_requirements", event.target.value)} /></label>
    </div>
    <Notice>资料或正文发生变化后，需要重新核对交付检查和整本定稿状态。</Notice>
    <label className="source-text-label">招标文件与技术要求<textarea rows="18" value={form.source_text} onChange={(event) => setField("source_text", event.target.value)} /></label>
  </form>;
}
