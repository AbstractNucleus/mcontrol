"""Regeneration must refresh a stale preview before accepting confirmation."""

import os
import socket

import pytest
from playwright.async_api import expect

from tests.browser.test_workspace import mock_url as mock_url
from tests.browser.test_workspace import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1", reason="opt-in local mock browser tests"
)


async def test_regenerate_refreshes_changed_settings_before_confirmation(page, mock_url):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = mock_url + "/servers/browser-regenerate"
    values = {
        "memory_budget_gb": "8", "port": str(port), "server_jar": "paper.jar",
        "java_version": "21",
    }
    created = await page.request.post(
        mock_url + "/servers/new",
        form={**values, "name": "browser-regenerate", "accept_eula": "on"},
    )
    assert created.ok
    updated = await page.request.post(
        base + "/variables", form={**values, "memory_budget_gb": "10"}
    )
    assert updated.ok

    await page.goto(base)
    await page.locator("[data-settings-open]").click()
    card = page.locator("#variables")
    await card.get_by_role("link", name="Regenerate", exact=True).click()
    await expect(card).to_contain_text("-Xmx8g")

    updated = await page.request.post(
        base + "/variables", form={**values, "memory_budget_gb": "12"}
    )
    assert updated.ok
    async with page.expect_response(base + "/regenerate/confirm") as result:
        await card.get_by_role("button", name="Confirm", exact=True).click()
    assert (await result.value).status == 409
    await expect(card).to_contain_text("-Xmx10g")

    async with page.expect_response(base + "/regenerate/confirm") as result:
        await card.get_by_role("button", name="Confirm", exact=True).click()
    assert (await result.value).status == 200
    await expect(card.get_by_role("link", name="Edit", exact=True)).to_be_visible()
    await expect(card.get_by_role("link", name="Regenerate", exact=True)).to_have_count(0)
