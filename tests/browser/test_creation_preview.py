"""Generated setup preview follows form edits without creating a server."""
import os

import pytest
from playwright.async_api import expect

from tests.browser.test_workspace import ROOT
from tests.browser.test_workspace import mock_url as mock_url
from tests.browser.test_workspace import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1", reason="opt-in browser tests"
)


@pytest.mark.parametrize("width", [390, 1440])
async def test_setup_preview_updates_and_switches_files(page, mock_url, width):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.goto(mock_url + "/servers/new")
    preview = page.locator('.setup-preview')
    code = page.locator('[data-preview-code]')
    picker = preview.get_by_role('combobox', name='Preview file')
    await expect(code).to_contain_text('my-minecraft-server')
    await page.get_by_role('textbox', name='Name', exact=True).fill('test-preview')
    await page.get_by_role('spinbutton', name='Memory budget (GB)', exact=True).fill('12')
    await page.get_by_role('spinbutton', name='Port', exact=True).fill('25580')
    await expect(code).to_contain_text('container_name: test-preview')
    await expect(code).to_contain_text('mem_limit: 12g')
    await expect(code).to_contain_text('25580:25565')
    await picker.select_option('server/start_server.sh')
    await expect(code).to_contain_text('-Xmx10g')
    await page.get_by_role(
        'textbox', name='Custom start script (optional)', exact=True
    ).fill('run.sh')
    await expect(code).to_contain_text('exec bash ./run.sh')
    await expect(code).not_to_contain_text('-Xmx')
    await page.get_by_role('textbox', name='Name', exact=True).fill('../bad')
    await expect(page.locator('[data-preview-status]')).to_contain_text('lowercase')
    await expect(code).to_be_empty()
    await page.get_by_role('textbox', name='Name', exact=True).fill('test-preview')
    await expect(code).to_contain_text('exec bash ./run.sh')
    await picker.select_option('server/server.properties')
    await expect(code).to_contain_text('GENERATED_ON_CREATE')
    assert (await page.locator('.setup-preview__code').bounding_box())['height'] < 200
    await preview.get_by_role('button', name='About setup preview').click()
    await expect(page.locator('#setup-preview-help')).to_be_visible()
    await page.wait_for_function("""() => {
      const popup = document.querySelector('#setup-preview-help').getBoundingClientRect();
      const button = document.querySelector('.setup-preview__help-button').getBoundingClientRect();
      return popup.left >= 0 && popup.right <= innerWidth
        && popup.top >= 0 && popup.bottom <= innerHeight
        && Math.min(Math.abs(popup.top - button.bottom),
                    Math.abs(button.top - popup.bottom)) <= 9;
    }""")
    await page.keyboard.press('Escape')
    await expect(page.locator('#setup-preview-help')).to_be_hidden()

    await expect(
        page.get_by_role('checkbox', name='I accept the Minecraft EULA')
    ).not_to_be_checked()
    assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    form_box = await page.locator('.new-server__form').bounding_box()
    preview_box = await preview.bounding_box()
    if width > 1100:
        assert preview_box['x'] >= form_box['x'] + form_box['width']
    else:
        assert preview_box['y'] >= form_box['y'] + form_box['height']
    await picker.select_option('docker-compose.yml')
    screenshots = ROOT / '.localdev' / 'ui-review'
    screenshots.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(screenshots / f'creation-preview-{width}.png'), full_page=True)
