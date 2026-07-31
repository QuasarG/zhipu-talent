# 人才库三栏溢出测量：找出实际撑宽节点
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
    docClientWidth: document.documentElement.clientWidth,
    docScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    offenders: [],
  };
  const seen = new Set();
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0) continue;
    const overRight = Math.round(r.right - vw);
    const overScroll = el.scrollWidth - el.clientWidth;
    if (overRight > 1 || overScroll > 1) {
      // 只保留最深的违规节点，避免父子重复刷屏
      let deepest = true;
      for (const child of el.children) {
        const cr = child.getBoundingClientRect();
        if (Math.round(cr.right - vw) > 1 || child.scrollWidth - child.clientWidth > 1) { deepest = false; break; }
      }
      const cls = (el.getAttribute('class') || '').slice(0, 160);
      const key = el.tagName + '|' + cls;
      if (seen.has(key)) continue;
      seen.add(key);
      report.offenders.push({
        tag: el.tagName, cls,
        clientWidth: el.clientWidth, scrollWidth: el.scrollWidth,
        rectLeft: Math.round(r.left), rectRight: Math.round(r.right),
        overRight, overScroll, deepest,
      });
    }
  }
  return report;
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
    resp = ctx.request.post(f"{BASE}/api/auth/login", data={"password": "neko-dev-test"})
    assert resp.ok, f"login failed: {resp.status}"
    page = ctx.new_page()
    page.goto(f"{BASE}/talent-pool", wait_until="networkidle")
    page.wait_for_timeout(1500)
    result = page.evaluate(JS)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    page.screenshot(path="tmp/pool_measure.png", full_page=False)
    browser.close()
