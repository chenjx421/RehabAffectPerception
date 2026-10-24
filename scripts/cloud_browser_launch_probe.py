"""Private cloud-only browser launch probe; prints no page data or credentials."""
from playwright.sync_api import sync_playwright

EXECUTABLE = "/opt/rehabaffect-browser/official-cft-156/chrome-headless-shell-linux64/chrome-headless-shell"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        executable_path=EXECUTABLE,
        args=["--disable-background-networking", "--disable-component-update", "--no-proxy-server"],
    )
    try:
        page = browser.new_page()
        response = page.goto("http://127.0.0.1:8793/demo2/login", wait_until="domcontentloaded")
        print({"status": response.status if response else None, "path": "/demo2/login"})
    finally:
        browser.close()
