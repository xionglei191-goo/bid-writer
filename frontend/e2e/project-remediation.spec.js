import { expect, test } from "@playwright/test";

async function setup(page, options = {}) {
  const state = { requests: [], review: [], mapping: [], repair: [], claims: [], responses: [], confirmations: [] };
  const requirement = (id, category, content) => ({ id, requirement_key: `R00${id}`, content, kind: "parameter", priority: "high", source_page: id + 2, requirement_fingerprint: `requirement-${id}`, planning_category: category, formal_technical: category === "technical", section_ids: id === 1 ? [11] : [], classification: { suggested_category: category, suggestion_reason: `${content}对应${category}范围，需人工核对`, suggestion_excerpt: `原文：${content}`, status: "pending", category: "", applicability: "applicable", response_status: "pending" } });
  state.project = { id: 41, name: "修复与原文核验验收项目", industry: "建筑", project_type: "技术标", region: "郑州", status: "draft", source_text: "工期180天。须提供资质证照。", profile: {},
    evidence_source: { current_project_source_hash: "source-one", stale_draft_ids: options.staleSource ? [20] : [], profile_conflicts: [] },
    requirements: [requirement(1, "technical", "施工总工期180天"), requirement(2, "qualification", "须提供有效资质证照"), requirement(3, "commercial", "报价应按清单填报"), requirement(4, "contract", "履约保证金按合同缴纳"), requirement(5, "reference", "项目背景介绍"), requirement(6, "unclassified", "未能判定适用范围")],
    sections: [{ id: 11, order_no: 1, title: "施工进度计划", requirement_ids: [1], status: "drafted", draft: { id: 20, content: "# 施工进度计划\n施工总工期180天。各工序严格衔接并每周检查进度。\n本章后续内容生成失败。", content_hash: "draft-one", status: "draft", confirmations: [], confirmation_resolutions: [], citations: [], evidence_status: "unsupported", generation: { status: "incomplete", can_repair: true, parts: [{ index: 0, status: "ai", requirement_ids: [1], missing_requirement_ids: [] }, { index: 1, status: "failed", requirement_ids: [], missing_requirement_ids: [] }] }, claims: [{ id: 70, text: "施工总工期180天。", risk_level: "high", support_status: "unsupported", source_stale: Boolean(options.staleSource), source_stale_reason: options.staleSource ? "项目原文已变化" : "", project_source_hash: "source-one", evidence: [{ id: 80, source_kind: "project_tender", source_title: "本项目招标文件", file_name: "招标文件.pdf", source_page: 3, source_excerpt: "施工总工期180天。", match_reason: "对象和工期数值一致", score: 0.93 }, { id: 81, source_kind: "knowledge_publication", source_title: "知识库进度参考", file_name: "历史案例.pdf", source_page: 12, source_excerpt: "编制总进度计划。", source_meta: { match_reason: "仅提供组织方法参考" }, score: 0.8 }] }] } }, { id: 12, order_no: 2, title: "质量管理", requirement_ids: [], status: "drafted", draft: { id: 21, content: "已完成且必须保留的质量正文", content_hash: "good-draft", status: "draft", confirmations: [], confirmation_resolutions: [], citations: [], claims: [], evidence_status: "supported", generation: { status: "ai", can_repair: false, parts: [] } } }],
  };
  if (options.confirmationIndices) {
    state.project.sections[0].draft.confirmations = ["AI编写失败，请补写", "项目经理人选需要实际资料", "高风险表述缺少充分证据：工期180天"];
    state.project.sections[0].draft.confirmation_required_indices = [1];
    state.project.sections[0].draft.generation = { status: "ai", can_repair: false, parts: [] };
    state.project.sections[0].draft.claims[0].support_status = "supported";
  }
  if (options.missingResponse) {
    state.project.sections[0].draft.generation = { status: "manual_edit", can_repair: false, parts: [] };
    state.project.sections[0].draft.claims[0].support_status = "supported";
    state.project.sections[0].draft.missing_response_requirement_ids = [1];
  }
  if (options.repairBlocked) {
    state.project.sections[0].draft.generation.can_repair = false;
    state.project.sections[0].draft.generation.repair_blocked = true;
    state.project.sections[0].draft.generation.repair_blocked_reason = "人工响应跨越原分段，已停用局部补写以保留正文片段，请继续人工处理。";
  }
  const workflow = () => ({ project_id: 41, project_hash: "project-one", source_hash: "source-one", items: state.project.requirements, metrics: {}, blockers: [] });
  const workbench = () => ({ project_id: 41, metrics: { mapped: 1, responded: 1, signed: 0, total: 6, technical_total: 1 }, tasks: [{ id: "generation-11", kind: "generation", title: "施工进度计划存在生成失败部分", detail: "第2部分生成失败，可仅补写本部分。", section_id: 11, draft_id: 20, action: "repair" }, { id: "evidence-70", kind: "evidence", title: "工期参数待核验", detail: "请核对原文件第3页工期依据。", section_id: 11, claim_id: 70, action: "review_claim" }, { id: "information-2", kind: "information", title: "补充真实资格证照", detail: "资质证照尚未登记响应。", requirement_id: 2, source_page: 4, action: "information" }] });
  await page.context().route("**/api/**", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname; const method = request.method();
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (method !== "GET") state.requests.push({ path, method, body: request.postDataJSON() });
    if (path === "/api/auth/config") return json({ enabled: false });
    if (path === "/api/status") return json({ version: "2.0.0", llm: { configured: false } });
    if (path === "/api/projects/41") return json(state.project);
    if (path.endsWith("/requirements/workflow")) return json(workflow());
    if (path.endsWith("/requirements/review")) {
      const body = request.postDataJSON(); state.review.push(body);
      if (options.staleRequirement) return json({ detail: "条款原文已变化，请重新载入后确认。" }, 409);
      for (const item of body.items) { const record = state.project.requirements.find((r) => r.id === item.requirement_id); Object.assign(record.classification, { category: item.category, reviewer: body.reviewer, status: "confirmed", review_reason: item.reason, response_text: item.response_text, basis_text: item.basis_text }); }
      return json(workflow());
    }
    if (path.endsWith("/requirements/1/mapping")) { state.mapping.push(request.postDataJSON()); state.project.requirements[0].section_ids = request.postDataJSON().section_ids; return json(workflow()); }
    if (path.endsWith("/requirements/1/response")) { state.responses.push(request.postDataJSON()); return json(workflow()); }
    if (path.endsWith("/workbench")) return json(workbench());
    if (path.endsWith("/sections/11/repair")) {
      state.repair.push(request.postDataJSON());
      state.project.sections[0].draft.generation = { status: "ai", can_repair: false, parts: [] };
      return json({ id: 91, job_type: "production.repair_section", status: "pending" });
    }
    if (path.endsWith("/sections/11/generate")) { state.project.sections[0].draft.generation.status = "fallback"; return json({ id: 92, job_type: "production.generate_section", status: "pending" }); }
    if (path.endsWith("/evidence/recheck")) return json({ id: 93, job_type: "production.recheck_evidence", status: "pending" });
    if (path.startsWith("/api/jobs/")) return json({ id: Number(path.split("/").at(-1)), job_type: "production.fixture", status: "completed", progress: 100, result: {} });
    if (path === "/api/projects/claims/70/resolve") { state.claims.push(request.postDataJSON()); state.project.sections[0].draft.claims[0].support_status = "confirmed"; return json({ status: "confirmed" }); }
    if (path === "/api/projects/drafts/20/confirm") { state.confirmations.push(request.postDataJSON()); return json({ status: "reviewed" }); }
    throw new Error(`Unexpected fixture API: ${method} ${path}`);
  });
  await page.goto("/#/projects/41");
  await expect(page.getByRole("heading", { name: state.project.name })).toBeVisible();
  return state;
}

