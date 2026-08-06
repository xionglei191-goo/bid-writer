const state = {
  currentTenderId: null,
  currentTender: null,
  currentRoute: "dashboard",
  currentDraftId: null,
  currentTemplateId: null,
  searchResults: [],
  draftCitations: [],
  requirements: [],
  templates: [],
  templateCoverage: null,
  templateAssets: null,
  benchmarks: null,
  documentTemplates: [],
  requirementResponses: [],
  acceptance: null,
  visualReview: null,
  planAudit: null,
  responseMatrix: null,
  llmStatus: null,
  orderDashboard: null,
  projectOverview: null,
  projectTimeline: null,
  task: null,
  documentSettings: null,
  enterpriseProfile: null,
  bidStrategy: null,
  finalDocument: null,
  processingRecords: [],
  profile: null,
  intakeAssistant: null,
  pricingRules: [],
  priceQuote: null,
  payments: null,
  orderConfirmation: null,
  communicationSuggestion: null,
  communications: [],
  productionPipeline: null,
  clientDeliveryPreparation: null,
  productionReadiness: null,
  commandCenter: null,
  productionStarter: null,
  orderWizard: null,
  channelOps: null,
  qualityGate: null,
  revisionTasks: null,
  sourceAudit: null,
  deliveryRelease: null,
  sourcePreview: null,
  kbAudit: null,
  kbOcrQueue: null,
  finalChecklist: null,
  polish: null,
  replacementPreview: null,
  replacementRecords: [],
  materials: [],
  deliveries: [],
  packageValidation: null,
  clientPackageValidation: null,
  deliveryAssistant: null,
  clientDeliveryConfirmation: null,
  feedback: [],
  feedbackRework: null,
  closureConfirmation: null,
  retrospectiveDashboard: null,
  projectRetrospective: null,
  caseAssets: [],
  documentBlocks: [],
  visualAssets: [],
  visualPlan: null,
  workflow: null,
  drafts: [],
  flowBusy: false,
  productionAction: "",
  productionSecondaryAction: "",
};

const ROUTES = {
  dashboard: {
    title: "工作台",
    subtitle: "项目状态、知识库和生产待办",
    sections: ["stage-dashboard"],
  },
  projects: {
    title: "项目管理",
    subtitle: "创建、打开和归档技术标项目",
    sections: ["stage-projects"],
  },
  knowledge: {
    title: "知识库",
    subtitle: "文档入库、OCR、全文检索与来源追溯",
    sections: ["stage-kb", "stage-search"],
  },
  templates: {
    title: "模板库",
    subtitle: "章节模板、施工工艺库与覆盖检查",
    sections: ["stage-templates"],
  },
  settings: {
    title: "系统设置",
    subtitle: "模型连接、投标单位资料与基础配置",
    sections: ["stage-ai", "stage-enterprise"],
  },
  "operations-intake": {
    title: "接单中心",
    subtitle: "订单向导、渠道沟通和生产启动",
    sections: ["stage-wizard", "stage-channel", "stage-starter", "stage-intake", "stage-communications"],
  },
  "operations-finance": {
    title: "报价收款",
    subtitle: "报价测算、价格规则、订单确认和收款",
    sections: ["stage-pricing", "stage-pricing-rules", "stage-confirmation", "stage-payments"],
  },
  "operations-delivery": {
    title: "交付售后",
    subtitle: "订单看板、发货、反馈和客户结案",
    sections: ["stage-command", "stage-orders", "stage-delivery", "stage-delivery-assistant", "stage-client-confirm", "stage-feedback", "stage-closure"],
  },
  "operations-assets": {
    title: "复盘与资产",
    subtitle: "生产履历、项目复盘和案例沉淀",
    sections: ["stage-case-assets", "stage-timeline", "stage-retro", "stage-project-retro"],
  },
  "project-overview": {
    title: "项目概览",
    subtitle: "项目状态、生产流程、任务和资料完整度",
    sections: ["stage-overview", "stage-workflow", "stage-task", "stage-materials"],
  },
  "project-tender": {
    title: "招标解析",
    subtitle: "招标文件、项目参数和响应矩阵",
    sections: ["stage-source", "stage-profile"],
  },
  "project-outline": {
    title: "目录策略",
    subtitle: "响应策略、章节目录和条款挂接",
    sections: ["stage-strategy", "stage-plan"],
  },
  "project-editor": {
    title: "章节编制",
    subtitle: "历史检索、章节生成、编辑和版本管理",
    sections: ["stage-search", "stage-generate"],
  },
  "project-visuals": {
    title: "图文配图",
    subtitle: "表格、组织架构、流程图、横道图和施工场景",
    sections: ["stage-rich-document"],
  },
  "project-review": {
    title: "质量审查",
    subtitle: "条款覆盖、来源、待确认项和全稿校正",
    sections: ["stage-workflow", "stage-polish"],
  },
  "project-delivery": {
    title: "成稿交付",
    subtitle: "整本预览、格式设置、导出和交付记录",
    sections: ["stage-final", "stage-document-settings", "stage-delivery"],
  },
};

function parseRoute() {
  const path = location.hash.replace(/^#\/?/, "").replace(/\/$/, "") || "dashboard";
  const projectMatch = path.match(/^projects\/(\d+)\/(overview|tender|outline|editor|visuals|review|delivery)$/);
  if (projectMatch) {
    return { key: `project-${projectMatch[2]}`, tenderId: Number(projectMatch[1]) };
  }
  const legacyProjectMatch = path.match(/^project\/(overview|tender|outline|editor|visuals|review|delivery)$/);
  if (legacyProjectMatch && state.currentTenderId) {
    return { key: `project-${legacyProjectMatch[1]}`, tenderId: Number(state.currentTenderId) };
  }
  const operationRoute = path === "operations" ? "operations-intake" : path.replace("operations/", "operations-");
  if (ROUTES[operationRoute]) return { key: operationRoute, tenderId: null };
  if (ROUTES[path]) return { key: path, tenderId: null };
  return { key: "dashboard", tenderId: null };
}

function projectRouteHref(page) {
  return state.currentTenderId ? `#/projects/${state.currentTenderId}/${page}` : "#/projects";
}

function updateProjectLinks() {
  document.querySelectorAll("#projectNav [data-route-link]").forEach((link) => {
    link.href = projectRouteHref(link.dataset.routeLink.replace("project-", ""));
  });
  const sidebarLink = el("sidebarProject")?.querySelector("a");
  if (sidebarLink) sidebarLink.href = projectRouteHref("overview");
}

function updateProjectContext(tender = state.currentTender) {
  const hasProject = Boolean(tender?.id);
  el("sidebarProject").hidden = !hasProject;
  if (!hasProject) {
    el("dashboardCurrentProject").innerHTML = '<article class="result-item"><h3>当前项目</h3><p>尚未选择项目。</p><a class="text-link" href="#/projects">打开项目列表</a></article>';
    return;
  }
  const name = tender.name || `项目 ${tender.id}`;
  const meta = `ID ${tender.id} / ${tender.industry || "未填行业"}`;
  el("sidebarProjectName").textContent = name;
  el("sidebarProjectMeta").textContent = meta;
  el("projectContextName").textContent = name;
  el("projectContextMeta").textContent = meta;
  el("dashboardCurrentProject").innerHTML = `
    <article class="result-item dashboard-project-row">
      <div><h3>当前项目</h3><strong>${escapeHtml(name)}</strong><p>${escapeHtml(meta)}</p></div>
      <a class="text-link" href="${projectRouteHref("overview")}">继续编制</a>
    </article>`;
  updateProjectLinks();
}

function renderRoute(route) {
  const config = ROUTES[route.key] || ROUTES.dashboard;
  state.currentRoute = route.key;
  document.querySelectorAll(".layout > section").forEach((section) => {
    section.classList.toggle("route-active", config.sections.includes(section.id));
  });
  const isProjectRoute = route.key.startsWith("project-");
  const isOperationsRoute = route.key.startsWith("operations-");
  el("projectContext").hidden = !isProjectRoute;
  el("projectNav").hidden = !isProjectRoute;
  el("productionGuide").hidden = !isProjectRoute;
  el("operationsNav").hidden = !isOperationsRoute;
  el("pageEyebrow").textContent = isProjectRoute ? "项目生产" : isOperationsRoute ? "运营管理" : "技术标生产";
  el("pageTitle").textContent = config.title;
  el("workspaceSubtitle").textContent = config.subtitle;
  document.querySelectorAll("[data-route-link]").forEach((link) => {
    const target = link.dataset.routeLink;
    const inGlobalNav = Boolean(link.closest(".global-nav"));
    const active = target === route.key
      || (inGlobalNav && target === "projects" && isProjectRoute)
      || (inGlobalNav && target === "operations-intake" && isOperationsRoute);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  updateProjectContext();
  if (isProjectRoute) renderProductionGuide(state.workflow);
  window.scrollTo({ top: 0, behavior: "auto" });
}

async function handleRoute() {
  const route = parseRoute();
  renderRoute(route);
  if (route.key.startsWith("project-") && route.tenderId && route.tenderId !== state.currentTenderId) {
    await loadTender(route.tenderId);
    renderRoute(route);
  }
}

function openTenderWorkspace(tenderId) {
  location.hash = `#/projects/${tenderId}/overview`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function apiForm(path, formData) {
  const response = await fetch(path, { method: "POST", body: formData });
  const payload = await response.json();
  if (!response.ok || payload.error) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function el(id) {
  return document.getElementById(id);
}

function setWorkspaceMode(mode, persist = true) {
  const selected = "full";
  document.body.dataset.workspaceMode = selected;
  el("coreWorkspaceMode").setAttribute("aria-pressed", String(selected === "core"));
  el("fullWorkspaceMode").setAttribute("aria-pressed", String(selected === "full"));
  if (persist) localStorage.setItem("bidWriterWorkspaceMode", selected);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function log(message) {
  el("statusLog").textContent = `${new Date().toLocaleTimeString()} ${message}\n${el("statusLog").textContent}`;
}

function renderStatus(data) {
  const items = [
    ["文档", data.documents],
    ["章节", data.sections],
    ["片段", data.chunks],
    ["项目", data.tenders],
    ["草稿", data.drafts],
    ["修订", data.revision_tasks],
    ["交付", data.deliveries],
    ["反馈", data.feedback],
    ["结案", data.closures],
    ["复盘", data.retrospectives],
    ["案例", data.case_assets],
    ["沟通", data.communications],
    ["格式", data.document_settings],
    ["企业", data.enterprise_profiles],
    ["策略", data.bid_strategies],
    ["成稿", data.final_documents],
    ["处理", data.document_processing],
    ["图文块", data.document_blocks],
    ["视觉资产", data.visual_assets],
  ];
  el("statusCards").innerHTML = items
    .map(([label, value]) => `<div class="card"><span>${label}</span><strong>${value ?? 0}</strong></div>`)
    .join("");
  const dashboardItems = [
    ["知识库文档", data.documents],
    ["在编项目", data.tenders],
    ["章节草稿", data.drafts],
    ["图文素材", data.visual_assets],
    ["待修订", data.revision_tasks],
  ];
  el("dashboardStatusCards").innerHTML = dashboardItems
    .map(([label, value]) => `<div class="card"><span>${label}</span><strong>${value ?? 0}</strong></div>`)
    .join("");
}

async function refreshStatus() {
  const data = await api("/api/status");
  renderStatus(data);
}

function renderKbAudit(report) {
  state.kbAudit = report || null;
  if (!report) {
    el("kbAudit").innerHTML = `
      <article class="result-item workflow-next">
        <h3>知识库体检</h3>
        <p>刷新后按目录查看入库数量、重复跳过、待 OCR、未索引和未入库原因。</p>
      </article>
    `;
    return;
  }
  const summary = report.summary || {};
  const reasons = report.top_reasons || [];
  const categories = report.top_categories || [];
  const directories = report.directories || [];
  el("kbAudit").innerHTML = `
    <article class="command-hero">
      <div>
        <p class="eyebrow">Manifest + SQLite FTS5</p>
        <h3>${escapeHtml(summary.title || "知识库体检")}</h3>
        <p>可入库 ${summary.manifest_ok ?? 0} 条，已索引 ${summary.indexed_documents ?? 0} 份；索引率 ${Math.round(Number(summary.indexed_rate || 0) * 100)}%。</p>
      </div>
      <div class="command-decision">
        <span class="review-status ${summary.not_indexed || summary.missing_markdown ? "needs_work" : "ready"}">${summary.not_indexed || summary.missing_markdown ? "needs_work" : "ready"}</span>
        <strong>${summary.indexed_sections ?? 0} 章节 / ${summary.indexed_chunks ?? 0} 片段</strong>
        <p>目录 ${summary.directories ?? 0} 个，未完成 ${summary.incomplete_directories ?? 0} 个。</p>
      </div>
    </article>
    <div class="kb-audit-grid">
      <article class="card"><span>Manifest</span><strong>${summary.manifest_rows ?? 0}</strong></article>
      <article class="card"><span>已入库</span><strong>${summary.indexed_documents ?? 0}</strong></article>
      <article class="card"><span>重复跳过</span><strong>${summary.manifest_skipped ?? 0}</strong></article>
      <article class="card"><span>待 OCR</span><strong>${summary.manifest_pending_ocr ?? 0}</strong></article>
      <article class="card"><span>未索引</span><strong>${summary.not_indexed ?? 0}</strong></article>
      <article class="card"><span>缺 Markdown</span><strong>${summary.missing_markdown ?? 0}</strong></article>
    </div>
    <div class="overview-columns">
      <article class="result-item">
        <h3>未入库原因</h3>
        ${
          reasons
            .map((item) => `<p><span class="tag">${item.count ?? 0}</span>${escapeHtml(item.reason || "")}</p>`)
            .join("") || "<p>暂无未入库原因。</p>"
        }
      </article>
      <article class="result-item">
        <h3>行业分布</h3>
        ${
          categories
            .slice(0, 12)
            .map((item) => `<p><span class="tag">${item.count ?? 0}</span>${escapeHtml(item.category || "未分类")}</p>`)
            .join("") || "<p>暂无行业分布。</p>"
        }
      </article>
    </div>
    <div class="kb-dir-grid">
      ${directories
        .slice(0, 80)
        .map((item) => {
          const reasonsText = (item.top_reasons || []).map((reason) => `${reason.reason} ${reason.count}`).join("；");
          const samplesText = (item.samples || []).map((sample) => sample.top_project || sample.source_path).filter(Boolean).slice(0, 2).join(" / ");
          return `
            <article class="result-item kb-dir-card">
              <h3><span class="tag">${escapeHtml(item.status_label || "")}</span>${escapeHtml(item.name || "")}</h3>
              <p>入库 ${item.indexed_files ?? 0}/${item.manifest_files ?? 0}；章节 ${item.sections ?? 0}；片段 ${item.chunks ?? 0}；问题 ${item.issue_count ?? 0}</p>
              ${reasonsText ? `<p>${escapeHtml(reasonsText)}</p>` : ""}
              ${samplesText ? `<p>${escapeHtml(samplesText)}</p>` : ""}
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

async function refreshKbAudit() {
  renderKbAudit(await api("/api/kb/audit"));
}

function renderKbOcrQueue(report) {
  state.kbOcrQueue = report || null;
  if (!report) {
    el("kbOcrQueue").innerHTML = `
      <article class="result-item workflow-next">
        <h3>OCR 补录队列</h3>
        <p>刷新后查看待 OCR 的 PDF、文件状态、补录条件和处理建议。</p>
      </article>
    `;
    return;
  }
  const summary = report.summary || {};
  const items = report.items || [];
  const tokenStatus = summary.token_configured ? "已配置 OCR Token" : "未配置 OCR Token";
  el("kbOcrQueue").innerHTML = `
    <article class="command-hero">
      <div>
        <p class="eyebrow">PaddleOCR Queue</p>
        <h3>${escapeHtml(summary.title || "OCR 补录队列")}</h3>
        <p>待补录 ${summary.pending_count ?? 0} 份，原文件就绪 ${summary.ready_files ?? 0} 份，可执行 ${summary.runnable_count ?? 0} 份；${escapeHtml(tokenStatus)}。</p>
      </div>
      <div class="command-decision">
        <span class="review-status ${summary.runnable_count ? "ready" : "needs_work"}">${summary.runnable_count ? "ready" : "needs_work"}</span>
        <strong>${summary.total_size_mb ?? 0} MB / ${summary.over_100_pages ?? 0} 份超 100 页</strong>
        <p>${escapeHtml((report.policy || {}).execution || "仅在人工点击单条补录时调用 OCR。")}</p>
      </div>
    </article>
    <div class="kb-audit-grid">
      <article class="card"><span>待 OCR</span><strong>${summary.pending_count ?? 0}</strong></article>
      <article class="card"><span>原文件就绪</span><strong>${summary.ready_files ?? 0}</strong></article>
      <article class="card"><span>可执行</span><strong>${summary.runnable_count ?? 0}</strong></article>
      <article class="card"><span>缺原文件</span><strong>${summary.missing_files ?? 0}</strong></article>
      <article class="card"><span>超 100 页</span><strong>${summary.over_100_pages ?? 0}</strong></article>
      <article class="card"><span>已显示</span><strong>${summary.shown ?? 0}</strong></article>
    </div>
    <div class="kb-ocr-grid">
      ${
        items
          .map((item) => {
            const warnings = (item.warnings || []).map((warning) => `<li>${escapeHtml(warning)}</li>`).join("");
            return `
              <article class="result-item kb-ocr-card">
                <h3><span class="tag">${escapeHtml(item.status_label || "")}</span>${escapeHtml(item.top_project || item.source_path || "")}</h3>
                <p><span class="tag">${escapeHtml(item.top_category || "未分类")}</span><span class="tag">${item.size_mb ?? 0} MB</span><span class="tag">${item.estimated_pages ?? "未知"} 页</span></p>
                <p>${escapeHtml(item.source_path || "")}</p>
                ${item.note ? `<p>${escapeHtml(item.note)}</p>` : ""}
                ${warnings ? `<ul>${warnings}</ul>` : ""}
                <div class="actions">
                  <button type="button" data-run-kb-ocr="${escapeHtml(item.id || "")}" ${item.can_run ? "" : "disabled"}>执行 OCR 补录</button>
                </div>
              </article>
            `;
          })
          .join("") || '<article class="result-item"><h3>暂无待 OCR 文件</h3><p>当前 manifest 没有 pending_ocr 记录。</p></article>'
      }
    </div>
  `;
}

async function refreshKbOcrQueue() {
  renderKbOcrQueue(await api("/api/kb/ocr-queue"));
}

async function runKbOcrItem(itemId) {
  if (!itemId) return;
  log(`开始 OCR 补录：${itemId}`);
  const result = await api(`/api/kb/ocr-queue/${encodeURIComponent(itemId)}/run`, {
    method: "POST",
    body: JSON.stringify({ reindex: true }),
  });
  log(`OCR 补录完成：${JSON.stringify(result)}`);
  await refreshKbAudit().catch(() => {});
  await refreshKbOcrQueue().catch(() => {});
  await refreshStatus().catch(() => {});
}

function cardStatusClass(value) {
  return value === "ready" || value === "complete" || value === "pass" ? "ready" : "needs_work";
}

function renderCommandCenter(report) {
  state.commandCenter = report || null;
  if (!report) {
    el("commandCenter").innerHTML = `
      <article class="result-item workflow-next">
        <h3>请选择或创建项目</h3>
        <p>打开项目后，这里会显示当前阶段、关键指标、阻碍项和下一步动作。</p>
      </article>
    `;
    return;
  }
  const tender = report.tender || {};
  const headline = report.headline || {};
  const blockers = report.blockers || [];
  const warnings = report.warnings || [];
  const risks = report.risks || [];
  const progress = report.progress || [];
  const cards = report.cards || [];
  const actions = report.primary_actions || [];
  el("commandCenter").innerHTML = `
    <article class="command-hero">
      <div>
        <p class="eyebrow">当前项目 #${tender.id ?? ""}</p>
        <h3>${escapeHtml(tender.name || "未命名项目")}</h3>
        <p>${escapeHtml(tender.industry || "未登记行业")} / ${escapeHtml(tender.region || "未登记地区")} / ${escapeHtml(headline.delivery_status || "待生产")}</p>
      </div>
      <div class="command-decision">
        <span class="review-status ${cardStatusClass(headline.readiness)}">${escapeHtml(headline.decision || "待评估")}</span>
        <strong>${escapeHtml(headline.next_step_title || "等待下一步")}</strong>
        <p>${escapeHtml(headline.next_step_action || "刷新后查看当前建议。")}</p>
      </div>
    </article>
    <div class="command-actions">
      ${
        actions
          .map(
            (action) => `
              <button
                type="button"
                class="${action.variant === "secondary" ? "secondary" : ""}"
                data-command-action="${escapeHtml(action.action_code || "")}"
                data-command-target="${escapeHtml(action.target || "")}"
              >${escapeHtml(action.label || "")}</button>
            `,
          )
          .join("") || "<p>暂无下一步动作。</p>"
      }
    </div>
    <div class="coverage-grid command-cards">
      ${
        cards
          .map(
            (card) => `
              <article class="card ${cardStatusClass(card.status)}">
                <span>${escapeHtml(card.label || "")}</span>
                <strong>${escapeHtml(card.value ?? "")}</strong>
                <p>${escapeHtml(card.detail || "")}</p>
              </article>
            `,
          )
          .join("")
      }
    </div>
    <div class="workflow-steps command-progress">
      ${
        progress
          .map(
            (step) => `
              <article class="workflow-step ${escapeHtml(step.status || "")}">
                <strong>${escapeHtml(step.title || "")}</strong>
                <p><span class="tag">${escapeHtml(workflowStatusLabel(step.status || ""))}</span>${escapeHtml(step.detail || "")}</p>
              </article>
            `,
          )
          .join("")
      }
    </div>
    <div class="overview-columns">
      <article class="result-item">
        <h3>阻碍与提醒</h3>
        ${
          [...blockers, ...warnings]
            .slice(0, 8)
            .map((item) => `<p><span class="tag">${escapeHtml(item.status || item.key || "检查")}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.action || item.detail || "")}</p>`)
            .join("") || "<p>当前没有关键阻碍。</p>"
        }
      </article>
      <article class="result-item">
        <h3>主要风险</h3>
        ${
          risks
            .slice(0, 8)
            .map((item) => `<p><span class="tag">${escapeHtml(item.level || "risk")}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.action || item.detail || "")}</p>`)
            .join("") || "<p>当前没有高优先级风险。</p>"
        }
      </article>
    </div>
  `;
}

async function refreshCommandCenter() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderCommandCenter(null);
    return;
  }
  renderCommandCenter(await api(`/api/tenders/${tenderId}/command-center`));
}

function renderProductionStarter(report) {
  state.productionStarter = report || null;
  if (!report) {
    el("productionStarter").innerHTML = `
      <article class="result-item workflow-next">
        <h3>请选择或创建项目</h3>
        <p>打开项目后，这里会生成接单判断、报价建议、资料缺口、渠道边界和开工清单。</p>
      </article>
    `;
    el("starterCustomerReply").value = "";
    return;
  }
  const summary = report.summary || {};
  const tender = report.tender || {};
  const cards = report.cards || [];
  const checklist = report.start_checklist || [];
  const policy = report.channel_policy || {};
  const actions = report.operator_actions || [];
  el("starterCustomerReply").value = report.customer_reply || "";
  el("productionStarter").innerHTML = `
    <article class="command-hero">
      <div>
        <p class="eyebrow">${escapeHtml(summary.strategy || "标书生产工具优先")}</p>
        <h3>${escapeHtml(summary.decision || "待判断")}</h3>
        <p>${escapeHtml(tender.name || "未命名项目")} / ${escapeHtml(tender.industry || "未登记行业")} / ${escapeHtml(summary.channel_mode || "待确认渠道")}</p>
      </div>
      <div class="command-decision">
        <span class="review-status ${cardStatusClass(summary.state || "")}">${escapeHtml(summary.state || "needs_work")}</span>
        <strong>${escapeHtml(summary.next_action || "先刷新启动包。")}</strong>
        <p>待处理清单 ${summary.pending_checks ?? 0} 项，综合评分 ${summary.score ?? 0}。</p>
      </div>
    </article>
    <div class="coverage-grid command-cards">
      ${
        cards
          .map(
            (card) => `
              <article class="card ${cardStatusClass(card.status || "")}">
                <span>${escapeHtml(card.label || "")}</span>
                <strong>${escapeHtml(card.value ?? "")}</strong>
                <p>${escapeHtml(card.detail || "")}</p>
              </article>
            `,
          )
          .join("")
      }
    </div>
    <div class="overview-columns">
      <article class="result-item">
        <h3>渠道边界</h3>
        <p><span class="tag">${escapeHtml(policy.platform || "未登记")}</span>${escapeHtml(policy.automation_boundary || "")}</p>
        ${(policy.manual_confirm || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
      </article>
      <article class="result-item">
        <h3>资料催补</h3>
        <pre class="mini-log">${escapeHtml(report.customer_material_request || "")}</pre>
      </article>
    </div>
    <div class="starter-checklist">
      ${
        checklist
          .map(
            (item) => `
              <article class="result-item ${escapeHtml(item.status || "")}">
                <h3><span class="tag">${escapeHtml(item.status || "")}</span>${escapeHtml(item.title || "")}</h3>
                <p>${escapeHtml(item.detail || "")}</p>
                ${item.action ? `<p>${escapeHtml(item.action)}</p>` : ""}
              </article>
            `,
          )
          .join("") || "<p>暂无开工清单。</p>"
      }
    </div>
    <div class="command-actions starter-actions">
      ${
        actions
          .slice(0, 6)
          .map(
            (action) => `
              <button
                type="button"
                class="${action.variant === "secondary" ? "secondary" : ""}"
                data-command-action="${escapeHtml(action.action_code || "")}"
                data-command-target="${escapeHtml(action.target || "")}"
              >${escapeHtml(action.label || "")}</button>
            `,
          )
          .join("") || "<p>暂无可执行动作。</p>"
      }
    </div>
  `;
}

async function refreshProductionStarter() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderProductionStarter(null);
    return;
  }
  renderProductionStarter(await api(`/api/tenders/${tenderId}/production-starter`));
}

function copyableLabel(key) {
  return {
    customer_reply: "接单回复",
    material_request: "资料清单",
    order_confirmation: "确认话术",
    channel_boundary: "渠道边界",
  }[key] || key;
}

function renderOrderWizard(report) {
  state.orderWizard = report || null;
  if (!report) {
    el("orderWizard").innerHTML = `
      <article class="result-item workflow-next">
        <h3>新单生产向导</h3>
        <p>先在接单助手粘贴客户消息，创建订单草稿后这里会显示完整生产路线。</p>
      </article>
    `;
    el("wizardCopyText").value = "";
    return;
  }
  const summary = report.summary || {};
  const tender = report.tender || {};
  const phases = report.phases || [];
  const steps = report.steps || [];
  const actions = report.action_bar || [];
  const copyables = report.copyables || {};
  const progress = Math.max(0, Math.min(100, Math.round(Number(summary.progress || 0) * 100)));
  el("wizardCopyText").value = summary.recommended_copy_text || "";
  el("orderWizard").innerHTML = `
    <article class="command-hero">
      <div>
        <p class="eyebrow">${escapeHtml(summary.strategy || "先生产工具，后交付助手")}</p>
        <h3>${escapeHtml(summary.current_phase || "接单确认")}：${escapeHtml(summary.current_step || "待开始")}</h3>
        <p>${escapeHtml(tender.name || "未命名项目")} / ${escapeHtml(tender.industry || "未登记行业")}</p>
      </div>
      <div class="wizard-progress">
        <span class="review-status ${cardStatusClass(summary.state || "")}">${escapeHtml(summary.state || "needs_work")}</span>
        <strong>${summary.completed_steps ?? 0}/${summary.total_steps ?? 0} 步</strong>
        <div class="wizard-meter"><span style="width:${progress}%"></span></div>
        <p>当前动作：${escapeHtml(summary.current_action || "刷新向导")}</p>
      </div>
    </article>
    <div class="wizard-phases">
      ${
        phases
          .map(
            (phase) => `
              <article class="card ${cardStatusClass(phase.status || "")}">
                <span>${escapeHtml(phase.label || "")}</span>
                <strong>${escapeHtml(phase.completed ?? 0)}/${escapeHtml(phase.total ?? 0)}</strong>
                <p>${escapeHtml(workflowStatusLabel(phase.status || ""))}</p>
              </article>
            `,
          )
          .join("")
      }
    </div>
    <div class="command-actions">
      ${
        actions
          .map(
            (action) => `
              <button
                type="button"
                class="${action.variant === "secondary" ? "secondary" : ""}"
                data-wizard-action="${escapeHtml(action.action_code || "")}"
                data-wizard-target="${escapeHtml(action.target || "")}"
              >${escapeHtml(action.label || "")}</button>
            `,
          )
          .join("")
      }
    </div>
    <div class="wizard-copy-grid">
      ${Object.keys(copyables)
        .map((key) => `<button type="button" class="secondary" data-wizard-copy="${escapeHtml(key)}">${escapeHtml(copyableLabel(key))}</button>`)
        .join("")}
    </div>
    <div class="wizard-steps">
      ${
        steps
          .map((step) => {
            const action = step.action || {};
            return `
              <article class="result-item wizard-step ${escapeHtml(step.status || "")}">
                <h3><span class="tag">${escapeHtml(workflowStatusLabel(step.status || ""))}</span>${escapeHtml(step.title || "")}</h3>
                <p><span class="tag">${escapeHtml(step.phase_label || "")}</span>${escapeHtml(step.detail || "")}</p>
                ${
                  action.label
                    ? `<button type="button" class="${action.variant === "secondary" ? "secondary" : ""}" data-wizard-action="${escapeHtml(action.action_code || "")}" data-wizard-target="${escapeHtml(action.target || "")}">${escapeHtml(action.label || "")}</button>`
                    : ""
                }
              </article>
            `;
          })
          .join("")
      }
    </div>
  `;
}

async function refreshOrderWizard() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderOrderWizard(null);
    return;
  }
  renderOrderWizard(await api(`/api/tenders/${tenderId}/order-wizard`));
}

async function refreshGuides() {
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function copyStarterReply() {
  const message = el("starterCustomerReply").value || "";
  if (!message.trim()) throw new Error("请先生成生产启动包。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("starterCustomerReply").select();
    document.execCommand("copy");
  }
  log("生产启动包接单回复已复制。");
}

async function copyWizardText(key = "") {
  if (state.orderWizard && key) {
    el("wizardCopyText").value = state.orderWizard.copyables?.[key] || "";
  } else if (state.orderWizard && !el("wizardCopyText").value.trim()) {
    el("wizardCopyText").value = state.orderWizard.summary?.recommended_copy_text || "";
  }
  const message = el("wizardCopyText").value || "";
  if (!message.trim()) throw new Error("请先生成新单生产向导。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("wizardCopyText").select();
    document.execCommand("copy");
  }
  log(`向导话术已复制${key ? `：${copyableLabel(key)}` : ""}。`);
}

function renderChannelOps(report) {
  state.channelOps = report || null;
  if (!report) {
    el("channelOps").innerHTML = `
      <article class="result-item workflow-next">
        <h3>渠道运营助手</h3>
        <p>打开项目后，这里会生成闲鱼、微信等渠道可复制话术和人工确认边界。</p>
      </article>
    `;
    el("channelScriptText").value = "";
    return;
  }
  const summary = report.summary || {};
  const policy = report.policy || {};
  const scripts = report.scripts || [];
  const checklist = report.checklist || [];
  const recommended = scripts.find((item) => item.key === summary.recommended_script_key) || scripts.find((item) => item.status === "ready") || {};
  el("channelScriptText").value = recommended.text || "";
  el("channelOps").innerHTML = `
    <article class="command-hero">
      <div>
        <p class="eyebrow">${escapeHtml(summary.mode || "人工确认后交付")}</p>
        <h3>${escapeHtml(summary.platform || "渠道")}：${escapeHtml(summary.current_step || "待推进")}</h3>
        <p>${escapeHtml(summary.automation_boundary || "只生成可复制话术，不自动操作平台账号。")}</p>
      </div>
      <div class="command-decision">
        <span class="review-status ${cardStatusClass(summary.state || "")}">${escapeHtml(summary.state || "needs_work")}</span>
        <strong>${summary.copy_assets ?? 0} 条可复制话术</strong>
        <p>待处理动作：${summary.pending_actions ?? 0} 项</p>
      </div>
    </article>
    <div class="channel-checklist">
      ${checklist
        .map(
          (item) => `
            <article class="card ${cardStatusClass(item.status || "")}">
              <span>${escapeHtml(item.title || "")}</span>
              <strong>${escapeHtml(workflowStatusLabel(item.status || ""))}</strong>
              <p>${escapeHtml(item.detail || "")}</p>
            </article>
          `,
        )
        .join("")}
    </div>
    <article class="result-item">
      <h3>人工确认边界</h3>
      ${(policy.manual_confirm || []).map((item) => `<p><span class="tag">确认</span>${escapeHtml(item)}</p>`).join("")}
      ${(policy.do_not_automate || []).map((item) => `<p><span class="tag">不自动化</span>${escapeHtml(item)}</p>`).join("")}
    </article>
    <div class="channel-script-grid">
      ${scripts
        .map(
          (item) => `
            <article class="result-item channel-script-card">
              <h3><span class="tag">${escapeHtml(item.stage || "")}</span>${escapeHtml(item.label || "")}</h3>
              <p>${escapeHtml(item.usage || "")}</p>
              <pre>${escapeHtml((item.text || "待生成").slice(0, 360))}</pre>
              <button type="button" class="secondary" data-channel-copy="${escapeHtml(item.key || "")}">复制</button>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

async function refreshChannelOps() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderChannelOps(null);
    return;
  }
  renderChannelOps(await api(`/api/tenders/${tenderId}/channel-ops`));
}

