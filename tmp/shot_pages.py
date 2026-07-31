# 截图：人才库详情面板 + 完整档案页
import sys
from playwright.sync_api import sync_playwright

CHROME = r"C:\Users\zexin\AppData\Local\ms-playwright\chromium_headless_shell-1223\chrome-headless-shell-win64\chrome-headless-shell.exe"
BASE = "http://127.0.0.1:8600"
WIDTH = int(sys.argv[1]) if len(sys.argv) > 1 else 1440
HEIGHT = int(sys.argv[2]) if len(sys.argv) > 2 else 900
TAG = sys.argv[3] if len(sys.argv) > 3 else "x"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
    assert ctx.request.post(f"{BASE}/api/auth/login", data={"password": "neko-dev-test"}).ok
    page = ctx.new_page()
    page.goto(f"{BASE}/talent-pool", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.locator("div[role=button]").first.click()
    page.wait_for_timeout(1000)
    page.screenshot(path=f"tmp/detail_{TAG}.png", full_page=False)
    # 进完整档案页
    page.get_by_text("查看完整档案").click()
    page.wait_for_timeout(1500)
    page.screenshot(path=f"tmp/profile_{TAG}.png", full_page=False)
    # 档案页页面级溢出检查
    res = page.evaluate("() => ({vw: document.documentElement.clientWidth, sw: document.documentElement.scrollWidth})")
    print(res)
    browser.close()