test("six scope filters preserve drafts and require actual reviewer for classification and mapping", async ({ page }) => {
  const state = await setup(page); await page.getByRole("button", { name: "招标解析", exact: true }).click();
  for (const label of ["技术要求", "资格资料", "商务条款", "合同条款", "参考信息", "待分类"]) await expect(page.getByRole("button", { name: new RegExp(`^${label}\\s*1$`) })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新解析", exact: true })).toBeDisabled();
  await expect(page.getByLabel("本次条款复核人")).toHaveValue("");
  await expect(page.getByRole("button", { name: "保存本条人工复核" })).toBeDisabled();
  await expect(page.getByText("原文：施工总工期180天", { exact: true })).toBeVisible();
  await page.getByLabel("本次条款复核人").fill("张工");
  await page.getByLabel("第 2 章 · 质量管理").check();
  await page.getByRole("button", { name: "保存章节映射" }).click();
  await expect.poll(() => state.mapping.length).toBe(1);
  expect(state.mapping[0]).toEqual({ reviewer: "张工", expected_fingerprint: "requirement-1", section_ids: [11, 12] });
  expect(state.project.sections[1].draft.content).toBe("已完成且必须保留的质量正文");
  await page.getByRole("button", { name: /^资格资料\s*1$/ }).click();
  await expect(page.getByLabel("本次条款复核人")).toHaveValue("");
  await page.getByLabel("本次条款复核人").fill("李工");
  await page.getByLabel("分类核对理由").fill("原文要求提交资质证照，属于资格资料");
  await page.getByLabel("实际响应或资料说明").fill("已核对投标单位资质证照，附件2");
  await page.getByLabel("资料出处或不适用依据").fill("资质证书扫描件第1页，有效期已核对");
  await page.getByRole("button", { name: "保存本条人工复核" }).click();
  await expect.poll(() => state.review.length).toBe(1);
  expect(state.review[0]).toMatchObject({ reviewer: "李工", expected_project_hash: "project-one", items: [{ requirement_id: 2, expected_fingerprint: "requirement-2", category: "qualification", applicability: "applicable", response_text: "已核对投标单位资质证照，附件2", basis_text: "资质证书扫描件第1页，有效期已核对" }] });
  expect(state.requests.some((request) => request.path.includes("generate") || request.path.endsWith("/confirm"))).toBe(false);
});

test("stale classification is rejected visibly and offers reload instead of automatic approval", async ({ page }) => {
  const state = await setup(page, { staleRequirement: true }); await page.getByRole("button", { name: "招标解析", exact: true }).click();
  await page.getByLabel("本次条款复核人").fill("张工"); await page.getByLabel("分类核对理由").fill("已核对工期参数");
  await page.getByRole("button", { name: "保存本条人工复核" }).click();
  await expect(page.getByText("条款原文已变化，请重新载入后确认。", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新载入条款" })).toBeVisible();
  expect(state.review).toHaveLength(1);
  expect(state.project.requirements[0].classification.status).toBe("pending");
});

test("manual response binding sends the selected current draft and exact evidence without regenerating", async ({ page }) => {
  const state = await setup(page); await page.getByRole("button", { name: "招标解析", exact: true }).click();
  await expect(page.getByRole("button", { name: "记录正文响应片段" })).toBeDisabled();
  await page.getByLabel("本次条款复核人").fill("赵工");
  await page.getByLabel("回应本条的正文原句").fill("施工总工期180天。各工序严格衔接并每周检查进度。");
  await page.getByRole("button", { name: "记录正文响应片段" }).click();
  await expect.poll(() => state.responses.length).toBe(1);
  expect(state.responses[0]).toEqual({ draft_id: 20, reviewer: "赵工", target_hash: "draft-one", requirement_fingerprint: "requirement-1", evidence_text: "施工总工期180天。各工序严格衔接并每周检查进度。" });
  expect(state.requests).toHaveLength(1);
  expect(state.project.sections[1].draft.content).toBe("已完成且必须保留的质量正文");
});

test("repair posts only failed section with current hash, preserves good chapters and rechecks evidence separately", async ({ page }) => {
  const state = await setup(page); await page.getByRole("button", { name: "处理待办", exact: true }).click();
  await expect(page.getByText("已映射技术条款", { exact: true })).toBeVisible();
  await expect(page.getByText("已回应技术条款", { exact: true })).toBeVisible();
  await expect(page.locator(".coverage-metrics .metric").nth(2)).toContainText("0/1");
  await expect(page.locator(".remediation-list article")).toHaveCount(3);
  await page.getByRole("button", { name: "仅补写失败部分", exact: true }).click();
  await expect.poll(() => state.repair.length).toBe(1);
  await expect(page.getByText("本章已生成 AI 草稿。正文、原文依据和实际资料仍需逐项核验，尚未自动签审。", { exact: true })).toBeVisible();
  expect(state.repair).toEqual([{ background: true, target_hash: "draft-one" }]);
  expect(state.project.sections[1].draft.content).toBe("已完成且必须保留的质量正文");
  await page.getByRole("button", { name: "重新核对原文证据", exact: true }).click();
  await expect(page.getByText("当前原文证据已重新检查，请处理仍缺依据或资料的事项。此操作不会替代人工签审。", { exact: true })).toBeVisible();
  expect(state.requests.map((request) => request.path)).toEqual(["/api/projects/41/sections/11/repair", "/api/projects/41/evidence/recheck"]);
  await page.getByRole("button", { name: "打开条款与资料", exact: true }).click();
  await expect(page.locator(".requirement-detail")).toContainText("须提供有效资质证照");
});

test("evidence shows separate source origins and requires an explicit identity plus both current hashes", async ({ page }) => {
  const state = await setup(page); await page.getByRole("button", { name: "章节编制", exact: true }).click();
  await expect(page.getByText("本项目招标原文", { exact: true })).toBeVisible();
  await expect(page.getByText("知识库参考来源", { exact: true })).toBeVisible();
  await expect(page.getByText("匹配原因：对象和工期数值一致", { exact: true })).toBeVisible();
  await expect(page.getByText("检索匹配度 93%（辅助定位）", { exact: true })).toBeVisible();
  await expect(page.getByLabel("本次证据核验人")).toHaveValue("");
  await expect(page.getByRole("button", { name: "确认本条依据", exact: true })).toBeDisabled();
  await page.getByLabel("本次证据核验人").fill("王工"); await page.getByLabel("核验依据与结论").fill("已核对招标文件第3页，工期180天一致");
  await page.getByRole("button", { name: "确认本条依据", exact: true }).click();
  await expect.poll(() => state.claims.length).toBe(1);
  expect(state.claims[0]).toEqual({ action: "confirm", resolution: "已核对招标文件第3页，工期180天一致", reviewer: "王工", target_hash: "draft-one", project_source_hash: "source-one" });
  await page.getByRole("button", { name: "重试本章", exact: true }).click();
  await expect(page.getByText("本章未取得完整 AI 结果，当前为回退草稿，请处理失败部分后核对正文。", { exact: true })).toBeVisible();
  await expect(page.getByText("章节草稿已生成，关键表述与来源证据已经建立。", { exact: true })).toHaveCount(0);
});

test("mobile scope, workbench and evidence fit 390px and stale source blocks confirmation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page, { staleSource: true });
  for (const [tab, shot] of [["招标解析", "requirements-mobile.png"], ["处理待办", "remediation-mobile.png"], ["章节编制", "evidence-mobile.png"]]) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await expect(page.locator(tab === "招标解析" ? ".requirement-detail" : tab === "处理待办" ? ".remediation-list" : ".evidence-panel")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: test.info().outputPath(shot), fullPage: true });
  }
  await page.getByLabel("本次证据核验人").fill("王工"); await page.getByLabel("核验依据与结论").fill("尚需核对新版原文");
  await expect(page.getByRole("button", { name: "确认本条依据", exact: true })).toBeDisabled();
  await page.getByLabel("本章签审人").fill("王工"); await expect(page.getByRole("button", { name: "签审本章", exact: true })).toBeDisabled();
});

