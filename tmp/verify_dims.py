# 复测：维度分显示（weighted/max）人才库面板 + 简历评估页
from playwright.sync_api import sync_playwright

CHROME = r"C:\Users\zexin\AppData\Local\ms-playwright\chromium_headless_shell-1223\chrome-headless-shell-win64\chrome-headless-shell.exe"
BASE = "http://127.0.0.1:8600"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    assert ctx.request.post(f"{BASE}/api/auth/login", data={"password": "neko-dev-test"}).ok
    page = ctx.new_page()
    # 人才库右侧面板
    page.goto(f"{BASE}/talent-pool", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.locator("div[role=button]").first.click()
    page.wait_for_timeout(1000)
    page.screenshot(path="tmp/verify_pool_dim.png", full_page=False)
    # 简历评估页维度列表
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_timeout(800)
    row = page.locator("div[role=button]").first
    if row.count():
        row.click()
        page.wait_for_timeout(1200)
    page.screenshot(path="tmp/verify_resume_dim.png", full_page=False)
    browser.close()
print("done")
