import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function workspace(page, options = {}) {
  const state = {
    saved: [], exports: [], confirmations: [], draftConfirmations: [], deliveries: [], jobs: {},
    finalized: false,
    project: {
      id: 41, name: "医院门诊楼技术标", industry: "医院", project_type: "房屋建筑", region: "郑州", status: "draft", updated_at: "2026-09-08 08:00:00", source_text: "施工工期180天。",
      profile: { duration: "180天", custom_business_value: "保留原值", compliance_confirmed: true, manual_finalized: true, final_approved: true },
      requirements: [{ id: 1, requirement_key: "R001", content: "工期180天", status: "confirmed", kind: "parameter", priority: "high", source_page: 3 }],
      sections: [{ id: 11, order_no: 1, title: "施工组织", requirement_ids: [1], status: "drafted", draft: { id: 20, content: "# 施工组织\n项目工期为180天。", content_hash: "draft-one", confirmations: [], confirmation_resolutions: [], citations: [], claims: [], evidence_status: "supported", status: "draft" } }],
    },
  };
  if (options.noDraft) state.project.sections[0].draft = null;
  const quality = () => ({
    ready: state.finalized, review_ready: !options.reviewBlocked, formal_ready: state.finalized,
    score: state.finalized ? 100 : 52, review_score: 100,
    metrics: { drafts: 1, sections: 1, coverage: 100, unreviewed_drafts: 0, claims: { support_rate: 100, high_unsupported: options.reviewBlocked ? 1 : 0 } },
    review_blockers: options.reviewBlocked ? [{ key: "unsupported_high_claims", title: "高风险表述缺少证据", detail: "共1项" }] : [],
    formal_blockers: state.finalized ? [] : [{ key: "bidder_identity", title: "缺少真实投标单位", detail: "正式版必须登记真实投标单位" }, { key: "manual_finalization", title: "人工定稿未完成", detail: "请完成整本复核" }],
    warnings: [],
  });
  const preview = () => ({ project_id: 41, project_hash: "project-version-one", markdown: "# 医院门诊楼技术标\n\n## 施工组织\n项目工期为180天。", confirmation: { valid: state.finalized, professional_reviewer: state.confirmations.at(-1)?.professional_reviewer, confirmed_at: "2026-09-08 09:00:00" } });
  await page.context().route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/config") return json({ enabled: false });
    if (path === "/api/status") return json({ version: "2.0.0", llm: { configured: false } });
    if (path === "/api/projects/41" && method === "GET") return json(state.project);
    if (path === "/api/projects/41" && method === "PATCH") {
      const body = request.postDataJSON(); state.saved.push(body);
      state.project = { ...state.project, ...body, profile: { ...state.project.profile, ...body.profile }, updated_at: "2026-09-08 08:01:00" };
      return json(state.project);
    }
    if (path === "/api/projects/41/quality") return json(quality());
    if (path === "/api/projects/41/workbench") return json({ project_id: 41, metrics: { mapped: 1, responded: 1, signed: state.finalized ? 1 : 0, total: 1, technical_total: 1 }, tasks: [] });
    if (path === "/api/projects/41/requirements/workflow") return json({ project_id: 41, project_hash: "project-version-one", source_hash: "source-one", items: state.project.requirements.map((item) => ({ ...item, requirement_fingerprint: "requirement-one", planning_category: "technical", classification: { suggested_category: "technical", suggestion_reason: "包含工期参数", status: "pending" }, section_ids: [11] })), metrics: {}, blockers: [] });
    if (path === "/api/projects/41/deliveries") return json(state.deliveries);
    if (path === "/api/projects/41/preview") return json(preview());
    if (path === "/api/projects/41/final-review") {
      const body = request.postDataJSON(); state.confirmations.push(body);
      if (options.stalePreview) return json({ detail: "项目版本已变化，请重新预览整本内容后再确认。" }, 409);
      state.finalized = true; return json(preview());
    }
    if (path === "/api/projects/drafts/20/confirm") { state.draftConfirmations.push(request.postDataJSON()); return json({ status: "reviewed" }); }
    if (path === "/api/projects/41/export") {
      const body = request.postDataJSON(); state.exports.push(body);
      const result = { delivery_id: state.exports.length, mode: body.mode, format: body.format, file_name: `医院门诊楼_${body.mode}.${body.format}`, download_url: `/api/projects/41/deliveries/${state.exports.length}/download`, available: true, current: true, created_at: "2026-09-08 09:00:00" };
      state.jobs[90] = () => { state.deliveries = [result]; return result; };
      return json({ id: 90, job_type: "production.export", status: "pending" });
    }
    if (/\/api\/projects\/41\/deliveries\/\d+\/download$/.test(path)) return route.fulfill({ status: 200, headers: { "Content-Type": "application/octet-stream", "Content-Disposition": "attachment; filename=review-fixture.docx" }, body: "isolated delivery fixture" });
    if (path === "/api/projects/41/requirements/parse") {
      state.jobs[91] = () => { state.project.requirements[0].content = "异步解析完成：工期180天"; return { parsed: 1 }; };
      return json({ id: 91, job_type: "production.parse_requirements", status: "pending" });
    }
    if (path === "/api/projects/41/outline") {
      state.jobs[92] = () => { state.project.sections[0].title = "异步目录完成"; return { built: 1 }; };
      return json({ id: 92, job_type: "production.build_outline", status: "pending" });
    }
    if (path.startsWith("/api/jobs/")) {
      const id = Number(path.split("/").at(-1));
      return json({ id, job_type: "production.fixture", status: "completed", progress: 100, result: state.jobs[id]() });
    }
    throw new Error(`Unexpected fixture API: ${method} ${path}`);
  });
  await page.goto("/#/projects/41");
  await expect(page.getByRole("heading", { name: "医院门诊楼技术标" })).toBeVisible();
  return state;
}