async function copyChannelScript(key = "") {
  if (state.channelOps) {
    const scripts = state.channelOps.scripts || [];
    const summary = state.channelOps.summary || {};
    const item = scripts.find((script) => script.key === key) || scripts.find((script) => script.key === summary.recommended_script_key) || scripts.find((script) => script.status === "ready");
    if (item?.text) el("channelScriptText").value = item.text;
  }
  const message = el("channelScriptText").value || "";
  if (!message.trim()) throw new Error("请先生成渠道运营助手。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("channelScriptText").select();
    document.execCommand("copy");
  }
  log(`渠道话术已复制${key ? `：${key}` : ""}。`);
}

function scrollToStage(target) {
  const node = target ? document.getElementById(target) : null;
  if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function parseCurrentTender() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const parsed = await api(`/api/tenders/${tenderId}/parse`, { method: "POST", body: "{}" });
  renderProfile(parsed.profile || {});
  renderRequirements(parsed.requirements || []);
  await refreshResponseMatrix().catch(() => {});
  await refreshWorkflow().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
  log(`招标要求解析完成：${(parsed.requirements || []).length} 条`);
}

async function executeCommandAction(action, target) {
  if (target) scrollToStage(target);
  if (action === "scroll") return;
  if (action === "parse_current") await parseCurrentTender();
  else if (action === "build_plan") await buildPlan();
  else if (action === "generate_all") await generateAllPlan();
  else if (action === "quality_gate") await refreshQualityGate();
  else if (action === "production_readiness") await refreshProductionReadiness();
  else if (action === "sync_revision_tasks") await syncRevisionTasks();
  else if (action === "export_package") await exportTender("package");
  else if (action === "delivery_assistant") await refreshDeliveryAssistant();
  else if (action === "closure_confirmation") await refreshClosureConfirmation();
  else if (action === "run_pipeline") await runProductionPipeline();
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function executeWizardAction(action, target) {
  if (target) scrollToStage(target);
  if (action === "scroll") return;
  if (action === "create_intake_tender") await createIntakeTender();
  else if (action === "build_intake") await buildIntakeAssistant();
  else if (action === "apply_intake_task") await applyIntakeTask();
  else if (action === "build_order_confirmation") await buildOrderConfirmation();
  else if (action === "copy_material_request") await copyWizardText("material_request");
  else if (action === "copy_order_confirmation") await copyWizardText("order_confirmation");
  else if (action === "copy_customer_reply") await copyWizardText("customer_reply");
  else if (action === "copy_recommended") await copyWizardText();
  else if (action === "refresh_guides") await refreshGuides();
  else await executeCommandAction(action, target);
  await refreshGuides();
}

function renderLlmStatus(data, probe = null) {
  state.llmStatus = data || null;
  const status = data || {};
  el("llmStatusPanel").innerHTML = [
    ["配置", status.configured ? "已配置" : "未配置"],
    ["模式", status.generation_mode === "llm" ? "LLM" : "本地保底"],
    ["模型", status.model || "未设置"],
    ["协议", status.wire_api === "responses" ? "Responses API" : "Chat Completions"],
    ["接口", status.base_url || "未设置"],
  ]
    .map(([label, value]) => `<article class="card"><span>${label}</span><strong>${escapeHtml(value)}</strong></article>`)
    .join("");
  if (!probe) {
    el("llmProbeResult").innerHTML = `<p>${escapeHtml(status.note || "刷新后显示模型配置状态。")}</p>`;
    return;
  }
  el("llmProbeResult").innerHTML = `
    <article class="result-item">
      <h3>${probe.ok ? "连通性正常" : "连通性未通过"}</h3>
      <p><span class="tag">${escapeHtml(probe.model || "")}</span><span class="tag">${probe.latency_ms ?? 0} ms</span>${escapeHtml(probe.sample || probe.error || "")}</p>
    </article>
  `;
}

async function refreshLlmStatus() {
  renderLlmStatus(await api("/api/llm/status"));
}

async function probeLlm() {
  const result = await api("/api/llm/probe", {
    method: "POST",
    body: "{}",
  });
  renderLlmStatus(result, result);
  log(result.ok ? "LLM connectivity check passed." : `LLM connectivity check failed: ${result.error || "not configured"}`);
}

function generationDisplay(item = {}) {
  const generation = item.generation || {};
  const mode = generation.mode || item.generation_mode || "unknown";
  const model = generation.model || item.generation_model || "";
  const error = generation.error || item.generation_error || "";
  const label = mode === "llm" ? "LLM 生成" : mode === "local_fallback" ? "本地保底" : "未知方式";
  return { mode, model, error, label };
}

function renderOrderDashboard(report) {
  state.orderDashboard = report || null;
  if (!report) {
    el("orderDashboard").innerHTML = "<p>刷新后显示订单排产、临期、返工和交付状态。</p>";
    return;
  }
  const summary = report.summary || {};
  const nextItems = report.next_items || [];
  const byStage = report.by_stage || [];
  el("orderDashboard").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>项目总数</span><strong>${summary.total ?? 0}</strong></article>
      <article class="card"><span>逾期</span><strong>${summary.overdue ?? 0}</strong></article>
      <article class="card"><span>48小时内</span><strong>${summary.due_soon ?? 0}</strong></article>
      <article class="card"><span>未处理反馈</span><strong>${summary.feedback_open ?? 0}</strong></article>
      <article class="card"><span>未收款</span><strong>${summary.payment_pending_amount ?? 0}</strong></article>
      <article class="card"><span>已结案</span><strong>${summary.closed ?? 0}</strong></article>
    </div>
    <article class="result-item">
      <h3>生产阶段</h3>
      ${byStage.map((item) => `<p><span class="tag">${escapeHtml(item.name)}</span>${item.count} 个项目</p>`).join("") || "<p>暂无项目。</p>"}
    </article>
    <article class="result-item">
      <h3>下一步待办</h3>
      ${
        nextItems
          .map(
            (item) => `
            <p>
              <span class="tag">${escapeHtml(item.urgency)}</span>
              <span class="tag">${escapeHtml(item.payment_status_label || "收款待确认")}</span>
              ${escapeHtml(item.name)} / ${escapeHtml(item.customer_name || "未登记客户")} / ${escapeHtml(item.stage)}
              / 目录 ${escapeHtml(item.plan_progress)} / ${escapeHtml(item.next_action)}
            </p>
          `,
          )
          .join("") || "<p>暂无待办。</p>"
      }
    </article>
  `;
}

async function refreshOrderDashboard() {
  renderOrderDashboard(await api("/api/orders/dashboard"));
}

function renderProjectOverview(report) {
  state.projectOverview = report || null;
  if (!report) {
    el("projectOverview").innerHTML = "<p>打开项目后，这里会集中显示订单状态、生产进度、风险和下一步动作。</p>";
    return;
  }
  const tender = report.tender || {};
  const task = report.task || {};
  const metrics = report.metrics || {};
  const readiness = report.readiness || {};
  const risks = report.risks || [];
  const actions = report.next_actions || [];
  el("projectOverview").innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>${escapeHtml(tender.name || "未命名项目")}</h3>
        <p>${escapeHtml(task.customer_name || "未登记客户")} / ${escapeHtml(task.source_platform || "未登记来源")} / ${escapeHtml(task.deadline || "未登记期限")} / ${escapeHtml(task.delivery_status || "待生产")}</p>
      </div>
      <span class="review-status ${readiness.export_ready ? "ready" : "needs_work"}">${escapeHtml(readiness.label || "待判断")}</span>
    </article>
    <div class="coverage-grid">
      <article class="card"><span>章节进度</span><strong>${metrics.generated_plans ?? 0}/${metrics.plans ?? 0}</strong></article>
      <article class="card"><span>质量门禁分</span><strong>${metrics.quality_score ?? 0}</strong></article>
      <article class="card"><span>必要资料</span><strong>${metrics.materials_ready ?? 0}/${metrics.materials_required ?? 0}</strong></article>
      <article class="card"><span>待沟通</span><strong>${metrics.communications_pending ?? 0}</strong></article>
      <article class="card"><span>收款</span><strong>${escapeHtml(metrics.payment_status_label || "未登记")}</strong></article>
    </div>
    <div class="overview-columns">
      <article class="result-item">
        <h3>主要风险</h3>
        ${
          risks
            .map((item) => `<p><span class="tag">${escapeHtml(item.level || "")}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.detail || "")}</p>`)
            .join("") || "<p>暂无关键风险。</p>"
        }
      </article>
      <article class="result-item">
        <h3>下一步动作</h3>
        ${
          actions
            .map((item) => `<p><span class="tag">${escapeHtml(item.target || "")}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.detail || "")}</p>`)
            .join("") || "<p>暂无待办动作。</p>"
        }
      </article>
    </div>
  `;
}

async function refreshProjectOverview() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderProjectOverview(null);
    return;
  }
  renderProjectOverview(await api(`/api/tenders/${tenderId}/overview`));
}

function renderProjectTimeline(report) {
  state.projectTimeline = report || null;
  if (!report) {
    el("projectTimeline").innerHTML = "<p>打开项目后，这里会自动整理项目创建、资料处理、报价、收款、生成、交付和复盘记录。</p>";
    return;
  }
  const summary = report.summary || {};
  const events = report.events || [];
  el("projectTimeline").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>履历事件</span><strong>${summary.total_events ?? 0}</strong></article>
      <article class="card"><span>最近动作</span><strong>${escapeHtml(summary.latest_title || "无")}</strong></article>
      <article class="card"><span>收款记录</span><strong>${summary.payment_events ?? 0}</strong></article>
      <article class="card"><span>章节记录</span><strong>${summary.draft_events ?? 0}</strong></article>
      <article class="card"><span>交付记录</span><strong>${summary.delivery_events ?? 0}</strong></article>
    </div>
    <article class="result-item">
      <h3>时间范围</h3>
      <p>起始：${escapeHtml(summary.first_event_at || "未记录")} / 最近：${escapeHtml(summary.latest_event_at || "未记录")} / 状态：${escapeHtml(summary.latest_status || "未标注")}</p>
    </article>
    <ol class="timeline-list">
      ${
        events
          .map(
            (item) => `
              <li class="timeline-event">
                <time>${escapeHtml(item.occurred_at || "未记录时间")}</time>
                <div>
                  <strong><span class="tag">${escapeHtml(item.kind_label || item.kind || "记录")}</span>${escapeHtml(item.title || "")}</strong>
                  <p>${escapeHtml(item.detail || "")}</p>
                  ${
                    item.source
                      ? `<p>来源：${escapeHtml(item.source)}</p>`
                      : ""
                  }
                  ${
                    item.ref_table
                      ? `<p>记录：${escapeHtml(item.ref_table)}${item.ref_id ? ` #${escapeHtml(item.ref_id)}` : ""}${item.status ? ` / ${escapeHtml(item.status)}` : ""}</p>`
                      : ""
                  }
                </div>
              </li>
            `,
          )
          .join("") || "<li class=\"timeline-event\"><time>无</time><div><strong>暂无履历</strong><p>当前项目还没有可展示的生产记录。</p></div></li>"
      }
    </ol>
  `;
}

async function refreshProjectTimeline() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderProjectTimeline(null);
    return;
  }
  renderProjectTimeline(await api(`/api/tenders/${tenderId}/timeline`));
}

async function syncAllTaskStatus() {
  const result = await api("/api/orders/sync-status", {
    method: "POST",
    body: "{}",
  });
  log(`生产状态同步完成：${result.changed}/${result.total} 个项目发生变化。`);
  await refreshTenders();
  await refreshOrderDashboard();
  await refreshWorkflow().catch(() => {});
}

function workflowStatusLabel(status) {
  return {
    complete: "已完成",
    current: "进行中",
    pending: "待处理",
    warning: "需关注",
    blocked: "需处理",
    skipped: "已跳过",
  }[status] || status;
}

const PRODUCTION_STAGES = [
  { key: "parse", title: "招标解析", route: "tender" },
  { key: "outline", title: "目录策略", route: "outline" },
  { key: "drafts", title: "章节编制", route: "editor" },
  { key: "visuals", title: "图文配图", route: "visuals" },
  { key: "review", title: "质量审查", route: "review" },
  { key: "delivery", title: "成稿交付", route: "delivery" },
];

function confirmationFor(key) {
  return state.workflow?.confirmations?.[key] || { status: "pending", confirmed: false };
}

function productionStageModel(report) {
  const summary = report?.summary || {};
  const confirmations = report?.confirmations || {};
  const parseConfirmed = Boolean(confirmations.parse?.confirmed);
  const outlineConfirmed = Boolean(confirmations.outline?.confirmed);
  const reviewConfirmed = Boolean(confirmations.review?.confirmed);
  const profileMissing = summary.profile_missing || [];
  const requirements = Number(summary.requirements || 0);
  const plans = Number(summary.plans || 0);
  const generatedPlans = Number(summary.generated_plans || 0);
  const missingPlans = Number(summary.missing_plans || 0);
  const planReady = state.planAudit?.summary?.readiness === "ready";
  const strategyReady = Boolean(
    state.bidStrategy &&
      (state.bidStrategy.positioning || state.bidStrategy.win_themes || state.bidStrategy.response_priorities),
  );
  const visualCount = (state.documentBlocks || []).filter((item) => item.block_type !== "text").length;
  const qualitySummary = state.qualityGate?.summary || {};
  const revisionSummary = state.revisionTasks?.summary || {};
  const highOpen = Number(revisionSummary.high_open ?? qualitySummary.high ?? 0);
  const finalApproved = state.finalDocument?.approval?.status === "approved" || state.finalDocument?.summary?.approval_status === "approved";
  const deliveryRecords = Number(summary.delivery_records || 0);

  const stages = [
    {
      ...PRODUCTION_STAGES[0],
      status: parseConfirmed ? "complete" : confirmations.parse?.status === "stale" ? "stale" : "current",
      note: parseConfirmed ? `${requirements} 条要求已确认` : requirements ? "待人工确认" : "等待解析",
    },
    {
      ...PRODUCTION_STAGES[1],
      status: outlineConfirmed ? "complete" : parseConfirmed ? (confirmations.outline?.status === "stale" ? "stale" : "current") : "pending",
      note: outlineConfirmed ? `${plans} 章已确认` : plans ? "待确认目录" : "等待规划",
    },
    {
      ...PRODUCTION_STAGES[2],
      status: plans > 0 && missingPlans === 0 ? "complete" : outlineConfirmed ? "current" : "pending",
      note: plans ? `${generatedPlans}/${plans} 章` : "等待目录",
    },
    {
      ...PRODUCTION_STAGES[3],
      status: visualCount > 0 ? "complete" : plans > 0 && missingPlans === 0 ? "current" : "pending",
      note: visualCount ? `${visualCount} 个图文块` : "待生成图表",
    },
    {
      ...PRODUCTION_STAGES[4],
      status: reviewConfirmed ? "complete" : plans > 0 && missingPlans === 0 ? (highOpen ? "blocked" : confirmations.review?.status === "stale" ? "stale" : "current") : "pending",
      note: reviewConfirmed ? "已确认" : highOpen ? `${highOpen} 个高风险项` : "待质量检查",
    },
    {
      ...PRODUCTION_STAGES[5],
      status: deliveryRecords > 0 && reviewConfirmed ? "complete" : reviewConfirmed ? "current" : deliveryRecords > 0 ? "stale" : "pending",
      note: deliveryRecords > 0 && !reviewConfirmed ? "历史交付，需重新确认" : deliveryRecords ? "已有交付记录" : finalApproved ? "可正式导出" : "等待定稿",
    },
  ];

  let action = { title: "打开招标解析", detail: "先解析招标文件并核对项目关键参数。", primary: "navigate_tender", primaryLabel: "打开招标解析", secondary: "", checks: [] };
  if (!requirements) {
    action = { title: "解析招标文件", detail: "从当前招标文件提取项目概况、评分点、技术要求和废标风险。", primary: "parse_current", primaryLabel: "开始解析", secondary: "navigate_tender", checks: ["尚未形成响应矩阵"] };
  } else if (profileMissing.length) {
    action = { title: "补全项目关键参数", detail: "关键参数将直接影响工期计划、资源配置和施工方案，缺失时不进入目录生成。", primary: "navigate_profile", primaryLabel: "补全参数", secondary: "navigate_tender", checks: [`已解析 ${requirements} 条要求`, `缺少 ${profileMissing.length} 项参数`] };
  } else if (!parseConfirmed) {
    action = { title: "确认招标解析结果", detail: "请核对项目参数和响应矩阵。确认后，若解析内容再次变化，系统会自动要求重新确认。", primary: "confirm_parse", primaryLabel: "确认解析结果", secondary: "navigate_tender", checks: [`${requirements} 条要求`, confirmations.parse?.status === "stale" ? "内容已变化" : "等待人工确认"] };
  } else if (!outlineConfirmed) {
    if (!strategyReady) action = { title: "生成响应策略", detail: "先形成项目定位、响应重点和风险控制，再据此规划章节。", primary: "generate_strategy", primaryLabel: "生成响应策略", secondary: "navigate_outline", checks: ["招标解析已确认"] };
    else if (!plans) action = { title: "生成技术标目录", detail: "根据招标要求和响应策略生成章节目录，并把条款挂接到对应章节。", primary: "build_plan", primaryLabel: "生成目录", secondary: "navigate_outline", checks: ["响应策略已形成"] };
    else if (!state.planAudit) action = { title: "检查目录完整性", detail: "检查施工工艺等标准章节和高优先级条款是否完整覆盖。", primary: "audit_plan", primaryLabel: "检查目录", secondary: "navigate_outline", checks: [`已规划 ${plans} 章`] };
    else if (!planReady) action = { title: "补齐目录缺口", detail: "目录仍有标准章节或招标条款未覆盖，需要先补齐再确认。", primary: "repair_plan", primaryLabel: "一键补齐缺章", secondary: "navigate_outline", checks: ["目录审计未通过"] };
    else action = { title: "确认目录与响应策略", detail: "确认章节结构、排序和条款挂接后进入正式章节生产。", primary: "confirm_outline", primaryLabel: "确认目录策略", secondary: "navigate_outline", checks: [`${plans} 个章节`, "目录审计通过"] };
  } else if (missingPlans > 0 || !plans) {
    action = { title: "生成未完成章节", detail: "系统将按目录逐章检索历史资料并生成初稿。失败章节可单独重试。", primary: "generate_all", primaryLabel: state.flowBusy ? "正在生成..." : `生成剩余 ${missingPlans || plans} 章`, secondary: "navigate_editor", checks: [`已完成 ${generatedPlans}/${plans} 章`] };
  } else if (!visualCount) {
    action = { title: "生成专业图表与示意图", detail: "根据章节内容生成表格、组织架构图、流程图和横道图；施工照片类素材需人工复核。", primary: "generate_visuals", primaryLabel: "生成图文内容", secondary: "continue_review", checks: [`${plans} 个章节已生成`, "图文配图可跳过"] };
  } else if (!reviewConfirmed) {
    if (!state.qualityGate || !state.revisionTasks) action = { title: "执行全稿质量检查", detail: "检查条款覆盖、项目名残留、来源缺失、空泛表述和图文完整性。", primary: "run_review", primaryLabel: "执行质量检查", secondary: "navigate_review", checks: [`${visualCount} 个图文块`] };
    else if (highOpen) action = { title: "处理高风险审查项", detail: "高风险问题会阻断正式导出。打开对应章节修订后重新执行质量检查。", primary: "open_review", primaryLabel: `处理 ${highOpen} 个高风险项`, secondary: "navigate_review", checks: ["正式导出已锁定"] };
    else action = { title: "确认质量审查结果", detail: "高风险问题已清理。确认后，正文再次修改会使本次确认自动失效。", primary: "confirm_review", primaryLabel: "确认审查通过", secondary: "navigate_review", checks: [`质量分 ${state.qualityGate?.score ?? "-"}`, `${revisionSummary.medium_open || 0} 个提醒项`] };
  } else if (!finalApproved) {
    action = { title: "确认整本定稿", detail: "预览整本章节、图表和格式设置，填写复核人后确认定稿。", primary: "approve_final", primaryLabel: "进入定稿确认", secondary: "navigate_delivery", checks: ["质量审查已确认"] };
  } else {
    action = { title: "导出正式技术标", detail: "当前版本已通过质量确认并完成定稿，可以导出 DOCX 进行最终人工复核。", primary: "export_docx", primaryLabel: "导出 DOCX", secondary: "navigate_delivery", checks: ["质量审查已确认", "整本已定稿"] };
  }
  return { stages, action };
}

function renderExportGate() {
  const gateNode = el("exportGateNotice");
  if (!gateNode) return;
  const gateReviewReady = Boolean(confirmationFor("review").confirmed);
  const gateFinalReady = state.finalDocument?.approval?.status === "approved" || state.finalDocument?.summary?.approval_status === "approved";
  const gateAcceptance = state.acceptance?.current || state.acceptance || null;
  const gateBlockers = gateAcceptance?.blockers || [];
  const gateReady = typeof gateAcceptance?.ready === "boolean" ? gateAcceptance.ready : gateReviewReady && gateFinalReady;
  gateNode.className = `notice ${gateReady ? "ready" : "blocked"}`;
  if (gateReady) {
    gateNode.textContent = "正式导出门禁已通过。";
  } else if (gateBlockers.length) {
    gateNode.textContent = `正式导出未解锁：${gateBlockers.map((item) => item.title || item.detail || "待处理").join("、")}。内部审查包仍可导出。`;
  } else {
    gateNode.textContent = `正式导出未解锁：${!gateReviewReady ? "请先确认质量审查" : "请先确认整本定稿"}。内部审查包仍可导出。`;
  }
  ["exportDocx", "exportClientPackage", "exportClientPackageForDelivery"].forEach((id) => {
    if (el(id)) el(id).disabled = !gateReady;
  });
  if (el("exportPackage")) el("exportPackage").disabled = false;
  return;
}

function renderProductionGuide(report) {
  const guide = el("productionGuide");
  if (!guide || guide.hidden || !report) {
    renderExportGate();
    return;
  }
  const model = productionStageModel(report);
  const action = model.action;
  state.productionAction = action.primary || "";
  state.productionSecondaryAction = action.secondary || "";
  el("productionStageTrack").innerHTML = model.stages
    .map((stage, index) => `<a class="production-stage-item ${escapeHtml(stage.status)}" href="${projectRouteHref(stage.route)}"><strong>${index + 1}. ${escapeHtml(stage.title)}</strong><span>${escapeHtml(stage.note)}</span></a>`)
    .join("");
  const currentStage = model.stages.find((stage) => ["current", "blocked", "stale"].includes(stage.status)) || model.stages.at(-1);
  el("productionStageLabel").textContent = `当前阶段：${currentStage.title}`;
  el("productionGuideTitle").textContent = action.title;
  el("productionGuideDetail").textContent = action.detail;
  el("productionGuideChecks").innerHTML = (action.checks || []).map((item) => `<span class="production-check">${escapeHtml(item)}</span>`).join("");
  const primary = el("productionPrimaryAction");
  primary.textContent = action.primaryLabel || "继续";
  primary.disabled = state.flowBusy;
  const secondary = el("productionSecondaryAction");
  secondary.hidden = !action.secondary;
  secondary.textContent = action.secondary === "continue_review" ? "跳过配图，进入审查" : "查看详情";
  renderExportGate();
}

async function confirmWorkflowStage(stageKey) {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  await api(`/api/tenders/${tenderId}/workflow-confirmations/${stageKey}`, {
    method: "PATCH",
    body: JSON.stringify({ confirmed: true, confirmed_by: el("finalDocApprovedBy")?.value || "内部复核" }),
  });
  log(`${{ parse: "招标解析", outline: "目录策略", review: "质量审查" }[stageKey]}已确认。`);
  await refreshWorkflow();
}

function navigateProject(page, targetId = "") {
  location.hash = `#/projects/${state.currentTenderId}/${page}`;
  if (targetId) setTimeout(() => document.getElementById(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
}

async function runProductionAction(action) {
  if (!action || state.flowBusy) return;
  if (action === "navigate_tender") return navigateProject("tender");
  if (action === "navigate_profile") return navigateProject("tender", "stage-profile");
  if (action === "navigate_outline") return navigateProject("outline");
  if (action === "navigate_editor") return navigateProject("editor");
  if (action === "navigate_review" || action === "open_review" || action === "continue_review") return navigateProject("review", action === "open_review" ? "revisionTasks" : "");
  if (action === "navigate_delivery" || action === "approve_final") return navigateProject("delivery", "stage-final");
  state.flowBusy = true;
  renderProductionGuide(state.workflow);
  try {
    if (action === "parse_current") await parseCurrentTender();
    else if (action === "confirm_parse") await confirmWorkflowStage("parse");
    else if (action === "generate_strategy") await generateBidStrategy();
    else if (action === "build_plan") await buildPlan();
    else if (action === "audit_plan") await refreshPlanAudit();
    else if (action === "repair_plan") await repairPlanAudit();
    else if (action === "confirm_outline") await confirmWorkflowStage("outline");
    else if (action === "generate_all") await generateAllPlan();
    else if (action === "generate_visuals") await generateRichDocument();
    else if (action === "run_review") {
      await refreshQualityGate();
      await syncRevisionTasks();
      await refreshSourceAudit();
    } else if (action === "confirm_review") await confirmWorkflowStage("review");
    else if (action === "export_docx") await exportTender("docx");
  } finally {
    state.flowBusy = false;
    renderProductionGuide(state.workflow);
  }
}

function renderWorkflow(report) {
  if (!report) {
    state.workflow = null;
    el("workflowBoard").innerHTML = "<p>打开项目后，这里会显示从资料补齐到导出 Word 的生产流程。</p>";
    el("projectNextStep").textContent = "等待项目数据";
    return;
  }
  state.workflow = report;
  const nextStep = report.next_step || {};
  el("projectNextStep").textContent = nextStep.title || "人工复核";
  el("workflowBoard").innerHTML = `
    <article class="result-item workflow-next">
      <h3>下一步：${escapeHtml(nextStep.title || "暂无")}</h3>
      <p>${escapeHtml(nextStep.detail || "")}</p>
      ${nextStep.action ? `<p><span class="tag">建议</span>${escapeHtml(nextStep.action)}</p>` : ""}
    </article>
    <div class="workflow-steps">
      ${(report.steps || [])
        .map(
          (step) => `
          <article class="workflow-step ${escapeHtml(step.status)}">
            <strong>${escapeHtml(step.title)}</strong>
            <p><span class="tag">${escapeHtml(workflowStatusLabel(step.status))}</span>${escapeHtml(step.detail)}</p>
          </article>
        `,
        )
        .join("")}
    </div>
  `;
  renderProductionGuide(report);
  renderGenerationProgress();
}

async function refreshWorkflow() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderWorkflow(null);
    renderDeliveryReview(null);
    return;
  }
  renderWorkflow(await api(`/api/tenders/${tenderId}/workflow`));
}

function renderDeliveryReview(report) {
  if (!report) {
    el("deliveryReviewReport").innerHTML = "";
    return;
  }
  const summary = report.summary || {};
  const blockers = report.blockers || [];
  const checklist = report.checklist || [];
  const recommendations = report.recommendations || [];
  el("deliveryReviewReport").innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>交付审查结论：${escapeHtml(summary.readiness_label || "")}</h3>
        <p>条款覆盖 ${toPercent(summary.draft_coverage_rate)} / 章节 ${summary.generated_sections ?? 0}/${summary.total_sections ?? 0} / 高优先级缺口 ${summary.high_priority_missing ?? 0} / 审查问题 ${summary.review_findings ?? 0}</p>
      </div>
      <span class="review-status ${escapeHtml(summary.readiness || "")}">${escapeHtml(summary.export_ready ? "可导出" : "需补齐")}</span>
    </article>
    <div class="review-checklist">
      ${checklist
        .map(
          (item) => `
          <article class="checklist-item ${escapeHtml(item.status)}">
            <strong>${escapeHtml(item.title)}</strong>
            <p><span class="tag">${escapeHtml(workflowStatusLabel(item.status))}</span>${escapeHtml(item.detail)}</p>
            ${item.action ? `<p>建议：${escapeHtml(item.action)}</p>` : ""}
          </article>
        `,
        )
        .join("")}
    </div>
    <article class="result-item">
      <h3>主要阻碍</h3>
      ${
        blockers
          .map((item) => `<p><span class="tag">${escapeHtml(item.severity)}</span>${escapeHtml(item.title)}：${escapeHtml(item.detail)}</p>`)
          .join("") || "<p>暂无阻碍项，可进入人工终审。</p>"
      }
    </article>
    <article class="result-item">
      <h3>处理建议</h3>
      ${recommendations.map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无额外建议。</p>"}
    </article>
  `;
}

async function refreshDeliveryReview() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderDeliveryReview(null);
    return;
  }
  renderDeliveryReview(await api(`/api/tenders/${tenderId}/delivery-review`));
}

function deliveryReleaseLabel(value) {
  return {
    ready: "可放行交付",
    conditional: "人工确认后放行",
    blocked: "暂不放行",
  }[value] || value || "待判断";
}

function renderDeliveryRelease(report, targetId = "deliveryReleaseReport") {
  state.deliveryRelease = report || null;
  const target = el(targetId);
  if (!target) return;
  if (!report) {
    target.innerHTML = "";
    return;
  }
  const summary = report.summary || {};
  const checks = report.checks || [];
  const blockers = report.blockers || [];
  const warnings = report.warnings || [];
  const actions = report.next_actions || [];
  const artifacts = report.artifacts || {};
  target.innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>交付放行：${escapeHtml(summary.release_label || deliveryReleaseLabel(summary.release_status))}</h3>
        <p>综合分 ${summary.score ?? 0} / 阻断项 ${summary.blockers ?? 0} / 提醒项 ${summary.warnings ?? 0} / 章节 ${summary.generated_sections ?? 0}/${summary.total_sections ?? 0}</p>
      </div>
      <span class="review-status ${summary.release_status === "ready" ? "ready" : summary.release_status === "blocked" ? "not_ready" : "needs_work"}">${escapeHtml(deliveryReleaseLabel(summary.release_status))}</span>
    </article>
    <div class="coverage-grid">
      <article class="card"><span>成稿确认</span><strong>${escapeHtml(finalDocumentStatusLabel(summary.approval_status))}</strong></article>
      <article class="card"><span>质量分</span><strong>${summary.quality_score ?? 0}</strong></article>
      <article class="card"><span>来源审计</span><strong>${escapeHtml(readinessStatusLabel(summary.source_readiness))}</strong></article>
      <article class="card"><span>ZIP 核验</span><strong>${summary.zip_readable ? "可读取" : "待生成"}</strong></article>
      <article class="card"><span>客户包</span><strong>${summary.client_zip_readable ? "可读取" : "待生成"}</strong></article>
    </div>
    <article class="result-item">
      <h3>放行检查</h3>
      ${
        checks
          .map((item) => `<p><span class="tag">${checkStatusLabel(item.status)}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.detail || "")}</p>`)
          .join("") || "<p>暂无检查项。</p>"
      }
    </article>
    <article class="result-item">
      <h3>阻断与提醒</h3>
      ${
        [...blockers, ...warnings]
          .map((item) => `<p><span class="tag">${checkStatusLabel(item.status)}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.action || item.detail || "")}</p>`)
          .join("") || "<p>暂无阻断或提醒项。</p>"
      }
    </article>
    <article class="result-item">
      <h3>下一步</h3>
      ${actions.map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>执行人工终审后交付。</p>"}
      ${artifacts.package_path ? `<p><span class="tag">交付包</span>${escapeHtml(artifacts.package_path)}</p>` : ""}
      ${artifacts.client_package_path ? `<p><span class="tag">客户包</span>${escapeHtml(artifacts.client_package_path)}</p>` : ""}
    </article>
  `;
}

async function refreshDeliveryRelease(targetId = "deliveryReleaseReport") {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderDeliveryRelease(null, targetId);
    return;
  }
  renderDeliveryRelease(await api(`/api/tenders/${tenderId}/delivery-release`), targetId);
}

