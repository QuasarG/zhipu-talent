# 全链路复测：手动加人 → 类型筛选/track 子选 → 面板排版
from playwright.sync_api import sync_playwright

CHROME = r"C:\Users\zexin\AppData\Local\ms-playwright\chromium_headless_shell-1223\chrome-headless-shell-win64\chrome-headless-shell.exe"
BASE = "http://127.0.0.1:8600"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    assert ctx.request.post(f"{BASE}/api/auth/login", data={"password": "neko-dev-test"}).ok
    page = ctx.new_page()

    # 1. 人才知识页：手动加入人才库
    page.goto(f"{BASE}/knowledge", wait_until="networkidle")
    page.wait_for_timeout(600)
    page.fill("input[placeholder='姓名（必填）']", "测试嘉宾")
    page.fill("input[placeholder='学校 / 机构']", "测试大学")
    page.fill("input[placeholder='研究方向']", "编译器")
    page.get_by_role("button", name="加入人才库").click()
    page.wait_for_timeout(1200)
    page.screenshot(path="tmp/v_knowledge_add.png", full_page=False)

    # 2. 人才库：人物调查筛选应显示新人
    page.goto(f"{BASE}/talent-pool", wait_until="networkidle")
    page.wait_for_timeout(1000)
    page.get_by_role("button", name="人物调查 1").click()
    page.wait_for_timeout(800)
    page.screenshot(path="tmp/v_pool_guest.png", full_page=False)
    guest_visible = page.locator("text=测试嘉宾").count()
    print("guest in pool:", guest_visible)

    # 3. 简历评估筛选 → track 子选出现
    page.get_by_role("button", name="简历评估 1").click()
    page.wait_for_timeout(600)
    track_chips = page.locator("button:has-text('Safety')").count()
    print("track chips under resume:", track_chips)
    page.screenshot(path="tmp/v_pool_resume.png", full_page=False)

    # 4. 选中人才看详情面板排版
    page.locator("div[role=button]").first.click()
    page.wait_for_timeout(1000)
    page.screenshot(path="tmp/v_pool_detail.png", full_page=False)

    # 5. 页面级溢出
    res = page.evaluate("() => ({vw: document.documentElement.clientWidth, sw: document.documentElement.scrollWidth})")
    print(res)
    browser.close()
print("done")
