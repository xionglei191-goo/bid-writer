import { expect, test } from "@playwright/test";

// Opt in only against the isolated acceptance service. This test never writes project data.
const projectId = process.env.BID_WRITER_E2E_PROJECT_ID;
test("isolated project exposes real classification, workbench and evidence without mutation", async ({ page, request, baseURL }) => {
  test.skip(!projectId, "Set BID_WRITER_E2E_PROJECT_ID for isolated acceptance data.");
  test.setTimeout(120_000);
  expect(new URL(baseURL).hostname).toBe("127.0.0.1");
  expect(["8877", "5174"]).toContain(new URL(baseURL).port);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", (route) => {
    if (route.request().method() === "GET") return route.continue();
    errors.push(`Unexpected mutation: ${route.request().method()} ${route.request().url()}`);
    return route.abort();
  });
  const [projectResponse, workflowResponse, workbenchResponse] = await Promise.all([
    request.get(`/api/projects/${projectId}`), request.get(`/api/projects/${projectId}/requirements/workflow`), request.get(`/api/projects/${projectId}/workbench`),
  ]);
  for (const response of [projectResponse, workflowResponse, workbenchResponse]) expect(response.ok()).toBe(true);
  const [project, workflow, workbench] = await Promise.all([projectResponse.json(), workflowResponse.json(), workbenchResponse.json()]);
  expect(workflow.items).toHaveLength(project.requirements.length);
  expect(workbench.metrics.total).toBe(project.requirements.length);
  expect(workbench.metrics.signed).toBeLessThanOrEqual(workbench.metrics.responded);
  expect(workbench.metrics.responded).toBeLessThanOrEqual(workbench.metrics.technical_total);
  await page.goto(`/#/projects/${projectId}`);
  await expect(page.getByRole("heading", { name: project.name, exact: true })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "招标解析", exact: true }).click();
  await expect(page.locator(".requirement-detail")).toBeVisible();
  await expect(page.getByLabel("本次条款复核人")).toHaveValue("");
  await expect(page.getByRole("button", { name: "保存本条人工复核", exact: true })).toBeDisabled();
  await expect(page.locator(".requirement-selector > button")).toHaveCount(workflow.items.length);
  await page.screenshot({ path: test.info().outputPath("live-requirements-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const renderedWorkbench = page.waitForResponse((response) => new URL(response.url()).pathname === `/api/projects/${projectId}/workbench`);
  await page.getByRole("button", { name: "处理待办", exact: true }).click();
  const currentWorkbench = await (await renderedWorkbench).json();
  await expect(page.locator(".coverage-metrics .metric").first()).toContainText(`${currentWorkbench.metrics.mapped}/${currentWorkbench.metrics.technical_total}`);
  await expect(page.locator(".remediation-list article")).toHaveCount(currentWorkbench.tasks.length);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.locator(".remediation-panel").scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath("live-workbench-mobile.png"), fullPage: false });
  await page.getByRole("button", { name: "章节编制", exact: true }).click();
  await expect(page.locator(".editor-main")).toBeVisible();
  if (project.sections[0]?.draft) {
    await expect(page.getByLabel("本章签审人")).toHaveValue("");
    await expect(page.getByRole("button", { name: "签审本章", exact: true }).or(page.getByRole("button", { name: "重新签审", exact: true }))).toBeDisabled();
  }
  const missingSection = project.sections.find((section) => section.draft?.missing_response_requirement_ids?.length);
  if (missingSection) {
    await page.locator(".chapter-list > button").filter({ has: page.locator("strong", { hasText: missingSection.title }) }).click();
    await expect(page.locator(".response-gaps summary")).toHaveText(`${missingSection.draft.missing_response_requirement_ids.length} 条要求尚未定位正文响应`);
    await expect(page.getByRole("button", { name: "签审本章", exact: true }).or(page.getByRole("button", { name: "重新签审", exact: true }))).toBeDisabled();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: test.info().outputPath("live-evidence-mobile.png"), fullPage: true });
  expect(errors).toEqual([]);
  await test.info().attach("real-response-summary", { contentType: "application/json", body: JSON.stringify({ project_id: project.id, requirements: workflow.items.length, scopes: workflow.metrics.counts, metrics: currentWorkbench.metrics, tasks: currentWorkbench.tasks.length, stale_drafts: project.evidence_source?.stale_draft_ids?.length, missing_response_items: project.sections.reduce((sum, section) => sum + (section.draft?.missing_response_requirement_ids?.length || 0), 0) }, null, 2) });
});