function renderSourceAudit(report) {
  state.sourceAudit = report || null;
  if (!report) {
    el("sourceAuditReport").innerHTML = "";
    return;
  }
  const summary = report.summary || {};
  const sections = report.sections || [];
  const sources = report.sources || [];
  const problemSections = sections.filter((item) => (item.problems || []).length);
  el("sourceAuditReport").innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>引用来源审计：${escapeHtml(summary.readiness || "待检查")}</h3>
        <p>章节 ${summary.cited_drafts ?? 0}/${summary.drafts ?? 0} / 引用 ${summary.valid_citations ?? 0}/${summary.total_citations ?? 0} / 失效 ${summary.invalid_citations ?? 0} / 独立来源 ${summary.unique_sources ?? 0}</p>
      </div>
      <span class="review-status ${summary.readiness === "ready" ? "ready" : summary.readiness === "needs_work" ? "not_ready" : "needs_work"}">${summary.uncited_drafts ? "有缺口" : "可追溯"}</span>
    </article>
    <div class="coverage-grid">
      <article class="card"><span>缺引用章节</span><strong>${summary.uncited_drafts ?? 0}</strong></article>
      <article class="card"><span>失效引用</span><strong>${summary.invalid_citations ?? 0}</strong></article>
      <article class="card"><span>案例引用</span><strong>${summary.case_asset_citations ?? 0}</strong></article>
      <article class="card"><span>知识库引用</span><strong>${summary.kb_citations ?? 0}</strong></article>
      <article class="card"><span>旧项目名风险</span><strong>${summary.old_project_findings ?? 0}</strong></article>
    </div>
    <div class="overview-columns">
      <article class="result-item">
        <h3>问题章节</h3>
        ${
          problemSections
            .map(
              (section) => `
                <p>
                  <span class="tag">${escapeHtml(section.section_title || "")}</span>
                  引用 ${section.citations_count ?? 0} 条，失效 ${section.invalid_citations ?? 0} 条。
                  ${(section.problems || []).map((problem) => `${escapeHtml(problem.title || "")}：${escapeHtml(problem.detail || "")}`).join(" / ")}
                </p>
              `,
            )
            .join("") || "<p>暂无来源审计问题。</p>"
        }
      </article>
      <article class="result-item">
        <h3>高频来源</h3>
        ${
          sources
            .slice(0, 8)
            .map(
              (source) => `
                <p>
                  <span class="tag">${escapeHtml(source.source_type || "")}</span>
                  <span class="tag">${source.indexed ? "已索引" : "未定位"}</span>
                  ${escapeHtml(source.source_path || source.key || "未登记来源")} / ${source.citations_count ?? 0} 次
                </p>
              `,
            )
            .join("") || "<p>暂无引用来源。</p>"
        }
      </article>
    </div>
    <article class="result-item">
      <h3>处理建议</h3>
      ${(report.recommendations || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无建议。</p>"}
    </article>
  `;
}

async function refreshSourceAudit() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderSourceAudit(null);
    return;
  }
  renderSourceAudit(await api(`/api/tenders/${tenderId}/source-audit`));
}

function renderFinalChecklist(report) {
  state.finalChecklist = report || null;
  if (!report) {
    el("finalChecklist").innerHTML = "";
    return;
  }
  const summary = report.summary || {};
  el("finalChecklist").innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>最终核对：${escapeHtml(summary.readiness_label || "")}</h3>
        <p>必选项 ${summary.required_confirmed ?? 0}/${summary.required_total ?? 0} / 待人工确认 ${summary.manual_pending ?? 0} / 自动阻碍 ${summary.auto_blockers ?? 0} / 自动提醒 ${summary.auto_warnings ?? 0}</p>
      </div>
      <span class="review-status ${summary.readiness === "ready" ? "ready" : summary.readiness === "needs_work" ? "not_ready" : "needs_work"}">${escapeHtml(summary.readiness || "")}</span>
    </article>
    <div class="table-list">
      ${(report.items || [])
        .map(
          (item) => `
          <article class="row-item delivery-row">
            <div>
              <strong>${escapeHtml(item.title || "")}</strong>
              <p><span class="tag">${escapeHtml(item.required ? "必选" : "建议")}</span><span class="tag">${escapeHtml(item.category || "")}</span><span class="tag">${escapeHtml(item.auto_status || "")}</span>${escapeHtml(item.auto_detail || "")}</p>
              <div class="final-check-edit-grid">
                <label>人工状态
                  <select data-final-status="${item.id}">
                    ${["待确认", "已确认", "需处理", "不适用"].map((status) => `<option value="${status}" ${status === item.status ? "selected" : ""}>${status}</option>`).join("")}
                  </select>
                </label>
                <label>负责人<input value="${escapeHtml(item.owner || "")}" data-final-owner="${item.id}" /></label>
                <label>备注<textarea rows="2" data-final-notes="${item.id}">${escapeHtml(item.notes || "")}</textarea></label>
              </div>
            </div>
            <button type="button" class="secondary" data-save-final-check="${item.id}">保存</button>
          </article>
        `,
        )
        .join("")}
    </div>
  `;
}

async function refreshFinalChecklist() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderFinalChecklist(null);
    return;
  }
  renderFinalChecklist(await api(`/api/tenders/${tenderId}/final-checklist`));
}

function finalDocumentStatusLabel(status) {
  return {
    draft: "待确认",
    reviewing: "复核中",
    needs_revision: "需修改",
    approved: "已定稿",
  }[status] || status || "待确认";
}

function renderFinalDocument(report) {
  state.finalDocument = report || null;
  const approval = report?.approval || {};
  if (el("finalDocStatus")) el("finalDocStatus").value = approval.status || "draft";
  if (el("finalDocApprovedBy")) el("finalDocApprovedBy").value = approval.approved_by || "";
  if (el("finalDocNotes")) el("finalDocNotes").value = approval.notes || "";
  if (!report) {
    el("finalDocumentSummary").innerHTML = "";
    el("finalDocumentWarnings").innerHTML = "";
    el("finalDocumentSections").innerHTML = "";
    el("finalDocumentContent").value = "";
    renderProductionGuide(state.workflow);
    return;
  }
  const summary = report.summary || {};
  el("finalDocumentSummary").innerHTML = [
    ["章节", `${summary.generated_sections ?? 0}/${summary.total_sections ?? 0}`],
    ["缺章", summary.missing_sections ?? 0],
    ["字数", summary.char_count ?? 0],
    ["风险", `${summary.blockers ?? 0}/${summary.warnings ?? 0}`],
    ["状态", finalDocumentStatusLabel(summary.approval_status)],
  ]
    .map(([label, value]) => `<article class="card"><span>${label}</span><strong>${escapeHtml(value)}</strong></article>`)
    .join("");
  el("finalDocumentWarnings").innerHTML =
    (report.warnings || [])
      .map(
        (item) => `
        <article class="result-item">
          <h3>${escapeHtml(item.title || "")}</h3>
          <p><span class="tag">${escapeHtml(item.level || "")}</span>${escapeHtml(item.detail || "")}</p>
        </article>
      `,
      )
      .join("") || "<p>暂无阻断项。</p>";
  el("finalDocumentSections").innerHTML =
    (report.sections || [])
      .map(
        (item) => `
        <article class="row-item">
          <div>
            <strong>${escapeHtml(item.order_no || "")}. ${escapeHtml(item.section_title || "")}</strong>
            <p><span class="tag">${escapeHtml(item.status === "missing" ? "未生成" : "已生成")}</span>${item.char_count ?? 0} 字 / 引用 ${item.citations ?? 0} 处</p>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无章节。</p>";
  el("finalDocumentContent").value = report.content || "";
  renderProductionGuide(state.workflow);
}

function finalDocumentPayload() {
  return {
    status: el("finalDocStatus").value || "draft",
    approved_by: el("finalDocApprovedBy").value,
    notes: el("finalDocNotes").value,
  };
}

async function refreshFinalDocument() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderFinalDocument(null);
    return;
  }
  renderFinalDocument(await api(`/api/tenders/${tenderId}/final-document`));
}

async function saveFinalDocument(statusOverride = null) {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("Please create or open a tender first.");
  const payload = finalDocumentPayload();
  if (statusOverride) payload.status = statusOverride;
  if (statusOverride === "approved" && !confirmationFor("review").confirmed) {
    navigateProject("review");
    throw new Error("请先处理审查问题并确认质量审查通过，再进行定稿。");
  }
  if (statusOverride === "approved" && !payload.approved_by.trim()) {
    payload.approved_by = "内部复核";
  }
  const report = await api(`/api/tenders/${tenderId}/final-document`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  renderFinalDocument(report);
  log(statusOverride === "approved" ? "Final document approved." : "Final document review status saved.");
  await refreshStatus().catch(() => {});
  await refreshDeliveryRelease().catch(() => {});
  await refreshDeliveryRelease("deliveryReleasePanel").catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshWorkflow().catch(() => {});
}

async function copyFinalDocument() {
  const content = el("finalDocumentContent").value;
  if (!content.trim()) throw new Error("Please refresh the final document first.");
  await navigator.clipboard.writeText(content);
  log("Final document Markdown copied.");
}

function finalCheckPayload(itemId) {
  return {
    status: document.querySelector(`[data-final-status="${itemId}"]`)?.value || "待确认",
    owner: document.querySelector(`[data-final-owner="${itemId}"]`)?.value || "",
    notes: document.querySelector(`[data-final-notes="${itemId}"]`)?.value || "",
  };
}

async function saveFinalCheck(itemId) {
  const item = await api(`/api/final-checks/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(finalCheckPayload(itemId)),
  });
  log(`最终核对项已保存：${item.title || item.id}`);
  await refreshFinalChecklist();
  await refreshFinalDocument().catch(() => {});
}

function renderQualityGate(report) {
  state.qualityGate = report || null;
  if (!report) {
    el("qualityGateReport").innerHTML = "";
    renderProductionGuide(state.workflow);
    return;
  }
  const summary = report.summary || {};
  const tasks = report.revision_tasks || [];
  el("qualityGateReport").innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>质量门禁：${escapeHtml(report.status_label || "")}</h3>
        <p>质量分 ${report.score ?? 0} / 修订任务 ${summary.task_count ?? 0} / 高风险 ${summary.high ?? 0} / 中风险 ${summary.medium ?? 0} / 低风险 ${summary.low ?? 0}</p>
      </div>
      <span class="review-status ${report.status === "pass" ? "ready" : report.status === "blocked" ? "not_ready" : "needs_work"}">${escapeHtml(report.status || "")}</span>
    </article>
    <div class="review-checklist">
      ${(report.gate_items || [])
        .map(
          (item) => `
          <article class="checklist-item ${escapeHtml(item.status === "blocked" ? "pending" : item.status)}">
            <strong>${escapeHtml(item.title || "")}</strong>
            <p><span class="tag">${escapeHtml(workflowStatusLabel(item.status))}</span>${escapeHtml(item.detail || "")}</p>
          </article>
        `,
        )
        .join("")}
    </div>
    <article class="result-item">
      <h3>修订任务清单</h3>
      ${
        tasks
          .slice(0, 20)
          .map(
            (item, index) =>
              `<p><span class="tag">${escapeHtml(item.severity || "")}</span>${index + 1}. ${escapeHtml(item.title || "")} / ${escapeHtml(
                item.scope || "",
              )}${item.section_title ? ` / ${escapeHtml(item.section_title)}` : ""}：${escapeHtml(item.action || "")}</p>`,
          )
          .join("") || "<p>暂无自动发现的修订任务，可进入人工终审。</p>"
      }
    </article>
  `;
  renderProductionGuide(state.workflow);
}

async function refreshQualityGate() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderQualityGate(null);
    renderRevisionTasks(null);
    renderSourceAudit(null);
    return;
  }
  renderQualityGate(await api(`/api/tenders/${tenderId}/quality-gate`));
}

function renderRevisionTasks(report) {
  state.revisionTasks = report || null;
  if (!report) {
    el("revisionTasks").innerHTML = "";
    renderProductionGuide(state.workflow);
    return;
  }
  const summary = report.summary || {};
  const items = report.items || [];
  el("revisionTasks").innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>修订任务台账：${summary.readiness === "ready" ? "已清理" : "需处理"}</h3>
        <p>当前有效 ${summary.active ?? 0} 条 / 待处理 ${summary.open ?? 0} 条 / 高风险待处理 ${summary.high_open ?? 0} 条 / 已处理 ${summary.done ?? 0} 条</p>
      </div>
      <span class="review-status ${summary.readiness === "ready" ? "ready" : "not_ready"}">${escapeHtml(summary.readiness || "")}</span>
    </article>
    <div class="coverage-grid">
      <article class="card"><span>全部任务</span><strong>${summary.total ?? 0}</strong></article>
      <article class="card"><span>有效任务</span><strong>${summary.active ?? 0}</strong></article>
      <article class="card"><span>高风险</span><strong>${summary.high_open ?? 0}</strong></article>
      <article class="card"><span>中风险</span><strong>${summary.medium_open ?? 0}</strong></article>
      <article class="card"><span>同步消除</span><strong>${summary.resolved_by_sync ?? 0}</strong></article>
    </div>
    <div class="table-list compact-list">
      ${
        items
          .map(
            (item) => `
            <article class="row-item delivery-row">
              <div>
                <strong><span class="tag">${escapeHtml(item.severity || "")}</span><span class="tag">${
                  item.active ? "有效" : "已消除"
                }</span>${escapeHtml(item.title || "")}</strong>
                <p>${escapeHtml(item.scope || "")}${item.section_title ? ` / ${escapeHtml(item.section_title)}` : ""}：${escapeHtml(
                  item.detail || "",
                )}</p>
                <p>动作：${escapeHtml(item.action || "")}</p>
                <div class="form-grid compact-grid">
                  <label>状态<input data-revision-status="${item.id}" value="${escapeHtml(item.status || "待处理")}" /></label>
                  <label>负责人<input data-revision-owner="${item.id}" value="${escapeHtml(item.owner || "")}" /></label>
                  <label>截止时间<input data-revision-due="${item.id}" value="${escapeHtml(item.due_at || "")}" /></label>
                  <label>备注<textarea rows="2" data-revision-notes="${item.id}">${escapeHtml(item.notes || "")}</textarea></label>
                </div>
              </div>
              <div class="button-group">
                ${item.draft_id || item.section_title ? `<button type="button" data-open-revision-draft="${item.draft_id || ""}" data-revision-section="${escapeHtml(item.section_title || "")}">打开对应章节</button>` : ""}
                <button type="button" class="secondary" data-save-revision="${item.id}">保存</button>
              </div>
            </article>
          `,
          )
          .join("") || "<p>暂无修订任务。执行质量门禁后可同步生成台账。</p>"
      }
    </div>
  `;
  renderProductionGuide(state.workflow);
}

async function refreshRevisionTasks() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderRevisionTasks(null);
    return;
  }
  renderRevisionTasks(await api(`/api/tenders/${tenderId}/revision-tasks`));
}

async function openRevisionDraft(draftId, sectionTitle = "") {
  navigateProject("editor");
  if (draftId) {
    await loadDraft(Number(draftId));
    setTimeout(() => el("draftContent")?.focus(), 80);
    return;
  }
  if (sectionTitle) {
    const draft = (state.drafts || []).find((item) => item.section_title === sectionTitle);
    if (draft) await loadDraft(Number(draft.id));
    else el("sectionTitle").value = sectionTitle;
  }
}

async function syncRevisionTasks() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/revision-tasks/sync`, {
    method: "POST",
    body: "{}",
  });
  renderRevisionTasks(report);
  const sync = report.sync || {};
  log(`修订任务已同步：新增 ${sync.inserted || 0} 条，更新 ${sync.updated || 0} 条，消除 ${sync.resolved || 0} 条。`);
  await refreshStatus().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
}

function revisionTaskPayload(taskId) {
  return {
    status: document.querySelector(`[data-revision-status="${taskId}"]`)?.value || "待处理",
    owner: document.querySelector(`[data-revision-owner="${taskId}"]`)?.value || "",
    due_at: document.querySelector(`[data-revision-due="${taskId}"]`)?.value || "",
    notes: document.querySelector(`[data-revision-notes="${taskId}"]`)?.value || "",
  };
}

async function saveRevisionTask(taskId) {
  const item = await api(`/api/revision-tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(revisionTaskPayload(taskId)),
  });
  log(`修订任务已保存：${item.title || item.id}`);
  await refreshRevisionTasks();
  await refreshProjectOverview().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
}

function renderProductionPipeline(report) {
  state.productionPipeline = report || null;
  if (!report) {
    el("productionPipeline").innerHTML = "";
    return;
  }
  const status = report.status || {};
  const packageInfo = report.package || {};
  el("productionPipeline").innerHTML = `
    <article class="result-item workflow-next">
      <h3>一键生产结果：${escapeHtml(status.current_status || "已完成")}</h3>
      <p>${escapeHtml(status.inferred?.reason || "")}</p>
      ${packageInfo.path ? `<p><span class="tag">交付包</span>${escapeHtml(packageInfo.path)}</p>` : ""}
    </article>
    <div class="workflow-steps">
      ${(report.steps || [])
        .map(
          (step) => `
          <article class="workflow-step ${escapeHtml(step.status)}">
            <strong>${escapeHtml(step.title)}</strong>
            <p><span class="tag">${escapeHtml(workflowStatusLabel(step.status))}</span>${escapeHtml(step.detail || "")}</p>
          </article>
        `,
        )
        .join("")}
    </div>
  `;
}

async function runProductionPipeline() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  log("开始一键生产交付包...");
  const result = await api(`/api/tenders/${tenderId}/production/run`, {
    method: "POST",
    body: JSON.stringify({
      force_parse: false,
      rebuild_plan: false,
      regenerate: false,
      export_package: true,
    }),
  });
  renderProductionPipeline(result);
  renderCoverage(result.coverage || null);
  await refreshProductionReadiness().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  renderQualityGate(result.quality_gate || null);
  await syncRevisionTasks().catch(() => {});
  await refreshSourceAudit().catch(() => {});
  renderDeliveryReview(result.delivery_review || null);
  renderDeliveryAssistant(result.delivery_assistant || null);
  await refreshFinalChecklist().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  renderTask(result.status?.task || state.task || {});
  log(`一键生产完成：${result.status?.current_status || "已完成"}`);
  await refreshMaterials();
  await refreshDrafts();
  await refreshPlan();
  await refreshDeliveries();
  await refreshPackageValidation().catch(() => {});
  await refreshClientPackageValidation().catch(() => {});
  await refreshDeliveryRelease().catch(() => {});
  await refreshTenders();
  await refreshStatus();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshSourceAudit().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

function renderClientDeliveryPreparation(report) {
  state.clientDeliveryPreparation = report || null;
  if (!report) {
    el("clientDeliveryPreparation").innerHTML = "";
    return;
  }
  const summary = report.summary || {};
  const steps = report.steps || [];
  el("clientDeliveryPreparation").innerHTML = `
    <article class="result-item workflow-next">
      <h3>客户交付准备：${escapeHtml(summary.send_label || "待确认")}</h3>
      <p><span class="tag">${summary.ready_to_send ? "可发货" : "需处理"}</span>客户包安全：${summary.client_package_ready ? "通过" : "未通过"} / 阻断 ${summary.blockers_count || 0} / 提醒 ${summary.warnings_count || 0}</p>
      ${summary.internal_package_path ? `<p><span class="tag">内部包</span>${escapeHtml(summary.internal_package_path)}</p>` : ""}
      ${summary.client_package_path ? `<p><span class="tag">客户包</span>${escapeHtml(summary.client_package_path)}</p>` : ""}
    </article>
    <div class="workflow-steps">
      ${steps
        .map(
          (step) => `
          <article class="workflow-step ${escapeHtml(step.status || "")}">
            <strong>${escapeHtml(step.title || "")}</strong>
            <p><span class="tag">${escapeHtml(workflowStatusLabel(step.status || ""))}</span>${escapeHtml(step.detail || "")}</p>
          </article>
        `,
        )
        .join("")}
    </div>
  `;
}

async function prepareClientDelivery() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  log("开始准备客户交付包...");
  const result = await api(`/api/tenders/${tenderId}/client-delivery/prepare`, {
    method: "POST",
    body: JSON.stringify({
      force_parse: false,
      rebuild_plan: false,
      regenerate: false,
      export_internal_package: true,
      extra_note: el("clientDeliveryNote")?.value || "",
    }),
  });
  renderClientDeliveryPreparation(result);
  renderProductionPipeline(result.pipeline || null);
  renderCoverage(result.pipeline?.coverage || null);
  renderQualityGate(result.pipeline?.quality_gate || null);
  renderDeliveryReview(result.pipeline?.delivery_review || null);
  renderDeliveryAssistant(result.pipeline?.delivery_assistant || null);
  renderClientPackageValidation(result.client_package_validation || null);
  renderClientDeliveryConfirmation(result.client_delivery_confirmation || null);
  renderTask(result.status?.task || state.task || {});
  log(`客户交付准备完成：${result.summary?.send_label || "待确认"}`);
  await refreshMaterials().catch(() => {});
  await refreshDrafts().catch(() => {});
  await refreshPlan().catch(() => {});
  await refreshDeliveries().catch(() => {});
  await refreshPackageValidation().catch(() => {});
  await refreshClientPackageValidation().catch(() => {});
  await refreshDeliveryRelease().catch(() => {});
  await refreshDeliveryRelease("deliveryReleasePanel").catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshTenders().catch(() => {});
  await refreshStatus().catch(() => {});
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

function readinessStatusLabel(value) {
  return {
    ready: "通过",
    needs_review: "需复核",
    needs_work: "需补齐",
    blocked: "阻断",
    ready_to_deliver: "可承诺交付",
    ready_for_final_review: "可进入终审",
    ready_to_produce: "可开始生产",
    needs_information: "需补充信息",
  }[value] || value || "待评估";
}

function checkStatusLabel(value) {
  return {
    complete: "已完成",
    warning: "需关注",
    pending: "待处理",
    blocked: "阻断",
  }[value] || value || "待确认";
}

function renderProductionReadiness(report) {
  state.productionReadiness = report || null;
  if (!report) {
    el("productionReadiness").innerHTML = "";
    return;
  }
  const summary = report.summary || {};
  const phases = report.phases || [];
  const issues = [...(report.blockers || []), ...(report.warnings || [])];
  el("productionReadiness").innerHTML = `
    <article class="result-item workflow-next">
      <h3>可交付性评估：${escapeHtml(summary.decision || readinessStatusLabel(summary.readiness))}</h3>
      <p>评估分 ${summary.score ?? 0} / 阻断项 ${summary.blockers ?? 0} / 提醒项 ${summary.warnings ?? 0} / 下一步：${escapeHtml(summary.workflow_next_step || "人工复核")}</p>
    </article>
    <div class="coverage-grid">
      <article class="card"><span>要求</span><strong>${summary.requirements ?? 0}</strong></article>
      <article class="card"><span>章节</span><strong>${summary.generated_sections ?? 0}/${summary.total_sections ?? 0}</strong></article>
      <article class="card"><span>质量分</span><strong>${summary.quality_score ?? 0}</strong></article>
      <article class="card"><span>收款</span><strong>${escapeHtml(summary.payment_status_label || "待确认")}</strong></article>
    </div>
    <div class="workflow-steps">
      ${phases
        .map(
          (phase) => `
          <article class="workflow-step ${phase.readiness === "ready" ? "complete" : phase.readiness === "blocked" ? "pending" : "current"}">
            <strong>${escapeHtml(phase.title || "")}：${escapeHtml(phase.decision || "")}</strong>
            ${(phase.checks || [])
              .map((item) => `<p><span class="tag">${checkStatusLabel(item.status)}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.detail || "")}</p>`)
              .join("")}
          </article>
        `,
        )
        .join("")}
    </div>
    <article class="result-item">
      <h3>阻断与提醒</h3>
      ${
        issues
          .slice(0, 16)
          .map((item) => `<p><span class="tag">${checkStatusLabel(item.status)}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.action || item.detail || "")}</p>`)
          .join("") || "<p>暂无阻断或提醒项。</p>"
      }
    </article>
  `;
}

async function refreshProductionReadiness() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderProductionReadiness(null);
    return;
  }
  renderProductionReadiness(await api(`/api/tenders/${tenderId}/production-readiness`));
}

async function refreshTemplates() {
  state.templates = await api("/api/templates");
  el("templateList").innerHTML =
    state.templates
      .map(
        (item) => `
        <article class="template-item">
          <h3>${escapeHtml(item.name)}</h3>
          <p>${escapeHtml(item.intent)}</p>
          <p><span class="tag">${escapeHtml(item.source === "custom" ? "自定义" : "默认")}</span><span class="tag">${escapeHtml(item.industry || "通用")}</span><span class="tag">v${escapeHtml(item.version || "1.0")}</span></p>
          <p>${escapeHtml((item.keywords || []).join(" / "))}</p>
          <ul>${(item.outline || []).map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>
          <div class="button-group template-actions">
            <button type="button" class="secondary" data-edit-template="${escapeHtml(item.name)}">编辑</button>
            ${item.id ? `<button type="button" class="secondary" data-delete-template="${item.id}">删除</button>` : ""}
          </div>
        </article>
      `,
      )
      .join("");
}

