"""Compact server-creation layout and accessible field-help checks."""

import os

import pytest
from playwright.async_api import expect

from tests.browser.test_workspace import ROOT
from tests.browser.test_workspace import mock_url as mock_url
from tests.browser.test_workspace import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1",
    reason="opt-in local mock browser tests",
)


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
async def test_creation_help_is_compact_accessible_and_responsive(
    page, mock_url, width
):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.goto(mock_url + "/servers/new")

    form = page.locator('form[action="/servers/new"]')
    await expect(form).to_be_visible()
    await expect(page.locator('link[href*="app.creation.css"]')).to_have_count(1)
    await expect(page.locator(".new-server__hint")).to_have_count(0)
    await expect(page.locator(".new-server__help-button")).to_have_count(6)
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    help_relationships = await form.evaluate("""form => {
      const buttons = [...form.querySelectorAll('.new-server__help-button')];
      const fields = [...form.querySelectorAll('[aria-describedby]')]
        .filter(field => field.getAttribute('aria-describedby').includes('-hint'));
      return {
        buttonsOutsideLabels: buttons.every(button => !button.closest('label')),
        descriptionsExist: fields.every(field => field.getAttribute('aria-describedby')
          .split(' ').every(id => document.getElementById(id))),
        describedFields: fields.map(field => field.name)
      };
    }""")
    assert help_relationships["buttonsOutsideLabels"]
    assert help_relationships["descriptionsExist"]
    assert help_relationships["describedFields"] == [
        "name",
        "memory_budget_gb",
        "port",
        "server_jar",
        "custom_start_script",
        "java_version",
    ]

    jar_field = form.locator('[name="server_jar"]').locator("..")
    script_field = form.locator('[name="custom_start_script"]').locator("..")
    jar_box = await jar_field.bounding_box()
    script_box = await script_field.bounding_box()
    assert jar_box and script_box
    if width > 767:
        assert abs(jar_box["y"] - script_box["y"]) <= 2
        assert jar_box["x"] + jar_box["width"] <= script_box["x"]
        assert (await form.bounding_box())["height"] < 760
    else:
        assert script_box["y"] >= jar_box["y"] + jar_box["height"]

    trigger = page.get_by_role("button", name="Help for custom start script")
    popover = page.locator("#new-server-script-hint")
    await trigger.focus()
    await page.keyboard.press("Enter")
    await expect(popover).to_be_visible()
    await expect(popover).to_contain_text("Windows .bat scripts are not supported")
    assert await popover.evaluate("""el => {
      const r = el.getBoundingClientRect();
      return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight;
    }""")
    await page.screenshot(
        path=str(ROOT / ".localdev" / "ui-review" / f"creation-popup-{width}.png")
    )
    await page.keyboard.press("Escape")
    await expect(popover).to_be_hidden()
    await expect(trigger).to_be_focused()

    await trigger.click()
    await expect(popover).to_be_visible()
    await page.get_by_role("heading", name="Create a server", exact=True).click()
    await expect(popover).to_be_hidden()

    await form.locator('[name="name"]').fill("valid-server")
    await form.locator('[name="memory_budget_gb"]').fill("8")
    await form.locator('[name="port"]').fill("25575")
    await form.locator('[name="server_jar"]').fill("paper.jar")
    validity = await form.evaluate("""form => {
      const eula = form.elements.accept_eula;
      return {
        valid: form.checkValidity(),
        eulaChecked: eula.checked,
        eulaRequired: eula.required,
        eulaMissing: eula.validity.valueMissing,
        action: form.getAttribute('action'),
        method: form.getAttribute('method')
      };
    }""")
    assert validity == {
        "valid": False,
        "eulaChecked": False,
        "eulaRequired": True,
        "eulaMissing": True,
        "action": "/servers/new",
        "method": "post",
    }

    screenshots = ROOT / ".localdev" / "ui-review"
    screenshots.mkdir(parents=True, exist_ok=True)
    await page.screenshot(
        path=str(screenshots / f"creation-help-{width}.png"),
        full_page=True,
        animations="disabled",
    )
