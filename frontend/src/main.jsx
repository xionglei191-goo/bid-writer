import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE = import.meta.env.VITE_BID_WRITER_API_BASE || "";
const WORKBENCH_URL = import.meta.env.VITE_BID_WRITER_WORKBENCH_URL || API_BASE || "http://127.0.0.1:8779";

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function statusLabel(value) {
  return {
    ready: "可交付",
    warning: "需关注",
    blocked: "不可交付",
  }[value] || "待核验";
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (!size) return "0 B";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function MetricCard({ label, value }) {
  return (
    <article className="card">
      <span>{label}</span>
      <strong>{value ?? 0}</strong>
    </article>
  );
}

function App() {
  const [status, setStatus] = useState({});
  const [tenders, setTenders] = useState([]);
  const [selectedTenderId, setSelectedTenderId] = useState("");
  const [packageValidation, setPackageValidation] = useState(null);
  const [message, setMessage] = useState("");

  const selectedTender = useMemo(
    () => tenders.find((item) => String(item.id) === String(selectedTenderId)) || tenders[0],
    [selectedTenderId, tenders],
  );

  async function refresh() {
    const [nextStatus, nextTenders] = await Promise.all([api("/api/status"), api("/api/tenders")]);
    setStatus(nextStatus);
    setTenders(nextTenders);
    if (!selectedTenderId && nextTenders[0]) setSelectedTenderId(String(nextTenders[0].id));
    setMessage("状态已刷新。");
  }

  async function validatePackage() {
    const tenderId = selectedTender?.id;
    if (!tenderId) {
      setPackageValidation(null);
      setMessage("当前没有可核验的项目。");
      return;
    }
    const report = await api(`/api/tenders/${tenderId}/package-validation`);
    setPackageValidation(report);
    setMessage(`交付包核验：${statusLabel(report.summary?.readiness)}`);
  }

  useEffect(() => {
    refresh().catch((error) => setMessage(error.message));
  }, []);

  const summary = packageValidation?.summary || {};
  const packageInfo = packageValidation?.package || {};
  const blockers = packageValidation?.blockers || [];
  const warnings = packageValidation?.warnings || [];

  return (
    <main className="react-workbench">
      <section className="panel wide react-dashboard">
        <div>
          <h1>技术标生产工作台</h1>
          <p>{message || "本地生产服务已连接。"}</p>
        </div>
        <div className="actions">
          <button type="button" onClick={() => refresh().catch((error) => setMessage(error.message))}>
            刷新状态
          </button>
          <button type="button" className="secondary" onClick={() => window.open(WORKBENCH_URL, "_blank")}>
            打开完整工作台
          </button>
        </div>
      </section>

      <section className="panel wide">
        <div className="cards">
          <MetricCard label="知识库文档" value={status.documents} />
          <MetricCard label="章节" value={status.sections} />
          <MetricCard label="片段" value={status.chunks} />
          <MetricCard label="项目" value={status.tenders} />
          <MetricCard label="交付记录" value={status.deliveries} />
        </div>
      </section>

      <section className="panel wide react-grid">
        <article className="result-item">
          <h2>项目队列</h2>
          <div className="table-list">
            {tenders.map((item) => (
              <article className="row-item" key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <p>
                    <span className="tag">#{item.id}</span>
                    {item.industry || "未标注行业"} / {item.delivery_status || "待处理"}
                  </p>
                </div>
                <button type="button" className="secondary" onClick={() => setSelectedTenderId(String(item.id))}>
                  选中
                </button>
              </article>
            ))}
            {!tenders.length && <p>暂无项目。</p>}
          </div>
        </article>

        <article className="result-item">
          <h2>交付包核验</h2>
          <label>
            当前项目
            <select value={selectedTenderId} onChange={(event) => setSelectedTenderId(event.target.value)}>
              {tenders.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.id} / {item.name}
                </option>
              ))}
            </select>
          </label>
          <div className="actions compact-actions">
            <button type="button" onClick={() => validatePackage().catch((error) => setMessage(error.message))}>
              核验最新交付包
            </button>
          </div>
          <div className="coverage-grid">
            <MetricCard label="核验状态" value={statusLabel(summary.readiness)} />
            <MetricCard label="文件齐全" value={`${summary.present_files || 0}/${summary.expected_files || 0}`} />
            <MetricCard label="核心缺失" value={summary.core_missing || 0} />
            <MetricCard label="JSON 异常" value={summary.invalid_json || 0} />
          </div>
          <p>
            <span className="tag">{summary.zip_readable ? "ZIP 可读取" : "ZIP 待确认"}</span>
            {packageInfo.name || "未生成交付包"} / {formatBytes(summary.package_size || packageInfo.size || 0)}
          </p>
          {[...blockers, ...warnings].slice(0, 6).map((item, index) => (
            <p key={`${item.title}-${index}`}>
              <span className="tag">{blockers.includes(item) ? "阻断" : "提醒"}</span>
              {item.title}：{item.detail}
            </p>
          ))}
        </article>
      </section>

      <section className="panel wide embedded-workbench">
        <h2>完整生产台</h2>
        <iframe title="完整技术标生产工作台" src={WORKBENCH_URL} />
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