function renderTemplateCoverage(report) {
  state.templateCoverage = report || null;
  if (!report) {
    el("templateCoverage").innerHTML = "<p>刷新后显示标准章节模板和施工工艺库覆盖情况。</p>";
    return;
  }
  const summary = report.summary || {};
  const items = report.items || [];
  const missing = report.missing || [];
  const methodGroups = report.construction_methods?.groups || [];
  el("templateCoverage").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>标准模板</span><strong>${summary.covered_total ?? 0}/${summary.standard_total ?? 0}</strong></article>
      <article class="card"><span>缺失模板</span><strong>${summary.missing_total ?? 0}</strong></article>
      <article class="card"><span>自定义模板</span><strong>${summary.custom_templates ?? 0}</strong></article>
      <article class="card"><span>工艺类型</span><strong>${summary.method_groups ?? 0}</strong></article>
      <article class="card"><span>工艺要点</span><strong>${summary.method_items ?? 0}</strong></article>
    </div>
    <div class="overview-columns">
      <article class="result-item">
        <h3>标准章节覆盖</h3>
        ${
          items
            .map(
              (item) => `
                <p>
                  <span class="tag">${item.covered ? "已覆盖" : "缺失"}</span>
                  <span class="tag">${escapeHtml(item.group || "")}</span>
                  ${escapeHtml(item.name || "")} / ${escapeHtml(item.source || "待补模板")}
                </p>
              `,
            )
            .join("") || "<p>暂无覆盖数据。</p>"
        }
      </article>
      <article class="result-item">
        <h3>施工工艺库</h3>
        ${
          methodGroups
            .map(
              (group) => `
                <p>
                  <span class="tag">${escapeHtml((group.keywords || []).slice(0, 3).join(" / "))}</span>
                  ${group.method_count ?? 0} 项：${escapeHtml((group.methods || []).slice(0, 3).join("；"))}
                </p>
              `,
            )
            .join("") || "<p>暂无施工工艺库。</p>"
        }
      </article>
    </div>
    <article class="result-item">
      <h3>处理建议</h3>
      ${(report.recommendations || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无建议。</p>"}
      ${missing.length ? `<p class="danger">缺失：${escapeHtml(missing.map((item) => item.name).join("、"))}</p>` : ""}
    </article>
  `;
}

async function refreshTemplateCoverage() {
  renderTemplateCoverage(await api("/api/templates/coverage"));
}

function renderTemplateAssets(report) {
  state.templateAssets = report || null;
  const counts = report?.summary || {};
  const industries = report?.industries || [];
  el("templateAssetCatalog").innerHTML = report ? `
    <div class="coverage-grid">
      <article class="card"><span>行业模板</span><strong>${counts.industries ?? 0}</strong></article>
      <article class="card"><span>专项工艺</span><strong>${counts.construction_methods ?? 0}</strong></article>
      <article class="card"><span>原生表格</span><strong>${counts.table_templates ?? 0}</strong></article>
      <article class="card"><span>流程图</span><strong>${counts.flow_templates ?? 0}</strong></article>
      <article class="card"><span>组织架构</span><strong>${counts.organization_templates ?? 0}</strong></article>
      <article class="card"><span>横道/总平面</span><strong>${(counts.gantt_templates ?? 0) + (counts.site_layout_templates ?? 0)}</strong></article>
    </div>
    <article class="result-item"><h3>五类行业模板</h3><p>${industries.map((item) => `<span class="tag">${escapeHtml(item.name || item.key || "")}</span>`).join("")}</p></article>
    ${state.benchmarks ? `<article class="result-item"><h3>固定泛化基准</h3><p>${(state.benchmarks.projects || []).map((item) => `<span class="tag">${escapeHtml(item.prefix)} ${escapeHtml(item.industry)} / ${escapeHtml(item.status)}</span>`).join("")}</p><p>数据集指纹：${escapeHtml(state.benchmarks.dataset_fingerprint || "")}</p></article>` : ""}
  ` : "<p>尚未加载行业资产目录。</p>";
}

async function refreshTemplateAssets() {
  const [assets, benchmarks] = await Promise.all([api("/api/template-assets"), api("/api/benchmarks")]);
  state.benchmarks = benchmarks;
  renderTemplateAssets(assets);
}

function renderDocumentTemplates(items) {
  state.documentTemplates = items || [];
  el("documentTemplateList").innerHTML = state.documentTemplates.map((item) => `
    <article class="row-item">
      <div><strong>${escapeHtml(item.name || "")}</strong><p><span class="tag">v${escapeHtml(item.version || "1.0")}</span><span class="tag">${item.is_default ? "默认" : "可选"}</span>${escapeHtml(item.source_docx_path || "系统内置样式")}</p></div>
      <div class="button-group">
        ${item.is_default ? "" : `<button type="button" class="secondary" data-default-document-template="${item.id}">设为默认</button>`}
        ${item.source_docx_path ? `<button type="button" class="secondary" data-delete-document-template="${item.id}">删除</button>` : ""}
      </div>
    </article>
  `).join("") || "<p>暂无企业文档模板。</p>";
  const select = el("docSettingTemplate");
  if (select) {
    const selected = String(state.documentSettings?.template_id || "");
    select.innerHTML = `<option value="">系统默认模板</option>${state.documentTemplates.map((item) => `<option value="${item.id}">${escapeHtml(item.name)} / v${escapeHtml(item.version || "1.0")}</option>`).join("")}`;
    select.value = selected;
  }
  document.querySelectorAll("[data-default-document-template]").forEach((button) => button.addEventListener("click", () => setDefaultDocumentTemplate(Number(button.dataset.defaultDocumentTemplate)).catch((e) => log(e.message))));
  document.querySelectorAll("[data-delete-document-template]").forEach((button) => button.addEventListener("click", () => deleteDocumentTemplate(Number(button.dataset.deleteDocumentTemplate)).catch((e) => log(e.message))));
}

async function refreshDocumentTemplates() {
  renderDocumentTemplates(await api("/api/document-templates"));
}

async function uploadDocumentTemplate() {
  const file = el("documentTemplateFile").files?.[0];
  if (!file) throw new Error("请选择 DOCX 企业模板。");
  const form = new FormData();
  form.append("file", file);
  form.append("name", el("documentTemplateName").value.trim() || file.name.replace(/\.docx$/i, ""));
  form.append("version", el("documentTemplateVersion").value.trim() || "1.0");
  form.append("is_default", el("documentTemplateDefault").checked ? "true" : "false");
  const response = await fetch("/api/document-templates/upload", { method: "POST", body: form });
  const payload = await response.json();
  if (!response.ok || payload.error) throw new Error(payload.error || `HTTP ${response.status}`);
  log(`企业模板已上传：${payload.name}`);
  el("documentTemplateFile").value = "";
  await refreshDocumentTemplates();
}

async function setDefaultDocumentTemplate(templateId) {
  await api(`/api/document-templates/${templateId}`, { method: "PATCH", body: JSON.stringify({ is_default: true }) });
  log("默认企业模板已更新。");
  await refreshDocumentTemplates();
}

async function deleteDocumentTemplate(templateId) {
  if (!window.confirm("确认删除这个企业模板？")) return;
  await api(`/api/document-templates/${templateId}`, { method: "DELETE" });
  await refreshDocumentTemplates();
}

function clearTemplateForm() {
  state.currentTemplateId = null;
  el("templateName").value = "";
  el("templateIndustry").value = "";
  el("templateProjectType").value = "";
  el("templateMethodKey").value = "";
  el("templateVersion").value = "1.0";
  el("templateKeywords").value = "";
  el("templateIntent").value = "";
  el("templateOutline").value = "";
  el("templateQualityPoints").value = "";
}

function editTemplate(name) {
  const item = state.templates.find((template) => template.name === name);
  if (!item) return;
  state.currentTemplateId = item.id || null;
  el("templateName").value = item.name || "";
  el("templateIndustry").value = item.industry || "";
  el("templateProjectType").value = item.project_type || "";
  el("templateMethodKey").value = item.method_key || "";
  el("templateVersion").value = item.version || "1.0";
  el("templateKeywords").value = (item.keywords || []).join("\n");
  el("templateIntent").value = item.intent || "";
  el("templateOutline").value = (item.outline || []).join("\n");
  el("templateQualityPoints").value = (item.quality_points || []).join("\n");
  log(item.id ? `已载入自定义模板：${item.name}` : `已载入默认模板，可保存为自定义覆盖：${item.name}`);
}

function templatePayload() {
  return {
    name: el("templateName").value.trim(),
    industry: el("templateIndustry").value.trim(),
    project_type: el("templateProjectType").value.trim(),
    method_key: el("templateMethodKey").value.trim(),
    version: el("templateVersion").value.trim() || "1.0",
    keywords: el("templateKeywords").value,
    intent: el("templateIntent").value,
    outline: el("templateOutline").value,
    quality_points: el("templateQualityPoints").value,
  };
}

async function saveTemplate() {
  const payload = templatePayload();
  if (!payload.name) throw new Error("请填写模板名称。");
  const path = state.currentTemplateId ? `/api/templates/${state.currentTemplateId}` : "/api/templates";
  const method = state.currentTemplateId ? "PATCH" : "POST";
  const saved = await api(path, { method, body: JSON.stringify(payload) });
  state.currentTemplateId = saved.id || null;
  log(`模板已保存：${saved.name}`);
  await refreshTemplates();
  await refreshTemplateCoverage().catch(() => {});
}

async function deleteTemplate(templateId) {
  if (!window.confirm(`确认删除自定义模板 ID ${templateId}？`)) return;
  const result = await api(`/api/templates/${templateId}`, { method: "DELETE" });
  log(result.deleted ? `自定义模板已删除：${templateId}` : `自定义模板不存在：${templateId}`);
  clearTemplateForm();
  await refreshTemplates();
  await refreshTemplateCoverage().catch(() => {});
}

async function refreshTenders() {
  const tenders = await api("/api/tenders");
  el("tenderList").innerHTML =
    tenders
      .map(
        (item) => `
        <article class="row-item">
          <div>
            <strong>${escapeHtml(item.name)}</strong>
            <p>ID ${item.id} / ${escapeHtml(item.industry || "未填行业")} / 要求 ${item.requirement_count ?? 0} / 草稿 ${item.draft_count ?? 0}</p>
            <p>${escapeHtml(item.customer_name || "未登记客户")} / ${escapeHtml(item.source_platform || "未登记来源")} / ${escapeHtml(item.deadline || "未登记期限")} / ${escapeHtml(item.delivery_status || "待生产")}</p>
          </div>
          <div class="button-group">
            <button type="button" data-load-tender="${item.id}">打开</button>
            <button type="button" class="secondary" data-delete-tender="${item.id}">删除</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无项目，可以先创建一个测试项目。</p>";
}

function renderProcessingRecords(items) {
  state.processingRecords = items || [];
  el("processingRecords").innerHTML =
    state.processingRecords
      .map(
        (item) => `
        <article class="row-item">
          <div>
            <strong>${escapeHtml(item.original_filename || item.source_path || "文本录入")}</strong>
            <p>
              <span class="tag">${escapeHtml(item.status || "")}</span>
              <span class="tag">${escapeHtml(item.file_type || "")}</span>
              <span class="tag">${escapeHtml(item.action || "")}</span>
              ${item.text_chars ?? 0} 字 / ${item.page_count ?? 0} 页 / ${escapeHtml(item.created_at || "")}
            </p>
            ${
              item.markdown_path || item.ocr_output_dir
                ? `<p>OCR 输出：${escapeHtml(item.markdown_path || item.ocr_output_dir)}</p>`
                : ""
            }
            ${item.error_message ? `<p class="danger">${escapeHtml(item.error_message)}</p>` : ""}
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无文档处理记录。</p>";
}

async function refreshProcessingRecords() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  const path = tenderId ? `/api/tenders/${tenderId}/document-processing` : "/api/document-processing";
  renderProcessingRecords(await api(path));
}

async function loadTender(tenderId) {
  const tender = await api(`/api/tenders/${tenderId}`);
  state.currentTenderId = tender.id;
  state.currentTender = tender;
  updateProjectContext(tender);
  el("draftTenderId").value = tender.id;
  el("tenderName").value = tender.name || "";
  el("tenderIndustry").value = tender.industry || "";
  el("tenderRegion").value = tender.region || "";
  if (tender.raw_text) el("tenderText").value = tender.raw_text;
  renderTask(tender.task || {});
  renderProfile(tender.profile || {});
  renderRequirements(tender.requirements || []);
  renderDraftList(tender.drafts || []);
  renderPlanList(tender.section_plans || []);
  clearSourcePreview();
  renderResponseMatrix(null);
  renderPlanAudit(null);
  renderCoverage(null);
  renderCommandCenter(null);
  renderProductionStarter(null);
  renderOrderWizard(null);
  renderChannelOps(null);
  renderProjectOverview(null);
  renderProjectTimeline(null);
  renderDocumentSettings(null);
  renderAcceptance(null);
  renderBidStrategy(null);
  renderPayments(null);
  renderProcessingRecords([]);
  renderDraftVersions([]);
  renderProductionPipeline(null);
  renderClientDeliveryPreparation(null);
  renderProductionReadiness(null);
  renderQualityGate(null);
  renderRevisionTasks(null);
  renderSourceAudit(null);
  renderPackageValidation(null);
  renderClientPackageValidation(null);
  renderFinalChecklist(null);
  renderFinalDocument(null);
  renderPolish(null);
  renderCommunicationSuggestion(null);
  renderReplacementPreview(null);
  await refreshReplacementRecords();
  await refreshProcessingRecords().catch(() => {});
  await refreshCommunications();
  await refreshCaseAssets();
  await refreshMaterials();
  await refreshDocumentTemplates().catch(() => {});
  await refreshDocumentSettings().catch(() => {});
  await refreshRichDocument().catch(() => {});
  await refreshBidStrategy().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshIntakeAssistant().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshPriceQuote().catch(() => {});
  await refreshPayments().catch(() => {});
  await refreshDeliveries();
  await refreshPackageValidation().catch(() => {});
  await refreshClientPackageValidation().catch(() => {});
  await refreshDeliveryRelease().catch(() => {});
  await refreshDeliveryRelease("deliveryReleasePanel").catch(() => {});
  await refreshFeedback();
  await refreshFeedbackRework().catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshClosureConfirmation().catch(() => {});
  await refreshProjectRetrospective().catch(() => {});
  log(`已打开项目：${tender.id}`);
  await refreshWorkflow();
  await refreshProductionReadiness().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryRelease().catch(() => {});
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshRevisionTasks().catch(() => {});
  await refreshSourceAudit().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshAcceptance().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function deleteTender(tenderId) {
  if (!window.confirm(`确认删除项目 ID ${tenderId}？`)) return;
  const result = await api(`/api/tenders/${tenderId}`, { method: "DELETE" });
  if (state.currentTenderId === tenderId) {
    state.currentTenderId = null;
    state.currentTender = null;
    state.currentDraftId = null;
    el("draftTenderId").value = "";
    renderRequirements([]);
    renderDraftList([]);
    renderCaseAssets([]);
    renderPlanList([]);
    clearSourcePreview();
    renderResponseMatrix(null);
    renderPlanAudit(null);
    renderCoverage(null);
    renderDraftVersions([]);
    renderDeliveryRecords([]);
    renderPackageValidation(null);
    renderFeedback([]);
    renderFeedbackRework(null);
    renderDeliveryAssistant(null);
    renderClientDeliveryConfirmation(null);
    renderClosureConfirmation(null);
    renderProjectRetrospective(null);
    renderIntakeAssistant(null);
    renderOrderConfirmation(null);
    renderPriceQuote(null);
    renderPayments(null);
    renderProjectOverview(null);
    renderProjectTimeline(null);
    renderDocumentSettings(null);
    renderBidStrategy(null);
    renderProcessingRecords([]);
    updateProjectContext(null);
    renderCommunicationSuggestion(null);
    renderCommunications([]);
    renderTask({});
    renderProfile({});
    renderWorkflow(null);
    renderProductionPipeline(null);
    renderClientDeliveryPreparation(null);
    renderProductionReadiness(null);
    renderQualityGate(null);
    renderRevisionTasks(null);
    renderSourceAudit(null);
    renderPackageValidation(null);
    renderClientPackageValidation(null);
    renderFinalChecklist(null);
    renderFinalDocument(null);
    renderPolish(null);
    renderReplacementPreview(null);
    renderReplacementRecords([]);
    renderMaterials([]);
    renderCommandCenter(null);
    renderProductionStarter(null);
    renderOrderWizard(null);
    renderChannelOps(null);
  }
  log(result.deleted ? `项目已删除：${tenderId}` : `项目不存在：${tenderId}`);
  if (result.deleted && location.hash.includes(`/projects/${tenderId}/`)) location.hash = "#/projects";
  await refreshTenders();
  await refreshStatus();
  await refreshOrderDashboard().catch(() => {});
  if (state.currentTenderId) await refreshWorkflow();
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function importKb(limit) {
  log(limit ? `开始导入前 ${limit} 份知识库...` : "开始导入全部知识库...");
  const data = await api("/api/kb/import", {
    method: "POST",
    body: JSON.stringify({ reset: true, limit_documents: limit }),
  });
  log(`导入完成：${JSON.stringify(data)}`);
  await refreshStatus();
  await refreshKbAudit().catch(() => {});
  await refreshKbOcrQueue().catch(() => {});
}

function renderSearchResults(items) {
  state.searchResults = items || [];
  el("searchResults").innerHTML =
    state.searchResults
      .map(
        (item, index) => {
          const sourceLabel = item.source_type === "case_asset" ? "案例资产" : "知识库";
          return `
        <article class="result-item">
          <h3>${escapeHtml(item.heading_text || "未命名章节")}</h3>
          <p><span class="tag">${escapeHtml(sourceLabel)}</span><span class="tag">${escapeHtml(item.top_category || "未分类")}</span>${escapeHtml(item.source_path || "")}</p>
          <p>${escapeHtml(item.summary || "")}</p>
          <button type="button" class="secondary" data-preview-search-source="${index}">查看来源</button>
        </article>
      `;
        },
      )
      .join("") || "<p>暂无结果，请先导入知识库或换个关键词。</p>";
}

function renderSourcePreview(report) {
  state.sourcePreview = report || null;
  if (!report) {
    el("sourcePreview").innerHTML = "";
    return;
  }
  const metadata = report.metadata || {};
  const content = report.markdown_excerpt || report.content || report.chunk_content || "";
  el("sourcePreview").innerHTML = `
    <article class="result-item">
      <h3>来源预览：${escapeHtml(report.title || report.heading_text || "未命名来源")}</h3>
      <p>
        <span class="tag">${escapeHtml(report.source_type === "case_asset" ? "案例资产" : "知识库")}</span>
        <span class="tag">${escapeHtml(report.file_exists ? "Markdown可定位" : "片段可定位")}</span>
        ${escapeHtml(report.top_category || "未分类")}
      </p>
      <p>${escapeHtml(report.source_path || "")}</p>
      ${report.resolved_markdown_path ? `<p>${escapeHtml(report.resolved_markdown_path)}</p>` : ""}
      <p>章节：${escapeHtml(report.heading_text || "")} / 页码：${escapeHtml(metadata.page_number || "未登记")} / 格式：${escapeHtml(metadata.document_format || "")}</p>
      <pre>${escapeHtml(content)}</pre>
    </article>
  `;
}

function sourcePreviewPayload(item) {
  return {
    source_type: item.source_type || "kb_chunk",
    id: item.id || item.chunk_id || null,
    chunk_id: item.chunk_id || item.id || null,
    source_path: item.source_path || "",
    markdown_path: item.markdown_path || "",
    heading_text: item.heading_text || "",
  };
}

async function previewSource(payload) {
  renderSourcePreview(await api("/api/sources/preview", {
    method: "POST",
    body: JSON.stringify(payload),
  }));
}

async function previewSearchSource(index) {
  const item = state.searchResults[Number(index)];
  if (!item) throw new Error("未找到检索结果来源。");
  await previewSource(sourcePreviewPayload(item));
}

async function previewDraftCitation(index) {
  const item = state.draftCitations[Number(index)];
  if (!item) throw new Error("未找到草稿引用来源。");
  await previewSource(sourcePreviewPayload(item));
}

function clearSourcePreview() {
  state.sourcePreview = null;
  state.searchResults = [];
  state.draftCitations = [];
  renderSourcePreview(null);
}

async function search() {
  const items = await api("/api/sections/search", {
    method: "POST",
    body: JSON.stringify({
      query: el("searchQuery").value,
      category: el("searchCategory").value,
      heading: el("searchHeading").value,
      limit: Number(el("searchLimit").value || 8),
    }),
  });
  renderSearchResults(items);
}

function selectedRequirementIds() {
  return [...document.querySelectorAll("[data-requirement-id]:checked")].map((node) => Number(node.dataset.requirementId));
}

function renderRequirements(items) {
  state.requirements = items || [];
  el("requirements").innerHTML =
    state.requirements
      .map(
        (item) => `
        <article class="row-item delivery-row requirement-item">
          <div>
            <label class="check-line">
              <input type="checkbox" data-requirement-id="${item.id}" checked />
              <span><strong>${escapeHtml(item.kind)} / ${escapeHtml(item.priority)}</strong><br />${escapeHtml(item.content)}</span>
            </label>
            <div class="requirement-edit-grid">
              <label>类型<input value="${escapeHtml(item.kind || "技术要求")}" data-req-kind="${item.id}" /></label>
              <label>优先级<input value="${escapeHtml(item.priority || "normal")}" data-req-priority="${item.id}" /></label>
              <label>响应范围
                <select data-req-scope="${item.id}">
                  ${[["chapter", "技术章节"], ["project_fact", "项目事实"], ["business", "商务资质"], ["compliance", "合规检查"]].map(([value, label]) => `<option value="${value}" ${item.response_scope === value ? "selected" : ""}>${label}</option>`).join("")}
                </select>
              </label>
              <label>适用性
                <select data-req-applicable="${item.id}"><option value="1" ${item.applicable !== false ? "selected" : ""}>适用</option><option value="0" ${item.applicable === false ? "selected" : ""}>不适用</option></select>
              </label>
              <label>分类复核
                <select data-req-review-status="${item.id}"><option value="pending" ${item.review_status !== "approved" ? "selected" : ""}>待复核</option><option value="approved" ${item.review_status === "approved" ? "selected" : ""}>已确认</option></select>
              </label>
              <label>分值<input type="number" min="0" step="0.5" value="${Number(item.score_weight || 0)}" data-req-score="${item.id}" /></label>
              <label>来源<input value="${escapeHtml(item.source_hint || "")}" data-req-source="${item.id}" /></label>
              <label>状态<input value="${escapeHtml(item.status || "pending")}" data-req-status="${item.id}" /></label>
              <label>条款内容<textarea rows="2" data-req-content="${item.id}">${escapeHtml(item.content || "")}</textarea></label>
            </div>
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-requirement="${item.id}">保存</button>
            <button type="button" class="secondary" data-delete-requirement="${item.id}">删除</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>没有解析出要求，请补充招标文件文本。</p>";
}

function renderResponseMatrix(report) {
  state.responseMatrix = report || null;
  if (!report) {
    el("responseMatrix").innerHTML = "";
    return;
  }
  const summary = report.summary || {};
  const requirements = report.requirements || [];
  const problemRequirements = requirements.filter((item) => !["verified", "not_applicable"].includes(item.response_status)).slice(0, 24);
  const readiness = summary.readiness === "ready" ? "ready" : summary.readiness === "pending" ? "needs_work" : "not_ready";
  el("responseMatrix").innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>逐条响应证据：${summary.readiness === "ready" ? "达到门槛" : summary.readiness === "pending" ? "待解析" : "需处理"}</h3>
        <p>技术条款 ${summary.chapter_requirements ?? 0} 条 / 自动定位 ${toPercent(summary.automatic_evidence_rate || 0)} / 已验证 ${toPercent(summary.chapter_evidence_rate || 0)} / 评分点 ${summary.verified_scoring_requirements ?? 0}/${summary.scoring_requirements ?? 0} / 高优先级 ${summary.verified_high_requirements ?? 0}/${summary.high_requirements ?? 0}</p>
      </div>
      <span class="review-status ${readiness}">高优先级缺口 ${summary.high_unplanned_requirements ?? 0}</span>
    </article>
    <div class="coverage-grid">
      <article class="card"><span>全部要求</span><strong>${summary.requirements ?? 0}</strong></article>
      <article class="card"><span>技术章节</span><strong>${summary.chapter_requirements ?? 0}</strong></article>
      <article class="card"><span>合规检查</span><strong>${summary.compliance_requirements ?? 0}</strong></article>
      <article class="card"><span>商务/事实</span><strong>${(summary.business_requirements ?? 0) + (summary.project_fact_requirements ?? 0)}</strong></article>
      <article class="card"><span>待证据复核</span><strong>${summary.requirements_needing_review ?? 0}</strong></article>
    </div>
    <div class="overview-columns">
      <article class="result-item">
        <h3>待处理条款</h3>
        ${
          problemRequirements
            .map((item) => {
              const sections = (item.planned_sections || []).map((section) => section.section_title).join(" / ") || "未挂接目录";
              const suggestion = item.suggested_section || item.suggested_template || "无建议";
              const evidence = item.best_evidence || {};
              const evidenceActions = (item.evidence || []).map((row) => `<button type="button" class="secondary inline-button" data-review-evidence="${row.id}" data-review-status="approved">确认</button><button type="button" class="secondary inline-button" data-review-evidence="${row.id}" data-review-status="rejected">驳回</button>`).join("");
              return `<div class="requirement-evidence-row"><p><span class="tag">${escapeHtml(item.response_scope || "")}</span><span class="tag">${escapeHtml(item.priority || "")}</span><span class="tag">${escapeHtml(
                 item.response_status || "",
               )}</span>${escapeHtml(item.content || "")}<br />目录：${escapeHtml(sections)} / 建议：${escapeHtml(suggestion)}${evidence.evidence_text ? `<br /><strong>证据：</strong>${escapeHtml(evidence.heading_path || evidence.section_title || "正文")} / ${escapeHtml(evidence.evidence_text)}` : ""}</p><div>${evidenceActions}</div></div>`;
            })
            .join("") || "<p>所有要求都已形成草稿响应。</p>"
        }
      </article>
      <article class="result-item">
        <h3>章节挂接概览</h3>
        ${
          (report.sections || [])
            .slice(0, 16)
            .map(
              (item) =>
                `<p><span class="tag">${item.draft_id ? "已生成" : "待生成"}</span>${item.order_no}. ${escapeHtml(
                  item.section_title || "",
                )} / 关联 ${item.linked_requirement_count ?? 0} 条 / 高优先级 ${item.high_linked_requirement_count ?? 0} 条</p>`,
            )
            .join("") || "<p>暂无目录章节。</p>"
        }
      </article>
    </div>
    <article class="result-item">
      <h3>处理建议</h3>
      ${(report.recommendations || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无建议。</p>"}
    </article>
  `;
  document.querySelectorAll("[data-review-evidence]").forEach((button) => button.addEventListener("click", () => reviewRequirementEvidence(Number(button.dataset.reviewEvidence), button.dataset.reviewStatus).catch((e) => log(e.message))));
}

async function refreshRequirements() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderRequirements([]);
    return;
  }
  renderRequirements(await api(`/api/tenders/${tenderId}/requirements`));
}

async function refreshResponseMatrix() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderResponseMatrix(null);
    return;
  }
  renderResponseMatrix(await api(`/api/tenders/${tenderId}/response-matrix`));
}

async function reclassifyRequirements() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const result = await api(`/api/tenders/${tenderId}/requirements/reclassify`, { method: "POST", body: "{}" });
  log(`条款重分类完成：${result.classification?.total || 0} 条，证据记录 ${result.evidence?.responses || 0} 条。`);
  await refreshRequirements();
  await refreshResponseMatrix();
  await refreshAcceptance().catch(() => {});
}

async function reviewRequirementEvidence(responseId, reviewStatus) {
  await api(`/api/requirement-responses/${responseId}`, {
    method: "PATCH",
    body: JSON.stringify({ review_status: reviewStatus, reviewed_by: el("docSettingReviewedBy")?.value || "人工复核" }),
  });
  log(reviewStatus === "approved" ? "正文证据已人工确认。" : "正文证据已驳回，需定向改写。");
  await refreshResponseMatrix();
  await refreshQualityGate().catch(() => {});
  await refreshAcceptance().catch(() => {});
}

async function autoLinkResponseMatrix() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const result = await api(`/api/tenders/${tenderId}/response-matrix/auto-link`, {
    method: "POST",
    body: "{}",
  });
  renderResponseMatrix(result.after || null);
  log(`响应矩阵挂接完成：新建目录 ${result.built_plan_count || 0} 个，新增挂接 ${result.linked_count || 0} 条。`);
  await refreshPlan().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshCoverage().catch(() => {});
  await refreshWorkflow().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
}

function requirementCreatePayload() {
  return {
    kind: el("requirementKind").value || "技术要求",
    priority: el("requirementPriority").value || "normal",
    source_hint: el("requirementSourceHint").value || "人工补充",
    content: el("requirementContent").value,
    status: "pending",
  };
}

async function addRequirement() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const payload = requirementCreatePayload();
  if (!payload.content.trim()) throw new Error("请填写条款内容。");
  const requirement = await api(`/api/tenders/${tenderId}/requirements`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  el("requirementContent").value = "";
  log(`已新增响应条款：${requirement.id}`);
  await refreshRequirements();
  await refreshTenders();
  await refreshResponseMatrix().catch(() => {});
  await refreshWorkflow().catch(() => {});
  await refreshCoverage().catch(() => {});
}

function requirementPayload(requirementId) {
  return {
    kind: document.querySelector(`[data-req-kind="${requirementId}"]`)?.value || "技术要求",
    priority: document.querySelector(`[data-req-priority="${requirementId}"]`)?.value || "normal",
    response_scope: document.querySelector(`[data-req-scope="${requirementId}"]`)?.value || "chapter",
    applicable: document.querySelector(`[data-req-applicable="${requirementId}"]`)?.value !== "0",
    review_status: document.querySelector(`[data-req-review-status="${requirementId}"]`)?.value || "pending",
    classification_source: "manual",
    score_weight: Number(document.querySelector(`[data-req-score="${requirementId}"]`)?.value || 0),
    source_hint: document.querySelector(`[data-req-source="${requirementId}"]`)?.value || "",
    status: document.querySelector(`[data-req-status="${requirementId}"]`)?.value || "pending",
    content: document.querySelector(`[data-req-content="${requirementId}"]`)?.value || "",
  };
}

async function saveRequirement(requirementId) {
  const payload = requirementPayload(requirementId);
  if (!payload.content.trim()) throw new Error("条款内容不能为空。");
  const requirement = await api(`/api/requirements/${requirementId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  log(`响应条款已保存：${requirement.id}`);
  await refreshRequirements();
  await refreshResponseMatrix().catch(() => {});
  await refreshWorkflow().catch(() => {});
  await refreshCoverage().catch(() => {});
}

async function deleteRequirement(requirementId) {
  if (!window.confirm(`确认删除响应条款 ID ${requirementId}？`)) return;
  const result = await api(`/api/requirements/${requirementId}`, { method: "DELETE" });
  log(result.deleted ? `响应条款已删除：${requirementId}` : `响应条款不存在：${requirementId}`);
  await refreshRequirements();
  await refreshPlan().catch(() => {});
  await refreshResponseMatrix().catch(() => {});
  await refreshCoverage().catch(() => {});
  await refreshTenders();
  await refreshWorkflow().catch(() => {});
}

const taskFields = {
  customer_name: "taskCustomerName",
  source_platform: "taskSourcePlatform",
  order_no: "taskOrderNo",
  contact: "taskContact",
  deadline: "taskDeadline",
  budget: "taskBudget",
  deliverable_format: "taskDeliverableFormat",
  delivery_status: "taskDeliveryStatus",
  delivery_notes: "taskDeliveryNotes",
  internal_owner: "taskInternalOwner",
};

function renderTask(task) {
  state.task = task || {};
  for (const [field, id] of Object.entries(taskFields)) {
    if (el(id)) el(id).value = state.task[field] ?? "";
  }
  if (el("intakeSourcePlatform") && !el("intakeSourcePlatform").value) el("intakeSourcePlatform").value = state.task.source_platform || "闲鱼";
  if (el("intakeDeadline") && !el("intakeDeadline").value) el("intakeDeadline").value = state.task.deadline || "";
  if (el("intakeBudget") && !el("intakeBudget").value) el("intakeBudget").value = state.task.budget || "";
  if (el("intakeDeliverableFormat") && !el("intakeDeliverableFormat").value) {
    el("intakeDeliverableFormat").value = state.task.deliverable_format || "DOCX + ZIP 交付包";
  }
  if (el("communicationChannel") && !el("communicationChannel").value) {
    el("communicationChannel").value = state.task.source_platform || "闲鱼";
  }
}

const documentSettingFields = {
  document_title: "docSettingTitle",
  document_subtitle: "docSettingSubtitle",
  document_type: "docSettingType",
  bidder_name: "docSettingBidder",
  version_label: "docSettingVersion",
  prepared_by: "docSettingPreparedBy",
  reviewed_by: "docSettingReviewedBy",
  document_date: "docSettingDate",
  confidentiality: "docSettingConfidentiality",
  header_text: "docSettingHeader",
  footer_text: "docSettingFooter",
  body_font: "docSettingBodyFont",
  body_font_size: "docSettingBodySize",
  heading_font: "docSettingHeadingFont",
  notes: "docSettingNotes",
};

const documentSettingChecks = {
  include_cover: "docSettingIncludeCover",
  include_toc: "docSettingIncludeToc",
  include_response_matrix: "docSettingIncludeMatrix",
  include_delivery_review: "docSettingIncludeReview",
  section_page_break: "docSettingPageBreak",
};

function renderDocumentSettings(settings) {
  state.documentSettings = settings || null;
  const data = settings || {};
  for (const [field, id] of Object.entries(documentSettingFields)) {
    if (el(id)) el(id).value = data[field] ?? "";
  }
  for (const [field, id] of Object.entries(documentSettingChecks)) {
    if (el(id)) el(id).checked = Boolean(data[field]);
  }
  renderDocumentTemplates(state.documentTemplates);
}

function documentSettingsPayload() {
  const payload = {};
  payload.template_id = el("docSettingTemplate")?.value ? Number(el("docSettingTemplate").value) : null;
  for (const [field, id] of Object.entries(documentSettingFields)) {
    payload[field] = el(id)?.value ?? "";
  }
  payload.body_font_size = Number(payload.body_font_size || 10.5);
  for (const [field, id] of Object.entries(documentSettingChecks)) {
    payload[field] = Boolean(el(id)?.checked);
  }
  return payload;
}

async function refreshDocumentSettings() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderDocumentSettings(null);
    return;
  }
  renderDocumentSettings(await api(`/api/tenders/${tenderId}/document-settings`));
}

async function saveDocumentSettings() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const settings = await api(`/api/tenders/${tenderId}/document-settings`, {
    method: "PATCH",
    body: JSON.stringify(documentSettingsPayload()),
  });
  renderDocumentSettings(settings);
  log("成稿格式设置已保存。");
  await refreshStatus().catch(() => {});
}

function renderMaterials(items) {
  state.materials = items || [];
  el("materialsList").innerHTML =
    state.materials
      .map(
        (item) => `
        <article class="row-item delivery-row">
          <div>
            <strong>${escapeHtml(item.name || "")}</strong>
            <p><span class="tag">${escapeHtml(item.status || "")}</span>${escapeHtml(item.category || "未分类")} / ${item.required ? "必需" : "可选"} / ${escapeHtml(item.updated_at || "")}</p>
            <div class="material-edit-grid">
              <label>状态<input value="${escapeHtml(item.status || "待补充")}" data-material-status="${item.id}" /></label>
              <label>来源<input value="${escapeHtml(item.source || "")}" data-material-source="${item.id}" placeholder="文件名 / 网盘 / 聊天记录" /></label>
              <label>负责人<input value="${escapeHtml(item.owner || "")}" data-material-owner="${item.id}" /></label>
              <label>期限<input value="${escapeHtml(item.due_at || "")}" data-material-due="${item.id}" /></label>
              <label>备注<textarea rows="2" data-material-notes="${item.id}">${escapeHtml(item.notes || "")}</textarea></label>
            </div>
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-material="${item.id}">保存</button>
            <button type="button" data-complete-material="${item.id}">标记已具备</button>
            <button type="button" class="secondary" data-delete-material="${item.id}">删除</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无资料项。打开项目后会自动生成默认资料清单。</p>";
}

async function refreshMaterials() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderMaterials([]);
    return;
  }
  renderMaterials(await api(`/api/tenders/${tenderId}/materials`));
}

function materialPayload(itemId, forcedStatus = "") {
  return {
    status: forcedStatus || document.querySelector(`[data-material-status="${itemId}"]`)?.value || "待补充",
    source: document.querySelector(`[data-material-source="${itemId}"]`)?.value || "",
    owner: document.querySelector(`[data-material-owner="${itemId}"]`)?.value || "",
    due_at: document.querySelector(`[data-material-due="${itemId}"]`)?.value || "",
    notes: document.querySelector(`[data-material-notes="${itemId}"]`)?.value || "",
  };
}

async function saveMaterial(itemId, forcedStatus = "") {
  await api(`/api/materials/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(materialPayload(itemId, forcedStatus)),
  });
  log(forcedStatus ? `资料项已标记为${forcedStatus}：${itemId}` : `资料项已保存：${itemId}`);
  await refreshMaterials();
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshQualityGate().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshGuides();
}

async function deleteMaterial(itemId) {
  if (!window.confirm(`确认删除资料项 ID ${itemId}？`)) return;
  await api(`/api/materials/${itemId}`, { method: "DELETE" });
  log(`资料项已删除：${itemId}`);
  await refreshMaterials();
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshQualityGate().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshGuides();
}

async function addMaterial() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const name = el("materialName").value.trim();
  if (!name) throw new Error("请填写资料名称。");
  await api(`/api/tenders/${tenderId}/materials`, {
    method: "POST",
    body: JSON.stringify({
      name,
      category: el("materialCategory").value || "补充资料",
      status: el("materialStatus").value || "待补充",
      source: el("materialSource").value,
      notes: el("materialNotes").value,
      owner: el("materialOwner").value,
      required: true,
    }),
  });
  el("materialName").value = "";
  el("materialSource").value = "";
  el("materialNotes").value = "";
  log(`资料项已新增：${name}`);
  await refreshMaterials();
  await refreshWorkflow();
  await refreshQualityGate().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshGuides();
}

function renderOrderConfirmation(report) {
  state.orderConfirmation = report || null;
  if (!report) {
    el("orderConfirmation").innerHTML = "";
    el("orderConfirmationMessage").value = "";
    return;
  }
  const commercial = report.commercial || {};
  const scope = report.scope || {};
  el("orderConfirmationMessage").value = report.customer_message || "";
  el("orderConfirmation").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>确认价格</span><strong>${escapeHtml(commercial.agreed_price || "待确认")}</strong></article>
      <article class="card"><span>交付期限</span><strong>${escapeHtml(commercial.deadline || "待确认")}</strong></article>
      <article class="card"><span>修改轮次</span><strong>${escapeHtml(commercial.revision_rounds || "2")}</strong></article>
      <article class="card"><span>待补资料</span><strong>${(scope.pending_materials || []).length}</strong></article>
    </div>
    <article class="result-item">
      <h3>交付范围</h3>
      ${(scope.deliverables || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无交付范围。</p>"}
    </article>
    <article class="result-item">
      <h3>不包含范围</h3>
      ${(scope.exclusions || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无边界说明。</p>"}
    </article>
  `;
}

function orderConfirmationPayload() {
  return {
    agreed_price: el("confirmationPrice").value,
    deadline: el("confirmationDeadline").value,
    revision_rounds: el("confirmationRevisionRounds").value,
    deliverables: el("confirmationDeliverables").value,
    exclusions: el("confirmationExclusions").value,
  };
}

async function refreshOrderConfirmation() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderOrderConfirmation(null);
    return;
  }
  renderOrderConfirmation(await api(`/api/tenders/${tenderId}/order-confirmation`));
}

async function buildOrderConfirmation() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/order-confirmation`, {
    method: "POST",
    body: JSON.stringify(orderConfirmationPayload()),
  });
  renderOrderConfirmation(report);
  log("订单确认单已生成。");
  await refreshGuides();
}

async function copyOrderConfirmation() {
  const message = el("orderConfirmationMessage").value || "";
  if (!message.trim()) throw new Error("请先生成订单确认单。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("orderConfirmationMessage").select();
    document.execCommand("copy");
  }
  log("订单确认话术已复制。");
}

function taskPayload() {
  const payload = {};
  for (const [field, id] of Object.entries(taskFields)) {
    const node = el(id);
    if (!node) continue;
    payload[field] = node.value;
  }
  return payload;
}

async function refreshTask() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  renderTask(await api(`/api/tenders/${tenderId}/task`));
}

async function saveTask() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const task = await api(`/api/tenders/${tenderId}/task`, {
    method: "PATCH",
    body: JSON.stringify(taskPayload()),
  });
  renderTask(task);
  log("生产任务已保存。");
  await refreshTenders();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProductionReadiness().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryRelease("deliveryReleasePanel").catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshPriceQuote().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function syncTaskStatus() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const result = await api(`/api/tenders/${tenderId}/task/sync-status`, {
    method: "POST",
    body: "{}",
  });
  renderTask(result.task || {});
  log(`当前项目状态已同步：${result.previous_status || "空"} -> ${result.current_status}`);
  await refreshTenders();
  await refreshOrderDashboard();
  await refreshWorkflow();
    await refreshProjectOverview().catch(() => {});
    await refreshDeliveryReview().catch(() => {});
    await refreshDeliveryAssistant().catch(() => {});
    await refreshClientDeliveryConfirmation().catch(() => {});
    await refreshClosureConfirmation().catch(() => {});
    await refreshRetrospectiveDashboard().catch(() => {});
    await refreshProjectRetrospective().catch(() => {});
    await refreshProjectTimeline().catch(() => {});
    await refreshGuides();
  }

function renderIntakeAssistant(report) {
  state.intakeAssistant = report || null;
  if (!report) {
    el("intakeAssistant").innerHTML = "";
    el("intakeReply").value = "";
    return;
  }
  const estimate = report.estimate || {};
  const acceptance = report.acceptance || {};
  const materials = report.materials || [];
  const risks = report.risks || [];
  el("intakeReply").value = report.reply_message || "";
  el("intakeAssistant").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>接单判断</span><strong>${escapeHtml(acceptance.decision || "待判断")}</strong></article>
      <article class="card"><span>建议报价</span><strong>${escapeHtml(estimate.suggested_price || "待估算")}</strong></article>
      <article class="card"><span>工作量</span><strong>${escapeHtml(estimate.workload || "待估算")}</strong></article>
      <article class="card"><span>交付周期</span><strong>${escapeHtml(estimate.turnaround || "待确认")}</strong></article>
    </div>
    <article class="result-item">
      <h3>判断原因</h3>
      <p>${escapeHtml(acceptance.reason || "")}</p>
    </article>
    <article class="result-item">
      <h3>资料清单</h3>
      ${
        materials
          .map((item) => `<p><span class="tag">${escapeHtml(item.status || "")}</span>${escapeHtml(item.name || "")}：${escapeHtml(item.reason || "")}</p>`)
          .join("") || "<p>暂无资料清单。</p>"
      }
    </article>
    <article class="result-item">
      <h3>风险提示</h3>
      ${
        risks
          .map((item) => `<p><span class="tag">${escapeHtml(item.level || "")}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.detail || "")}</p>`)
          .join("") || "<p>暂无明显风险。</p>"
      }
    </article>
  `;
}

function intakePayload() {
  return {
    customer_message: el("intakeCustomerMessage").value,
    customer_name: el("taskCustomerName").value,
    source_platform: el("intakeSourcePlatform").value,
    contact: el("taskContact").value,
    deadline: el("intakeDeadline").value,
    budget_expectation: el("intakeBudget").value,
    deliverable_format: el("intakeDeliverableFormat").value,
    rush_level: el("intakeRushLevel").value,
    project_name: el("tenderName").value,
    industry: el("tenderIndustry").value,
    region: el("tenderRegion").value,
  };
}

async function refreshIntakeAssistant() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderIntakeAssistant(null);
    return;
  }
  renderIntakeAssistant(await api(`/api/tenders/${tenderId}/intake-assistant`));
}

async function buildIntakeAssistant() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/intake-assistant`, {
    method: "POST",
    body: JSON.stringify(intakePayload()),
  });
  renderIntakeAssistant(report);
  renderPriceQuote(null);
  await refreshPriceQuote().catch(() => {});
  log(`接单建议已生成：${report.acceptance?.decision || "待判断"} / ${report.estimate?.suggested_price || "待估算"}`);
  await refreshGuides();
}

async function createIntakeTender() {
  const payload = intakePayload();
  if (!payload.customer_message.trim()) throw new Error("请先粘贴客户原始消息。");
  const result = await api("/api/intake/create-tender", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const tender = result.tender || {};
  state.currentTenderId = tender.id;
  state.currentDraftId = null;
  el("draftTenderId").value = tender.id || "";
  el("tenderName").value = tender.name || payload.project_name || "";
  el("tenderIndustry").value = tender.industry || payload.industry || "";
  el("tenderRegion").value = tender.region || payload.region || "";
  el("tenderText").value = payload.customer_message;
  renderTask(result.task || tender.task || {});
  renderProfile(tender.profile || result.parsed?.profile || {});
  renderRequirements(tender.requirements || result.parsed?.requirements || []);
  renderDraftList([]);
  renderPlanList(tender.section_plans || []);
  renderResponseMatrix(null);
  renderPlanAudit(null);
  renderDraftVersions([]);
  renderDeliveryRecords([]);
  renderFeedback([]);
  renderFeedbackRework(null);
  renderDeliveryAssistant(null);
  renderClientDeliveryConfirmation(null);
  renderClosureConfirmation(null);
  renderProjectRetrospective(null);
  renderOrderConfirmation(null);
  renderPriceQuote(null);
  renderPayments(null);
  renderProjectTimeline(null);
  renderBidStrategy(null);
  renderProcessingRecords([]);
  renderProductionPipeline(null);
  renderClientDeliveryPreparation(null);
  renderProductionReadiness(null);
  renderOrderWizard(null);
  renderQualityGate(null);
  renderRevisionTasks(null);
  renderSourceAudit(null);
  renderFinalChecklist(null);
  renderFinalDocument(null);
  renderPolish(null);
  renderCommunicationSuggestion(null);
  renderReplacementPreview(null);
  renderReplacementRecords([]);
  await refreshMaterials();
  await refreshDocumentSettings().catch(() => {});
  await refreshBidStrategy().catch(() => {});
  await refreshProcessingRecords().catch(() => {});
  await refreshCommunications();
  renderCoverage(null);
  renderIntakeAssistant(result.intake || null);
  log(`订单草稿已创建：项目 ID ${tender.id}`);
  await refreshStatus();
  await refreshTenders();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProductionReadiness().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshGuides();
}

async function applyIntakeTask() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  if (!state.intakeAssistant) await buildIntakeAssistant();
  const suggestedTask = state.intakeAssistant?.suggested_task || {};
  const task = await api(`/api/tenders/${tenderId}/task`, {
    method: "PATCH",
    body: JSON.stringify(suggestedTask),
  });
  renderTask(task);
  log("接单建议已回填到生产任务。");
  await refreshTenders();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryRelease("deliveryReleasePanel").catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshClosureConfirmation().catch(() => {});
  await refreshProjectRetrospective().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function copyIntakeReply() {
  const message = el("intakeReply").value || "";
  if (!message.trim()) throw new Error("请先生成接单建议。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("intakeReply").select();
    document.execCommand("copy");
  }
  log("接单回复已复制。");
}

function communicationPayload(includeReply = true) {
  return {
    stage: el("communicationStage").value,
    direction: el("communicationDirection").value,
    channel: el("communicationChannel").value,
    customer_message: el("communicationCustomerMessage").value,
    system_reply: includeReply ? el("communicationReply").value : "",
    status: el("communicationStatus").value,
    notes: el("communicationNotes").value,
  };
}

function renderCommunicationSuggestion(report) {
  state.communicationSuggestion = report || null;
  if (!report) {
    el("communicationSuggestion").innerHTML = "";
    el("communicationReply").value = "";
    return;
  }
  el("communicationReply").value = report.reply || "";
  const summary = report.summary || {};
  const summaryItems = Object.entries(summary)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `<p><span class="tag">${escapeHtml(key)}</span>${escapeHtml(value)}</p>`)
    .join("");
  el("communicationSuggestion").innerHTML = `
    <article class="result-item">
      <h3>${escapeHtml(report.stage || "沟通回复")} / ${escapeHtml(report.source || "系统建议")}</h3>
      <p>${escapeHtml(report.safety_note || "")}</p>
      ${summaryItems || "<p>已按当前项目状态生成回复。</p>"}
    </article>
  `;
}

function renderCommunications(items) {
  state.communications = items || [];
  el("communicationRecords").innerHTML =
    state.communications
      .map(
        (item) => `
        <article class="row-item delivery-row">
          <div>
            <strong>${escapeHtml(item.stage || "沟通记录")}</strong>
            <p><span class="tag">${escapeHtml(item.status || "待发送")}</span>${escapeHtml(item.channel || "未登记渠道")} / ${escapeHtml(item.direction || "outgoing")} / ${escapeHtml(item.created_at || "")}</p>
            <p>${escapeHtml((item.customer_message || item.system_reply || "").slice(0, 120))}</p>
            <div class="communication-edit-grid">
              <label>阶段<input value="${escapeHtml(item.stage || "询盘")}" data-communication-stage="${item.id}" /></label>
              <label>状态<input value="${escapeHtml(item.status || "待发送")}" data-communication-status="${item.id}" /></label>
              <label>渠道<input value="${escapeHtml(item.channel || "")}" data-communication-channel="${item.id}" /></label>
              <label>方向<input value="${escapeHtml(item.direction || "outgoing")}" data-communication-direction="${item.id}" /></label>
              <label>回复<textarea rows="3" data-communication-reply="${item.id}">${escapeHtml(item.system_reply || "")}</textarea></label>
            </div>
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-communication="${item.id}">保存</button>
            <button type="button" class="secondary" data-delete-communication="${item.id}">删除</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无沟通记录。生成回复并保存后，这里会形成订单沟通流水。</p>";
}

async function refreshCommunications() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderCommunications([]);
    return;
  }
  renderCommunications(await api(`/api/tenders/${tenderId}/communications`));
}

async function suggestCommunication() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/communications/suggest`, {
    method: "POST",
    body: JSON.stringify(communicationPayload(false)),
  });
  renderCommunicationSuggestion(report);
  log(`沟通回复已生成：${report.stage || "沟通"}`);
}

async function saveCommunication() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  if (!el("communicationReply").value.trim()) await suggestCommunication();
  const record = await api(`/api/tenders/${tenderId}/communications`, {
    method: "POST",
    body: JSON.stringify(communicationPayload(true)),
  });
  log(`沟通记录已保存：${record.stage || "沟通"} / ${record.status || "待发送"}`);
  await refreshCommunications();
  await refreshProjectOverview().catch(() => {});
  await refreshStatus().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

function communicationRecordPayload(recordId) {
  return {
    stage: document.querySelector(`[data-communication-stage="${recordId}"]`)?.value || "询盘",
    status: document.querySelector(`[data-communication-status="${recordId}"]`)?.value || "待发送",
    channel: document.querySelector(`[data-communication-channel="${recordId}"]`)?.value || "",
    direction: document.querySelector(`[data-communication-direction="${recordId}"]`)?.value || "outgoing",
    system_reply: document.querySelector(`[data-communication-reply="${recordId}"]`)?.value || "",
  };
}

async function saveCommunicationRecord(recordId) {
  await api(`/api/communications/${recordId}`, {
    method: "PATCH",
    body: JSON.stringify(communicationRecordPayload(recordId)),
  });
  log(`沟通记录已更新：${recordId}`);
  await refreshCommunications();
  await refreshProjectOverview().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

async function deleteCommunication(recordId) {
  if (!window.confirm(`确认删除沟通记录 ID ${recordId}？`)) return;
  const result = await api(`/api/communications/${recordId}`, { method: "DELETE" });
  log(result.deleted ? `沟通记录已删除：${recordId}` : `沟通记录不存在：${recordId}`);
  await refreshCommunications();
  await refreshProjectOverview().catch(() => {});
  await refreshStatus().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

async function copyCommunicationReply() {
  const message = el("communicationReply").value || "";
  if (!message.trim()) throw new Error("请先生成沟通回复。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("communicationReply").select();
    document.execCommand("copy");
  }
  log("沟通回复已复制。");
}

function renderPricingRules(items) {
  state.pricingRules = items || [];
  el("pricingRules").innerHTML =
    state.pricingRules
      .map(
        (item) => `
        <article class="row-item delivery-row">
          <div>
            <strong>${escapeHtml(item.name || "")}</strong>
            <p><span class="tag">${escapeHtml(item.category || "未分类")}</span>${escapeHtml(item.rule_key || "")} / ${escapeHtml(item.unit || "")}</p>
            <div class="pricing-rule-grid">
              <label>规则名称<input value="${escapeHtml(item.name || "")}" data-rule-name="${item.id}" /></label>
              <label>数值<input value="${escapeHtml(item.value || "")}" data-rule-value="${item.id}" /></label>
              <label>状态<input value="${item.enabled ? "启用" : "停用"}" data-rule-enabled="${item.id}" /></label>
              <label>说明<input value="${escapeHtml(item.description || "")}" data-rule-description="${item.id}" /></label>
            </div>
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-rule="${item.id}">保存</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无报价规则。</p>";
}

async function refreshPricingRules() {
  renderPricingRules(await api("/api/pricing/rules"));
}

function pricingRulePayload(ruleId) {
  const enabledText = document.querySelector(`[data-rule-enabled="${ruleId}"]`)?.value || "启用";
  return {
    name: document.querySelector(`[data-rule-name="${ruleId}"]`)?.value || "",
    value: document.querySelector(`[data-rule-value="${ruleId}"]`)?.value || "",
    enabled: !["0", "否", "停用", "false", "False"].includes(enabledText.trim()),
    description: document.querySelector(`[data-rule-description="${ruleId}"]`)?.value || "",
  };
}

async function savePricingRule(ruleId) {
  await api(`/api/pricing/rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(pricingRulePayload(ruleId)),
  });
  log(`报价规则已保存：${ruleId}`);
  await refreshPricingRules();
  await refreshPriceQuote().catch(() => {});
  await refreshIntakeAssistant().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
}

function renderPriceQuote(report) {
  state.priceQuote = report || null;
  if (!report) {
    el("priceQuote").innerHTML = "";
    el("priceQuoteMessage").value = "";
    return;
  }
  const lineItems = report.line_items || [];
  const records = report.records || [];
  el("priceQuoteMessage").value = report.customer_message || "";
  el("priceQuote").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>建议报价</span><strong>${escapeHtml(report.suggested_price || "待测算")}</strong></article>
      <article class="card"><span>工作量</span><strong>${escapeHtml(report.workload || "待测算")}</strong></article>
      <article class="card"><span>交付周期</span><strong>${escapeHtml(report.turnaround || "待确认")}</strong></article>
      <article class="card"><span>资料缺口</span><strong>${report.material_gap_count ?? 0}</strong></article>
    </div>
    <article class="result-item">
      <h3>测算依据</h3>
      <p>预计章节 ${escapeHtml(report.estimated_sections || 0)}，招标要求 ${escapeHtml(report.requirement_count || 0)}，原文 ${escapeHtml(report.raw_text_chars || 0)} 字。</p>
      <p><span class="tag">${report.rush ? "加急" : "普通"}</span><span class="tag">${report.complex_work ? "复杂" : "常规"}</span><span class="tag">${report.light_work ? "轻量" : "完整"}</span></p>
    </article>
    <article class="result-item">
      <h3>加价与折扣</h3>
      ${lineItems.map((item) => `<p><span class="tag">${escapeHtml(item.amount)} 元</span>${escapeHtml(item.name || "")}：${escapeHtml(item.detail || "")}</p>`).join("") || "<p>暂无测算明细。</p>"}
    </article>
    <article class="result-item">
      <h3>历史报价</h3>
      ${records.map((item) => `<p><span class="tag">${escapeHtml(item.suggested_price || "")}</span>${escapeHtml(item.created_at || "")} / ${escapeHtml(item.workload || "")} / ${escapeHtml(item.turnaround || "")}</p>`).join("") || "<p>暂无已保存报价记录。</p>"}
    </article>
  `;
}

async function refreshPriceQuote() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderPriceQuote(null);
    return;
  }
  const report = await api(`/api/tenders/${tenderId}/price-quote`);
  report.records = await api(`/api/tenders/${tenderId}/quotations`).catch(() => []);
  renderPriceQuote(report);
}

async function buildPriceQuote(saveRecord = false) {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/price-quote`, {
    method: "POST",
    body: JSON.stringify({
      customer_message: el("intakeCustomerMessage").value,
      source_platform: el("intakeSourcePlatform").value,
      save_record: saveRecord,
    }),
  });
  report.records = await api(`/api/tenders/${tenderId}/quotations`).catch(() => []);
  renderPriceQuote(report);
  if (!el("confirmationPrice").value) el("confirmationPrice").value = report.suggested_price || "";
  if (!el("taskBudget").value) el("taskBudget").value = report.suggested_price || "";
  log(saveRecord ? `报价记录已保存：${report.suggested_price}` : `报价测算已生成：${report.suggested_price}`);
}

async function copyPriceQuote() {
  const message = el("priceQuoteMessage").value || "";
  if (!message.trim()) throw new Error("请先生成报价测算。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("priceQuoteMessage").select();
    document.execCommand("copy");
  }
  log("报价话术已复制。");
}

function renderPayments(report) {
  state.payments = report || null;
  const summary = report || {};
  const records = summary.records || [];
  el("paymentSummary").innerHTML = `
    <article class="card"><span>收款状态</span><strong>${escapeHtml(summary.status_label || "待记录")}</strong></article>
    <article class="card"><span>订单金额</span><strong>${escapeHtml(summary.expected_amount ?? 0)} 元</strong></article>
    <article class="card"><span>已确认</span><strong>${escapeHtml(summary.received_amount ?? 0)} 元</strong></article>
    <article class="card"><span>未收</span><strong>${escapeHtml(summary.outstanding_amount ?? 0)} 元</strong></article>
  `;
  el("paymentRecords").innerHTML =
    records
      .map(
        (item) => `
        <article class="row-item delivery-row">
          <div>
            <strong>收款记录 #${item.id}</strong>
            <p>${escapeHtml(item.payment_stage || "定金")} / ${escapeHtml(item.status || "待确认")} / ${escapeHtml(item.amount || 0)} 元 / ${escapeHtml(item.received_at || item.created_at || "")}</p>
            <div class="delivery-edit-grid">
              <label>金额<input type="number" min="0" step="0.01" value="${escapeHtml(item.amount || 0)}" data-payment-amount="${item.id}" /></label>
              <label>阶段<input value="${escapeHtml(item.payment_stage || "")}" data-payment-stage="${item.id}" /></label>
              <label>方式<input value="${escapeHtml(item.payment_method || "")}" data-payment-method="${item.id}" /></label>
              <label>状态<input value="${escapeHtml(item.status || "")}" data-payment-status="${item.id}" /></label>
              <label>收款日期<input value="${escapeHtml(item.received_at || "")}" data-payment-received="${item.id}" /></label>
              <label>凭证<input value="${escapeHtml(item.proof || "")}" data-payment-proof="${item.id}" /></label>
              <label>备注<input value="${escapeHtml(item.notes || "")}" data-payment-notes="${item.id}" /></label>
            </div>
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-payment="${item.id}">保存</button>
            <button type="button" class="secondary" data-delete-payment="${item.id}">删除</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无收款记录。交付正式文件前请人工确认收款或定金状态。</p>";
}

async function refreshPayments() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderPayments(null);
    return;
  }
  renderPayments(await api(`/api/tenders/${tenderId}/payments`));
}

function paymentFormPayload() {
  return {
    amount: Number(el("paymentAmount").value || 0),
    payment_stage: el("paymentStage").value,
    payment_method: el("paymentMethod").value,
    status: el("paymentStatus").value,
    received_at: el("paymentReceivedAt").value,
    proof: el("paymentProof").value,
    notes: el("paymentNotes").value,
  };
}

function paymentRowPayload(paymentId) {
  return {
    amount: Number(document.querySelector(`[data-payment-amount="${paymentId}"]`)?.value || 0),
    payment_stage: document.querySelector(`[data-payment-stage="${paymentId}"]`)?.value || "",
    payment_method: document.querySelector(`[data-payment-method="${paymentId}"]`)?.value || "",
    status: document.querySelector(`[data-payment-status="${paymentId}"]`)?.value || "",
    received_at: document.querySelector(`[data-payment-received="${paymentId}"]`)?.value || "",
    proof: document.querySelector(`[data-payment-proof="${paymentId}"]`)?.value || "",
    notes: document.querySelector(`[data-payment-notes="${paymentId}"]`)?.value || "",
  };
}

async function addPayment() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const record = await api(`/api/tenders/${tenderId}/payments`, {
    method: "POST",
    body: JSON.stringify(paymentFormPayload()),
  });
  log(`收款记录已新增：${record.id}`);
  await refreshPayments();
  await refreshOrderDashboard().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshQualityGate().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

async function savePayment(paymentId) {
  await api(`/api/payments/${paymentId}`, {
    method: "PATCH",
    body: JSON.stringify(paymentRowPayload(paymentId)),
  });
  log(`收款记录已保存：${paymentId}`);
  await refreshPayments();
  await refreshOrderDashboard().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshQualityGate().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

async function deletePayment(paymentId) {
  await api(`/api/payments/${paymentId}`, { method: "DELETE" });
  log(`收款记录已删除：${paymentId}`);
  await refreshPayments();
  await refreshOrderDashboard().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshQualityGate().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (!size) return "0 B";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function deliveryPackageFormatLabel(value) {
  return {
    zip: "内部归档包",
    package: "内部归档包",
    client_zip: "客户发货包",
  }[value] || value || "交付包";
}

function renderDeliveryRecords(items) {
  state.deliveries = items || [];
  el("deliveryRecords").innerHTML =
    state.deliveries
      .map(
        (item) => `
        <article class="row-item delivery-row">
          <div>
            <strong>交付记录 #${item.id}</strong>
            <p><span class="tag">${escapeHtml(deliveryPackageFormatLabel(item.package_format))}</span>${escapeHtml(item.status || "已导出")} / ${escapeHtml(item.exported_at || "")} / ${formatBytes(item.package_size)}</p>
            <p>${escapeHtml(item.package_path || "")}</p>
            <div class="delivery-edit-grid">
              <label>发送渠道<input value="${escapeHtml(item.delivery_channel || "")}" data-delivery-channel="${item.id}" placeholder="闲鱼 / 微信 / 邮件 / 网盘" /></label>
              <label>接收人<input value="${escapeHtml(item.recipient || "")}" data-delivery-recipient="${item.id}" placeholder="客户名称或联系人" /></label>
              <label>状态<input value="${escapeHtml(item.status || "已导出")}" data-delivery-status="${item.id}" placeholder="已导出 / 已交付 / 需返工 / 已结案" /></label>
              <label>备注<input value="${escapeHtml(item.notes || "")}" data-delivery-notes="${item.id}" placeholder="发送说明、客户确认、返工原因" /></label>
            </div>
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-delivery="${item.id}">保存</button>
            <button type="button" data-mark-delivered="${item.id}">标记已交付</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无交付记录。导出交付包 ZIP 后会自动生成记录。</p>";
}

async function refreshDeliveries() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderDeliveryRecords([]);
    return;
  }
  renderDeliveryRecords(await api(`/api/tenders/${tenderId}/deliveries`));
}