test("chapter confirmation asks only real information items and preserves their original indices", async ({ page }) => {
  const state = await setup(page, { confirmationIndices: true }); await page.getByRole("button", { name: "章节编制", exact: true }).click();
  await expect(page.locator(".confirmation-panel textarea")).toHaveCount(1);
  await expect(page.locator(".confirmation-panel")).toContainText("项目经理人选需要实际资料");
  await expect(page.locator(".confirmation-panel")).not.toContainText("高风险表述缺少充分证据");
  await expect(page.locator(".confirmation-panel")).not.toContainText("AI编写失败");
  await page.getByLabel("本章签审人").fill("黄工");
  await page.locator(".confirmation-panel textarea").fill("已核对实际项目经理任命文件及资格证照");
  await page.getByRole("button", { name: "签审本章", exact: true }).click();
  await expect.poll(() => state.confirmations.length).toBe(1);
  expect(state.confirmations[0].resolutions).toEqual([{ index: 1, resolution: "已核对实际项目经理任命文件及资格证照" }]);
});

test("manually edited chapter still requires missing response binding before signoff", async ({ page }) => {
  await setup(page, { missingResponse: true }); await page.getByRole("button", { name: "章节编制", exact: true }).click();
  await expect(page.getByText("人工修改后，待核验。生成草稿不会自动认定证据成立或完成签审。", { exact: true })).toBeVisible();
  await page.getByLabel("本章签审人").fill("王工"); await expect(page.getByRole("button", { name: "签审本章", exact: true })).toBeDisabled();
  await page.locator(".response-gaps summary").click();
  await page.getByRole("button", { name: /R001 · 定位正文响应/ }).click();
  await expect(page.getByLabel("回应本条的正文原句")).toBeVisible();
  await expect(page.locator(".requirement-detail")).toContainText("施工总工期180天");
});

test("manual response preservation explains why repair is blocked and opens the current editor", async ({ page }) => {
  const state = await setup(page, { repairBlocked: true }); await page.getByRole("button", { name: "章节编制", exact: true }).click();
  await expect(page.getByText("人工响应跨越原分段，已停用局部补写以保留正文片段，请继续人工处理。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重试本章", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "继续人工补写", exact: true }).click();
  await expect(page.getByLabel("本章正文")).toBeFocused();
  await page.getByRole("button", { name: "处理待办", exact: true }).click();
  await expect(page.getByRole("button", { name: "仅补写失败部分", exact: true })).toHaveCount(0);
  await expect(page.locator('[data-task-id="generation-11"]')).toContainText("人工响应跨越原分段");
  expect(state.requests).toHaveLength(0);
});
