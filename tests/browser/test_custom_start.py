"""Custom script creation must work without a jar in the browser form."""

import os
import socket

import pytest
from playwright.async_api import expect

from tests.browser.test_workspace import mock_url as mock_url
from tests.browser.test_workspace import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1", reason="opt-in local mock browser tests"
)


@pytest.mark.parametrize("width", [390, 1440])
async def test_create_custom_script_without_jar(page, mock_url, width):
    await page.set_viewport_size({"width": width, "height": 1000})
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    name = f"browser-script-{width}"
    await page.goto(mock_url + "/servers/new")
    form = page.locator('form[action="/servers/new"]')
    await form.locator('[name="name"]').fill(name)
    await form.locator('[name="memory_budget_gb"]').fill("8")
    await form.locator('[name="port"]').fill(str(port))
    await form.locator('[name="custom_start_script"]').fill("run.sh")
    await form.locator('[name="accept_eula"]').check()
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    await form.get_by_role("button", name="Create", exact=True).click()
    await expect(page).to_have_url(mock_url + f"/servers/{name}")
    await expect(page.locator("#variables")).to_contain_text("run.sh")
    await page.locator("[data-settings-open]").click()
    await page.locator("#variables").get_by_role("link", name="Edit", exact=True).click()
    script = page.locator('#variables [name="custom_start_script"]')
    await expect(script).to_have_value("run.sh")
    await script.fill("scripts/launch.sh")
    await page.locator("#variables").get_by_role("button", name="Save", exact=True).click()
    await expect(page.locator("#variables")).to_contain_text("scripts/launch.sh")
