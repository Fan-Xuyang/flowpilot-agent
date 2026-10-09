import os
from pathlib import Path
from playwright.async_api import async_playwright


class BrowserSession:
    def __init__(self):
        self.manager = None

    async def __aenter__(self):
        self.manager = await async_playwright().start()
        executable = os.getenv("BROWSER_EXECUTABLE")
        if not executable and not Path(self.manager.chromium.executable_path).exists():
            cache = (
                Path(os.getenv("LOCALAPPDATA", str(Path.home() / ".cache")))
                / "ms-playwright"
            )
            candidates = list(cache.glob("chromium-*/chrome-win64/chrome.exe"))
            if candidates:
                executable = str(max(candidates, key=lambda p: p.stat().st_mtime))
        self.browser = await self.manager.chromium.launch(
            headless=True,
            executable_path=executable or None,
            args=[
                "--enable-features=WebMCP,WebMCPTesting",
                "--enable-blink-features=WebMCP,WebMCPTesting",
                "--enable-experimental-web-platform-features",
            ],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1100, "height": 920}
        )
        self.page = await self.context.new_page()
        self.page.set_default_timeout(4000)
        return self

    async def __aexit__(self, *args):
        if hasattr(self, "browser"):
            await self.browser.close()
        if self.manager:
            await self.manager.stop()


async def observe(page, previous=None):
    snapshot = await page.evaluate("""() => ({
        url:location.href, title:document.title,
        controls:Array.from(document.querySelectorAll('input,select,textarea,button')).filter(e=>e.getClientRects().length).map(e=>({
            tag:e.tagName.toLowerCase(),label:e.labels?.[0]?.textContent?.trim()||e.textContent?.trim(),
            value:e.value,options:e.tagName==='SELECT'?Array.from(e.options).map(o=>o.textContent):undefined
        })), tools:window.localPageTools?.catalog||[],nativeWebMCP:!!window.localPageTools?.nativeRegistered
    })""")
    if previous:
        before = {x["label"]: x for x in previous["controls"]}
        changed = [x for x in snapshot["controls"] if x != before.get(x["label"])]
        delta = {
            "changed": changed,
            "removed": [
                x for x in before if x not in {v["label"] for v in snapshot["controls"]}
            ],
        }
    else:
        delta = {"baseline": snapshot}
    return snapshot, delta


async def fill_fields(page, payload, prefer_tools=True):
    tools = await page.evaluate(
        "() => window.localPageTools?.catalog?.map(t=>t.name)||[]"
    )
    if prefer_tools and "prepare_procurement" in tools:
        result = await page.evaluate(
            '(payload)=>window.localPageTools.call("prepare_procurement",payload)',
            payload,
        )
        return {
            "route": "page-tool",
            "native_webmcp": await page.evaluate(
                "() => window.localPageTools.nativeRegistered"
            ),
            "result": result,
        }
    labels = {
        "department": "申请部门",
        "item": "采购物品",
        "quantity": "数量",
        "budget": "预算上限（元）",
        "reason": "申请用途",
    }
    for field, label in labels.items():
        control = page.get_by_label(label, exact=True)
        if field == "department":
            await control.select_option(label=payload[field])
        else:
            await control.fill(str(payload[field]))
    return {
        "route": "semantic-dom",
        "native_webmcp": False,
        "result": {"submitted": False},
    }


async def verify_fields(page, payload):
    actual = await page.evaluate("() => window.readProcurement()")
    for k, v in payload.items():
        if str(actual.get(k)) != str(v):
            raise ValueError("页面字段与计划不一致：" + k)
    return actual
