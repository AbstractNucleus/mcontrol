"""Whole-page and navigation regressions against the isolated browser fixture."""

import os
import re
import socket

import pytest
from playwright.async_api import expect

from tests.browser.test_workspace import ROOT
from tests.browser.test_workspace import mock_url as mock_url
from tests.browser.test_workspace import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1", reason="opt-in local mock browser tests"
)


async def _screenshot(page, name, full_page=True):
    folder = ROOT / ".localdev" / "ui-review"
    folder.mkdir(parents=True, exist_ok=True)
    await page.screenshot(
        path=str(folder / f"{name}.png"), full_page=full_page, animations="disabled"
    )


@pytest.mark.parametrize("width", [390, 768, 1440])
@pytest.mark.parametrize("system_scheme", ["light", "dark"])
async def test_secondary_pages_responsive(page, mock_url, width, system_scheme):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.emulate_media(color_scheme=system_scheme, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "response",
        lambda response: errors.append(f"{response.status} {response.url}")
        if "/static/" in response.url and response.status >= 400 else None,
    )
    for path, heading, name in [
        ("/players", "Players", "players"),
        ("/servers/new", "Create a server", "new-server"),
        ("/missing-redesign-page", None, "not-found"),
    ]:
        response = await page.goto(mock_url + path)
        assert response.status == (404 if heading is None else 200)
        if heading:
            await expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        await expect(page.locator("main")).to_be_visible()
        await expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        await _screenshot(page, f"{name}-{width}-dark")
    assert not errors


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("system_scheme", ["light", "dark"])
async def test_fleet_visuals(page, mock_url, width, system_scheme):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.emulate_media(color_scheme=system_scheme, reduced_motion="reduce")
    await page.goto(mock_url + "/")
    await expect(page.locator(".server-card")).to_have_count(5)
    await expect(page.locator(".fleet-insights")).to_have_count(0)
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    ratios = await page.evaluate("""() => {
      const sample = document.createElement('span'); document.body.append(sample);
      sample.style.setProperty('transition', 'none', 'important');
      const luminance = token => {
        sample.style.color = `var(${token})`;
        return getComputedStyle(sample).color.match(/[\\d.]+/g).slice(0,3).map(Number)
          .map(c => c/255).map(c => c <= .04045 ? c/12.92 : ((c+.055)/1.055)**2.4)
          .reduce((sum,c,i) => sum+c*[.2126,.7152,.0722][i],0);
      };
      const foreground = luminance('--fg-primary-action');
      const results = ['--bg-primary-action', '--bg-primary-action-hover'].map(token => {
        const background = luminance(token);
        return {token, ratio:(Math.max(foreground,background)+.05)
          /(Math.min(foreground,background)+.05)};
      });
      sample.remove(); return results;
    }""")
    assert all(result["ratio"] >= 4.5 for result in ratios), ratios
    await _screenshot(page, f"fleet-{width}-dark")


async def test_sidebar_footer_stays_in_short_viewport(page, mock_url):
    await page.set_viewport_size({"width": 1280, "height": 720})
    await page.emulate_media(color_scheme="light", reduced_motion="reduce")
    await page.goto(mock_url + "/")
    footer = page.locator(".sidebar__footer")
    await expect(footer).to_be_visible()
    assert await footer.evaluate(
        "el => { const r = el.getBoundingClientRect(); "
        "return r.top >= 0 && r.bottom <= innerHeight; }"
    )
    await expect(footer.get_by_role("button", name="Collapse sidebar")).to_be_visible()
    await expect(footer.get_by_role("radio")).to_have_count(0)
    await expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    await _screenshot(page, "sidebar-1280x720-dark", full_page=False)


async def test_server_switcher_tracks_lifecycle_changes(page, mock_url):
    await page.goto(mock_url + "/servers/cobblemon")
    current = page.locator('.server-switcher__panel a[aria-current="page"]')
    await expect(current.locator("small")).to_have_text("Stopped")
    await page.get_by_role("button", name="Start cobblemon", exact=True).click()
    await expect(page.locator("#state-pill")).to_have_text("Running")
    await expect(current.locator("small")).to_have_text("Running")
    await page.get_by_role("button", name="Stop cobblemon", exact=True).click()
    await expect(page.locator("#state-pill")).to_have_text("Stopped")
    await expect(current.locator("small")).to_have_text("Stopped")
    await page.locator(".server-switcher summary").press("Enter")
    await page.get_by_role("navigation", name="Switch server", exact=True).get_by_role(
        "link", name="atm10 Running", exact=True
    ).click()
    await expect(page).to_have_url(mock_url + "/servers/atm10")