function packageReadinessLabel(value) {
  return {
    ready: "可交付",
    warning: "需关注",
    blocked: "不可交付",
  }[value] || "待核验";
}

function fileStatusLabel(value) {
  return {
    complete: "已具备",
    missing: "缺失",
    empty: "空文件",
  }[value] || value || "待确认";
}

function renderPackageValidation(report) {
  state.packageValidation = report || null;
  if (!report) {
    el("packageValidation").innerHTML = "<p>导出交付包后，可在这里核验文件是否齐全。</p>";
    return;
  }
  const summary = report.summary || {};
  const packageInfo = report.package || {};
  const blockers = report.blockers || [];
  const warnings = report.warnings || [];
  const files = report.files || [];
  const missingFiles = files.filter((item) => item.status !== "complete");
  const jsonIssues = (report.json_checks || []).filter((item) => !item.valid);
  el("packageValidation").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>核验状态</span><strong>${packageReadinessLabel(summary.readiness)}</strong></article>
      <article class="card"><span>文件齐全</span><strong>${summary.present_files || 0}/${summary.expected_files || 0}</strong></article>
      <article class="card"><span>核心缺失</span><strong>${summary.core_missing || 0}</strong></article>
      <article class="card"><span>JSON 异常</span><strong>${summary.invalid_json || 0}</strong></article>
    </div>
    <article class="result-item">
      <h3>最新交付包</h3>
      <p><span class="tag">${summary.zip_readable ? "ZIP 可读取" : "ZIP 待确认"}</span>${escapeHtml(packageInfo.name || "未生成")}</p>
      <p>${escapeHtml(packageInfo.path || "暂无交付包路径")}</p>
      <p>大小：${formatBytes(summary.package_size || packageInfo.size || 0)}</p>
    </article>
    <article class="result-item">
      <h3>阻断项</h3>
      ${blockers.map((item) => `<p><span class="tag">阻断</span>${escapeHtml(item.title)}：${escapeHtml(item.detail || "")}</p>`).join("") || "<p>暂无阻断项。</p>"}
    </article>
    <article class="result-item">
      <h3>提醒项</h3>
      ${warnings.map((item) => `<p><span class="tag">提醒</span>${escapeHtml(item.title)}：${escapeHtml(item.detail || "")}</p>`).join("") || "<p>暂无提醒项。</p>"}
    </article>
    <article class="result-item">
      <h3>缺失或异常文件</h3>
      ${
        missingFiles
          .slice(0, 24)
          .map((item) => `<p><span class="tag">${fileStatusLabel(item.status)}</span>${escapeHtml(item.level)} / ${escapeHtml(item.name)}</p>`)
          .join("") || "<p>全部期望文件已具备。</p>"
      }
      ${missingFiles.length > 24 ? `<p>另有 ${missingFiles.length - 24} 项未展示。</p>` : ""}
      ${jsonIssues.map((item) => `<p><span class="tag">JSON异常</span>${escapeHtml(item.name)}：${escapeHtml(item.error || "")}</p>`).join("")}
    </article>
  `;
}

async function refreshPackageValidation() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderPackageValidation(null);
    return;
  }
  renderPackageValidation(await api(`/api/tenders/${tenderId}/package-validation`));
}

function renderClientPackageValidation(report) {
  state.clientPackageValidation = report || null;
  if (!report) {
    el("clientPackageValidation").innerHTML = "<p>导出客户发货包后，可在这里核验外发文件是否安全。</p>";
    return;
  }
  const summary = report.summary || {};
  const packageInfo = report.package || {};
  const blockers = report.blockers || [];
  const warnings = report.warnings || [];
  const files = report.files || [];
  const missingFiles = files.filter((item) => item.status !== "complete");
  const contentFindings = report.content_findings || [];
  const forbiddenFiles = report.forbidden_files || [];
  el("clientPackageValidation").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>客户包状态</span><strong>${packageReadinessLabel(summary.readiness)}</strong></article>
      <article class="card"><span>文件齐全</span><strong>${summary.present_files || 0}/${summary.expected_files || 0}</strong></article>
      <article class="card"><span>内部文件</span><strong>${summary.forbidden_files || 0}</strong></article>
      <article class="card"><span>内容风险</span><strong>${summary.content_findings || 0}</strong></article>
    </div>
    <article class="result-item">
      <h3>最新客户发货包</h3>
      <p><span class="tag">${summary.zip_readable ? "ZIP 可读取" : "ZIP 待确认"}</span>${escapeHtml(packageInfo.name || "未生成")}</p>
      <p>${escapeHtml(packageInfo.path || "暂无客户包路径")}</p>
      <p>大小：${formatBytes(summary.package_size || packageInfo.size || 0)}</p>
    </article>
    <article class="result-item">
      <h3>阻断与提醒</h3>
      ${
        [...blockers, ...warnings]
          .map((item) => `<p><span class="tag">${blockers.includes(item) ? "阻断" : "提醒"}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.detail || "")}</p>`)
          .join("") || "<p>暂无阻断或提醒项。</p>"
      }
    </article>
    <article class="result-item">
      <h3>文件与内容风险</h3>
      ${
        missingFiles
          .map((item) => `<p><span class="tag">${fileStatusLabel(item.status)}</span>${escapeHtml(item.name || "")}</p>`)
          .join("") || "<p>客户文件齐全。</p>"
      }
      ${forbiddenFiles.map((item) => `<p><span class="tag">内部文件</span>${escapeHtml(item.name || "")} / ${escapeHtml(item.keyword || "")}</p>`).join("")}
      ${contentFindings.map((item) => `<p><span class="tag">内容风险</span>${escapeHtml(item.file || "")} / ${escapeHtml(item.pattern || "")}</p>`).join("")}
    </article>
  `;
}

async function refreshClientPackageValidation() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderClientPackageValidation(null);
    return;
  }
  renderClientPackageValidation(await api(`/api/tenders/${tenderId}/client-package-validation`));
}

function deliveryPayload(recordId, forcedStatus = "") {
  const channel = document.querySelector(`[data-delivery-channel="${recordId}"]`)?.value || "";
  const recipient = document.querySelector(`[data-delivery-recipient="${recordId}"]`)?.value || "";
  const status = forcedStatus || document.querySelector(`[data-delivery-status="${recordId}"]`)?.value || "已导出";
  const notes = document.querySelector(`[data-delivery-notes="${recordId}"]`)?.value || "";
  return {
    delivery_channel: channel,
    recipient,
    status,
    notes,
  };
}

async function saveDeliveryRecord(recordId, forcedStatus = "") {
  await api(`/api/deliveries/${recordId}`, {
    method: "PATCH",
    body: JSON.stringify(deliveryPayload(recordId, forcedStatus)),
  });
  log(forcedStatus === "已交付" ? `交付记录已标记为已交付：${recordId}` : `交付记录已保存：${recordId}`);
  await refreshDeliveries();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshPackageValidation().catch(() => {});
  await refreshClientPackageValidation().catch(() => {});
  await refreshDeliveryRelease("deliveryReleasePanel").catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClosureConfirmation().catch(() => {});
  await refreshProjectRetrospective().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

function renderDeliveryAssistant(report) {
  state.deliveryAssistant = report || null;
  if (!report) {
    el("deliveryAssistant").innerHTML = "";
    el("deliveryMessage").value = "";
    return;
  }
  const summary = report.summary || {};
  const files = report.files || [];
  const actions = report.actions || [];
  el("deliveryMessage").value = report.customer_message || "";
  el("deliveryAssistant").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>交付包</span><strong>${summary.has_package ? "已生成" : "待导出"}</strong></article>
      <article class="card"><span>文件状态</span><strong>${summary.package_exists ? "存在" : "待确认"}</strong></article>
      <article class="card"><span>交付状态</span><strong>${escapeHtml(summary.delivery_status || "待生产")}</strong></article>
      <article class="card"><span>审查结论</span><strong>${escapeHtml(summary.readiness_text || "待确认")}</strong></article>
    </div>
    <article class="result-item">
      <h3>交付文件清单</h3>
      ${
        files
          .map((item) => `<p><span class="tag">${item.exists ? "可用" : "待生成"}</span>${escapeHtml(item.name)}：${escapeHtml(item.purpose || "")}</p>`)
          .join("") || "<p>暂无文件清单。请先导出交付包。</p>"
      }
    </article>
    <article class="result-item">
      <h3>内部动作</h3>
      ${actions.map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无待处理动作。</p>"}
    </article>
  `;
}

async function refreshDeliveryAssistant() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderDeliveryAssistant(null);
    return;
  }
  renderDeliveryAssistant(await api(`/api/tenders/${tenderId}/delivery-assistant`));
}

async function copyDeliveryMessage() {
  const message = el("deliveryMessage").value || "";
  if (!message.trim()) throw new Error("请先生成交付说明。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("deliveryMessage").select();
    document.execCommand("copy");
  }
  log("客户发货说明已复制。");
}

function renderClientDeliveryConfirmation(report) {
  state.clientDeliveryConfirmation = report || null;
  if (!report) {
    el("clientDeliveryConfirmation").innerHTML = "<p>导出客户发货包后，可在这里生成外发前确认单。</p>";
    el("clientDeliveryMessage").value = "";
    return;
  }
  const summary = report.summary || {};
  const task = report.task || {};
  const latestPackage = report.latest_client_package || {};
  const checklist = report.checklist || [];
  const blockers = report.blockers || [];
  const warnings = report.warnings || [];
  if (!el("clientDeliveryChannel").value) {
    el("clientDeliveryChannel").value = latestPackage.delivery_channel || task.source_platform || "";
  }
  if (!el("clientDeliveryRecipient").value) {
    el("clientDeliveryRecipient").value = latestPackage.recipient || task.customer_name || "";
  }
  el("clientDeliveryMessage").value = report.customer_message || "";
  el("clientDeliveryConfirmation").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>发货状态</span><strong>${escapeHtml(summary.send_label || "待确认")}</strong></article>
      <article class="card"><span>客户包安全</span><strong>${summary.client_package_ready ? "通过" : "未通过"}</strong></article>
      <article class="card"><span>未处理反馈</span><strong>${summary.open_feedback ?? 0}</strong></article>
      <article class="card"><span>收款状态</span><strong>${escapeHtml(summary.payment_status_label || "未登记")}</strong></article>
    </div>
    <article class="result-item">
      <h3>最新客户发货包</h3>
      <p><span class="tag">${escapeHtml(summary.latest_client_delivery_status || "未交付")}</span>${escapeHtml(latestPackage.package_path || "尚未导出客户发货包")}</p>
      <p>客户包存在：${summary.package_exists ? "是" : "否"} / 可记录发货：${summary.can_record_delivery ? "是" : "否"}</p>
    </article>
    <div class="review-checklist">
      ${
        checklist
          .map(
            (item) => `
            <article class="checklist-item ${escapeHtml(item.status || "")}">
              <strong>${escapeHtml(item.title || "")}</strong>
              <p>${escapeHtml(item.detail || "")}</p>
              <p>${escapeHtml(item.action || "无需处理")}</p>
            </article>
          `,
          )
          .join("") || "<p>暂无检查项。</p>"
      }
    </div>
    <article class="result-item">
      <h3>阻断项</h3>
      ${blockers.map((item) => `<p><span class="tag">${escapeHtml(item.severity || "high")}</span>${escapeHtml(item.title || "")}：${escapeHtml(item.detail || "")}</p>`).join("") || "<p>暂无阻断项。</p>"}
    </article>
    <article class="result-item">
      <h3>提醒项</h3>
      ${warnings.map((item) => `<p><span class="tag">提醒</span>${escapeHtml(item.title || "")}：${escapeHtml(item.detail || "")}</p>`).join("") || "<p>暂无提醒项。</p>"}
    </article>
  `;
}

async function refreshClientDeliveryConfirmation() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderClientDeliveryConfirmation(null);
    return;
  }
  renderClientDeliveryConfirmation(await api(`/api/tenders/${tenderId}/client-delivery-confirmation`));
}

function clientDeliveryPayload() {
  return {
    delivery_channel: el("clientDeliveryChannel").value,
    recipient: el("clientDeliveryRecipient").value,
    confirmation_note: el("clientDeliveryNote").value,
    customer_message: el("clientDeliveryMessage").value,
  };
}

