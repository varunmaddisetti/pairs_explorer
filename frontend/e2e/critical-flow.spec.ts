import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test("open demo → choose pair → explanation → change as-of → reveal → backtest → export card", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  // 1. open demo: synthetic labels are prominent
  await page.goto("/");
  await expect(page.getByTestId("mode-badge").first()).toHaveText("SYNTHETIC DEMO");
  await expect(page.getByTestId("source-strip")).toContainText("All prices are generated");
  await expect(page.getByTestId("scanner-table")).toBeVisible();
  const eligibleTab = page.getByTestId("tab-eligible");
  await expect(eligibleTab).toContainText(/Eligible \(\d\)/);

  // 2. choose a pair from the scanner
  await page.getByTestId("row-S_BANK_A/S_BANK_B").click();
  await expect(page).toHaveURL(/view=pair&a=S_BANK_A&b=S_BANK_B/);
  await expect(page.getByTestId("pair-title")).toHaveText("S_BANK_A / S_BANK_B");

  // 3. explanation is factual and labelled
  const expl = page.getByTestId("explanation");
  await expect(expl).toContainText("SYNTHETIC DEMO");
  await expect(expl).toContainText("Engle-Granger test (null: no cointegration)");
  await expect(expl).toContainText("not a probability of profit");
  await expect(page.getByTestId("labels")).toContainText("Relationship evidence");
  const latestAsOf = (await page.getByTestId("pair-asof").textContent())!;

  // 4. change the as-of date in playback: statistics refit at that date, future hidden
  await page.getByTestId("nav-playback").click();
  await expect(page).toHaveURL(/view=playback/);
  await page.getByTestId("asof-input").fill("2023-06-30");
  await expect(page.getByTestId("playback-asof")).toHaveText("2023-06-30");
  await expect(page).toHaveURL(/asof=2023-06-30/);
  await expect(page.getByTestId("explanation")).toContainText("to 2023-06-30");
  await expect(page.getByTestId("playback-scanner")).toContainText("Scanner as of 2023-06-30");
  expect(latestAsOf).not.toBe("2023-06-30");
  await expect(page.getByTestId("reveal-panel")).toHaveCount(0);
  await page.getByTestId("reveal-button").click();
  const reveal = page.getByTestId("reveal-panel");
  await expect(reveal).toContainText("FUTURE OUTCOME");
  await expect(reveal).toContainText("sessions available");
  // moving the as-of date hides the future again
  await page.getByRole("button", { name: "Move -5 sessions" }).click();
  await expect(page.getByTestId("reveal-panel")).toHaveCount(0);
  await expect(page.getByTestId("playback-asof")).toHaveText("2023-06-23");

  // 5. run a backtest with defaults, then an exploratory variant
  await page.getByTestId("nav-backtest").click();
  const label = page.getByTestId("result-label");
  await expect(label).toContainText("HYPOTHETICAL SIMULATION ON SYNTHETIC DATA");
  await expect(label).toContainText("pre-specified defaults");
  await expect(page.getByTestId("bt-trades")).not.toContainText("n/a");
  await expect(page.getByTestId("segments")).toContainText("Final holdout");
  await page.getByTestId("param-slippage_bps").fill("30");
  await page.getByTestId("run-backtest").click();
  await expect(label).toContainText("exploratory (non-default parameters: slippage_bps)");
  await expect(page).toHaveURL(/p_slippage_bps=30/);

  // 6. export the research card from the pair page and check it is a labelled PNG
  await page.getByTestId("nav-pair").click();
  await expect(page.getByTestId("pair-title")).toBeVisible();
  const [dl] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-card").click()]);
  expect(dl.suggestedFilename()).toMatch(/^pde_card_S_BANK_A_S_BANK_B_\d{4}-\d{2}-\d{2}_synthetic_demo\.png$/);
  const path = info.outputPath("card.png");
  await dl.saveAs(path);
  const buf = readFileSync(path);
  expect(buf.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  expect(buf.length).toBeGreaterThan(30_000);

  expect(errors).toEqual([]);
});

test("no horizontal page overflow and legible labels", async ({ page }) => {
  for (const path of ["/", "/?view=pair&a=S_IT_A&b=S_IT_B", "/?view=playback&a=S_BREAK_A&b=S_BREAK_B&asof=2024-04-09&reveal=1",
    "/?view=backtest&a=S_BANK_A&b=S_BANK_B", "/?view=method"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, path).toBeLessThanOrEqual(1);
    await expect(page.getByTestId("mode-badge").first()).toBeVisible();
  }
  await page.goto("/?view=method");
  await expect(page.getByTestId("status-PUBLIC_DISPLAY_PERMITTED")).toHaveText("no");
  await expect(page.getByTestId("status-SYNTHETIC_DEMO")).toHaveText("yes");
});