async def test_fleet_refresh_keeps_all_servers_visible(page, mock_url):
    await page.goto(mock_url + "/")
    await expect(page.get_by_role("combobox", name="Status", exact=True)).to_have_count(0)
    await expect(page.get_by_role("button", name="All servers", exact=True)).to_have_count(0)
    await expect(page.get_by_role("button", name="Running", exact=True)).to_have_count(0)
    await expect(page.get_by_role("button", name="Stopped", exact=True)).to_have_count(0)
    await expect(page.locator(".server-card:visible")).to_have_count(5)
    observed = page.locator("#fleet time[data-observed-at]")
    before = await observed.get_attribute("data-observed-at")
    async with page.expect_response("**/fleet/status") as response:
        await page.evaluate(
            "document.getElementById('fleet').dispatchEvent(new Event('mc:refresh'))"
        )
    assert (await response.value).status == 200
    await expect(observed).not_to_have_attribute("data-observed-at", before)
    await expect(page.locator(".server-card:visible")).to_have_count(5)


@pytest.mark.parametrize("width", [390, 1440])
async def test_navigation_stays_dark_with_saved_light_preference(page, mock_url, width):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.emulate_media(color_scheme="light")
    await page.add_init_script("localStorage.setItem('theme', 'light')")
    await page.goto(mock_url + "/")
    sidebar = page.locator("#primary-sidebar")
    sections = page.get_by_role("navigation", name="mcontrol sections")
    if width == 390:
        await page.get_by_role("button", name="Menu", exact=True).click()
    await expect(sidebar.locator('[data-theme-toggle]')).to_have_count(0)
    await expect(sidebar.get_by_role("link", name="mcontrol", exact=True)).to_have_attribute(
        "aria-current", "page"
    )
    await expect(sidebar.get_by_role("link", name="Players", exact=True)).to_have_count(0)
    await expect(sidebar.get_by_role("link", name="Trash", exact=True)).to_have_count(0)
    await expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    if width == 390:
        await _screenshot(page, "sidebar-drawer-390-dark", full_page=False)
        await page.get_by_role("button", name="Menu", exact=True).click()
        await expect(sidebar).to_be_hidden()
    await sections.get_by_role("link", name="Players", exact=True).click()
    await expect(page).to_have_url(mock_url + "/players")
    await expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    await expect(sections.get_by_role("link", name="Players", exact=True)).to_have_attribute(
        "aria-current", "page"
    )
    await expect(sections.get_by_role("link", name="Trash", exact=True)).to_have_count(0)
    await page.emulate_media(color_scheme="dark")
    await expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    await page.emulate_media(color_scheme="light")
    await expect(page.locator("html")).to_have_attribute("data-theme", "dark")


@pytest.mark.parametrize("javascript_enabled", [False, True])
async def test_dark_appearance_without_javascript_or_storage(page, mock_url, javascript_enabled):
    context = await page.context.browser.new_context(
        java_script_enabled=javascript_enabled, color_scheme="light"
    )
    try:
        await context.add_init_script("""Object.defineProperty(window, 'localStorage', {
          get() { throw new Error('Storage is unavailable'); }
        });""")
        tab = await context.new_page()
        await tab.goto(mock_url + "/")
        await expect(tab.locator("html")).to_have_attribute("data-theme", "dark")
        await expect(tab.locator('[data-theme-toggle]')).to_have_count(0)
        assert await tab.locator("html").evaluate(
            "el => getComputedStyle(el).colorScheme"
        ) == "dark"
        await expect(tab.locator('meta[name="color-scheme"]')).to_have_attribute("content", "dark")
    finally:
        await context.close()