async function copyClientDeliveryMessage() {
  const message = el("clientDeliveryMessage").value || "";
  if (!message.trim()) throw new Error("请先生成客户发货确认。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("clientDeliveryMessage").select();
    document.execCommand("copy");
  }
  log("客户发货话术已复制。");
}

async function recordClientDeliveryConfirmation() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/client-delivery-confirmation`, {
    method: "POST",
    body: JSON.stringify(clientDeliveryPayload()),
  });
  renderClientDeliveryConfirmation(report);
  log("已记录客户包已发出。");
  await refreshDeliveries().catch(() => {});
  await refreshStatus().catch(() => {});
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshClientPackageValidation().catch(() => {});
  await refreshDeliveryRelease("deliveryReleasePanel").catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClosureConfirmation().catch(() => {});
  await refreshProjectRetrospective().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

function renderFeedback(items) {
  state.feedback = items || [];
  el("feedbackList").innerHTML =
    state.feedback
      .map(
        (item) => `
        <article class="row-item delivery-row">
          <div>
            <strong>反馈 #${item.id}</strong>
            <p><span class="tag">${escapeHtml(item.status || "待处理")}</span>${escapeHtml(item.priority || "normal")} / ${escapeHtml(item.related_section || "未关联章节")} / ${escapeHtml(item.created_at || "")}</p>
            <p>${escapeHtml(item.feedback_text || "")}</p>
            <div class="feedback-edit-grid">
              <label>状态<input value="${escapeHtml(item.status || "待处理")}" data-feedback-status="${item.id}" /></label>
              <label>关联章节<input value="${escapeHtml(item.related_section || "")}" data-feedback-section="${item.id}" /></label>
              <label>优先级<input value="${escapeHtml(item.priority || "normal")}" data-feedback-priority="${item.id}" /></label>
              <label>负责人<input value="${escapeHtml(item.owner || "")}" data-feedback-owner="${item.id}" /></label>
              <label>处理计划<textarea rows="2" data-feedback-action="${item.id}">${escapeHtml(item.action_plan || "")}</textarea></label>
            </div>
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-feedback="${item.id}">保存</button>
            <button type="button" data-resolve-feedback="${item.id}">标记已解决</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无客户反馈。收到客户修改意见后，可在这里登记并跟踪处理。</p>";
}

async function refreshFeedback() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderFeedback([]);
    return;
  }
  renderFeedback(await api(`/api/tenders/${tenderId}/feedback`));
}

async function addFeedback() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const feedbackText = el("feedbackText").value.trim();
  if (!feedbackText) throw new Error("请填写反馈内容。");
  await api(`/api/tenders/${tenderId}/feedback`, {
    method: "POST",
    body: JSON.stringify({
      feedback_text: feedbackText,
      related_section: el("feedbackSection").value,
      priority: el("feedbackPriority").value || "normal",
      action_plan: el("feedbackActionPlan").value,
      owner: el("feedbackOwner").value,
    }),
  });
  el("feedbackText").value = "";
  el("feedbackActionPlan").value = "";
  log("客户反馈已新增。");
  await refreshFeedback();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshFeedbackRework().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshClosureConfirmation().catch(() => {});
  await refreshProjectRetrospective().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

function feedbackPayload(itemId, forcedStatus = "") {
  return {
    status: forcedStatus || document.querySelector(`[data-feedback-status="${itemId}"]`)?.value || "待处理",
    related_section: document.querySelector(`[data-feedback-section="${itemId}"]`)?.value || "",
    priority: document.querySelector(`[data-feedback-priority="${itemId}"]`)?.value || "normal",
    owner: document.querySelector(`[data-feedback-owner="${itemId}"]`)?.value || "",
    action_plan: document.querySelector(`[data-feedback-action="${itemId}"]`)?.value || "",
  };
}

async function saveFeedback(itemId, forcedStatus = "") {
  await api(`/api/feedback/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(feedbackPayload(itemId, forcedStatus)),
  });
  log(forcedStatus === "已解决" ? `反馈已标记为已解决：${itemId}` : `反馈已保存：${itemId}`);
  await refreshFeedback();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshFeedbackRework().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshClosureConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

function renderFeedbackRework(report) {
  state.feedbackRework = report || null;
  if (!report) {
    el("feedbackRework").innerHTML = "<p>登记客户反馈后，可在这里生成返工处理单。</p>";
    el("feedbackReworkMessage").value = "";
    return;
  }
  const summary = report.summary || {};
  const items = report.items || [];
  el("feedbackReworkMessage").value = report.customer_message || "";
  el("feedbackRework").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>返工状态</span><strong>${escapeHtml(summary.rework_status || "待确认")}</strong></article>
      <article class="card"><span>未处理反馈</span><strong>${summary.open_feedback ?? 0}</strong></article>
      <article class="card"><span>高优先级</span><strong>${summary.high_priority ?? 0}</strong></article>
      <article class="card"><span>影响章节</span><strong>${summary.affected_sections ?? 0}</strong></article>
      <article class="card"><span>已改稿</span><strong>${summary.executed_updates ?? 0}</strong></article>
    </div>
    <article class="result-item">
      <h3>返工处理明细</h3>
      ${
        items
          .map((item) => {
            const targets = (item.target_sections || []).map((section) => section.section_title).join("、") || "待确认章节";
            return `<p><span class="tag">${escapeHtml(item.priority || "normal")}</span>#${item.id} ${escapeHtml(item.feedback_text || "")}<br />涉及：${escapeHtml(targets)}<br />计划：${escapeHtml(item.suggested_action_plan || "")}</p>`;
          })
          .join("") || "<p>暂无未处理反馈。</p>"
      }
    </article>
  `;
}

async function refreshFeedbackRework() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderFeedbackRework(null);
    return;
  }
  renderFeedbackRework(await api(`/api/tenders/${tenderId}/feedback-rework`));
}

async function applyFeedbackRework() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/feedback-rework`, {
    method: "POST",
    body: JSON.stringify({
      owner: el("feedbackOwner").value,
      overwrite_action_plan: false,
    }),
  });
  renderFeedbackRework(report);
  log(`返工计划已应用：${report.summary?.applied_updates || 0} 条反馈进入处理中。`);
  await refreshFeedback();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshClosureConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

async function executeFeedbackRework() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/feedback-rework/execute`, {
    method: "POST",
    body: JSON.stringify({
      owner: el("feedbackOwner").value,
      overwrite_action_plan: false,
      generate_missing_drafts: true,
    }),
  });
  renderFeedbackRework(report);
  log(`返工改稿已执行：更新 ${report.execution?.updated_drafts || 0} 份草稿，生成 ${report.execution?.generated_drafts || 0} 份缺失草稿。`);
  await refreshFeedback();
  await refreshDrafts().catch(() => {});
  await refreshDraftVersions().catch(() => {});
  await refreshCoverage().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryAssistant().catch(() => {});
  await refreshClientDeliveryConfirmation().catch(() => {});
  await refreshClosureConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
}

async function copyFeedbackReworkMessage() {
  const message = el("feedbackReworkMessage").value || "";
  if (!message.trim()) throw new Error("请先生成返工处理单。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("feedbackReworkMessage").select();
    document.execCommand("copy");
  }
  log("客户返工回复已复制。");
}

function renderClosureConfirmation(report) {
  state.closureConfirmation = report || null;
  if (!report) {
    el("closureConfirmation").innerHTML = "";
    el("closureMessage").value = "";
    return;
  }
  const summary = report.summary || {};
  const latestDelivery = report.latest_delivery || {};
  const latestClosure = report.latest_closure || {};
  const checklist = report.checklist || [];
  const blockers = report.blockers || [];
  const actions = report.pending_actions || [];
  const records = report.closure_records || [];
  el("closureMessage").value = report.customer_message || "";
  el("closureConfirmation").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>结案状态</span><strong>${escapeHtml(summary.closure_status || "待确认")}</strong></article>
      <article class="card"><span>交付状态</span><strong>${escapeHtml(summary.delivery_status || "未交付")}</strong></article>
      <article class="card"><span>未处理反馈</span><strong>${summary.open_feedback ?? 0}</strong></article>
      <article class="card"><span>可记录结案</span><strong>${summary.can_record_closure ? "是" : "否"}</strong></article>
    </div>
    <article class="result-item">
      <h3>最新归档</h3>
      <p>交付包：${escapeHtml(latestDelivery.package_path || "尚未导出")}</p>
      <p>结案记录：${escapeHtml(latestClosure.status || "未记录")} / ${escapeHtml(latestClosure.confirmed_by || "未登记确认人")} / ${escapeHtml(latestClosure.confirmed_at || latestClosure.created_at || "")}</p>
    </article>
    <div class="review-checklist">
      ${
        checklist
          .map(
            (item) => `
            <article class="checklist-item ${escapeHtml(item.status || "")}">
              <strong>${escapeHtml(item.title || "")}</strong>
              <p>${escapeHtml(item.detail || "")}</p>
              <p>${escapeHtml(item.action || "无需处理")}</p>
            </article>
          `,
          )
          .join("") || "<p>暂无检查项。</p>"
      }
    </div>
    <article class="result-item">
      <h3>未满足事项</h3>
      ${blockers.map((item) => `<p><span class="tag">${escapeHtml(item.severity)}</span>${escapeHtml(item.title)}：${escapeHtml(item.detail)}</p>`).join("") || "<p>暂无阻碍事项。</p>"}
    </article>
    <article class="result-item">
      <h3>下一步</h3>
      ${actions.map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无待处理动作。</p>"}
    </article>
    <article class="result-item">
      <h3>历史结案记录</h3>
      ${
        records
          .map((item) => `<p><span class="tag">${escapeHtml(item.status || "")}</span>${escapeHtml(item.created_at || "")} / ${escapeHtml(item.confirmed_by || "未登记确认人")} / ${escapeHtml(item.confirmation_note || "")}</p>`)
          .join("") || "<p>暂无客户结案确认记录。</p>"
      }
    </article>
  `;
}

function closurePayload(includeConfirmation = false) {
  const payload = {
    reply_deadline: el("closureReplyDeadline").value,
    extra_note: el("closureExtraNote").value,
  };
  if (includeConfirmation) {
    payload.status = "客户已确认";
    payload.confirmed_by = el("closureConfirmedBy").value;
    payload.confirmation_note = el("closureNote").value;
    payload.customer_message = el("closureMessage").value;
  }
  return payload;
}

async function refreshClosureConfirmation() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderClosureConfirmation(null);
    return;
  }
  renderClosureConfirmation(await api(`/api/tenders/${tenderId}/closure-confirmation`));
}

async function buildClosureConfirmation() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/closure-confirmation`, {
    method: "POST",
    body: JSON.stringify(closurePayload(false)),
  });
  renderClosureConfirmation(report);
  log(`结案确认已生成：${report.summary?.closure_status || "待确认"}`);
}

async function copyClosureMessage() {
  const message = el("closureMessage").value || "";
  if (!message.trim()) throw new Error("请先生成结案确认。");
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(message);
  } else {
    el("closureMessage").select();
    document.execCommand("copy");
  }
  log("客户结案话术已复制。");
}

async function recordClosure() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/closures`, {
    method: "POST",
    body: JSON.stringify(closurePayload(true)),
  });
  renderClosureConfirmation(report);
  log("已记录客户确认结案。");
  await refreshStatus().catch(() => {});
  await refreshDeliveries().catch(() => {});
  await refreshOrderDashboard().catch(() => {});
  await refreshRetrospectiveDashboard().catch(() => {});
  await refreshProjectRetrospective().catch(() => {});
  await refreshWorkflow();
  await refreshProjectTimeline().catch(() => {});
}

function moneyText(value) {
  if (value === null || value === undefined || value === "") return "未计算";
  const number = Number(value);
  if (!Number.isFinite(number)) return escapeHtml(value);
  return `${number.toFixed(number % 1 === 0 ? 0 : 2)}`;
}

function renderRetrospectiveDashboard(report) {
  state.retrospectiveDashboard = report || null;
  if (!report) {
    el("retrospectiveDashboard").innerHTML = "<p>刷新后显示已结案项目、待复盘项目、收入和高风险案例。</p>";
    return;
  }
  const summary = report.summary || {};
  const items = report.items || [];
  el("retrospectiveDashboard").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>项目总数</span><strong>${summary.total ?? 0}</strong></article>
      <article class="card"><span>已复盘</span><strong>${summary.reviewed ?? 0}</strong></article>
      <article class="card"><span>待复盘</span><strong>${summary.pending_review ?? 0}</strong></article>
      <article class="card"><span>高风险</span><strong>${summary.high_risk ?? 0}</strong></article>
      <article class="card"><span>成交合计</span><strong>${moneyText(summary.total_revenue)}</strong></article>
    </div>
    <article class="result-item">
      <h3>复盘项目</h3>
      ${
        items
          .slice(0, 12)
          .map(
            (item) => `
              <p>
                <span class="tag">${escapeHtml(item.retrospective_status || "待复盘")}</span>
                ${escapeHtml(item.name || "")} / ${escapeHtml(item.customer_name || "未登记客户")} /
                成交 ${escapeHtml(item.actual_price || item.budget || "未登记")} /
                风险 ${escapeHtml(item.risk_level || "待评估")} /
                复用 ${escapeHtml(item.reusable_score || "未评估")}
              </p>
            `,
          )
          .join("") || "<p>暂无复盘项目。</p>"
      }
    </article>
  `;
}

async function refreshRetrospectiveDashboard() {
  renderRetrospectiveDashboard(await api("/api/retrospectives/dashboard"));
}

const retrospectiveFields = {
  status: "retroStatus",
  actual_price: "retroActualPrice",
  actual_cost: "retroActualCost",
  work_hours: "retroWorkHours",
  revision_count: "retroRevisionCount",
  satisfaction: "retroSatisfaction",
  risk_level: "retroRiskLevel",
  reusable_score: "retroReusableScore",
  industry_tags: "retroIndustryTags",
  reusable_assets: "retroReusableAssets",
  lessons: "retroLessons",
  next_action: "retroNextAction",
};

function renderProjectRetrospective(report) {
  state.projectRetrospective = report || null;
  if (!report) {
    el("projectRetrospective").innerHTML = "";
    for (const id of Object.values(retrospectiveFields)) {
      if (el(id)) el(id).value = "";
    }
    el("retroStatus").value = "待复盘";
    return;
  }
  const retro = report.retrospective || {};
  const summary = report.summary || {};
  for (const [field, id] of Object.entries(retrospectiveFields)) {
    const node = el(id);
    if (!node) continue;
    node.value = retro[field] ?? "";
  }
  el("retroStatus").value = retro.status || "待复盘";
  el("retroRiskLevel").value = retro.risk_level || summary.risk_level || "";
  el("retroReusableScore").value = retro.reusable_score || summary.reusable_score || "";
  el("projectRetrospective").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>结案状态</span><strong>${escapeHtml(summary.closure_status || "未结案")}</strong></article>
      <article class="card"><span>交付次数</span><strong>${summary.delivery_total ?? 0}</strong></article>
      <article class="card"><span>反馈</span><strong>${summary.feedback_total ?? 0}</strong></article>
      <article class="card"><span>毛利</span><strong>${moneyText(summary.gross_margin_value)}</strong></article>
      <article class="card"><span>小时收入</span><strong>${moneyText(summary.hourly_revenue_value)}</strong></article>
    </div>
    <article class="result-item">
      <h3>复盘建议</h3>
      <p>${escapeHtml(summary.recommendation || "")}</p>
      <p><span class="tag">${summary.can_archive_case ? "可沉淀" : "待完善"}</span>成稿章节 ${escapeHtml(summary.generated_sections || 0)}/${escapeHtml(summary.total_sections || 0)}，风险 ${escapeHtml(summary.risk_level || "待评估")}，复用评分 ${escapeHtml(summary.reusable_score || "未评估")}/5。</p>
    </article>
  `;
}

function retrospectivePayload() {
  const payload = {};
  for (const [field, id] of Object.entries(retrospectiveFields)) {
    const value = el(id)?.value ?? "";
    if (field === "work_hours") payload[field] = value ? Number(value) : null;
    else if (field === "revision_count" || field === "reusable_score") payload[field] = value ? Number(value) : null;
    else payload[field] = value;
  }
  return payload;
}

async function refreshProjectRetrospective() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderProjectRetrospective(null);
    return;
  }
  renderProjectRetrospective(await api(`/api/tenders/${tenderId}/retrospective`));
}

async function saveProjectRetrospective() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/retrospective`, {
    method: "PATCH",
    body: JSON.stringify(retrospectivePayload()),
  });
  renderProjectRetrospective(report);
  log("项目复盘已保存。");
  await refreshStatus().catch(() => {});
  await refreshRetrospectiveDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProjectTimeline().catch(() => {});
}

const enterpriseProfileFields = {
  profile_name: "enterpriseProfileName",
  bidder_name: "enterpriseBidderName",
  legal_representative: "enterpriseLegalRepresentative",
  contact: "enterpriseContact",
  qualification_summary: "enterpriseQualification",
  capability_summary: "enterpriseCapability",
  quality_system: "enterpriseQualitySystem",
  safety_system: "enterpriseSafetySystem",
  key_personnel: "enterpriseKeyPersonnel",
  equipment_resources: "enterpriseEquipment",
  similar_projects: "enterpriseSimilarProjects",
  service_commitment: "enterpriseServiceCommitment",
  notes: "enterpriseNotes",
};

function renderEnterpriseProfile(profile) {
  state.enterpriseProfile = profile || {};
  for (const [field, id] of Object.entries(enterpriseProfileFields)) {
    if (el(id)) el(id).value = state.enterpriseProfile[field] ?? "";
  }
}

function enterpriseProfilePayload() {
  const payload = {};
  for (const [field, id] of Object.entries(enterpriseProfileFields)) {
    const node = el(id);
    if (!node) continue;
    payload[field] = node.value;
  }
  payload.is_default = true;
  return payload;
}

async function refreshEnterpriseProfile() {
  renderEnterpriseProfile(await api("/api/enterprise-profile"));
}

async function saveEnterpriseProfile() {
  const profile = await api("/api/enterprise-profile", {
    method: "PATCH",
    body: JSON.stringify(enterpriseProfilePayload()),
  });
  renderEnterpriseProfile(profile);
  log("投标单位资料已保存，后续章节生成和交付包会使用这些信息。");
  await refreshStatus().catch(() => {});
  await refreshDocumentSettings().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshQualityGate().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
}

const profileFields = {
  project_name: "profileProjectName",
  project_type: "profileProjectType",
  structure_type: "profileStructureType",
  building_area: "profileBuildingArea",
  floor_info: "profileFloorInfo",
  duration_days: "profileDurationDays",
  quality_target: "profileQualityTarget",
  safety_target: "profileSafetyTarget",
  contract_scope: "profileContractScope",
  site_conditions: "profileSiteConditions",
  key_constraints: "profileKeyConstraints",
  special_requirements: "profileSpecialRequirements",
};

function renderProfile(profile) {
  state.profile = profile || {};
  for (const [field, id] of Object.entries(profileFields)) {
    if (el(id)) el(id).value = state.profile[field] ?? "";
  }
  renderProductionGuide(state.workflow);
}

function profilePayload() {
  const payload = {};
  for (const [field, id] of Object.entries(profileFields)) {
    const node = el(id);
    if (!node) continue;
    payload[field] = field === "duration_days" && node.value ? Number(node.value) : node.value;
  }
  payload.industry = el("tenderIndustry").value;
  payload.region = el("tenderRegion").value;
  return payload;
}

async function refreshProfile() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  renderProfile(await api(`/api/tenders/${tenderId}/profile`));
}

async function saveProfile() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const profile = await api(`/api/tenders/${tenderId}/profile`, {
    method: "PATCH",
    body: JSON.stringify(profilePayload()),
  });
  renderProfile(profile);
  log("项目资料已保存，后续章节生成会使用这些参数。");
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshBidStrategy().catch(() => {});
  await refreshFinalDocument().catch(() => {});
}

const bidStrategyFields = {
  positioning: "strategyPositioning",
  win_themes: "strategyWinThemes",
  key_constraints: "strategyConstraints",
  risk_controls: "strategyRiskControls",
  response_priorities: "strategyPriorities",
  writing_tone: "strategyTone",
  reference_keywords: "strategyKeywords",
  forbidden_terms: "strategyForbidden",
  notes: "strategyNotes",
};

function renderBidStrategy(strategy) {
  state.bidStrategy = strategy || null;
  const data = strategy || {};
  for (const [field, id] of Object.entries(bidStrategyFields)) {
    if (el(id)) el(id).value = data[field] ?? "";
  }
  const focusItems = data.section_focus || [];
  el("bidStrategyFocus").innerHTML =
    focusItems
      .map(
        (item) => `
        <article class="result-item">
          <h3>${escapeHtml(item.order_no || "")}. ${escapeHtml(item.section_title || "Untitled section")}</h3>
          <p>${escapeHtml(item.focus || "")}</p>
          <p>
            <span class="tag">Linked requirements ${item.linked_requirements ?? 0}</span>
            <span class="tag">High priority ${item.high_priority ?? 0}</span>
          </p>
        </article>
      `,
      )
      .join("") || "<p>Generate a bid strategy to show section focus items.</p>";
  renderProductionGuide(state.workflow);
}

function bidStrategyPayload() {
  const payload = { status: "manual" };
  for (const [field, id] of Object.entries(bidStrategyFields)) {
    const node = el(id);
    if (!node) continue;
    payload[field] = node.value;
  }
  return payload;
}

async function refreshBidStrategy() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderBidStrategy(null);
    return;
  }
  renderBidStrategy(await api(`/api/tenders/${tenderId}/bid-strategy`));
}

async function generateBidStrategy() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("Please create or open a tender first.");
  const strategy = await api(`/api/tenders/${tenderId}/bid-strategy/generate`, {
    method: "POST",
    body: "{}",
  });
  renderBidStrategy(strategy);
  log("Bid strategy generated; later section drafts will use it.");
  await refreshStatus().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
}

async function saveBidStrategy() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("Please create or open a tender first.");
  const strategy = await api(`/api/tenders/${tenderId}/bid-strategy`, {
    method: "PATCH",
    body: JSON.stringify(bidStrategyPayload()),
  });
  renderBidStrategy(strategy);
  log("Bid strategy saved.");
  await refreshStatus().catch(() => {});
}

function renderDraftList(items) {
  state.drafts = items || [];
  el("draftList").innerHTML =
    state.drafts
      .map((item) => {
        const generation = generationDisplay(item);
        return `
        <article class="row-item">
          <div>
            <strong>${escapeHtml(item.section_title)}</strong>
            <p><span class="tag">${escapeHtml(generation.label)}</span>${escapeHtml(generation.model || "")}${generation.error ? ` / ${escapeHtml(generation.error)}` : ""}</p>
            <p>草稿 ID ${item.id} / ${item.char_count ?? 0} 字 / ${escapeHtml(item.updated_at || "")}</p>
          </div>
          <div class="button-group">
            <button type="button" data-load-draft="${item.id}">打开草稿</button>
            <button type="button" class="secondary" data-create-case-asset="${item.id}">沉淀为案例</button>
          </div>
        </article>
      `;
      })
      .join("") || "<p>当前项目还没有草稿。</p>";
  renderGenerationProgress();
  renderProductionGuide(state.workflow);
}

function documentBlockTypeLabel(value) {
  return {
    text: "正文",
    table: "专业表格",
    organization_chart: "组织架构图",
    flow_chart: "流程图",
    gantt_chart: "横道图",
    image: "示例图片",
    callout: "提示",
  }[value] || value || "内容块";
}

function visualClassLabel(value) {
  return {
    technical_diagram: "程序技术图",
    ai_scene: "AI 场景示意",
    historical_reference: "历史参考图",
    real_material: "真实材料",
    reference: "参考资料",
  }[value] || value || "参考资料";
}

function renderVisualPlan(plan) {
  state.visualPlan = plan || null;
  const summary = plan?.summary || {};
  const settings = plan?.settings || {};
  el("visualGenerationStatus").textContent = settings.note || "尚未生成智能配图计划。";
  el("visualPlanSummary").innerHTML = [
    ["程序技术图", summary.technical_diagrams || 0],
    ["AI 场景计划", summary.ai_hybrid_plans || 0],
    ["已生成 AI 图", summary.ai_generated || 0],
    ["真实资料要求", summary.real_only_requirements || 0],
  ].map(([label, value]) => `<article class="card"><span>${label}</span><strong>${value}</strong></article>`).join("");
  const plans = plan?.ai_hybrid_plans || [];
  el("visualSceneKey").innerHTML = plans.length
    ? plans.map((item) => `<option value="${escapeHtml(item.scene_key)}" data-section="${escapeHtml(item.section_title)}">${escapeHtml(item.title)} / ${escapeHtml(item.status)}</option>`).join("")
    : '<option value="">暂无适用场景</option>';
  const selected = plans[0];
  if (selected && !el("visualHybridSection").value.trim()) el("visualHybridSection").value = selected.section_title || "";
  const realItems = plan?.real_only_requirements || [];
  el("visualPlanList").innerHTML = [
    ...plans.map((item) => `
      <article class="row-item">
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <p><span class="tag">AI 底图 + 程序标注</span><span class="tag">${escapeHtml(item.status)}</span><span class="tag">${escapeHtml(item.review_status)}</span>${escapeHtml(item.section_title)}</p>
          <p>${escapeHtml((item.steps || []).join(" → "))}</p>
          <button type="button" class="secondary" data-copy-visual-prompt="${escapeHtml(item.scene_key)}">复制生图提示词</button>
        </div>
      </article>`),
    ...realItems.map((item) => `
      <article class="row-item">
        <div>
          <strong>${escapeHtml(item.title)}</strong>
          <p><span class="tag">仅真实资料</span>${escapeHtml(item.section_title)}</p>
          <p>${escapeHtml(item.reason)}</p>
        </div>
      </article>`),
  ].join("") || "<p>尚未形成配图计划。</p>";
  document.querySelectorAll("[data-copy-visual-prompt]").forEach((button) => {
    button.addEventListener("click", async () => {
      const item = plans.find((candidate) => candidate.scene_key === button.dataset.copyVisualPrompt);
      if (!item) return;
      await navigator.clipboard.writeText(item.prompt || "");
      log(`已复制“${item.title}”生图提示词。`);
    });
  });
}

function renderRichDocument(blocks = [], assets = []) {
  state.documentBlocks = blocks || [];
  state.visualAssets = assets || [];
  const counts = state.documentBlocks.reduce((result, item) => {
    result[item.block_type] = (result[item.block_type] || 0) + 1;
    return result;
  }, {});
  const sections = [...new Set(state.documentBlocks.map((item) => item.section_title).filter(Boolean))];
  el("documentBlockSummary").innerHTML = [
    ["章节", sections.length],
    ["专业表格", counts.table || 0],
    ["组织架构", counts.organization_chart || 0],
    ["流程图", counts.flow_chart || 0],
    ["横道图", counts.gantt_chart || 0],
    ["示例图片", counts.image || 0],
  ].map(([label, value]) => `<article class="card"><span>${label}</span><strong>${value}</strong></article>`).join("");

  el("documentBlockList").innerHTML = sections.map((section) => {
    const sectionBlocks = state.documentBlocks.filter((item) => item.section_title === section && item.block_type !== "text");
    const labels = sectionBlocks.map((item) => documentBlockTypeLabel(item.block_type));
    const sectionCounts = labels.reduce((result, label) => {
      result[label] = (result[label] || 0) + 1;
      return result;
    }, {});
    return `
      <article class="row-item">
        <div>
          <strong>${escapeHtml(section)}</strong>
          <p>${Object.entries(sectionCounts).map(([label, count]) => `<span class="tag">${escapeHtml(label)} ${count}</span>`).join("") || "仅正文"}</p>
          <p>${sectionBlocks.slice(0, 6).map((item) => escapeHtml(item.caption || item.title || documentBlockTypeLabel(item.block_type))).join(" / ")}</p>
        </div>
      </article>
    `;
  }).join("") || "<p>尚未生成图文内容。完成章节草稿后，点击“生成专业图表与示意图”。</p>";

  const usedIds = new Set((state.visualReview?.items || []).map((item) => Number(item.id)));
  const visualSummary = state.visualReview || {};
  el("visualReviewSummary").innerHTML = `
    <article class="result-item delivery-summary">
      <div><h3>正式成稿素材复核</h3><p>使用中 ${visualSummary.total_used ?? 0} 项 / 已通过 ${visualSummary.approved ?? 0} / 待复核 ${visualSummary.pending ?? 0} / 禁止使用 ${visualSummary.rejected ?? 0} / 文件缺失 ${visualSummary.missing_files ?? 0}</p></div>
      <span class="review-status ${visualSummary.ready ? "ready" : "not_ready"}">${visualSummary.ready ? "可用于正式导出" : "尚未放行"}</span>
    </article>`;
  el("visualAssetGallery").innerHTML = state.visualAssets.slice(0, 70).map((asset) => `
    <article class="visual-asset-item">
      <img src="/api/visual-assets/${asset.id}/file" alt="${escapeHtml(asset.caption || asset.name || "视觉资料")}" loading="lazy" />
      <div>
        <label class="check-line"><input type="checkbox" data-visual-select="${asset.id}" ${usedIds.has(Number(asset.id)) ? "checked" : ""} /><span><strong>${escapeHtml(asset.caption || asset.name || "视觉资料")}</strong></span></label>
        <p><span class="tag">${escapeHtml(visualClassLabel(asset.visual_class))}</span><span class="tag">${escapeHtml(asset.review_status || "待复核")}</span>${escapeHtml(asset.section_title || "公共资产")}</p>
        <p><span class="tag">${usedIds.has(Number(asset.id)) ? "正式稿使用中" : "候选素材"}</span>${escapeHtml(asset.source_kind || "")}</p>
        <p>${escapeHtml(asset.disclaimer || (asset.source_kind === "generated_schematic" ? "投标阶段技术示意图，非施工图" : "使用前须人工确认"))}</p>
        <div class="visual-review-actions">
          <button type="button" title="审核通过" data-visual-review="${asset.id}" data-review-status="已通过">通过</button>
          <button type="button" class="secondary" title="标记为需修改" data-visual-review="${asset.id}" data-review-status="需修改">需修改</button>
        </div>
      </div>
    </article>
  `).join("") || "<p>暂无视觉资产。</p>";
  document.querySelectorAll("[data-visual-review]").forEach((button) => {
    button.addEventListener("click", () => reviewVisualAsset(Number(button.dataset.visualReview), button.dataset.reviewStatus).catch((e) => log(e.message)));
  });
  renderProductionGuide(state.workflow);
}

async function refreshRichDocument() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderRichDocument([], []);
    return;
  }
  const [blocks, assets, plan, visualReview] = await Promise.all([
    api(`/api/tenders/${tenderId}/document-blocks`),
    api(`/api/tenders/${tenderId}/visual-assets`),
    api(`/api/tenders/${tenderId}/visual-plan`),
    api(`/api/tenders/${tenderId}/visual-review`),
  ]);
  state.visualReview = visualReview;
  renderRichDocument(blocks, assets);
  renderVisualPlan(plan);
}

function selectedVisualAssetIds() {
  return [...document.querySelectorAll("[data-visual-select]:checked")].map((node) => Number(node.dataset.visualSelect));
}

async function batchReviewVisualAssets(reviewStatus) {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先打开一个项目。");
  const assetIds = selectedVisualAssetIds();
  if (!assetIds.length) throw new Error("请选择至少一项视觉素材。");
  const result = await api(`/api/tenders/${tenderId}/visual-assets/review-batch`, {
    method: "POST",
    body: JSON.stringify({ asset_ids: assetIds, review_status: reviewStatus, review_notes: "批量人工复核" }),
  });
  state.visualReview = result.summary || null;
  log(`已批量复核 ${result.updated?.length || 0} 项视觉素材：${reviewStatus}`);
  await refreshRichDocument();
  await refreshQualityGate().catch(() => {});
  await refreshAcceptance().catch(() => {});
}

async function autoValidateVisualAssets() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先打开一个项目。");
  const result = await api(`/api/tenders/${tenderId}/visual-assets/auto-validate`, { method: "POST", body: "{}" });
  log(`程序化图表校验完成：${result.updated?.length || 0} 项。历史图片和 AI 场景仍需人工复核。`);
  await refreshRichDocument();
  await refreshAcceptance().catch(() => {});
}

async function buildVisualPlan() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先打开一个项目。");
  const plan = await api(`/api/tenders/${tenderId}/visual-plan`);
  renderVisualPlan(plan);
  log(`配图计划已生成：AI 场景 ${plan.summary?.ai_hybrid_plans || 0} 项，真实资料 ${plan.summary?.real_only_requirements || 0} 项。`);
}

async function generateHybridVisual() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先打开一个项目。");
  const sceneKey = el("visualSceneKey").value;
  if (!sceneKey) throw new Error("当前项目没有可生成的施工场景。");
  const result = await api(`/api/tenders/${tenderId}/visual-assets/generate-hybrid`, {
    method: "POST",
    body: JSON.stringify({
      scene_key: sceneKey,
      source_path: el("visualHybridBase").value.trim(),
      section_title: el("visualHybridSection").value.trim(),
      attach: true,
    }),
  });
  log(`已生成并挂接：${result.asset?.caption || result.asset?.name || sceneKey}`);
  await refreshRichDocument();
}

async function reviewVisualAsset(assetId, reviewStatus) {
  await api(`/api/visual-assets/${assetId}/review`, {
    method: "PATCH",
    body: JSON.stringify({ review_status: reviewStatus, review_notes: "工作台人工审核" }),
  });
  log(`视觉资产 ${assetId} 已标记为“${reviewStatus}”。`);
  await refreshRichDocument();
}

async function generateRichDocument() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先打开一个项目。");
  const report = await api(`/api/tenders/${tenderId}/document-blocks/generate`, {
    method: "POST",
    body: JSON.stringify({ regenerate: true }),
  });
  renderRichDocument(report.blocks || [], report.assets || []);
  const summary = report.summary || {};
  log(`图文标书已生成：表格 ${summary.tables || 0}、流程图 ${summary.flow_charts || 0}、横道图 ${summary.gantt_charts || 0}、图片 ${summary.images || 0}。`);
  await refreshStatus().catch(() => {});
}

async function importVisualAsset() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先打开一个项目。");
  const sourcePath = el("visualAssetSource").value.trim();
  if (!sourcePath) throw new Error("请输入本机图片或 DOCX 路径。");
  const result = await api(`/api/tenders/${tenderId}/visual-assets/import`, {
    method: "POST",
    body: JSON.stringify({
      source_path: sourcePath,
      section_title: el("visualAssetSection").value.trim(),
      name: el("visualAssetName").value.trim(),
      industry: el("tenderIndustry").value.trim(),
    }),
  });
  log(result.imported !== undefined ? `已从 Word 提取 ${result.imported} 张可用图片。` : "视觉资料已导入。");
  await generateRichDocument();
}

function renderCaseAssets(items) {
  state.caseAssets = items || [];
  el("caseAssets").innerHTML =
    state.caseAssets
      .map(
        (item) => `
        <article class="row-item delivery-row">
          <div>
            <strong>${escapeHtml(item.section_title || "未命名章节")}</strong>
            <p>ID ${item.id} / ${escapeHtml(item.project_name || "未命名项目")} / ${escapeHtml(item.industry || "未填行业")} / ${escapeHtml(item.updated_at || "")}</p>
            <div class="case-asset-edit-grid">
              <label>章节<input value="${escapeHtml(item.section_title || "")}" data-case-title="${item.id}" /></label>
              <label>行业<input value="${escapeHtml(item.industry || "")}" data-case-industry="${item.id}" /></label>
              <label>标签<input value="${escapeHtml(item.tags || "")}" data-case-tags="${item.id}" /></label>
              <label>评分<input type="number" min="1" max="5" value="${escapeHtml(item.reusable_score || 3)}" data-case-score="${item.id}" /></label>
              <label>状态<input value="${escapeHtml(item.source_status || "人工沉淀")}" data-case-status="${item.id}" /></label>
              <label>摘要<textarea rows="2" data-case-summary="${item.id}">${escapeHtml(item.summary || "")}</textarea></label>
            </div>
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-case-asset="${item.id}">保存</button>
            <button type="button" class="secondary" data-delete-case-asset="${item.id}">删除</button>
          </div>
        </article>
      `,
      )
      .join("") || "<p>当前项目还没有沉淀案例。可先生成章节，再从草稿列表沉淀。</p>";
}

function renderDraftVersions(items) {
  el("draftVersions").innerHTML =
    items
      .map(
        (item) => `
        <article class="row-item">
          <div>
            <strong>v${item.version_no} / ${escapeHtml(item.origin || "saved")}</strong>
            <p>${item.char_count ?? 0} 字 / ${escapeHtml(item.created_at || "")}</p>
          </div>
          <button type="button" class="secondary" data-restore-version="${item.id}">恢复</button>
        </article>
      `,
      )
      .join("") || "<p>打开或生成草稿后，会在这里显示保存版本。</p>";
}

function renderPlanList(items) {
  const draftsById = new Map((state.drafts || []).map((draft) => [Number(draft.id), draft]));
  el("planList").innerHTML =
    items
      .map((item) => {
        const draft = draftsById.get(Number(item.draft_id));
        const failed = Boolean(draft?.generation_error);
        const statusClass = failed ? "failed" : item.draft_id ? "complete" : "pending";
        const statusLabel = failed ? "生成失败" : item.draft_id ? "已生成" : "待生成";
        return `
        <article class="row-item">
          <div>
            <div class="plan-edit-grid">
              <label>序号<input type="number" min="1" value="${item.order_no}" data-plan-order-input="${item.id}" /></label>
              <label>章节<input value="${escapeHtml(item.section_title)}" data-plan-title-input="${item.id}" /></label>
            </div>
            <p><span class="plan-status ${statusClass}">${statusLabel}</span>${escapeHtml(item.template_name || "通用模板")} / ${escapeHtml(item.rationale || "")}</p>
            ${failed ? `<p class="danger-text">${escapeHtml(draft.generation_error)}</p>` : ""}
          </div>
          <div class="button-group">
            <button type="button" class="secondary" data-save-plan="${item.id}">保存</button>
            <button type="button" data-generate-plan="${item.id}">${failed ? "重试本章" : item.draft_id ? "重新生成" : "生成本章"}</button>
            ${item.draft_id ? `<button type="button" class="secondary" data-load-draft="${item.draft_id}">打开草稿</button>` : ""}
            <button type="button" class="secondary" data-delete-plan="${item.id}">删除</button>
          </div>
        </article>
      `;
      })
      .join("") || "<p>暂无目录规划。创建并解析项目后，点击“生成目录规划”。</p>";
  renderGenerationProgress();
}

function renderGenerationProgress() {
  const node = el("generationProgress");
  if (!node) return;
  const summary = state.workflow?.summary || {};
  const plans = Number(summary.plans || 0);
  const generated = Number(summary.generated_plans || 0);
  const failed = (state.drafts || []).filter((draft) => draft.generation_error).length;
  if (!plans) {
    node.innerHTML = '<div class="notice">目录确认后，这里将按章节显示生成进度和失败重试入口。</div>';
    return;
  }
  node.innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>目录章节</span><strong>${plans}</strong></article>
      <article class="card"><span>已生成</span><strong>${generated}</strong></article>
      <article class="card"><span>待生成</span><strong>${Math.max(0, plans - generated)}</strong></article>
      <article class="card"><span>失败待重试</span><strong>${failed}</strong></article>
    </div>
    ${state.flowBusy ? '<div class="notice">章节正在生成，请保持页面打开。完成后会自动刷新目录和审查状态。</div>' : ""}
  `;
}

