import { expect, test } from "@playwright/test";

const username = process.env.BID_WRITER_E2E_USERNAME;
const password = process.env.BID_WRITER_E2E_PASSWORD;

test.beforeEach(async ({ page }) => {
  test.skip(!username || !password, "Set BID_WRITER_E2E_USERNAME and BID_WRITER_E2E_PASSWORD");
  await page.goto("/#/settings");
  await page.getByLabel("账号").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "运行环境" })).toBeVisible();
});

test("admin can inspect the private deployment runtime", async ({ page }) => {
  const me = await page.request.get("/api/auth/me");
  expect(me.ok()).toBeTruthy();
  expect((await me.json()).user.roles).toContain("admin");
  const runtime = await (await page.request.get("/api/status")).json();
  await expect(page.getByText(runtime.llm.operational ? "模型可用" : runtime.llm.configured ? "模型需检查" : "模型未配置", { exact: true })).toBeVisible();
  if (runtime.llm.last_error_code) await expect(page.getByText(runtime.llm.last_error_code, { exact: true })).toBeVisible();
  await expect(page.locator(".definition-list strong").filter({ hasText: /^postgresql$/ }).first()).toBeVisible();
  await expect(page.locator(".definition-list strong").filter({ hasText: /^minio$/ }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "后台任务" })).toBeVisible();
  await expect(page.getByText("retrieval.rebuild", { exact: true }).first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Traceback");
});

test("settings remain usable at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("heading", { name: "运行环境" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("retrieval evaluation workspace exposes automated review and metrics", async ({ page }) => {
  await page.goto("/#/knowledge/evaluation");
  await expect(page.getByRole("button", { name: "AI 独立复核" })).toBeVisible();
  await expect(page.getByRole("button", { name: "运行白银评测" })).toBeVisible();
  await expect(page.getByRole("option", { name: /live-20260809-v2/ })).toBeAttached();
  await expect(page.getByText("困难负样本拒绝", { exact: true })).toBeVisible();
  await expect(page.getByText("负样本提升", { exact: true })).toBeVisible();
});

test("retrieval evaluation workspace remains usable at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/knowledge/evaluation");
  await expect(page.getByRole("button", { name: "AI 独立复核" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
