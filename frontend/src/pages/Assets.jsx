import React, { useEffect, useState } from "react";
import { Boxes, FileImage, Folder, TableProperties, Workflow } from "lucide-react";
import { api } from "../api";
import { Empty, Metric, PageHeader } from "../components";

export default function Assets() {
  const [data, setData] = useState({ items: [] });
  useEffect(() => { api("/api/templates/assets").then(setData).catch(() => {}); }, []);
  const counts = data.items.reduce((result, item) => ({ ...result, [item.kind]: (result[item.kind] || 0) + 1 }), {});
  return <><PageHeader eyebrow="模板与资产中心" title="标准内容组件" description="施工工艺、原生表格、流程图、组织架构图、横道图和企业文档模板。" /><section className="metric-grid four"><Metric label="资产目录" value={counts.directory || 0} /><Metric label="图像文件" value={(counts.png || 0) + (counts.jpg || 0)} /><Metric label="表格模板" value={counts.xlsx || 0} /><Metric label="全部资产" value={data.items.length} /></section><section className="panel"><div className="asset-categories"><article><Boxes size={20} /><strong>施工工艺模板</strong><span>标准工序、控制参数、质量检查与安全措施</span></article><article><TableProperties size={20} /><strong>原生表格</strong><span>资源计划、检查记录和措施清单</span></article><article><Workflow size={20} /><strong>结构化图表</strong><span>流程图、组织架构图和进度横道图</span></article><article><FileImage size={20} /><strong>施工示意图</strong><span>已审核的模板图和非证据性场景图</span></article></div><div className="file-list">{data.items.map((item) => <div key={item.path}><Folder size={17} /><div><strong>{item.name}</strong><span>{item.path}</span></div><small>{item.kind}</small></div>)}{!data.items.length && <Empty title="资产库为空" detail="经过审核的知识图表和模板将在这里统一管理。" />}</div></section></>;
}