function renderPlanAudit(report) {
  state.planAudit = report || null;
  if (!report) {
    el("planAudit").innerHTML = "";
    renderProductionGuide(state.workflow);
    return;
  }
  const summary = report.summary || {};
  const missing = report.missing_standard || [];
  const unplanned = report.unplanned_requirements || [];
  const readiness = summary.readiness === "ready" ? "ready" : "not_ready";
  el("planAudit").innerHTML = `
    <article class="result-item delivery-summary">
      <div>
        <h3>目录完整性审计：${summary.readiness === "ready" ? "可继续生产" : "需补齐"}</h3>
        <p>标准章节 ${summary.standard_covered ?? 0}/${summary.standard_total ?? 0} / 缺章 ${summary.missing_standard ?? 0} / 未挂接要求 ${summary.unplanned_requirements ?? 0}</p>
      </div>
      <span class="review-status ${readiness}">${summary.construction_method_present ? "施工工艺已覆盖" : "施工工艺缺失"}</span>
    </article>
    <div class="coverage-grid">
      <article class="card"><span>目录章节</span><strong>${summary.plans ?? 0}</strong></article>
      <article class="card"><span>已生成</span><strong>${summary.generated_plans ?? 0}</strong></article>
      <article class="card"><span>标准覆盖</span><strong>${summary.standard_covered ?? 0}/${summary.standard_total ?? 0}</strong></article>
      <article class="card"><span>缺失章节</span><strong>${summary.missing_standard ?? 0}</strong></article>
      <article class="card"><span>高优先级缺口</span><strong>${summary.high_unplanned_requirements ?? 0}</strong></article>
    </div>
    <div class="overview-columns">
      <article class="result-item">
        <h3>缺失标准章节</h3>
        ${
          missing
            .slice(0, 12)
            .map(
              (item) =>
                `<p><span class="tag">${escapeHtml(item.severity || "medium")}</span>${escapeHtml(item.name || "")} / ${escapeHtml(
                  item.group || "",
                )} / 关联要求 ${item.matched_requirement_count ?? 0} 条</p>`,
            )
            .join("") || "<p>标准章节已覆盖。</p>"
        }
      </article>
      <article class="result-item">
        <h3>未挂接要求</h3>
        ${
          unplanned
            .slice(0, 12)
            .map(
              (item) =>
                `<p><span class="tag">${escapeHtml(item.priority || "")}</span><span class="tag">${escapeHtml(
                  item.suggested_template || "",
                )}</span>${escapeHtml(item.content || "")}</p>`,
            )
            .join("") || "<p>全部解析要求已挂接到目录。</p>"
        }
      </article>
    </div>
    <article class="result-item">
      <h3>处理建议</h3>
      ${(report.recommendations || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无额外建议。</p>"}
    </article>
  `;
  renderProductionGuide(state.workflow);
}

function toPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function renderCoverage(report) {
  if (!report) {
    el("coverageReport").innerHTML = "";
    return;
  }
  const summary = report.summary || {};
  const missingRequirements = (report.requirements || []).filter((item) => item.status !== "generated").slice(0, 12);
  el("coverageReport").innerHTML = `
    <div class="coverage-grid">
      <article class="card"><span>条款草稿覆盖</span><strong>${toPercent(summary.draft_coverage_rate)}</strong></article>
      <article class="card"><span>目录生成</span><strong>${summary.generated_sections ?? 0}/${summary.total_sections ?? 0}</strong></article>
      <article class="card"><span>高优先级缺口</span><strong>${summary.high_priority_missing ?? 0}</strong></article>
      <article class="card"><span>审查问题</span><strong>${summary.review_findings ?? 0}</strong></article>
    </div>
    <article class="result-item">
      <h3>处理建议</h3>
      ${(report.recommendations || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}
    </article>
    <article class="result-item">
      <h3>目录覆盖</h3>
      ${(report.sections || [])
        .map(
          (item) =>
            `<p><span class="tag">${item.status === "generated" ? "已生成" : "待生成"}</span>${item.order_no}. ${escapeHtml(
              item.section_title,
            )} / 条款 ${item.requirement_count} / 字数 ${item.char_count} / 引用 ${item.citations_count} / 问题 ${
              item.findings_count
            }</p>`,
        )
        .join("")}
    </article>
    <article class="result-item">
      <h3>尚未形成草稿响应的条款</h3>
      ${
        missingRequirements
          .map(
            (item) =>
              `<p><span class="tag">${item.status === "planned" ? "已规划" : "未覆盖"}</span>${escapeHtml(item.kind)} / ${escapeHtml(
                item.priority,
              )}：${escapeHtml(item.content)}</p>`,
          )
          .join("") || "<p>全部解析条款已形成草稿响应。</p>"
      }
    </article>
  `;
}

async function refreshPlan() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) return;
  renderPlanList(await api(`/api/tenders/${tenderId}/plan`));
}

async function refreshPlanAudit() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderPlanAudit(null);
    return;
  }
  renderPlanAudit(await api(`/api/tenders/${tenderId}/plan/audit`));
}

async function repairPlanAudit() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const result = await api(`/api/tenders/${tenderId}/plan/repair`, {
    method: "POST",
    body: "{}",
  });
  renderPlanAudit(result.after || null);
  log(result.added_count ? `已补齐 ${result.added_count} 个目录章节。` : "目录审计未发现缺失标准章节。");
  await refreshPlan();
  await refreshResponseMatrix().catch(() => {});
  await refreshCoverage().catch(() => {});
  await refreshWorkflow().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshGuides();
}

async function buildPlan() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const plan = await api(`/api/tenders/${tenderId}/plan`, { method: "POST", body: "{}" });
  renderPlanList(plan);
  renderCoverage(null);
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  log(`目录规划已生成：${plan.length} 个章节`);
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshBidStrategy().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function addPlanSection() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const sectionTitle = el("customSectionTitle").value.trim();
  if (!sectionTitle) throw new Error("请填写新增章节名称。");
  await api(`/api/tenders/${tenderId}/plan/sections`, {
    method: "POST",
    body: JSON.stringify({
      section_title: sectionTitle,
      order_no: el("customSectionOrder").value ? Number(el("customSectionOrder").value) : null,
      requirement_ids: selectedRequirementIds(),
    }),
  });
  el("customSectionTitle").value = "";
  el("customSectionOrder").value = "";
  await refreshPlan();
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshCoverage().catch(() => {});
  log(`已添加目录章节：${sectionTitle}`);
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshSourceAudit().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshGuides();
}

async function savePlanSection(planId) {
  const titleInput = document.querySelector(`[data-plan-title-input="${planId}"]`);
  const orderInput = document.querySelector(`[data-plan-order-input="${planId}"]`);
  const title = titleInput?.value?.trim();
  if (!title) throw new Error("章节名称不能为空。");
  await api(`/api/section-plans/${planId}`, {
    method: "PATCH",
    body: JSON.stringify({
      section_title: title,
      order_no: Number(orderInput?.value || 1),
    }),
  });
  await refreshPlan();
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshCoverage().catch(() => {});
  log(`目录章节已保存：${title}`);
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshSourceAudit().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshGuides();
}

async function deletePlanSection(planId) {
  if (!window.confirm(`确认删除目录章节 ID ${planId}？`)) return;
  await api(`/api/section-plans/${planId}`, { method: "DELETE" });
  await refreshPlan();
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshCoverage().catch(() => {});
  log(`目录章节已删除：${planId}`);
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function generatePlanSection(planId) {
  const ownsBusy = !state.flowBusy;
  if (ownsBusy) state.flowBusy = true;
  renderGenerationProgress();
  renderProductionGuide(state.workflow);
  let draft;
  try {
    draft = await api(`/api/section-plans/${planId}/generate`, { method: "POST", body: "{}" });
  } finally {
    if (ownsBusy) state.flowBusy = false;
  }
  state.currentDraftId = draft.id;
  state.currentTenderId = draft.tender_id;
  el("draftTenderId").value = draft.tender_id;
  el("sectionTitle").value = draft.section_title;
  el("draftContent").value = draft.content;
  renderDraftMeta(draft);
  log(`已按目录规划生成章节：草稿 ID ${draft.id}`);
  await refreshDraftVersions();
  await refreshDrafts();
  await refreshPlan();
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshStatus();
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function generateAllPlan() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const ownsBusy = !state.flowBusy;
  if (ownsBusy) state.flowBusy = true;
  renderGenerationProgress();
  renderProductionGuide(state.workflow);
  log("开始按目录批量生成章节...");
  let result;
  try {
    result = await api(`/api/tenders/${tenderId}/plan/generate-all`, {
      method: "POST",
      body: JSON.stringify({ regenerate: false }),
    });
  } finally {
    if (ownsBusy) state.flowBusy = false;
  }
  renderPlanList(result.plans || []);
  log(`批量生成完成：新增 ${result.generated_count} 章，跳过 ${result.skipped_count} 章`);
  await refreshDrafts();
  renderPlanList(result.plans || []);
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshCoverage();
  await refreshStatus();
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function refreshCoverage() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/coverage`);
  renderCoverage(report);
}

async function refreshDrafts() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) return;
  renderDraftList(await api(`/api/tenders/${tenderId}/drafts`));
}

function caseAssetDefaults() {
  return {
    tags: el("caseAssetTags").value,
    reusable_score: Number(el("caseAssetScore").value || 4),
    source_status: el("caseAssetSourceStatus").value || "草稿沉淀",
  };
}

async function refreshCaseAssets() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderCaseAssets([]);
    return;
  }
  renderCaseAssets(await api(`/api/tenders/${tenderId}/case-assets`));
}

async function createDraftCaseAsset(draftId) {
  const asset = await api(`/api/drafts/${draftId}/case-asset`, {
    method: "POST",
    body: JSON.stringify(caseAssetDefaults()),
  });
  log(`已沉淀案例资产：${asset.section_title || asset.id}`);
  await refreshCaseAssets();
  await refreshStatus();
  await refreshProjectTimeline().catch(() => {});
}

async function createTenderCaseAssets() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const result = await api(`/api/tenders/${tenderId}/case-assets`, {
    method: "POST",
    body: JSON.stringify(caseAssetDefaults()),
  });
  log(`当前项目已处理 ${result.processed_count ?? result.created_count ?? 0} 条案例资产，新增 ${result.created_count ?? 0} 条，更新 ${result.updated_count ?? 0} 条。`);
  await refreshCaseAssets();
  await refreshStatus();
  await refreshProjectTimeline().catch(() => {});
}

function caseAssetPayload(assetId) {
  return {
    section_title: document.querySelector(`[data-case-title="${assetId}"]`)?.value || "",
    industry: document.querySelector(`[data-case-industry="${assetId}"]`)?.value || "",
    tags: document.querySelector(`[data-case-tags="${assetId}"]`)?.value || "",
    reusable_score: Number(document.querySelector(`[data-case-score="${assetId}"]`)?.value || 3),
    source_status: document.querySelector(`[data-case-status="${assetId}"]`)?.value || "人工沉淀",
    summary: document.querySelector(`[data-case-summary="${assetId}"]`)?.value || "",
  };
}

async function saveCaseAsset(assetId) {
  const asset = await api(`/api/case-assets/${assetId}`, {
    method: "PATCH",
    body: JSON.stringify(caseAssetPayload(assetId)),
  });
  log(`案例资产已保存：${asset.section_title || asset.id}`);
  await refreshCaseAssets();
  await refreshProjectTimeline().catch(() => {});
}

async function deleteCaseAsset(assetId) {
  if (!window.confirm(`确认删除案例资产 ID ${assetId}？`)) return;
  const result = await api(`/api/case-assets/${assetId}`, { method: "DELETE" });
  log(result.deleted ? `案例资产已删除：${assetId}` : `案例资产不存在：${assetId}`);
  await refreshCaseAssets();
  await refreshStatus();
  await refreshProjectTimeline().catch(() => {});
}

async function refreshDraftVersions() {
  if (!state.currentDraftId) {
    renderDraftVersions([]);
    return;
  }
  renderDraftVersions(await api(`/api/drafts/${state.currentDraftId}/versions`));
}

function renderPolish(report) {
  state.polish = report || null;
  if (!report) {
    el("polishPanel").innerHTML = "";
    return;
  }
  const suggestions = report.suggestions || [];
  el("polishPanel").innerHTML = `
    <article class="result-item">
      <h3>风险词扫描</h3>
      <p>已扫描 ${report.draft_count ?? 0} 个草稿，发现 ${suggestions.length} 类可校正表述。</p>
      ${
        suggestions
          .map(
            (item, index) => `
            <p>
              <span class="tag">${escapeHtml(item.type || "")}</span>
              ${escapeHtml(item.search_text || "")} -> ${escapeHtml(item.replace_text || "")}，
              共 ${item.total_count ?? 0} 处
              <button type="button" class="secondary inline-button" data-fill-replacement="${index}">填入</button>
            </p>
          `,
          )
          .join("") || "<p>暂未发现旧项目名或不当承诺残留。</p>"
      }
    </article>
  `;
}

function renderReplacementPreview(report) {
  state.replacementPreview = report || null;
  if (!report) {
    el("replacementPreview").innerHTML = "";
    return;
  }
  el("replacementPreview").innerHTML = `
    <article class="result-item">
      <h3>替换预览</h3>
      <p>查找“${escapeHtml(report.search_text || "")}”，将影响 ${report.changed_drafts ?? 0} 个草稿，共 ${report.changed_count ?? 0} 处。</p>
      ${(report.matches || [])
        .map((item) => `<p><span class="tag">草稿 ${item.draft_id}</span>${escapeHtml(item.section_title || "")}：${item.count ?? 0} 处</p>`)
        .join("") || "<p>没有匹配到需要替换的内容。</p>"}
    </article>
  `;
}

function renderReplacementRecords(items) {
  state.replacementRecords = items || [];
  el("replacementRecords").innerHTML =
    state.replacementRecords
      .map(
        (item) => `
        <article class="row-item">
          <div>
            <strong>${escapeHtml(item.search_text || "")} -> ${escapeHtml(item.replace_text || "")}</strong>
            <p>${escapeHtml(item.created_at || "")} / 草稿 ${item.changed_drafts ?? 0} 个 / 替换 ${item.changed_count ?? 0} 处 / ${escapeHtml(item.notes || "")}</p>
          </div>
        </article>
      `,
      )
      .join("") || "<p>暂无项目化校正记录。</p>";
}

async function scanPolish() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const report = await api(`/api/tenders/${tenderId}/polish`);
  renderPolish(report);
  renderReplacementRecords(report.records || []);
}

function replacementPayload() {
  return {
    search_text: el("replacementSearch").value,
    replace_text: el("replacementText").value,
    notes: el("replacementNotes").value,
  };
}

async function previewReplacement() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const payload = replacementPayload();
  if (!payload.search_text.trim()) throw new Error("请填写查找词。");
  renderReplacementPreview(
    await api(`/api/tenders/${tenderId}/replacements/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  );
}

