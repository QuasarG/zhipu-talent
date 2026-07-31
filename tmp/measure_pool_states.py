# 人才库三栏溢出测量：列表详情视图 + 选中人才详情
import json
import sys
from playwright.sync_api import sync_playwright

CHROME = r"C:\Users\zexin\AppData\Local\ms-playwright\chromium_headless_shell-1223\chrome-headless-shell-win64\chrome-headless-shell.exe"
BASE = "http://127.0.0.1:8600"
WIDTH = int(sys.argv[1]) if len(sys.argv) > 1 else 1440
HEIGHT = int(sys.argv[2]) if len(sys.argv) > 2 else 900

JS = r"""
() => {
  const vw = document.documentElement.clientWidth;
  const report = {
    viewport: vw,
    docScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    offenders: [],
  };
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0) continue;
    const overRight = Math.round(r.right - vw);
    const overScroll = el.scrollWidth - el.clientWidth;
    if (overRight > 1 || overScroll > 4) {
      report.offenders.push({
        tag: el.tagName,
        cls: (el.getAttribute('class') || '').slice(0, 140),
        clientWidth: el.clientWidth, scrollWidth: el.scrollWidth,
        rectRight: Math.round(r.right), overRight, overScroll,
      });
    }
  }
  return report;
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
    assert ctx.request.post(f"{BASE}/api/auth/login", data={"password": "neko-dev-test"}).ok
    page = ctx.new_page()
    page.goto(f"{BASE}/talent-pool", wait_until="networkidle")
    page.wait_for_timeout(800)
    # 选中第一位人才，展开右侧详情栏
    row = page.locator("div[role=button]").first
    if row.count():
        row.click()
        page.wait_for_timeout(800)
    # 切到列表详情视图
    page.get_by_text("列表详情").click()
    page.wait_for_timeout(800)
    print("== 列表详情视图 ==")
    print(json.dumps(page.evaluate(JS), ensure_ascii=False, indent=1))
    page.screenshot(path="tmp/pool_list_view.png", full_page=False)
    # 切回关系图谱再测一次（带详情选中态）
    page.get_by_text("关系图谱").click()
    page.wait_for_timeout(800)
    print("== 关系图谱视图（已选中人才） ==")
    print(json.dumps(page.evaluate(JS), ensure_ascii=False, indent=1))
    page.screenshot(path="tmp/pool_graph_selected.png", full_page=False)
    browser.close()
