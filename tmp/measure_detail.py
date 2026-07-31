# 测量人才库右侧详情面板：各 section 高度 + 溢出量
import json
import sys
from playwright.sync_api import sync_playwright

CHROME = r"C:\Users\zexin\AppData\Local\ms-playwright\chromium_headless_shell-1223\chrome-headless-shell-win64\chrome-headless-shell.exe"
BASE = "http://127.0.0.1:8600"
WIDTH = int(sys.argv[1]) if len(sys.argv) > 1 else 1440
HEIGHT = int(sys.argv[2]) if len(sys.argv) > 2 else 900

JS = r"""
() => {
  // 详情卡 = 第三个 grid 列里的 md3-card
  const cards = [...document.querySelectorAll('.grid > .md3-card')];
  const detail = cards[cards.length - 1];
  if (!detail) return { error: 'no detail card' };
  const scroller = detail.querySelector('.overflow-y-auto');
  const sections = [...(scroller ? scroller.children : [])].map((el) => ({
    tag: el.tagName,
    title: (el.querySelector('h3')?.textContent || el.getAttribute('class') || '').slice(0, 30),
    height: Math.round(el.getBoundingClientRect().height),
  }));
  const parts = [...detail.children].map((el) => ({
    cls: (el.getAttribute('class') || '').slice(0, 40),
    height: Math.round(el.getBoundingClientRect().height),
  }));
  return {
    cardHeight: Math.round(detail.getBoundingClientRect().height),
    parts,
    scrollerClient: scroller ? scroller.clientHeight : 0,
    scrollerScroll: scroller ? scroller.scrollHeight : 0,
    overflow: scroller ? scroller.scrollHeight - scroller.clientHeight : 0,
    sections,
  };
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT})
    assert ctx.request.post(f"{BASE}/api/auth/login", data={"password": "neko-dev-test"}).ok
    page = ctx.new_page()
    page.goto(f"{BASE}/talent-pool", wait_until="networkidle")
    page.wait_for_timeout(800)
    page.locator("div[role=button]").first.click()
    page.wait_for_timeout(1000)
    print(json.dumps(page.evaluate(JS), ensure_ascii=False, indent=1))
    browser.close()
