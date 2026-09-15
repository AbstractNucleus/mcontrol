"""Archive dialogs, actual context menus, and ZIP round trips on temporary files."""

import asyncio
import io
import os
import zipfile

import pytest
from playwright.async_api import expect

from tests.browser.test_workspace import ROOT
from tests.browser.test_workspace import mock_url as mock_url
from tests.browser.test_workspace import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1", reason="opt-in local mock browser tests"
)


async def upload(page, mock_url, name, data):
    response = await page.request.post(
        mock_url + "/servers/atm10/files/upload",
        multipart={
            "path": "",
            "files": {"name": name, "mimeType": "application/octet-stream", "buffer": data},
        },
    )
    assert response.ok, await response.text()


async def open_files(page, mock_url, width=1440):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.goto(mock_url + "/servers/atm10")
    await page.get_by_role("button", name="Focus Files", exact=True).click()
    await expect(page.locator("#file-tree")).to_contain_text("docker-compose.yml")


@pytest.mark.parametrize("width", [390, 1440])
async def test_zip_compression_and_extract_destinations(page, mock_url, width):
    name = f"archive-source-{width}.txt"
    content = b"archive browser round trip\n"
    await upload(page, mock_url, name, content)
    await open_files(page, mock_url, width)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    await page.locator(f'[data-tree-path="{name}"] input[type=checkbox]').check()
    await page.get_by_role("button", name="Compress selected", exact=True).click()
    dialog = page.get_by_role("dialog", name="Compress selected items")
    await expect(dialog.get_by_role("button", name="Compress", exact=True)).to_be_enabled()
    archive = f"browser-roundtrip-{width}.zip"
    await dialog.get_by_role("textbox", name="Archive name", exact=True).fill(archive)
    screenshots = ROOT / ".localdev" / "ui-review"
    screenshots.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(screenshots / f"archive-dialog-{width}.png"))
    await dialog.get_by_role("button", name="Compress", exact=True).click()
    await expect(dialog).to_have_count(0)
    await expect(page.locator("#file-bulk-toolbar")).to_be_hidden()
    row = page.locator(f'[data-tree-path="{archive}"]')
    await expect(row).to_be_visible()
    response = await page.request.get(
        mock_url + f"/servers/atm10/files/download?path={archive}"
    )
    assert response.ok
    with zipfile.ZipFile(io.BytesIO(await response.body())) as result:
        assert result.read(name) == content
    await row.click(button="right")
    menu = row.locator(".file-tree__menu-panel")
    await expect(menu).to_be_visible()
    await menu.get_by_role("button", name=f"Extract to browser-roundtrip-{width}/…").click()
    dialog = page.get_by_role("dialog", name="Extract to folder")
    destination = dialog.get_by_role("textbox", name="Destination folder", exact=True)
    await expect(destination).to_have_value(f"browser-roundtrip-{width}")
    assert await dialog.evaluate("el => { const r = el.getBoundingClientRect(); "
                                 "return r.left >= 0 && r.right <= innerWidth && "
                                 "r.top >= 0 && r.bottom <= innerHeight; }")
    folder = f"browser-extracted-{width}"
    await destination.fill(folder)
    await expect(dialog.get_by_role("button", name="Extract", exact=True)).to_be_enabled()
    await dialog.get_by_role("button", name="Extract", exact=True).click()
    await expect(dialog).to_have_count(0)
    await expect(row).to_be_visible()
    extracted = await page.request.get(
        mock_url + f"/servers/atm10/files/download?path={folder}/{name}"
    )
    assert extracted.ok
    assert await extracted.body() == content

    # Extract here needs a distinct entry so its no-overwrite rule is respected.
    here_name = f"extract-here-{width}.txt"
    here_archive = f"extract-here-{width}.ZIP"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as result:
        result.writestr(here_name, b"here")
    await upload(page, mock_url, here_archive, buffer.getvalue())
    await open_files(page, mock_url, width)
    await expect(page.locator("#file-tree")).to_contain_text(here_archive)
    row = page.locator(f'[data-tree-path="{here_archive}"]')
    await row.locator("summary").click()
    await expect(row.locator(".file-tree__menu-panel")).to_be_visible()
    await row.get_by_role("button", name="Extract here", exact=True).click()
    await expect(page.locator(f'[data-tree-path="{here_name}"]')).to_be_visible()
    await expect(row).to_be_visible()
    assert not errors