async function qualityPage(page) { await page.getByRole("button", { name: "质量交付", exact: true }).click(); }

test("business details save without replaying old signoff flags", async ({ page }) => {
  const state = await workspace(page);
  await page.getByLabel("真实投标单位", { exact: true }).fill("河南建设工程有限公司");
  await page.getByLabel("专业复核人", { exact: true }).fill("王工");
  await page.getByLabel("授权签字人", { exact: true }).fill("李工");
  await page.getByLabel("交付期限", { exact: true }).fill("2026-09-30 18:00");
  await page.getByLabel("签字盖章要求").fill("封面按招标要求签字盖章");
  await page.getByRole("button", { name: "保存资料" }).click();
  await expect.poll(() => state.saved.length).toBe(1);
  expect(state.saved[0].profile).toMatchObject({ bidder_name: "河南建设工程有限公司", professional_reviewer: "王工", authorized_signatory: "李工", delivery_deadline: "2026-09-30 18:00" });
  for (const key of ["compliance_confirmed", "manual_finalized", "final_approved", "custom_business_value"]) expect(state.saved[0].profile).not.toHaveProperty(key);
  expect(state.project.profile.custom_business_value).toBe("保留原值");
});

test("review export passes explicit mode, waits for completion and exposes actual download", async ({ page }) => {
  const state = await workspace(page); await qualityPage(page);
  await expect(page.getByRole("button", { name: "正式Word", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "送审Word", exact: true }).click();
  await expect(page.getByText("本次导出：送审版", { exact: true })).toBeVisible();
  expect(state.exports).toEqual([{ format: "docx", mode: "review", background: true }]);
  const downloadEvent = page.waitForEvent("download");
  await page.locator(".delivery-latest").getByRole("link").click();
  const download = await downloadEvent;
  expect(await readFile(await download.path(), "utf8")).toBe("isolated delivery fixture");
  await expect(page.getByRole("link", { name: "下载此版本" })).toHaveAttribute("href", "/api/projects/41/deliveries/1/download");
  expect(state.confirmations).toHaveLength(0);
  await page.screenshot({ path: test.info().outputPath("quality-desktop.png"), fullPage: true });
});

test("formal signoff requires preview, actual reviewer and both explicit acknowledgments", async ({ page }) => {
  const state = await workspace(page); await qualityPage(page);
  await page.getByRole("button", { name: "打开当前整本预览" }).click();
  await expect(page.getByLabel("整本正文", { exact: true })).toContainText("项目工期为180天");
  const submit = page.getByRole("button", { name: "确认合规并完成定稿" });
  await expect(page.getByLabel("本次整本复核人")).toHaveValue("");
  await expect(page.getByRole("checkbox").first()).not.toBeChecked();
  await expect(page.getByRole("checkbox").last()).not.toBeChecked();
  await expect(submit).toBeDisabled();
  await page.getByLabel("本次整本复核人").fill("陈工");
  await page.getByRole("checkbox").first().check();
  await expect(submit).toBeDisabled();
  await page.getByRole("checkbox").last().check();
  await submit.click();
  await expect(page.getByRole("button", { name: "正式Word", exact: true })).toBeEnabled();
  expect(state.confirmations).toEqual([{ project_hash: "project-version-one", professional_reviewer: "陈工", compliance_confirmed: true, manual_finalized: true }]);
  await expect(page.getByRole("checkbox").first()).not.toBeChecked();
  await page.getByRole("button", { name: "正式Word", exact: true }).click();
  await expect(page.getByText("本次导出：正式版", { exact: true })).toBeVisible();
  expect(state.exports[0].mode).toBe("formal");
});

test("stale preview rejection stays blocked and requires fresh preview", async ({ page }) => {
  const state = await workspace(page, { stalePreview: true }); await qualityPage(page);
  await page.getByRole("button", { name: "打开当前整本预览" }).click();
  await page.getByLabel("本次整本复核人").fill("陈工");
  await page.getByRole("checkbox").first().check(); await page.getByRole("checkbox").last().check();
  await page.getByRole("button", { name: "确认合规并完成定稿" }).click();
  await expect(page.getByText("项目版本已变化，请重新预览整本内容后再确认。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "正式Word", exact: true })).toBeDisabled();
  expect(state.finalized).toBe(false);
  await page.getByRole("button", { name: "打开当前整本预览" }).click();
  await expect(page.getByLabel("本次整本复核人")).toHaveValue("");
  await expect(page.getByRole("checkbox").first()).not.toBeChecked();
});

test("missing evidence prevents every export and finalization at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await workspace(page, { reviewBlocked: true }); await qualityPage(page);
  for (const name of ["送审Word", "送审PDF", "送审交付包", "正式Word", "正式PDF", "正式交付包"]) await expect(page.getByRole("button", { name, exact: true })).toBeDisabled();
  await expect(page.getByText("高风险表述缺少证据", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "打开当前整本预览" }).click();
  await page.getByLabel("本次整本复核人").fill("陈工");
  await page.getByRole("checkbox").first().check(); await page.getByRole("checkbox").last().check();
  await expect(page.getByRole("button", { name: "确认合规并完成定稿" })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: test.info().outputPath("quality-mobile.png"), fullPage: true });
});

test("chapter signoff binds current content and existing drafts lock preparation", async ({ page }) => {
  const state = await workspace(page);
  await page.getByRole("button", { name: "章节编制", exact: true }).click();
  await expect(page.getByLabel("本章签审人")).toHaveValue("");
  await expect(page.getByRole("button", { name: "签审本章", exact: true })).toBeDisabled();
  expect(state.draftConfirmations).toHaveLength(0);
  await page.getByLabel("本章签审人").fill("赵工");
  await page.getByRole("button", { name: "签审本章", exact: true }).click();
  await expect.poll(() => state.draftConfirmations.length).toBe(1);
  expect(state.draftConfirmations[0]).toEqual({ reviewer: "赵工", target_hash: "draft-one", resolutions: [] });
  await page.getByRole("button", { name: "招标解析", exact: true }).click();
  await expect(page.getByRole("button", { name: "重新解析", exact: true })).toBeDisabled();
  await expect(page.getByText("参数要求", { exact: true })).toBeVisible();
  await expect(page.getByText("原文件第 3 页", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "目录策略", exact: true }).click();
  await expect(page.getByRole("button", { name: "生成目录", exact: true })).toBeDisabled();
  await expect(page.getByText("已有章节正文，目录重建已锁定，保留当前草稿和签审记录。", { exact: true })).toBeVisible();
});

test("preparation without drafts waits for the asynchronous result", async ({ page }) => {
  await workspace(page, { noDraft: true });
  await page.getByRole("button", { name: "招标解析", exact: true }).click();
  await page.getByRole("button", { name: "重新解析", exact: true }).click();
  await expect(page.locator(".requirement-detail > p").first()).toHaveText("异步解析完成：工期180天");
  await page.getByRole("button", { name: "目录策略", exact: true }).click();
  await page.getByRole("button", { name: "生成目录", exact: true }).click();
  await expect(page.getByText("异步目录完成", { exact: true })).toBeVisible();
});
