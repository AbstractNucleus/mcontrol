"""Explorer interactions against temporary mock server files."""

import os

import pytest
from playwright.async_api import expect

from tests.browser.test_workspace import ROOT
from tests.browser.test_workspace import mock_url as mock_url
from tests.browser.test_workspace import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1", reason="opt-in local mock browser tests"
)


@pytest.mark.parametrize("width", [390, 1440])
async def test_explorer_nested_selection_and_context_menu(page, mock_url, width):
    folder = f"explorer-{width}"
    nested = f"{folder}/configuration"
    filename = "server-performance-and-world-generation-settings.json"
    path = f"{nested}/{filename}"
    for parent, name in [("", folder), (folder, "configuration")]:
        response = await page.request.post(
            mock_url + "/servers/atm10/files/mkdir", form={"path": parent, "dirname": name}
        )
        assert response.ok, await response.text()
    response = await page.request.post(
        mock_url + "/servers/atm10/files/upload",
        multipart={
            "path": nested,
            "files": {
                "name": filename,
                "mimeType": "application/json",
                "buffer": b'{"enabled":true}',
            },
        },
    )
    assert response.ok, await response.text()
    await page.set_viewport_size({"width": width, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    await page.goto(mock_url + "/servers/atm10")
    await page.get_by_role("button", name="Focus Files", exact=True).click()
    root_row = page.locator(f'[data-tree-path="{folder}"]')
    await root_row.focus()
    await page.keyboard.press("ArrowRight")
    nested_row = page.locator(f'[data-tree-path="{nested}"]')
    await expect(nested_row).to_be_visible()
    await page.wait_for_function("!document.querySelector('#file-tree .htmx-settling')")
    await page.keyboard.press("ArrowRight")
    await expect(nested_row).to_be_focused()
    await page.keyboard.press("ArrowRight")
    row = page.locator(f'[data-tree-path="{path}"]')
    await expect(row).to_be_visible()
    await page.wait_for_function("!document.querySelector('#file-tree .htmx-settling')")
    await page.keyboard.press("ArrowRight")
    await expect(row).to_be_focused()
    await page.keyboard.press("Space")
    await expect(page.locator("[data-bulk-count]")).to_have_text("1 selected")
    await page.locator('[data-bulk-action="clear"]').click()
    await expect(row.get_by_role("checkbox")).not_to_be_checked()
    link = row.get_by_role("link", name=filename, exact=True)
    await link.click()
    await expect(page.locator(".cm-editor")).to_be_visible()
    if width == 390:
        await expect(page.locator("#file-tree")).to_be_hidden()
        await page.get_by_role("button", name="Back to files", exact=False).click()
    else:
        await page.locator("[data-file-nav-size]").select_option("160")
    await expect(link).to_have_attribute("aria-current", "true")
    await row.focus()
    await page.keyboard.press("Shift+F10")
    menu = row.locator(".file-tree__menu-panel")
    await expect(row.locator(".file-tree__menu-panel:popover-open")).to_be_visible()
    assert await menu.evaluate("""el => {
      const r = el.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + 10);
      return r.left >= 8 && r.right <= innerWidth - 8 && r.top >= 8
        && r.bottom <= innerHeight - 8 && el.contains(top);
    }""")
    assert await page.locator("#file-tree").evaluate("el => el.scrollWidth <= el.clientWidth")
    await page.keyboard.press("ArrowDown")
    await expect(menu.get_by_role("link", name="Download", exact=True)).to_be_focused()
    await page.keyboard.press("ArrowDown")
    await page.keyboard.press("Enter")
    await expect(page.get_by_role("textbox", name="New name", exact=True)).to_have_value(filename)
    await page.keyboard.press("Escape")
    await expect(page.locator("#file-rename-form")).to_have_count(0)
    await expect(menu).to_be_hidden()
    await page.keyboard.press("Control+p")
    search = page.get_by_role("searchbox", name="Search files", exact=True)
    await expect(search).to_be_focused()
    await search.fill("server-performance")
    await expect(page.locator("#file-search-results")).to_contain_text(filename)
    await page.keyboard.press("Escape")
    await expect(search).to_have_value("")
    if width != 390:
        await page.locator("[data-file-nav-size]").select_option("240")
    await row.focus()
    await page.screenshot(
        path=str(ROOT / ".localdev" / "ui-review" / f"explorer-{width}.png"),
        full_page=True,
        animations="disabled",
    )
    assert not errors
