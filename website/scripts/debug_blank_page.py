#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


URL = "http://127.0.0.1:8080/"
OUT_DIR = Path(__file__).resolve().parents[1] / "tmp_debug"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shot = OUT_DIR / "blank_page_debug.png"
    report = OUT_DIR / "blank_page_report.json"

    console_msgs: list[dict] = []
    page_errors: list[str] = []
    req_failed: list[dict] = []
    req_bad: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        def on_console(msg):
            console_msgs.append({"type": msg.type, "text": msg.text})

        def on_page_error(err):
            page_errors.append(str(err))

        def on_req_failed(req):
            failure = req.failure
            if isinstance(failure, dict):
                err_text = failure.get("errorText", "unknown")
            elif isinstance(failure, str):
                err_text = failure
            else:
                err_text = "unknown"
            req_failed.append(
                {
                    "url": req.url,
                    "method": req.method,
                    "error": err_text,
                }
            )

        def on_response(resp):
            if resp.status >= 400:
                req_bad.append({"url": resp.url, "status": resp.status})

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("requestfailed", on_req_failed)
        page.on("response", on_response)

        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)

        page.screenshot(path=str(shot), full_page=True)

        body_text = page.inner_text("body")
        body_html = page.content()

        browser.close()

    summary = {
        "url": URL,
        "screenshot": str(shot),
        "body_text_len": len(body_text.strip()),
        "body_html_len": len(body_html),
        "console": console_msgs,
        "page_errors": page_errors,
        "request_failed": req_failed,
        "request_http_4xx_5xx": req_bad,
    }

    report.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