@pytest.mark.parametrize("width", [390, 1440])
async def test_roster_filters_and_remove_dialog_keyboard(page, mock_url, width):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.goto(mock_url + "/players")
    search = page.locator("[data-roster-search]")
    rows = page.locator("[data-roster-name]:visible")
    await search.fill("nOtCh")
    await expect(rows).to_have_count(1)
    await expect(rows).to_have_attribute("data-roster-name", "Notch")
    await search.fill("no-such-player")
    await expect(rows).to_have_count(0)
    await expect(page.locator("[data-roster-empty]")).to_be_visible()
    await search.fill("")
    await page.locator("[data-roster-server]").select_option("atm10")
    await expect(rows).to_have_count(3)
    await search.fill("Notch")
    trigger = rows.get_by_role("link", name="Remove", exact=True)
    await trigger.click()
    dialog = page.get_by_role("dialog", name="Remove Notch from roster?")
    await expect(dialog).to_be_visible()
    await expect(dialog.get_by_role("button", name="Remove from all servers")).to_be_visible()
    assert await dialog.evaluate("el => el.contains(document.activeElement)")
    cancel = dialog.get_by_role("button", name="Cancel", exact=True)
    await cancel.focus()
    await page.keyboard.press("Tab")
    assert await dialog.evaluate("el => el.contains(document.activeElement)")
    await page.keyboard.press("Shift+Tab")
    await expect(cancel).to_be_focused()
    await _screenshot(page, f"player-dialog-{width}")
    await page.keyboard.press("Escape")
    await expect(dialog).to_have_count(0)
    await expect(trigger).to_be_focused()
    await expect(rows).to_have_attribute("data-roster-name", "Notch")


@pytest.mark.parametrize("width", [390, 1440])
async def test_create_validation_and_delete_confirmation(page, mock_url, width):
    await page.set_viewport_size({"width": width, "height": 1000})
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    name = f"browser-redesign-{width}"
    await page.goto(mock_url + "/servers/new")
    form = page.locator('form[action="/servers/new"]')
    await form.locator('[name="name"]').fill("Invalid Name")
    await form.locator('[name="memory_budget_gb"]').fill("8")
    await form.locator('[name="port"]').fill(str(port))
    await form.locator('[name="server_jar"]').fill("paper.jar")
    await form.locator('[name="java_version"]').select_option("21")
    await form.locator('[name="loader"]').select_option("vanilla")
    await form.locator('summary').click()
    await form.locator('[name="jvm_extra_args"]').fill("-XX:+UseG1GC")
    await form.locator('[name="accept_eula"]').check()
    async with page.expect_response(
        lambda response: response.url.endswith("/servers/new")
        and response.request.method == "POST"
    ) as rejected:
        await form.get_by_role("button", name="Create", exact=True).click()
    assert (await rejected.value).status == 422
    await expect(form.locator('[name="name"]')).to_have_value("Invalid Name")
    await expect(form.locator('[name="server_jar"]')).to_have_value("paper.jar")
    await expect(form.locator('[name="jvm_extra_args"]')).to_have_value("-XX:+UseG1GC")
    await expect(form).to_contain_text("lowercase letters")
    await form.locator('[name="name"]').fill(name)
    await form.get_by_role("button", name="Create", exact=True).click()
    await expect(page).to_have_url(mock_url + f"/servers/{name}")
    await expect(page.locator("#file-tree")).to_contain_text("docker-compose.yml")
    await page.locator("details.detail-menu > summary").click()
    await page.get_by_role("button", name="Delete server", exact=True).click()
    dialog = page.get_by_role("dialog", name=f"Delete {name}?")
    await expect(dialog).to_be_visible()
    await dialog.locator('[name="confirm_name"]').fill("wrong-name")
    await dialog.get_by_role("button", name="Delete", exact=True).click()
    await expect(dialog.locator(".confirm-modal__error")).to_be_visible()
    await expect(dialog.locator('[name="confirm_name"]')).to_have_value("wrong-name")
    await dialog.locator('[name="confirm_name"]').fill(name)
    await dialog.get_by_role("button", name="Delete", exact=True).click()
    await expect(page).to_have_url(mock_url + "/")
    await expect(page.locator(f'.server-card[data-name="{name}"]')).to_have_count(0)



@pytest.mark.parametrize("width", [390, 1158])
async def test_focused_panel_return_control_is_not_covered(page, mock_url, width):
    await page.set_viewport_size({"width": width, "height": 1100})
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator("#file-tree")).to_contain_text("docker-compose.yml")
    await page.get_by_role("button", name="Focus Files", exact=True).click()
    panel = page.locator('[data-pane="files"]')
    button = panel.get_by_role("button", name="Back to workspace", exact=True)
    await expect(button).to_be_focused()
    await page.evaluate(
        "new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    assert await button.evaluate("""el => {
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
      return hit === el || el.contains(hit);
    }""")
    await _screenshot(page, f"focus-files-visible-{width}", full_page=False)
    await button.click()
    await expect(panel).not_to_have_class(re.compile("panel--focused"))
    await expect(page.locator('[data-pane="console"]')).to_be_visible()
