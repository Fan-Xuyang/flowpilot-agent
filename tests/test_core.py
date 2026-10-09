import asyncio
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
from app.agent import demo_plan as browser_demo, digest


def test_browser_plan_validation_and_digest():
    plan = browser_demo("研发部采购 3 台电脑，预算 18000 元")
    assert plan.payload.quantity == 3
    assert plan.payload.budget == 18000
    payload = plan.payload.model_dump()
    assert digest(payload) != digest({**payload, "quantity": 4})
    assert digest(payload) == digest(dict(reversed(list(payload.items()))))
    with pytest.raises(ValueError):
        browser_demo("采购 99 台电脑")


def test_page_tool_and_semantic_dom():
    from app.browser import BrowserSession, fill_fields, verify_fields, observe

    payload = browser_demo("研发部采购 3 台电脑，预算 18000 元").payload.model_dump()

    async def scenario():
        async with BrowserSession() as session:
            page = session.page
            await page.goto((ROOT / "app/portal.html").as_uri())
            baseline, _ = await observe(page)
            first = await fill_fields(page, payload, True)
            assert first["route"] == "page-tool"
            await verify_fields(page, payload)
            _, delta = await observe(page, baseline)
            assert delta["changed"]
            changed = {**payload, "quantity": 4}
            second = await fill_fields(page, changed, False)
            assert second["route"] == "semantic-dom"
            await verify_fields(page, changed)
            assert not await page.evaluate("() => !!window.procurementReceipt")

    asyncio.run(scenario())