async def test_archive_errors_keep_inputs_and_block_duplicate_submit(page, mock_url):
    await page.route("**/files/archive-capabilities", lambda route: route.fulfill(
        json={"zip": True, "rar_extract": False, "rar_compress": False}
    ))
    await open_files(page, mock_url)
    await page.locator('[data-tree-path="docker-compose.yml"] input[type=checkbox]').check()
    await page.get_by_role("button", name="Compress selected", exact=True).click()
    dialog = page.get_by_role("dialog", name="Compress selected items")
    await expect(dialog.locator("[data-archive-support]")).to_contain_text("licensed rar tool")
    assert await dialog.locator('option[value="rar"]').evaluate("el => el.disabled")
    name = dialog.get_by_role("textbox", name="Archive name", exact=True)
    await name.fill("retry.zip")
    await dialog.get_by_role("textbox", name="Destination folder", exact=True).fill("config")
    started = asyncio.Event()
    release = asyncio.Event()
    requests = []

    async def fail_compression(route):
        requests.append(route.request.post_data)
        started.set()
        await release.wait()
        await route.fulfill(status=409, json={"detail": "An archive already exists."})

    await page.route("**/files/compress", fail_compression)
    submit = dialog.get_by_role("button", name="Compress", exact=True)
    await submit.click()
    await asyncio.wait_for(started.wait(), timeout=5)
    await expect(submit).to_be_disabled()
    await expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_disabled()
    await expect(dialog.locator("[data-archive-progress]")).to_have_text(
        "Compressing selected items…"
    )
    await page.keyboard.press("Escape")
    await expect(dialog).to_be_visible()
    await dialog.locator("form").evaluate(
        "el => el.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
    )
    release.set()
    await expect(dialog.get_by_role("alert")).to_contain_text("An archive already exists.")
    assert len(requests) == 1
    await expect(name).to_have_value("retry.zip")
    destination = dialog.get_by_role("textbox", name="Destination folder", exact=True)
    await expect(destination).to_have_value("config")
    await expect(submit).to_be_enabled()
    await expect(page.locator("[data-bulk-count]")).to_have_text("1 selected")
    await page.route("**/files/compress", lambda route: route.fulfill(status=204))
    await submit.click()
    await expect(dialog).to_have_count(0)
    await expect(page.locator("#file-bulk-toolbar")).to_be_hidden()

    await upload(page, mock_url, "unavailable.RAR", b"not a real archive")
    await open_files(page, mock_url)
    row = page.locator('[data-tree-path="unavailable.RAR"]')
    await row.click(button="right")
    await expect(row.locator(".file-tree__menu-panel")).to_be_visible()
    await row.get_by_role("button", name="Extract to unavailable/…").click()
    dialog = page.get_by_role("dialog", name="Extract to folder")
    await expect(dialog.locator("[data-archive-support]")).to_contain_text(
        "RAR extraction is unavailable"
    )
    await expect(dialog.get_by_role("button", name="Extract", exact=True)).to_be_disabled()
    await page.keyboard.press("Escape")
    await expect(dialog).to_have_count(0)


async def test_capability_wait_and_rar_format_submission(page, mock_url):
    release = asyncio.Event()
    requests = []

    async def wait_for_capabilities(route):
        await release.wait()
        await route.fulfill(json={"zip": True, "rar_extract": True, "rar_compress": True})

    async def record_compression(route):
        requests.append(route.request.post_data)
        await route.fulfill(status=204)

    await page.route("**/files/archive-capabilities", wait_for_capabilities)
    await page.route("**/files/compress", record_compression)
    await open_files(page, mock_url)
    await page.locator('[data-tree-path="docker-compose.yml"] input[type=checkbox]').check()
    await page.get_by_role("button", name="Compress selected", exact=True).click()
    dialog = page.get_by_role("dialog", name="Compress selected items")
    submit = dialog.get_by_role("button", name="Compress", exact=True)
    await expect(submit).to_be_disabled()
    archive_name = dialog.get_by_role("textbox", name="Archive name", exact=True)
    await archive_name.fill("chosen.zip")
    await archive_name.press("Enter")
    await dialog.locator("form").evaluate(
        "el => el.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
    )
    assert not requests
    await expect(dialog).to_be_visible()
    release.set()
    await expect(submit).to_be_enabled()
    await archive_name.fill("folder/chosen.zip")
    await submit.click()
    assert not requests
    assert await archive_name.evaluate("el => !el.checkValidity()")
    await archive_name.fill("chosen.zip")
    await dialog.get_by_role("combobox", name="Format", exact=True).select_option("rar")
    await expect(archive_name).to_have_value("chosen.rar")
    await dialog.locator(".file-archive-dialog__picker summary").click()
    await dialog.get_by_role("button", name="(server root)", exact=True).click()
    await expect(dialog.get_by_role("textbox", name="Destination folder", exact=True)).to_be_empty()
    await submit.click()
    await expect(dialog).to_have_count(0)
    assert len(requests) == 1
    assert 'name="format"\r\n\r\nrar' in requests[0]
    assert 'name="archive_name"\r\n\r\nchosen.rar' in requests[0]
