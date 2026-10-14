"""Run against a started API + built UI + export worker. Uses local demo mode."""

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--exports", action="store_true")
    args = parser.parse_args()
    output = Path("artifacts/browser")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda exc: failures.append(str(exc)))
        page.goto(args.url)
        page.evaluate("document.fonts.ready")
        page.get_by_label("用户名").fill("demo")
        page.get_by_label("密码", exact=True).fill(os.environ.get("ERP_EVAL_PASSWORD", "erp-demo-2026"))
        page.get_by_role("button", name="进入工作台").click()
        expect(page.get_by_role("heading", name="今天，想了解哪些销售数据？")).to_be_visible()
        page.screenshot(path=str(output / "welcome.png"))
        question = page.get_by_role("textbox", name="输入分析问题")
        question.fill("2026 年 9 月华东地区销售额最高的 5 个客户")
        page.get_by_role("button", name="开始分析").click()
        expect(page.locator(".result-card")).to_have_count(1, timeout=15000)
        expect(page.locator(".result-card .chart svg")).to_be_visible()
        expect(page.locator(".result-card tbody tr")).to_have_count(5)
        page.wait_for_function("performance.getEntriesByName('erp-query-complete').length === 1")
        page.screenshot(path=str(output / "query.png"))
        question.fill("只看华北地区")
        question.press("Enter")
        expect(page.locator(".result-card")).to_have_count(2, timeout=15000)
        page.locator(".result-card").last.get_by_label("图表类型").select_option("table")
        expect(page.locator(".result-card").last.locator(".chart")).to_have_count(0)
        if args.exports:
            for format, label in [("docx", "↓ Word"), ("pdf", "↓ PDF")]:
                with page.expect_download(timeout=180000) as download:
                    page.locator(".result-card").first.get_by_role("button", name=label).click()
                download.value.save_as(output / f"report.{format}")
        timing = page.evaluate("performance.getEntriesByName('erp-query-complete').map(e => e.duration)")
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "mobile.png"))
        assert page.evaluate("document.body.scrollWidth <= window.innerWidth"), "mobile overflow"
        assert not failures, failures
        (output / "smoke.json").write_text(
            json.dumps(
                {
                    "mode": "demo",
                    "browser_complete_ms": timing,
                    "page_errors": failures,
                    "formal_acceptance": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()
        print("Browser flow passed; artifacts/browser contains screenshots and measured demo timings.")


if __name__ == "__main__":
    main()
