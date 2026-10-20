/* Dedicated headless browser checks; does not attach to the user's browser. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const runtime = path.join(process.env.USERPROFILE, ".cache", "codex-runtimes",
  "codex-primary-runtime", "dependencies", "node", "node_modules", "playwright");
const { chromium } = require(runtime);
const root = path.resolve(__dirname, "..");
const output = path.join(root, "tmp", "workbench-ui");
const assets = path.join(root, "docs", "assets", "workbench");
const url = process.argv[2] || "http://127.0.0.1:8501";

async function main() {
  fs.mkdirSync(output, { recursive: true });
  fs.mkdirSync(assets, { recursive: true });
  const browser = await chromium.launch({
    executablePath: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    headless: true,
  });
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  const checks = [];
  async function screenshot(name, target = page) {
    await target.screenshot({ path: path.join(output, name), fullPage: true });
    fs.copyFileSync(path.join(output, name), path.join(assets, name));
  }
  async function navigate(name, target = page) {
    await target.getByTestId("stSidebar").getByText(name, { exact: true }).click();
    await target.getByRole("heading", { name, exact: true }).waitFor();
  }
  async function downloadRecord() {
    await page.getByRole("tab", { name: "配置与导出", exact: true }).click();
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: "下载本次实验", exact: true }).click();
    const download = await pending;
    const destination = path.join(output, download.suggestedFilename());
    await download.saveAs(destination);
    return JSON.parse(fs.readFileSync(destination, "utf8"));
  }
  try {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { name: "主体反馈实验", exact: true }).waitFor();
    await page.getByTestId("stVegaLiteChart").first().waitFor();
    await screenshot("agents-desktop.png");
    const charts = await page.getByTestId("stVegaLiteChart").evaluateAll(nodes => nodes.map(node => {
      const box = node.getBoundingClientRect();
      const marks = node.querySelectorAll("svg path, svg rect, svg line, svg text");
      return { width: box.width, height: box.height, svg_marks: marks.length };
    }));
    assert.ok(charts.filter(chart => chart.width > 0 && chart.height > 0 && chart.svg_marks > 10).length >= 4,
      "Expected four rendered vector charts");
    checks.push({ name: "desktop_charts_nonblank", charts });

    await page.getByRole("spinbutton", { name: "碳价路径系数", exact: true }).fill("0");
    await page.getByRole("button", { name: "运行主体实验", exact: true }).click();
    await page.getByText("结果所用参数：碳价 0", { exact: false }).waitFor();
    const record = await downloadRecord();
    assert.equal(record.mode, "synthetic");
    assert.equal(record.parameters.carbon_multiplier, 0);
    assert.ok(record.configuration.policy.carbon_price_by_step.every(value => value === 0));
    assert.ok(record.implementation_sha256["src/energy_model/workbench.py"]);
    checks.push({ name: "submitted_parameter_and_actual_download", run_id: record.run_id });

    await screenshot("export-desktop.png");
    await navigate("连续储能实验");
    assert.equal(await page.getByRole("tab", { name: "运行轨迹", exact: true }).getAttribute("aria-selected"), "true");
    await page.getByTestId("stVegaLiteChart").first().waitFor();
    await screenshot("operations-desktop.png");
    checks.push({ name: "operation_navigation_and_chart" });
    const defaults = await downloadRecord();
    assert.equal(defaults.summaries.with_storage.unserved_mwh, 0);
    assert.ok(Math.abs(defaults.summaries.without_storage.unserved_mwh - 18.7) < 1e-8);
    await page.getByRole("tab", { name: "能量账本", exact: true }).click();
    assert.ok(await page.getByText("电力发电＋SOC初", { exact: false }).isVisible());
    checks.push({ name: "operation_default_export_and_ledger", run_id: defaults.run_id });
    await page.getByRole("spinbutton", { name: "储能容量 MWh", exact: true }).fill("0");
    await page.getByRole("button", { name: "运行储能对照", exact: true }).click();
    await page.getByText("结果所用参数：容量 0 MWh", { exact: false }).waitFor();
    const zero = await downloadRecord();
    assert.deepEqual(zero.cases.with_storage.rows, zero.cases.without_storage.rows);
    checks.push({ name: "zero_storage_actual_download" });
    await page.getByRole("button", { name: "恢复默认", exact: true }).click();
    await page.getByText("结果所用参数：容量 40 MWh", { exact: false }).waitFor();

    await navigate("主体反馈实验");
    assert.equal(await page.getByRole("spinbutton", { name: "碳价路径系数", exact: true }).inputValue(), "0.00");
    await page.getByRole("tab", { name: "系统轨迹", exact: true }).click();
    // Streamlit's select is a combobox implemented with a listbox popup.
    await page.getByRole("combobox", { name: "展示机制", exact: true }).click();
    await page.getByRole("option", { name: "冻结设备替代", exact: true }).click();
    const metric = record.summaries.frozen_equipment.unserved_service_su.toLocaleString("en-US", {
      minimumFractionDigits: 3, maximumFractionDigits: 3,
    });
    await page.getByTestId("stMetricValue").first().getByText(metric, { exact: true }).waitFor();
    await page.getByRole("tab", { name: "主体决策", exact: true }).click();
    await page.getByText("冻结设备替代 · 信息截止步", { exact: false }).waitFor();
    await screenshot("decisions-desktop.png");
    checks.push({ name: "navigation_persistence_and_mechanism_consistency" });
    await page.getByRole("button", { name: "恢复默认", exact: true }).click();
    await navigate("官方数据与进度");
    await page.getByText("准入仅限各自用途。", { exact: false }).waitFor();
    await screenshot("evidence-desktop.png");
    await page.getByRole("button", { name: "重新核对", exact: true }).click();
    await page.getByText("准入仅限各自用途。", { exact: false }).waitFor();
    await page.getByRole("tab", { name: "来源与范围", exact: true }).click();
    assert.ok(await page.getByText("文件路径：", { exact: false }).isVisible());
    const sourceLinks = await page.getByRole("link", { name: /^官方来源 / }).evaluateAll(
      nodes => nodes.map(node => node.href));
    assert.ok(sourceLinks.length > 0 && sourceLinks.every(href => /^https?:\/\//.test(href)));
    await screenshot("source-desktop.png");
    await page.getByRole("tab", { name: "目标进度", exact: true }).click();
    assert.ok(await page.getByText("运行界面与程序测试不代表科研验收", { exact: false }).isVisible());
    checks.push({ name: "evidence_live_check" });

    const mobileContext = await browser.newContext({
      viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    });
    const mobile = await mobileContext.newPage();
    mobile.on("pageerror", error => errors.push(error.message));
    await mobile.goto(url, { waitUntil: "domcontentloaded" });
    await mobile.getByRole("heading", { name: "主体反馈实验", exact: true }).waitFor();
    await mobile.getByTestId("stVegaLiteChart").first().waitFor();
    await screenshot("agents-mobile.png", mobile);
    const dimensions = await mobile.evaluate(() => ({
      viewport: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      sidebarRight: document.querySelector('[data-testid="stSidebar"]')?.getBoundingClientRect().right ?? 0,
    }));
    assert.ok(dimensions.scrollWidth <= dimensions.viewport + 2, "Unexpected page horizontal overflow");
    assert.ok(dimensions.sidebarRight <= 2, "Mobile sidebar must not cover the research view");
    checks.push({ name: "mobile_no_page_overflow", dimensions });
    await mobile.getByRole("button", { name: "Expand sidebar", exact: true }).click();
    await navigate("连续储能实验", mobile);
    await mobile.getByRole("button", { name: "Collapse sidebar", exact: true }).click();
    await mobile.waitForFunction(() =>
      document.querySelector('[data-testid="stSidebar"]').getBoundingClientRect().right <= 2);
    const afterNavigation = await mobile.evaluate(() => ({
      viewport: window.innerWidth, scrollWidth: document.documentElement.scrollWidth,
    }));
    assert.ok(afterNavigation.scrollWidth <= afterNavigation.viewport + 2);
    await screenshot("operations-mobile.png", mobile);
    assert.ok(await mobile.getByRole("heading", { name: "连续储能实验", exact: true }).isVisible());
    checks.push({ name: "mobile_navigation_opens_and_switches" });
    assert.equal(await mobile.getByTestId("stException").count(), 0);
    assert.equal(await page.getByTestId("stException").count(), 0);
    assert.deepEqual(errors, []);
    const result = { checked_at: new Date().toISOString(), url, checks, page_errors: errors,
      screenshot_directory: output };
    fs.writeFileSync(path.join(output, "browser-checks.json"), JSON.stringify(result, null, 2) + "\n");
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    await page.screenshot({ path: path.join(output, "browser-failure.png"), fullPage: true });
    console.error("Rendered chart inventory:", await page.locator("[data-testid]").evaluateAll(
      nodes => [...new Set(nodes.map(node => node.dataset.testid).filter(id => /chart|vega/i.test(id)))]
    ));
    throw error;
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