async function applyReplacement() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const payload = replacementPayload();
  if (!payload.search_text.trim()) throw new Error("请填写查找词。");
  if (!window.confirm(`确认把全部草稿中的“${payload.search_text}”替换为“${payload.replace_text}”？`)) return;
  const result = await api(`/api/tenders/${tenderId}/replacements/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderReplacementPreview(result);
  log(`全稿替换完成：影响 ${result.changed_drafts ?? 0} 个草稿，共 ${result.changed_count ?? 0} 处。`);
  await refreshDrafts();
  await refreshReplacementRecords();
  await refreshCoverage().catch(() => {});
  await refreshQualityGate().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
  await refreshFinalDocument().catch(() => {});
}

async function refreshReplacementRecords() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderReplacementRecords([]);
    return;
  }
  renderReplacementRecords(await api(`/api/tenders/${tenderId}/replacements`));
}

function fillReplacement(index) {
  const item = state.polish?.suggestions?.[index];
  if (!item) return;
  el("replacementSearch").value = item.search_text || "";
  el("replacementText").value = item.replace_text || "";
  el("replacementNotes").value = item.type === "old_project_name" ? "交付前旧项目名清理" : "交付前风险承诺清理";
  renderReplacementPreview(null);
}

async function createTender() {
  const tender = await api("/api/tenders/import", {
    method: "POST",
    body: JSON.stringify({
      name: el("tenderName").value,
      text: el("tenderText").value,
      industry: el("tenderIndustry").value,
      region: el("tenderRegion").value,
    }),
  });
  state.currentTenderId = tender.id;
  el("draftTenderId").value = tender.id;
  const parsed = await api(`/api/tenders/${tender.id}/parse`, { method: "POST", body: "{}" });
  await refreshTask();
  renderProfile(parsed.profile || {});
  renderRequirements(parsed.requirements);
  renderDraftList([]);
  renderCaseAssets([]);
  renderPlanList([]);
  clearSourcePreview();
  renderResponseMatrix(null);
  renderPlanAudit(null);
  renderDraftVersions([]);
  renderDeliveryRecords([]);
  renderFeedback([]);
  renderDeliveryAssistant(null);
  renderClosureConfirmation(null);
  renderProjectRetrospective(null);
  renderIntakeAssistant(null);
  renderOrderConfirmation(null);
  renderPriceQuote(null);
  renderPayments(null);
  renderProjectTimeline(null);
  renderBidStrategy(null);
  renderProductionPipeline(null);
  renderProductionReadiness(null);
  renderQualityGate(null);
  renderSourceAudit(null);
  renderFinalChecklist(null);
  renderPolish(null);
  renderCommunicationSuggestion(null);
  renderCommunications([]);
  renderReplacementPreview(null);
  renderReplacementRecords([]);
  await refreshMaterials();
  await refreshDocumentSettings().catch(() => {});
  await refreshBidStrategy().catch(() => {});
  await refreshProcessingRecords().catch(() => {});
  renderCoverage(null);
  renderProjectOverview(null);
  renderCommandCenter(null);
  renderProductionStarter(null);
  renderOrderWizard(null);
  renderChannelOps(null);
  log(`项目已创建并解析：ID ${tender.id}`);
  await refreshStatus();
  await refreshTenders();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProductionReadiness().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshRevisionTasks().catch(() => {});
  await refreshSourceAudit().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function uploadTender() {
  const file = el("tenderFile").files[0];
  if (!file) throw new Error("请先选择招标文件。");
  const form = new FormData();
  form.append("file", file);
  form.append("industry", el("tenderIndustry").value);
  form.append("region", el("tenderRegion").value);
  const tender = await apiForm("/api/tenders/upload", form);
  state.currentTenderId = tender.id;
  el("draftTenderId").value = tender.id;
  const parsed = await api(`/api/tenders/${tender.id}/parse`, { method: "POST", body: "{}" });
  await refreshTask();
  renderProfile(parsed.profile || {});
  renderRequirements(parsed.requirements);
  renderDraftList([]);
  renderCaseAssets([]);
  renderPlanList([]);
  clearSourcePreview();
  renderResponseMatrix(null);
  renderPlanAudit(null);
  renderDraftVersions([]);
  renderDeliveryRecords([]);
  renderFeedback([]);
  renderDeliveryAssistant(null);
  renderClosureConfirmation(null);
  renderProjectRetrospective(null);
  renderIntakeAssistant(null);
  renderOrderConfirmation(null);
  renderPriceQuote(null);
  renderPayments(null);
  renderBidStrategy(null);
  renderProcessingRecords([]);
  renderProductionPipeline(null);
  renderProductionReadiness(null);
  renderQualityGate(null);
  renderRevisionTasks(null);
  renderSourceAudit(null);
  renderFinalChecklist(null);
  renderFinalDocument(null);
  renderPolish(null);
  renderCommunicationSuggestion(null);
  renderCommunications([]);
  renderReplacementPreview(null);
  await refreshReplacementRecords();
  await refreshMaterials();
  await refreshDocumentSettings().catch(() => {});
  await refreshBidStrategy().catch(() => {});
  await refreshProcessingRecords().catch(() => {});
  renderCoverage(null);
  renderProjectOverview(null);
  renderCommandCenter(null);
  renderProductionStarter(null);
  renderOrderWizard(null);
  renderChannelOps(null);
  log(`文件已上传并解析：ID ${tender.id}`);
  await refreshStatus();
  await refreshTenders();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshProductionReadiness().catch(() => {});
  await refreshProjectOverview().catch(() => {});
  await refreshDeliveryReview().catch(() => {});
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshRevisionTasks().catch(() => {});
  await refreshSourceAudit().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function applyTenderSourceResult(result, message) {
  const tender = result.tender || {};
  state.currentTenderId = tender.id || state.currentTenderId;
  state.currentDraftId = null;
  el("draftTenderId").value = tender.id || "";
  el("tenderName").value = tender.name || el("tenderName").value;
  el("tenderIndustry").value = tender.industry || el("tenderIndustry").value;
  el("tenderRegion").value = tender.region || el("tenderRegion").value;
  if (tender.raw_text) el("tenderText").value = tender.raw_text;
  renderTask(tender.task || state.task || {});
  renderProfile(tender.profile || result.profile || {});
  renderRequirements(tender.requirements || result.requirements || []);
  renderDraftList(tender.drafts || []);
  await refreshCaseAssets();
  renderPlanList(tender.section_plans || []);
  clearSourcePreview();
  renderResponseMatrix(null);
  renderPlanAudit(null);
  renderDraftVersions([]);
  renderDeliveryAssistant(null);
  renderClosureConfirmation(null);
  renderProjectRetrospective(null);
  renderOrderConfirmation(null);
  renderPriceQuote(null);
  renderPayments(null);
  renderProjectTimeline(null);
  renderFinalDocument(null);
  renderProductionPipeline(null);
  renderProductionReadiness(null);
  renderCommandCenter(null);
  renderProductionStarter(null);
  renderOrderWizard(null);
  renderChannelOps(null);
  renderQualityGate(null);
  renderRevisionTasks(null);
  renderSourceAudit(null);
  renderCommunicationSuggestion(null);
  await refreshCommunications();
  await refreshDocumentSettings().catch(() => {});
  await refreshBidStrategy().catch(() => {});
  await refreshProcessingRecords().catch(() => {});
  await refreshMaterials();
  await refreshProjectOverview().catch(() => {});
  await refreshPayments().catch(() => {});
  renderCoverage(null);
  log(message);
  await refreshStatus();
  await refreshTenders();
  await refreshOrderDashboard().catch(() => {});
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshResponseMatrix().catch(() => {});
  await refreshPlanAudit().catch(() => {});
  await refreshRevisionTasks().catch(() => {});
  await refreshSourceAudit().catch(() => {});
  await refreshFinalChecklist().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshIntakeAssistant().catch(() => {});
  await refreshOrderConfirmation().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

async function updateTenderSource() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const text = el("tenderText").value.trim();
  if (!text) throw new Error("请先粘贴完整招标文件文本。");
  const result = await api(`/api/tenders/${tenderId}/source`, {
    method: "POST",
    body: JSON.stringify({
      name: el("tenderName").value,
      text,
      industry: el("tenderIndustry").value,
      region: el("tenderRegion").value,
      mode: "replace",
      reset_plan: true,
      parse: true,
    }),
  });
  await applyTenderSourceResult(result, `当前项目已补充招标文本并重新解析：ID ${tenderId}`);
}

async function uploadTenderSource() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建或打开项目。");
  const file = el("tenderFile").files[0];
  if (!file) throw new Error("请先选择招标文件。");
  const form = new FormData();
  form.append("file", file);
  form.append("industry", el("tenderIndustry").value);
  form.append("region", el("tenderRegion").value);
  const result = await apiForm(`/api/tenders/${tenderId}/source/upload`, form);
  await applyTenderSourceResult(result, `当前项目已上传招标文件并重新解析：ID ${tenderId}`);
}

async function generateDraft() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先创建项目或填写项目 ID。");
  const draft = await api("/api/drafts/generate", {
    method: "POST",
    body: JSON.stringify({
      tender_id: tenderId,
      section_title: el("sectionTitle").value,
      category: el("draftCategory").value,
      requirement_ids: selectedRequirementIds(),
    }),
  });
  state.currentDraftId = draft.id;
  el("draftContent").value = draft.content;
  renderDraftMeta(draft);
  log(`章节已生成：草稿 ID ${draft.id}`);
  await refreshDraftVersions();
  await refreshStatus();
  await refreshDrafts();
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshCommandCenter().catch(() => {});
  await refreshProductionStarter().catch(() => {});
  await refreshOrderWizard().catch(() => {});
  await refreshChannelOps().catch(() => {});
}

function renderDraftMeta(draft) {
  const citations = draft.citations || [];
  state.draftCitations = citations;
  const review = draft.review || [];
  const contract = draft.chapter_contract || {};
  const validation = draft.contract_validation || {};
  const generation = generationDisplay(draft);
  const linkedRequirements = contract.requirements || draft.requirements || [];
  el("chapterContractPanel").innerHTML = contract.section_title ? `
    <div class="contract-heading"><div><span class="eyebrow">章节编制合同</span><h3>${escapeHtml(contract.section_title || "")}</h3></div><span class="review-status ${validation.ready_for_review ? "ready" : "needs_work"}">${validation.ready_for_review ? "可送审" : "需完善"}</span></div>
    <p><span class="tag">${escapeHtml(contract.template_name || "通用模板")}</span><span class="tag">${validation.char_count || 0}/${validation.minimum_chars || 0} 字</span><span class="tag">待确认 ${validation.placeholder_count || 0}</span></p>
    <h4>对应条款</h4>
    <div class="contract-list">${linkedRequirements.map((item) => `<p><span class="tag">${escapeHtml(item.priority || "normal")}</span>${escapeHtml(item.content || "")}</p>`).join("") || "<p>本章暂无直接挂接条款。</p>"}</div>
    <h4>必写结构</h4>
    <p>${(contract.required_subsections || []).map((item) => `<span class="tag ${validation.missing_subsections?.includes(item) ? "danger-tag" : ""}">${escapeHtml(item)}</span>`).join("") || "按模板编制"}</p>
    ${(contract.construction_method_structure || []).length ? `<h4>工艺八要素</h4><p>${contract.construction_method_structure.map((item) => `<span class="tag ${validation.missing_method_fields?.includes(item) ? "danger-tag" : ""}">${escapeHtml(item)}</span>`).join("")}</p>` : ""}
    <h4>图表要求</h4>
    <p>${[...(contract.table_slots || []), ...(contract.visual_slots || [])].map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("") || "本章无强制图表槽位"}</p>
    <h4>禁止编造</h4>
    <p>${escapeHtml((contract.forbidden_assumptions || []).join("；"))}</p>
  ` : "<p>生成或重新打开章节后显示编制合同、对应条款和缺口。</p>";
  el("draftMeta").innerHTML = `
    <article class="result-item">
      <h3>生成方式</h3>
      <p><span class="tag">${escapeHtml(generation.label)}</span>${escapeHtml(generation.model || "未配置模型")}</p>
      ${generation.error ? `<p class="danger">${escapeHtml(generation.error)}</p>` : ""}
    </article>
    <article class="result-item">
      <h3>引用来源</h3>
      ${
        citations
          .map(
            (c, index) => `
            <p>
              ${escapeHtml(c.source_path || "")} / ${escapeHtml(c.heading_text || "")}
              <button type="button" class="secondary inline-button" data-preview-draft-citation="${index}">查看来源</button>
            </p>
          `,
          )
          .join("") || "<p>暂无引用。</p>"
      }
    </article>
    <article class="result-item">
      <h3>审查结果</h3>
      ${review.map((f) => `<p><span class="tag">${escapeHtml(f.severity)}</span>${escapeHtml(f.message)}</p>`).join("") || "<p>尚未审查。</p>"}
    </article>
  `;
}

async function loadDraft(draftId) {
  const draft = await api(`/api/drafts/${draftId}`);
  state.currentDraftId = draft.id;
  state.currentTenderId = draft.tender_id;
  el("draftTenderId").value = draft.tender_id;
  el("sectionTitle").value = draft.section_title;
  el("draftContent").value = draft.content;
  renderDraftMeta(draft);
  await refreshDraftVersions();
  log(`已打开草稿：${draft.id}`);
}

async function saveDraft() {
  if (!state.currentDraftId) throw new Error("当前没有打开的草稿。");
  const draft = await api(`/api/drafts/${state.currentDraftId}`, {
    method: "PATCH",
    body: JSON.stringify({ content: el("draftContent").value }),
  });
  renderDraftMeta(draft);
  log(`草稿已保存：${draft.id}`);
  await refreshDraftVersions();
  await refreshDrafts();
  await refreshWorkflow();
  await refreshDeliveryReview().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshGuides();
}

async function restoreDraftVersion(versionId) {
  if (!state.currentDraftId) throw new Error("请先打开一个草稿。");
  const draft = await api(`/api/drafts/${state.currentDraftId}/versions/${versionId}/restore`, {
    method: "POST",
    body: "{}",
  });
  el("draftContent").value = draft.content;
  renderDraftMeta(draft);
  log(`已恢复草稿版本：${versionId}`);
  await refreshDraftVersions();
  await refreshDrafts();
  await refreshSourceAudit().catch(() => {});
  await refreshFinalDocument().catch(() => {});
  await refreshProjectTimeline().catch(() => {});
  await refreshGuides();
}

async function reviewTender() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  const findings = await api(`/api/tenders/${tenderId}/review`);
  el("draftMeta").innerHTML = `
    <article class="result-item">
      <h3>审查结果</h3>
      ${findings.map((f) => `<p><span class="tag">${escapeHtml(f.severity)}</span>${escapeHtml(f.message)}</p>`).join("") || "<p>未发现明显问题。</p>"}
    </article>
  `;
}

function renderAcceptance(report) {
  state.acceptance = report || null;
  if (!report) {
    el("acceptancePanel").innerHTML = "<p>打开项目后显示正式交付验收状态。</p>";
    return;
  }
  const current = report.current || report;
  const metrics = current.metrics || {};
  const blockers = current.blockers || [];
  const runs = report.runs || (current.run ? [current.run] : []);
  el("acceptancePanel").innerHTML = `
    <article class="acceptance-hero">
      <div><p class="eyebrow">正式交付能力</p><h3>${current.ready ? "已达到正式导出条件" : "仍有阻断项"}</h3><p>质量分 ${current.quality_score ?? 0} / 正文证据 ${toPercent(metrics.chapter_evidence_rate || 0)} / 评分点 ${escapeHtml(metrics.scoring_verified || "0/0")} / 合规确认 ${escapeHtml(metrics.compliance_confirmed || "0/0")}</p></div>
      <span class="review-status ${current.ready ? "ready" : "not_ready"}">${current.ready ? "可交付" : `${blockers.length} 项待处理`}</span>
    </article>
    <div class="coverage-grid">
      <article class="card"><span>章节</span><strong>${metrics.generated_sections ?? 0}/${metrics.sections ?? 0}</strong></article>
      <article class="card"><span>正文字符</span><strong>${metrics.char_count ?? 0}</strong></article>
      <article class="card"><span>待确认</span><strong>${metrics.placeholders ?? 0}</strong></article>
      <article class="card"><span>有效来源</span><strong>${metrics.valid_citations ?? 0}</strong></article>
      <article class="card"><span>视觉通过</span><strong>${metrics.visuals_approved ?? 0}/${metrics.visuals_used ?? 0}</strong></article>
      <article class="card"><span>DOCX 预检</span><strong>${metrics.docx_layout_ready ? `${metrics.docx_visual_metrics?.pages ?? 0} 页通过` : "待预检"}</strong></article>
    </div>
    <div class="table-list compact-list">
      ${blockers.map((item) => `<article class="row-item"><div><strong>${escapeHtml(item.title || "")}</strong><p>${escapeHtml(item.detail || "")}</p></div><button type="button" class="secondary" data-acceptance-target="${escapeHtml(item.target || "review")}">去处理</button></article>`).join("") || "<article class=\"result-item\"><strong>所有硬性门禁均已通过。</strong></article>"}
    </div>
    <h3 class="subheading">验收记录</h3>
    <div class="table-list compact-list">${runs.slice(0, 8).map((item) => `<article class="row-item"><div><strong>${escapeHtml(item.status || "")}</strong><p>${escapeHtml(item.created_at || "")} / 质量分 ${item.quality_score ?? 0} / 人工精修 ${item.manual_edit_hours ?? "未记录"} 小时</p><p>${escapeHtml(item.conclusion || "")}</p></div></article>`).join("") || "<p>尚未记录正式验收。</p>"}</div>
  `;
  document.querySelectorAll("[data-acceptance-target]").forEach((button) => button.addEventListener("click", () => navigateProject(button.dataset.acceptanceTarget || "review")));
  const notice = el("exportGateNotice");
  if (notice) notice.innerHTML = current.ready ? "<strong>正式导出门禁已通过。</strong>" : `<strong>正式导出暂不可用。</strong> ${blockers.map((item) => escapeHtml(item.title || "")).join("、")}`;
  renderExportGate();
}

async function refreshAcceptance() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) {
    renderAcceptance(null);
    return;
  }
  renderAcceptance(await api(`/api/tenders/${tenderId}/acceptance`));
}

async function runAcceptance() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先打开一个项目。");
  const hoursText = el("acceptanceManualHours").value.trim();
  const result = await api(`/api/tenders/${tenderId}/acceptance/run`, {
    method: "POST",
    body: JSON.stringify({
      manual_edit_hours: hoursText ? Number(hoursText) : null,
      conclusion: el("acceptanceConclusion").value.trim(),
      exports: {},
    }),
  });
  log(`正式验收已记录：质量分 ${result.quality_score ?? 0}，${result.ready ? "通过" : "仍需整改"}。`);
  await refreshAcceptance();
}

async function runDocxPreflight() {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (!tenderId) throw new Error("请先打开一个项目。");
  const result = await api(`/api/tenders/${tenderId}/docx-preflight`, {
    method: "POST",
    body: "{}",
  });
  const metrics = result.layout_audit?.metrics || {};
  const visual = result.layout_audit?.visual_render?.metrics || {};
  log(`DOCX 预检已通过：${metrics.tables ?? 0} 个表格，${metrics.drawings ?? 0} 个图形，${visual.pages ?? 0} 页无空白与越界。`);
  await refreshAcceptance();
}

async function exportTender(format) {
  const tenderId = Number(el("draftTenderId").value || state.currentTenderId);
  if (["docx", "formal_docx", "client_package", "client_zip"].includes(format)) {
    const acceptance = await api(`/api/tenders/${tenderId}/acceptance`);
    renderAcceptance(acceptance);
    if (!acceptance.current?.ready) {
      const first = acceptance.current?.blockers?.[0];
      navigateProject(first?.target || "review");
      throw new Error(first?.detail || "正式导出门禁尚未通过。");
    }
  }
  const result = await api(`/api/tenders/${tenderId}/export`, {
    method: "POST",
    body: JSON.stringify({ format }),
  });
  log(`已导出 ${format}：${result.path}`);
  await refreshAcceptance().catch(() => {});
  if (["package", "zip", "client_package", "client_zip"].includes(format)) {
    await refreshDeliveries();
    await refreshPackageValidation().catch(() => {});
    await refreshClientPackageValidation().catch(() => {});
    await refreshDeliveryRelease().catch(() => {});
    await refreshDeliveryRelease("deliveryReleasePanel").catch(() => {});
    await refreshProductionReadiness().catch(() => {});
    await refreshOrderDashboard().catch(() => {});
    await refreshWorkflow();
    await refreshProjectOverview().catch(() => {});
    await refreshDeliveryReview().catch(() => {});
    await refreshResponseMatrix().catch(() => {});
    await refreshPlanAudit().catch(() => {});
    await refreshRevisionTasks().catch(() => {});
    await refreshSourceAudit().catch(() => {});
    await refreshDeliveryAssistant().catch(() => {});
    await refreshClientDeliveryConfirmation().catch(() => {});
    await refreshFinalChecklist().catch(() => {});
    await refreshClosureConfirmation().catch(() => {});
    await refreshProjectRetrospective().catch(() => {});
    await refreshProjectTimeline().catch(() => {});
    await refreshCommandCenter().catch(() => {});
    await refreshProductionStarter().catch(() => {});
    await refreshOrderWizard().catch(() => {});
    await refreshChannelOps().catch(() => {});
  }
  if (result.download_url) window.open(result.download_url, "_blank");
}

document.addEventListener("click", (event) => {
  const tenderId = event.target?.dataset?.loadTender;
  const deleteTenderId = event.target?.dataset?.deleteTender;
  const draftId = event.target?.dataset?.loadDraft;
  const planId = event.target?.dataset?.generatePlan;
  const savePlanId = event.target?.dataset?.savePlan;
  const deletePlanId = event.target?.dataset?.deletePlan;
  const versionId = event.target?.dataset?.restoreVersion;
  const saveDeliveryId = event.target?.dataset?.saveDelivery;
  const markDeliveredId = event.target?.dataset?.markDelivered;
  const saveFeedbackId = event.target?.dataset?.saveFeedback;
  const resolveFeedbackId = event.target?.dataset?.resolveFeedback;
  const saveMaterialId = event.target?.dataset?.saveMaterial;
  const completeMaterialId = event.target?.dataset?.completeMaterial;
  const deleteMaterialId = event.target?.dataset?.deleteMaterial;
  const savePaymentId = event.target?.dataset?.savePayment;
  const deletePaymentId = event.target?.dataset?.deletePayment;
  const saveRuleId = event.target?.dataset?.saveRule;
  const createCaseAssetId = event.target?.dataset?.createCaseAsset;
  const saveCaseAssetId = event.target?.dataset?.saveCaseAsset;
  const deleteCaseAssetId = event.target?.dataset?.deleteCaseAsset;
  const editTemplateName = event.target?.dataset?.editTemplate;
  const deleteTemplateId = event.target?.dataset?.deleteTemplate;
  const saveRequirementId = event.target?.dataset?.saveRequirement;
  const deleteRequirementId = event.target?.dataset?.deleteRequirement;
  const saveFinalCheckId = event.target?.dataset?.saveFinalCheck;
  const saveRevisionId = event.target?.dataset?.saveRevision;
  const openRevisionDraftId = event.target?.dataset?.openRevisionDraft;
  const revisionSection = event.target?.dataset?.revisionSection;
  const fillReplacementIndex = event.target?.dataset?.fillReplacement;
  const saveCommunicationId = event.target?.dataset?.saveCommunication;
  const deleteCommunicationId = event.target?.dataset?.deleteCommunication;
  const previewSearchIndex = event.target?.dataset?.previewSearchSource;
  const previewCitationIndex = event.target?.dataset?.previewDraftCitation;
  const commandAction = event.target?.dataset?.commandAction;
  const commandTarget = event.target?.dataset?.commandTarget;
  const wizardAction = event.target?.dataset?.wizardAction;
  const wizardTarget = event.target?.dataset?.wizardTarget;
  const wizardCopy = event.target?.dataset?.wizardCopy;
  const channelCopy = event.target?.dataset?.channelCopy;
  const runKbOcr = event.target?.dataset?.runKbOcr;
  if (tenderId) openTenderWorkspace(Number(tenderId));
  if (deleteTenderId) deleteTender(Number(deleteTenderId)).catch((e) => log(e.message));
  if (draftId) loadDraft(Number(draftId)).catch((e) => log(e.message));
  if (planId) generatePlanSection(Number(planId)).catch((e) => log(e.message));
  if (savePlanId) savePlanSection(Number(savePlanId)).catch((e) => log(e.message));
  if (deletePlanId) deletePlanSection(Number(deletePlanId)).catch((e) => log(e.message));
  if (versionId) restoreDraftVersion(Number(versionId)).catch((e) => log(e.message));
  if (saveDeliveryId) saveDeliveryRecord(Number(saveDeliveryId)).catch((e) => log(e.message));
  if (markDeliveredId) saveDeliveryRecord(Number(markDeliveredId), "已交付").catch((e) => log(e.message));
  if (saveFeedbackId) saveFeedback(Number(saveFeedbackId)).catch((e) => log(e.message));
  if (resolveFeedbackId) saveFeedback(Number(resolveFeedbackId), "已解决").catch((e) => log(e.message));
  if (saveMaterialId) saveMaterial(Number(saveMaterialId)).catch((e) => log(e.message));
  if (completeMaterialId) saveMaterial(Number(completeMaterialId), "已具备").catch((e) => log(e.message));
  if (deleteMaterialId) deleteMaterial(Number(deleteMaterialId)).catch((e) => log(e.message));
  if (savePaymentId) savePayment(Number(savePaymentId)).catch((e) => log(e.message));
  if (deletePaymentId) deletePayment(Number(deletePaymentId)).catch((e) => log(e.message));
  if (saveRuleId) savePricingRule(Number(saveRuleId)).catch((e) => log(e.message));
  if (createCaseAssetId) createDraftCaseAsset(Number(createCaseAssetId)).catch((e) => log(e.message));
  if (saveCaseAssetId) saveCaseAsset(Number(saveCaseAssetId)).catch((e) => log(e.message));
  if (deleteCaseAssetId) deleteCaseAsset(Number(deleteCaseAssetId)).catch((e) => log(e.message));
  if (editTemplateName) editTemplate(editTemplateName);
  if (deleteTemplateId) deleteTemplate(Number(deleteTemplateId)).catch((e) => log(e.message));
  if (saveRequirementId) saveRequirement(Number(saveRequirementId)).catch((e) => log(e.message));
  if (deleteRequirementId) deleteRequirement(Number(deleteRequirementId)).catch((e) => log(e.message));
  if (saveFinalCheckId) saveFinalCheck(Number(saveFinalCheckId)).catch((e) => log(e.message));
  if (saveRevisionId) saveRevisionTask(Number(saveRevisionId)).catch((e) => log(e.message));
  if (openRevisionDraftId !== undefined || revisionSection) openRevisionDraft(openRevisionDraftId, revisionSection).catch((e) => log(e.message));
  if (fillReplacementIndex) fillReplacement(Number(fillReplacementIndex));
  if (saveCommunicationId) saveCommunicationRecord(Number(saveCommunicationId)).catch((e) => log(e.message));
  if (deleteCommunicationId) deleteCommunication(Number(deleteCommunicationId)).catch((e) => log(e.message));
  if (previewSearchIndex) previewSearchSource(Number(previewSearchIndex)).catch((e) => log(e.message));
  if (previewCitationIndex) previewDraftCitation(Number(previewCitationIndex)).catch((e) => log(e.message));
  if (commandAction) executeCommandAction(commandAction, commandTarget).catch((e) => log(e.message));
  if (wizardAction) executeWizardAction(wizardAction, wizardTarget).catch((e) => log(e.message));
  if (wizardCopy) copyWizardText(wizardCopy).catch((e) => log(e.message));
  if (channelCopy) copyChannelScript(channelCopy).catch((e) => log(e.message));
  if (runKbOcr) runKbOcrItem(runKbOcr).catch((e) => log(e.message));
});

setWorkspaceMode("full", false);
window.addEventListener("hashchange", () => handleRoute().catch((e) => log(e.message)));
el("coreWorkspaceMode").addEventListener("click", () => setWorkspaceMode("core"));
el("fullWorkspaceMode").addEventListener("click", () => setWorkspaceMode("full"));
el("productionPrimaryAction").addEventListener("click", () => runProductionAction(state.productionAction).catch((e) => log(e.message)));
el("productionSecondaryAction").addEventListener("click", () => runProductionAction(state.productionSecondaryAction).catch((e) => log(e.message)));
el("refreshStatus").addEventListener("click", () => refreshStatus().catch((e) => log(e.message)));
el("refreshKbAudit").addEventListener("click", () => refreshKbAudit().catch((e) => log(e.message)));
el("refreshKbOcrQueue").addEventListener("click", () => refreshKbOcrQueue().catch((e) => log(e.message)));
el("refreshLlmStatus").addEventListener("click", () => refreshLlmStatus().catch((e) => log(e.message)));
el("probeLlm").addEventListener("click", () => probeLlm().catch((e) => log(e.message)));
el("refreshTenders").addEventListener("click", () => refreshTenders().catch((e) => log(e.message)));
el("refreshProcessingRecords").addEventListener("click", () => refreshProcessingRecords().catch((e) => log(e.message)));
el("refreshOrderDashboard").addEventListener("click", () => refreshOrderDashboard().catch((e) => log(e.message)));
el("refreshCommandCenter").addEventListener("click", () => refreshCommandCenter().catch((e) => log(e.message)));
el("commandRunPipeline").addEventListener("click", () => runProductionPipeline().catch((e) => log(e.message)));
el("refreshProductionStarter").addEventListener("click", () => refreshProductionStarter().catch((e) => log(e.message)));
el("copyStarterReply").addEventListener("click", () => copyStarterReply().catch((e) => log(e.message)));
el("refreshOrderWizard").addEventListener("click", () => refreshOrderWizard().catch((e) => log(e.message)));
el("wizardCreateIntake").addEventListener("click", () => createIntakeTender().catch((e) => log(e.message)));
el("wizardRunPipeline").addEventListener("click", () => runProductionPipeline().catch((e) => log(e.message)));
el("copyWizardText").addEventListener("click", () => copyWizardText().catch((e) => log(e.message)));
el("refreshChannelOps").addEventListener("click", () => refreshChannelOps().catch((e) => log(e.message)));
el("copyChannelScript").addEventListener("click", () => copyChannelScript().catch((e) => log(e.message)));
el("refreshProjectOverview").addEventListener("click", () => refreshProjectOverview().catch((e) => log(e.message)));
el("refreshProjectTimeline").addEventListener("click", () => refreshProjectTimeline().catch((e) => log(e.message)));
el("syncAllTaskStatus").addEventListener("click", () => syncAllTaskStatus().catch((e) => log(e.message)));
el("buildPlan").addEventListener("click", () => buildPlan().catch((e) => log(e.message)));
el("addPlanSection").addEventListener("click", () => addPlanSection().catch((e) => log(e.message)));
el("generateAllPlan").addEventListener("click", () => generateAllPlan().catch((e) => log(e.message)));
el("refreshPlanAudit").addEventListener("click", () => refreshPlanAudit().catch((e) => log(e.message)));
el("repairPlanAudit").addEventListener("click", () => repairPlanAudit().catch((e) => log(e.message)));
el("refreshCoverage").addEventListener("click", () => refreshCoverage().catch((e) => log(e.message)));
el("refreshPlan").addEventListener("click", () => refreshPlan().catch((e) => log(e.message)));
el("refreshWorkflow").addEventListener("click", () => refreshWorkflow().catch((e) => log(e.message)));
el("runProductionPipeline").addEventListener("click", () => runProductionPipeline().catch((e) => log(e.message)));
el("prepareClientDelivery").addEventListener("click", () => prepareClientDelivery().catch((e) => log(e.message)));
el("refreshProductionReadiness").addEventListener("click", () => refreshProductionReadiness().catch((e) => log(e.message)));
el("refreshQualityGate").addEventListener("click", () => refreshQualityGate().catch((e) => log(e.message)));
el("syncRevisionTasks").addEventListener("click", () => syncRevisionTasks().catch((e) => log(e.message)));
el("refreshRevisionTasks").addEventListener("click", () => refreshRevisionTasks().catch((e) => log(e.message)));
el("refreshSourceAudit").addEventListener("click", () => refreshSourceAudit().catch((e) => log(e.message)));
el("refreshDeliveryReview").addEventListener("click", () => refreshDeliveryReview().catch((e) => log(e.message)));
el("refreshDeliveryRelease").addEventListener("click", () => refreshDeliveryRelease().catch((e) => log(e.message)));
el("refreshFinalChecklist").addEventListener("click", () => refreshFinalChecklist().catch((e) => log(e.message)));
el("refreshFinalDocument").addEventListener("click", () => refreshFinalDocument().catch((e) => log(e.message)));
el("saveFinalDocument").addEventListener("click", () => saveFinalDocument().catch((e) => log(e.message)));
el("approveFinalDocument").addEventListener("click", () => saveFinalDocument("approved").catch((e) => log(e.message)));
el("copyFinalDocument").addEventListener("click", () => copyFinalDocument().catch((e) => log(e.message)));
el("saveTask").addEventListener("click", () => saveTask().catch((e) => log(e.message)));
el("syncTaskStatus").addEventListener("click", () => syncTaskStatus().catch((e) => log(e.message)));
el("refreshTask").addEventListener("click", () => refreshTask().catch((e) => log(e.message)));
el("saveDocumentSettings").addEventListener("click", () => saveDocumentSettings().catch((e) => log(e.message)));
el("refreshDocumentSettings").addEventListener("click", () => refreshDocumentSettings().catch((e) => log(e.message)));
el("saveEnterpriseProfile").addEventListener("click", () => saveEnterpriseProfile().catch((e) => log(e.message)));
el("refreshEnterpriseProfile").addEventListener("click", () => refreshEnterpriseProfile().catch((e) => log(e.message)));
el("generateBidStrategy").addEventListener("click", () => generateBidStrategy().catch((e) => log(e.message)));
el("saveBidStrategy").addEventListener("click", () => saveBidStrategy().catch((e) => log(e.message)));
el("refreshBidStrategy").addEventListener("click", () => refreshBidStrategy().catch((e) => log(e.message)));
el("createIntakeTender").addEventListener("click", () => createIntakeTender().catch((e) => log(e.message)));
el("buildIntakeAssistant").addEventListener("click", () => buildIntakeAssistant().catch((e) => log(e.message)));
el("applyIntakeTask").addEventListener("click", () => applyIntakeTask().catch((e) => log(e.message)));
el("copyIntakeReply").addEventListener("click", () => copyIntakeReply().catch((e) => log(e.message)));
el("refreshResponseMatrix").addEventListener("click", () => refreshResponseMatrix().catch((e) => log(e.message)));
el("autoLinkResponseMatrix").addEventListener("click", () => autoLinkResponseMatrix().catch((e) => log(e.message)));
el("suggestCommunication").addEventListener("click", () => suggestCommunication().catch((e) => log(e.message)));
el("saveCommunication").addEventListener("click", () => saveCommunication().catch((e) => log(e.message)));
el("copyCommunicationReply").addEventListener("click", () => copyCommunicationReply().catch((e) => log(e.message)));
el("refreshCommunications").addEventListener("click", () => refreshCommunications().catch((e) => log(e.message)));
el("buildPriceQuote").addEventListener("click", () => buildPriceQuote(false).catch((e) => log(e.message)));
el("savePriceQuote").addEventListener("click", () => buildPriceQuote(true).catch((e) => log(e.message)));
el("copyPriceQuote").addEventListener("click", () => copyPriceQuote().catch((e) => log(e.message)));
el("addPayment").addEventListener("click", () => addPayment().catch((e) => log(e.message)));
el("refreshPayments").addEventListener("click", () => refreshPayments().catch((e) => log(e.message)));
el("refreshPricingRules").addEventListener("click", () => refreshPricingRules().catch((e) => log(e.message)));
el("refreshCaseAssets").addEventListener("click", () => refreshCaseAssets().catch((e) => log(e.message)));
el("createTenderCaseAssets").addEventListener("click", () => createTenderCaseAssets().catch((e) => log(e.message)));
el("saveTemplate").addEventListener("click", () => saveTemplate().catch((e) => log(e.message)));
el("clearTemplateForm").addEventListener("click", () => clearTemplateForm());
el("refreshTemplateCoverage").addEventListener("click", () => refreshTemplateCoverage().catch((e) => log(e.message)));
el("uploadDocumentTemplate").addEventListener("click", () => uploadDocumentTemplate().catch((e) => log(e.message)));
el("refreshDocumentTemplates").addEventListener("click", () => refreshDocumentTemplates().catch((e) => log(e.message)));
el("addRequirement").addEventListener("click", () => addRequirement().catch((e) => log(e.message)));
el("reclassifyRequirements").addEventListener("click", () => reclassifyRequirements().catch((e) => log(e.message)));
el("refreshRequirements").addEventListener("click", () => refreshRequirements().catch((e) => log(e.message)));
el("buildOrderConfirmation").addEventListener("click", () => buildOrderConfirmation().catch((e) => log(e.message)));
el("copyOrderConfirmation").addEventListener("click", () => copyOrderConfirmation().catch((e) => log(e.message)));
el("refreshDeliveries").addEventListener("click", () => refreshDeliveries().catch((e) => log(e.message)));
el("refreshPackageValidation").addEventListener("click", () => refreshPackageValidation().catch((e) => log(e.message)));
el("refreshClientPackageValidation").addEventListener("click", () => refreshClientPackageValidation().catch((e) => log(e.message)));
el("refreshDeliveryReleaseForDelivery").addEventListener("click", () => refreshDeliveryRelease("deliveryReleasePanel").catch((e) => log(e.message)));
el("exportClientPackageForDelivery").addEventListener("click", () => exportTender("client_package").catch((e) => log(e.message)));
el("prepareClientDeliveryForDelivery").addEventListener("click", () => prepareClientDelivery().catch((e) => log(e.message)));
el("refreshDeliveryAssistant").addEventListener("click", () => refreshDeliveryAssistant().catch((e) => log(e.message)));
el("copyDeliveryMessage").addEventListener("click", () => copyDeliveryMessage().catch((e) => log(e.message)));
el("refreshClientDeliveryConfirmation").addEventListener("click", () => refreshClientDeliveryConfirmation().catch((e) => log(e.message)));
el("copyClientDeliveryMessage").addEventListener("click", () => copyClientDeliveryMessage().catch((e) => log(e.message)));
el("recordClientDeliveryConfirmation").addEventListener("click", () => recordClientDeliveryConfirmation().catch((e) => log(e.message)));
el("addFeedback").addEventListener("click", () => addFeedback().catch((e) => log(e.message)));
el("refreshFeedback").addEventListener("click", () => refreshFeedback().catch((e) => log(e.message)));
el("refreshFeedbackRework").addEventListener("click", () => refreshFeedbackRework().catch((e) => log(e.message)));
el("applyFeedbackRework").addEventListener("click", () => applyFeedbackRework().catch((e) => log(e.message)));
el("executeFeedbackRework").addEventListener("click", () => executeFeedbackRework().catch((e) => log(e.message)));
el("copyFeedbackReworkMessage").addEventListener("click", () => copyFeedbackReworkMessage().catch((e) => log(e.message)));
el("buildClosureConfirmation").addEventListener("click", () => buildClosureConfirmation().catch((e) => log(e.message)));
el("copyClosureMessage").addEventListener("click", () => copyClosureMessage().catch((e) => log(e.message)));
el("recordClosure").addEventListener("click", () => recordClosure().catch((e) => log(e.message)));
el("refreshRetrospectiveDashboard").addEventListener("click", () => refreshRetrospectiveDashboard().catch((e) => log(e.message)));
el("refreshProjectRetrospective").addEventListener("click", () => refreshProjectRetrospective().catch((e) => log(e.message)));
el("saveProjectRetrospective").addEventListener("click", () => saveProjectRetrospective().catch((e) => log(e.message)));
el("saveProfile").addEventListener("click", () => saveProfile().catch((e) => log(e.message)));
el("refreshProfile").addEventListener("click", () => refreshProfile().catch((e) => log(e.message)));
el("addMaterial").addEventListener("click", () => addMaterial().catch((e) => log(e.message)));
el("refreshMaterials").addEventListener("click", () => refreshMaterials().catch((e) => log(e.message)));
el("generateDocumentBlocks").addEventListener("click", () => generateRichDocument().catch((e) => log(e.message)));
el("buildVisualPlan").addEventListener("click", () => buildVisualPlan().catch((e) => log(e.message)));
el("generateHybridVisual").addEventListener("click", () => generateHybridVisual().catch((e) => log(e.message)));
el("visualSceneKey").addEventListener("change", (event) => {
  const option = event.target.selectedOptions?.[0];
  if (option?.dataset.section) el("visualHybridSection").value = option.dataset.section;
});
el("refreshDocumentBlocks").addEventListener("click", () => refreshRichDocument().catch((e) => log(e.message)));
el("autoValidateVisuals").addEventListener("click", () => autoValidateVisualAssets().catch((e) => log(e.message)));
el("approveSelectedVisuals").addEventListener("click", () => batchReviewVisualAssets("已通过").catch((e) => log(e.message)));
el("rejectSelectedVisuals").addEventListener("click", () => batchReviewVisualAssets("需修改").catch((e) => log(e.message)));
el("importVisualAsset").addEventListener("click", () => importVisualAsset().catch((e) => log(e.message)));
el("importSample").addEventListener("click", () => importKb(100).catch((e) => log(e.message)));
el("importAll").addEventListener("click", () => importKb(null).catch((e) => log(e.message)));
el("searchButton").addEventListener("click", () => search().catch((e) => log(e.message)));
el("createTender").addEventListener("click", () => createTender().catch((e) => log(e.message)));
el("uploadTender").addEventListener("click", () => uploadTender().catch((e) => log(e.message)));
el("updateTenderSource").addEventListener("click", () => updateTenderSource().catch((e) => log(e.message)));
el("uploadTenderSource").addEventListener("click", () => uploadTenderSource().catch((e) => log(e.message)));
el("generateDraft").addEventListener("click", () => generateDraft().catch((e) => log(e.message)));
el("saveDraft").addEventListener("click", () => saveDraft().catch((e) => log(e.message)));
el("scanPolish").addEventListener("click", () => scanPolish().catch((e) => log(e.message)));
el("previewReplacement").addEventListener("click", () => previewReplacement().catch((e) => log(e.message)));
el("applyReplacement").addEventListener("click", () => applyReplacement().catch((e) => log(e.message)));
el("refreshReplacements").addEventListener("click", () => refreshReplacementRecords().catch((e) => log(e.message)));
el("reviewTender").addEventListener("click", () => reviewTender().catch((e) => log(e.message)));
el("exportMarkdown").addEventListener("click", () => exportTender("markdown").catch((e) => log(e.message)));
el("exportDocx").addEventListener("click", () => exportTender("docx").catch((e) => log(e.message)));
el("exportPackage").addEventListener("click", () => exportTender("package").catch((e) => log(e.message)));
el("exportClientPackage").addEventListener("click", () => exportTender("client_package").catch((e) => log(e.message)));
el("refreshAcceptance").addEventListener("click", () => refreshAcceptance().catch((e) => log(e.message)));
el("runDocxPreflight").addEventListener("click", () => runDocxPreflight().catch((e) => log(e.message)));
el("runAcceptance").addEventListener("click", () => runAcceptance().catch((e) => log(e.message)));

renderWorkflow(null);
renderKbAudit(null);
renderKbOcrQueue(null);
renderCommandCenter(null);
renderProductionStarter(null);
renderOrderWizard(null);
renderChannelOps(null);
renderOrderDashboard(null);
renderProjectOverview(null);
renderProjectTimeline(null);
renderResponseMatrix(null);
renderPlanAudit(null);
renderDocumentSettings(null);
renderEnterpriseProfile(null);
renderBidStrategy(null);
renderLlmStatus(null);
renderTemplateCoverage(null);
renderTemplateAssets(null);
renderDocumentTemplates([]);
renderProcessingRecords([]);
renderSourcePreview(null);
renderIntakeAssistant(null);
renderCommunicationSuggestion(null);
renderCommunications([]);
renderPriceQuote(null);
renderPayments(null);
renderPricingRules([]);
renderCaseAssets([]);
renderOrderConfirmation(null);
renderClosureConfirmation(null);
renderRetrospectiveDashboard(null);
renderProjectRetrospective(null);
renderProductionPipeline(null);
renderClientDeliveryPreparation(null);
renderProductionReadiness(null);
renderQualityGate(null);
renderRevisionTasks(null);
renderSourceAudit(null);
renderFinalChecklist(null);
renderFinalDocument(null);
renderPolish(null);
renderReplacementPreview(null);
renderReplacementRecords([]);
renderMaterials([]);
renderRichDocument([], []);
renderAcceptance(null);
renderPackageValidation(null);
renderClientPackageValidation(null);
renderClientDeliveryConfirmation(null);
renderFeedbackRework(null);
updateProjectContext(null);
handleRoute().catch((e) => log(e.message));
Promise.all([
  refreshStatus(),
  refreshKbAudit().catch(() => {}),
  refreshKbOcrQueue().catch(() => {}),
  refreshLlmStatus(),
  refreshEnterpriseProfile(),
  refreshTenders(),
  refreshProcessingRecords(),
  refreshOrderDashboard(),
  refreshRetrospectiveDashboard(),
  refreshPricingRules(),
  refreshTemplates(),
  refreshTemplateCoverage(),
  refreshTemplateAssets(),
  refreshDocumentTemplates(),
]).catch((e) => log(e.message));
