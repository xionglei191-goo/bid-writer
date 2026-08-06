import React, { useEffect, useState } from "react";
import { CheckCircle2, Database, FolderTree, Settings2 } from "lucide-react";
import { api } from "../api";
import { Empty, PageHeader, Status } from "../components";

export default function SystemSettings() {
  const [config, setConfig] = useState(null); const [status, setStatus] = useState(null);
  useEffect(() => { Promise.all([api("/api/system/config"), api("/api/status")]).then(([a, b]) => { setConfig(a); setStatus(b); }).catch(() => {}); }, []);
  if (!config) return <Empty title="正在读取系统配置" />;
  return <><PageHeader eyebrow="系统设置" title="运行环境" description="本地目录、大模型、数据库与功能开关。" /><section className="settings-grid"><article className="panel"><div className="panel-title"><div><FolderTree size={18} /><h2>目录边界</h2></div></div><div className="definition-list">{Object.entries(config.paths).map(([key, value]) => <div key={key}><span>{key}</span><code>{value}</code></div>)}</div></article><article className="panel"><div className="panel-title"><div><Settings2 size={18} /><h2>模型与功能</h2></div></div><div className="definition-list"><div><span>大模型</span><strong>{config.llm.model}</strong></div><div><span>接口协议</span><strong>{config.llm.wire_api}</strong></div><div><span>连接状态</span><Status value={config.llm.configured ? "approved" : "review_required"} /></div><div><span>运营模块</span><strong>{config.operations_enabled ? "已启用" : "已隔离"}</strong></div></div></article><article className="panel wide"><div className="panel-title"><div><Database size={18} /><h2>数据架构</h2></div></div><div className="architecture-lines"><div><CheckCircle2 size={17} /><span>原始资料只从 01_原始标书库 读取</span></div><div><CheckCircle2 size={17} /><span>正式知识只从 02_知识库/06_已发布知识库 检索</span></div><div><CheckCircle2 size={17} /><span>SQLite仅保存可重建的运行索引</span></div><div><CheckCircle2 size={17} /><span>正式交付文件写入 04_交付与报告</span></div><code>{status?.database}</code></div></article></section></>;
}
