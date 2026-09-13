"""Opt-in browser checks, isolated from production DB, Docker, and server files.

MCONTROL_BROWSER_TESTS=1 uv run pytest tests/browser -v
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright, expect

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1", reason="opt-in local mock browser tests"
)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mock_url(tmp_path_factory):
    folder = tmp_path_factory.mktemp("mcontrol-browser")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "MCONTROL_MOCK_BASE": str(folder / "servers"),
        "MCONTROL_MOCK_STREAMS": "1",
    }
    with (folder / "app.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "dev_mock:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError((folder / "app.log").read_text())
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Mock app did not become ready")
            yield f"http://127.0.0.1:{port}"
        finally:
            process.terminate()
            process.wait(timeout=10)


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context(viewport={"width": 1440, "height": 1000})
        tab = await context.new_page()
        yield tab
        await browser.close()


@pytest.mark.parametrize("width", [390, 768, 1280, 1920])
@pytest.mark.parametrize("system_scheme", ["light", "dark"])
async def test_responsive_workspace(page, mock_url, width, system_scheme):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.emulate_media(color_scheme=system_scheme)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    await expect(page.locator("#server-resources")).to_contain_text("CPU")
    await expect(page.locator("#file-tree")).to_contain_text("docker-compose.yml")
    await page.get_by_role("link", name="docker-compose.yml", exact=True).click()
    await expect(page.locator(".cm-editor")).to_be_visible()
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert await page.locator(".cm-editor").evaluate(
        "el => el.getBoundingClientRect().height > 120"
    )
    if width == 390:
        await expect(page.locator("#file-tree")).to_be_hidden()
        await page.get_by_role("button", name="Back to files").click()
        await expect(page.locator("#file-tree")).to_be_visible()
        await page.get_by_role("button", name="Menu", exact=True).click()
        await expect(page.locator("#primary-sidebar")).to_be_visible()
        await page.keyboard.press("Escape")
        await expect(page.locator("#primary-sidebar")).to_be_hidden()
    screenshots = ROOT / ".localdev" / "ui-review"
    screenshots.mkdir(parents=True, exist_ok=True)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.screenshot(path=str(screenshots / f"workspace-{width}-dark.png"), full_page=True)
    await page.goto(mock_url + "/")
    await expect(page.locator("#fleet")).to_contain_text("atm10")
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    await page.locator("[data-fleet-state]").select_option("Stopped")
    await expect(page.locator(".server-card:visible")).to_have_count(2)
    await page.goto(mock_url + "/players")
    await expect(page.locator("[data-roster-name]").first).to_be_visible()
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    await page.goto(mock_url + "/servers/new")
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors


async def test_shared_layout_cancel_save_and_migration(page, mock_url):
    await page.add_init_script(
        "localStorage.setItem('mcontrol:dashboard:v2', JSON.stringify({"
        "order:['files','console','players','bindings'],"
        "hidden:[],collapsed:[],full:['files']}))"
    )
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator("[data-dashboard] > section").first).to_have_attribute(
        "data-pane", "files"
    )
    await page.get_by_label("More actions", exact=True).click()
    await page.get_by_role("button", name="Customize layout").click()
    await page.get_by_role("button", name="Reset", exact=True).click()
    await expect(page.locator("[data-dashboard] > section").first).to_have_attribute(
        "data-pane", "console"
    )
    await page.get_by_role("button", name="Cancel", exact=True).click()
    await expect(page.locator("[data-dashboard] > section").first).to_have_attribute(
        "data-pane", "files"
    )
    await page.get_by_label("More actions", exact=True).click()
    await page.get_by_role("button", name="Customize layout").click()
    await page.get_by_role("button", name="Reset", exact=True).click()
    await page.get_by_role("combobox", name="Console width").select_option("12")
    await page.get_by_role("button", name="Save layout").click()
    await page.goto(mock_url + "/servers/cobblemon")
    await expect(page.locator('[data-pane="console"]')).to_have_attribute("data-span", "12")
    await expect(page.locator("[data-dashboard] > section").first).to_have_attribute(
        "data-pane", "console"
    )


async def test_focus_keeps_dirty_editor_and_failed_save(page, mock_url):
    await page.goto(mock_url + "/servers/atm10")
    await page.get_by_role("link", name="docker-compose.yml", exact=True).click()
    editor = page.locator(".cm-content")
    await expect(editor).to_be_visible()
    await editor.click()
    await page.keyboard.press("Control+End")
    await page.keyboard.type("\n# unsaved-workspace-test")
    await page.get_by_role("button", name="Focus Files", exact=True).click()
    await expect(editor).to_contain_text("unsaved-workspace-test")
    await page.get_by_role("button", name="Back to workspace", exact=True).first.click()
    await expect(editor).to_contain_text("unsaved-workspace-test")
    await page.route(
        "**/files/save",
        lambda route: route.fulfill(
            status=500, content_type="application/json", body='{"detail":"Test save rejected"}'
        ),
    )
    await page.get_by_role("button", name="Save", exact=True).click()
    await expect(page.locator(".request-notice")).to_contain_text("Test save rejected")
    await expect(editor).to_contain_text("unsaved-workspace-test")
    dialogs = []
    page.on(
        "dialog",
        lambda dialog: (dialogs.append(dialog.message), asyncio.create_task(dialog.dismiss())),
    )
    # File selection asks before discarding dirty contents.
    await page.get_by_role("button", name="server/", exact=True).click()
    await page.get_by_role("link", name="server.properties", exact=True).click()
    assert dialogs and "unsaved" in dialogs[0].lower()
    await expect(editor).to_contain_text("unsaved-workspace-test")


async def test_failed_load_retry_and_stale_resource_recovery(page, mock_url):
    async def fail(route):
        await route.fulfill(status=502, content_type="text/plain", body="Bad gateway")

    await page.route("**/files/tree?path=", fail)
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator(".request-notice")).to_contain_text("HTTP 502")
    await page.unroute("**/files/tree?path=", fail)
    await page.locator(".request-notice").get_by_role("button", name="Retry").click()
    await expect(page.locator("#file-tree")).to_contain_text("docker-compose.yml")
    await expect(page.locator(".request-notice")).to_have_count(0)
    old = await page.locator("#server-resources").inner_text()
    await page.route("**/resources", fail)
    await expect(page.locator(".request-notice")).to_contain_text("HTTP 502", timeout=8000)
    await expect(page.locator("#server-resources")).to_contain_text("CPU")
    await expect(page.locator("#state-pill")).to_have_text("Unavailable")
    assert "CPU" in old
    await page.unroute("**/resources", fail)
    await page.locator(".request-notice").get_by_role("button", name="Retry").click()
    await expect(page.locator(".request-notice")).to_have_count(0)
    await expect(page.locator("#state-pill")).to_have_text("Running")


async def test_request_timeout_is_visible(page, mock_url):
    async def delay(route):
        await asyncio.sleep(14)
        try:
            await route.fulfill(status=200, body="late")
        except Exception:
            pass

    await page.route("**/files/tree?path=", delay)
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator(".request-notice")).to_contain_text("12 seconds", timeout=13500)


async def test_console_connection_and_rejected_command(page, mock_url):
    attempts = 0

    async def rcon(route):
        nonlocal attempts
        if route.request.method == "POST":
            await route.fulfill(
                status=409,
                content_type="application/json",
                body='{"detail":"Test connection lost"}',
            )
        else:
            attempts += 1
            if attempts == 1:
                await route.fulfill(status=502, body="Temporary failure")
            else:
                await route.continue_()

    await page.route("**/rcon", rcon)
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert attempts >= 2
    await page.get_by_role("textbox", name="RCON command").fill("list")
    await page.get_by_role("button", name="Send", exact=True).click()
    await expect(page.locator("[data-command-error]")).to_contain_text("Test connection lost")
    await expect(page.get_by_role("textbox", name="RCON command")).to_have_value("list")
    await page.get_by_role("combobox", name="Log severity").select_option("WARN")
    await expect(page.locator("#console-output > span:visible")).to_contain_text(["Can't keep up"])


async def test_newer_typing_stays_dirty_after_save(page, mock_url):
    await page.goto(mock_url + "/servers/atm10")
    await page.get_by_role("link", name="docker-compose.yml", exact=True).click()
    editor = page.locator(".cm-content")
    await editor.click()
    await page.keyboard.press("Control+End")
    await page.keyboard.type("\n# first draft")
    saving = asyncio.Event()
    release = asyncio.Event()

    async def save(route):
        saving.set()
        await release.wait()
        await route.fulfill(
            status=200, content_type="text/html",
            body=(
                '<span id="file-editor-meta">'
                '<input name="mtime_ns" value="1" type="hidden"></span>'
            ),
        )

    await page.route("**/files/save", save)
    await page.get_by_role("button", name="Save", exact=True).click()
    await saving.wait()
    await expect(page.locator("[data-editor-status]")).to_have_text("Saving…")
    await editor.click()
    await page.keyboard.press("Control+End")
    await page.keyboard.type("\n# newer draft")
    release.set()
    await expect(page.get_by_role("button", name="Save", exact=True)).to_be_enabled()
    await expect(page.locator("[data-editor-status]")).to_have_text("Unsaved changes")
    await expect(editor).to_contain_text("newer draft")


async def test_access_failure_rolls_back_and_retry_applies(page, mock_url):
    await page.goto(mock_url + "/servers/cobblemon")
    checkbox = page.get_by_role("checkbox", name="Allow Notch to join", exact=True)
    await expect(checkbox).to_be_visible()
    before = await checkbox.is_checked()
    release = asyncio.Event()

    async def fail(route):
        await release.wait()
        await route.fulfill(status=502, body="Fixture failure")

    await page.route("**/players/*/whitelist", fail)
    await checkbox.click()
    await expect(page.locator("[data-membership-status]")).to_have_text("Updating server access…")
    await expect(checkbox).to_be_disabled()
    release.set()
    await expect(page.locator("[data-membership-status]")).to_contain_text("Change failed")
    assert await checkbox.is_checked() == before
    await page.unroute("**/players/*/whitelist", fail)
    await checkbox.click()
    await expect(page.locator("[data-membership-status]")).to_contain_text("Access saved on disk")
    assert await checkbox.is_checked() != before


async def test_visible_refresh_does_not_overlap_and_hidden_streams_pause(page, mock_url):
    await page.add_init_script(
        "window.fixtureHidden = false; Object.defineProperty(document, 'hidden', "
        "{get: () => window.fixtureHidden})"
    )
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator("[data-stream-status-label]")).to_have_text("Commands ready")
    await expect(page.locator("#server-resources")).to_contain_text("CPU")
    requests = []
    release = asyncio.Event()

    async def resources(route):
        requests.append(route.request.url)
        await release.wait()
        await route.continue_()

    await page.route("**/resources", resources)
    await page.evaluate("htmx.trigger('#server-resources', 'mc:refresh')")
    await page.wait_for_timeout(5500)
    assert len(requests) == 1
    release.set()
    await expect(page.locator("#server-resources")).not_to_have_attribute("aria-busy", "true")
    await page.evaluate(
        "window.fixtureHidden = true; document.dispatchEvent(new Event('visibilitychange'))"
    )
    await expect(page.locator("[data-log-status]")).to_have_text("Logs paused")
    await expect(page.get_by_role("button", name="Send", exact=True)).to_be_disabled()
    count = len(requests)
    await page.wait_for_timeout(5500)
    assert len(requests) == count
    await page.evaluate(
        "window.fixtureHidden = false; document.dispatchEvent(new Event('visibilitychange'))"
    )
    await expect(page.get_by_role("button", name="Send", exact=True)).to_be_enabled()
    await expect(page.locator("[data-log-status]")).to_have_text("Logs live")
    assert len(requests) > count


@pytest.mark.parametrize("system_scheme", ["light", "dark"])
async def test_keyboard_settings_touch_targets_and_contrast(page, mock_url, system_scheme):
    await page.emulate_media(color_scheme=system_scheme, reduced_motion="reduce")
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(mock_url + "/servers/atm10")
    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("#server-settings")).to_be_visible()
    await page.keyboard.press("Escape")
    await expect(page.get_by_role("button", name="Settings", exact=True)).to_be_focused()
    await page.get_by_role("button", name="Menu", exact=True).click()
    await page.keyboard.press("Escape")
    await expect(page.get_by_role("button", name="Menu", exact=True)).to_be_focused()
    await expect(page.locator(".access-toggle").first).to_be_visible()
    for selector in [
        "[data-mobile-menu]", "[data-settings-open]", ".access-toggle", "[data-panel-focus]"
    ]:
        assert await page.locator(selector).first.evaluate(
            "el => el.getBoundingClientRect().height >= 44"
        )
    ratios = await page.evaluate("""() => {
      const sample = document.createElement('span'); document.body.append(sample);
      sample.style.setProperty('transition', 'none', 'important');
      const color = token => {
        sample.style.color = `var(${token})`;
        return getComputedStyle(sample).color.match(/[\\d.]+/g).slice(0,3).map(Number);
      };
      const luminance = rgb => rgb.map(c => c/255)
        .map(c => c <= .04045 ? c/12.92 : ((c+.055)/1.055)**2.4)
        .reduce((sum,c,i) => sum+c*[.2126,.7152,.0722][i],0);
      const pairs = [
        ['--fg-primary','--bg-page'], ['--fg-secondary','--bg-surface'],
        ['--fg-muted','--bg-sunken'], ['--accent-fg','--accent'],
        ['--accent-fg','--accent-hover'], ['--accent-text','--bg-surface'],
        ['--success-fg','--success-bg'], ['--warning-fg','--warning-bg'],
        ['--danger-fg','--danger-bg'], ['--fg-terminal-dim','--bg-terminal']
      ];
      const results = pairs.map(([a,b]) => {
        const x=luminance(color(a)), y=luminance(color(b));
        return {pair:[a,b], ratio:(Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
      }); sample.remove(); return results;
    }""")
    assert all(result["ratio"] >= 4.5 for result in ratios), ratios


@pytest.mark.parametrize("width", [320, 390, 768, 1280, 1920])
async def test_workspace_telemetry_and_settings_alignment(page, mock_url, width):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator("#server-resources")).to_contain_text("CPU")
    await expect(page.locator("#server-disk")).to_contain_text("Disk")
    await expect(page.locator("#file-tree")).to_contain_text("docker-compose.yml")
    geometry = await page.evaluate("""() => {
      const rect = selector => document.querySelector(selector).getBoundingClientRect();
      const cards = Array.from(document.querySelectorAll(
        '#server-resources > .resources-strip__item, #server-disk'
      )).map(el => el.getBoundingClientRect());
      const fresh = rect('#resources-freshness');
      const identity = rect('.detail-identity__text');
      return {
        tops: cards.map(r => r.top), bottoms: cards.map(r => r.bottom),
        widths: cards.map(r => r.width),
        freshnessInIdentity: fresh.left >= identity.left && fresh.right <= identity.right
          && fresh.top >= identity.top && fresh.bottom <= identity.bottom,
        freshnessAboveCards: fresh.bottom <= Math.min(...cards.map(r => r.top)),
        flashDisplay: getComputedStyle(document.querySelector('#lifecycle-flash')).display,
        overflows: document.documentElement.scrollWidth > innerWidth
      };
    }""")
    assert not geometry["overflows"]
    assert geometry["flashDisplay"] == "none"
    assert geometry["freshnessInIdentity"] and geometry["freshnessAboveCards"], geometry
    await expect(page.locator(".workspace-toolbar")).to_be_hidden()
    await expect(page.get_by_role("button", name="Customize layout")).to_be_hidden()
    await expect(page.locator("#resources-freshness")).to_have_count(1)
    async with page.expect_response("**/servers/atm10/resources"):
        await page.evaluate(
            "htmx.trigger(document.querySelector('#server-resources'), 'mc:refresh')"
        )
    await expect(page.locator(".detail-identity__text > #resources-freshness")).to_contain_text(
        "Checked"
    )
    await expect(page.locator("#resources-freshness")).to_have_count(1)
    if width >= 768:
        assert max(geometry["tops"]) - min(geometry["tops"]) <= 1, geometry
        assert max(geometry["bottoms"]) - min(geometry["bottoms"]) <= 1, geometry
        assert abs(geometry["widths"][1] - geometry["widths"][3]) <= 1, geometry
    await page.get_by_label("More actions", exact=True).click()
    await page.get_by_role("button", name="Customize layout").click()
    await expect(page.get_by_role("button", name="Save layout", exact=True)).to_be_visible()
    inline = await page.locator(".workspace-toolbar").evaluate("""el => {
      const row = el.getBoundingClientRect();
      const controls = Array.from(el.querySelectorAll('.layout-actions button'))
        .map(button => button.getBoundingClientRect());
      return {inside: controls.every(r => r.left >= row.left && r.right <= row.right
          && r.top >= row.top && r.bottom <= row.bottom),
        centers: controls.map(r => Math.abs((r.top + r.bottom
          - controls[0].top - controls[0].bottom) / 2)),
        overflows: document.documentElement.scrollWidth > innerWidth};
    }""")
    assert inline["inside"] and not inline["overflows"], inline
    if width >= 1280:
        assert max(inline["centers"]) <= 1, inline
    async with page.expect_response("**/servers/atm10/resources"):
        await page.evaluate(
            "htmx.trigger(document.querySelector('#server-resources'), 'mc:refresh')"
        )
    await expect(page.get_by_role("button", name="Save layout", exact=True)).to_be_visible()
    await expect(page.locator("#resources-freshness")).to_have_count(1)
    await page.get_by_role("button", name="Cancel", exact=True).click()
    await expect(page.locator(".workspace-toolbar")).to_be_hidden()
    await expect(page.get_by_label("More actions", exact=True)).to_be_focused()
    screenshots = ROOT / ".localdev" / "ui-review"
    screenshots.mkdir(parents=True, exist_ok=True)
    await page.screenshot(
        path=str(screenshots / f"workspace-alignment-{width}.png"), full_page=True
    )
    await page.get_by_role("button", name="Settings", exact=True).click()
    await expect(page.locator("#server-settings")).to_be_visible()
    settings = await page.locator("#server-settings").evaluate("""el => {
      const heading = el.querySelector(':scope > header').getBoundingClientRect();
      const card = el.querySelector('.settings-section').getBoundingClientRect();
      return {width: el.getBoundingClientRect().width, headingLeft: heading.left,
        cardLeft: card.left, headingRight: heading.right, cardRight: card.right};
    }""")
    assert settings["width"] <= 960, settings
    assert abs(settings["headingLeft"] - settings["cardLeft"]) <= 1, settings
    assert abs(settings["headingRight"] - settings["cardRight"]) <= 1, settings


@pytest.mark.parametrize("width", [320, 390, 1440, 1920])
async def test_panel_customization_stays_inside_titlebar(page, mock_url, width):
    await page.set_viewport_size({"width": width, "height": 1000})
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator("#server-resources")).to_contain_text("CPU")
    headers = page.locator(".panel__bar")
    normal_heights = await headers.evaluate_all(
        "els => els.map(el => el.getBoundingClientRect().height)"
    )
    assert all(height == (52 if width < 768 else 48) for height in normal_heights)
    await page.get_by_label("More actions", exact=True).click()
    await page.get_by_role("button", name="Customize layout").click()
    geometry = await headers.evaluate_all("""headers => headers.map(header => {
      const bar = header.getBoundingClientRect();
      const controls = Array.from(header.querySelectorAll('button, input, select'));
      const rects = controls.map(el => el.getBoundingClientRect());
      const layout = header.querySelector('.panel__layout');
      const hide = header.querySelector('[data-panel-hide]').getBoundingClientRect();
      const up = header.querySelector('[data-move="-1"]').getBoundingClientRect();
      return {
        pane: header.closest('[data-pane]').dataset.pane,
        width: bar.width,
        inside: rects.every(r => r.left >= bar.left && r.right <= bar.right
          && r.top >= bar.top && r.bottom <= bar.bottom),
        nonoverlapping: rects.every((r, i) => rects.slice(i + 1).every(s =>
          r.right <= s.left || s.right <= r.left || r.bottom <= s.top || s.bottom <= r.top)),
        touchTargets: rects.every(r => r.width >= 44 && r.height >= 44),
        hideRowDelta: Math.abs(hide.top - up.top),
        layoutBackground: getComputedStyle(layout).backgroundColor,
        labels: controls.every(el => el.getAttribute('aria-label')),
        titleContained: header.querySelector('.panel__title').scrollWidth
          <= header.querySelector('.panel__title').clientWidth
      };
    })""")
    assert all(item["inside"] and item["nonoverlapping"] for item in geometry), geometry
    assert all(item["labels"] and item["titleContained"] for item in geometry), geometry
    assert all(item["layoutBackground"] == "rgba(0, 0, 0, 0)" for item in geometry)
    assert await page.locator(".panel > .panel__layout").count() == 0
    assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width < 768:
        assert all(item["touchTargets"] for item in geometry), geometry
    if width == 390:
        assert all(item["hideRowDelta"] <= 1 for item in geometry), geometry
    if width == 1440:
        assert 300 <= next(item["width"] for item in geometry if item["pane"] == "players") <= 400
    async with page.expect_response("**/servers/atm10/resources"):
        await page.evaluate("htmx.trigger('#server-resources', 'mc:refresh')")
    await expect(page.locator(".panel__bar > .panel__layout:visible")).to_have_count(3)
    screenshots = ROOT / ".localdev" / "ui-review"
    screenshots.mkdir(parents=True, exist_ok=True)
    await page.screenshot(
        path=str(screenshots / f"panel-customization-{width}.png"), full_page=True
    )
    await page.get_by_role("button", name="Cancel", exact=True).click()
    assert await headers.evaluate_all(
        "els => els.map(el => el.getBoundingClientRect().height)"
    ) == normal_heights


async def test_titlebar_layout_controls_keep_move_resize_hide_and_drag(page, mock_url):
    await page.goto(mock_url + "/servers/atm10")
    await page.get_by_label("More actions", exact=True).click()
    await page.get_by_role("button", name="Customize layout").click()
    console = page.locator('[data-pane="console"]')
    players = page.locator('[data-pane="players"]')
    first_panel = page.locator("[data-dashboard] > section").first
    await players.get_by_role("button", name="Move Players up", exact=True).click()
    await expect(first_panel).to_have_attribute("data-pane", "players")
    await players.get_by_role("button", name="Move Players down", exact=True).click()
    await expect(first_panel).to_have_attribute("data-pane", "console")
    await console.get_by_role("combobox", name="Console width").select_option("12")
    await expect(console).to_have_attribute("data-span", "12")
    height = console.get_by_role("slider", name="Console height")
    await height.focus()
    await page.keyboard.press("ArrowRight")
    await expect(console).to_have_attribute("data-height", "440")
    await players.get_by_role("button", name="Hide Players", exact=True).click()
    await expect(players).to_be_hidden()
    await expect(page.locator('[data-show-panel="players"]')).to_be_focused()
    await page.locator('[data-show-panel="players"]').check()
    await expect(players).to_be_visible()
    transfer = await page.evaluate_handle("new DataTransfer()")
    grip = players.get_by_role("button", name="Move Players", exact=True)
    await grip.dispatch_event("dragstart", {"dataTransfer": transfer})
    await expect(players).to_have_class("panel panel--dragging")
    await console.locator(".panel__bar").dispatch_event("drop", {"dataTransfer": transfer})
    await expect(first_panel).to_have_attribute("data-pane", "players")
    await expect(players).to_have_class("panel")
    await page.get_by_role("button", name="Cancel", exact=True).click()
    await expect(first_panel).to_have_attribute("data-pane", "console")
    await expect(console).to_have_attribute("data-span", "8")
    await expect(console).to_have_attribute("data-height", "420")


@pytest.mark.parametrize("width,reduced", [(390, False), (1440, False), (1440, True)])
async def test_native_panel_drag_targets_settle_and_cancel(page, mock_url, width, reduced):
    await page.set_viewport_size({"width": width, "height": 1400})
    await page.emulate_media(reduced_motion="reduce" if reduced else "no-preference")
    await page.goto(mock_url + "/servers/atm10")
    await expect(page.locator("#server-resources")).to_contain_text("CPU")
    await page.get_by_label("More actions", exact=True).click()
    await page.get_by_role("button", name="Customize layout").click()
    panels = page.locator("[data-dashboard] > section")
    for panel in await panels.all():
        await panel.locator(".panel__collapse").click()
    await page.evaluate("""() => {
      window.fixtureDropAnimations = [];
      document.addEventListener('drop', () => window.fixtureDropAnimations.push(
        document.querySelectorAll('.panel--settling').length));
      const original = DataTransfer.prototype.setDragImage;
      DataTransfer.prototype.setDragImage = function(el, x, y) {
        const rect = el.getBoundingClientRect();
        window.fixtureDragPreview = {width: rect.width, height: rect.height,
          title: el.textContent.trim(), connected: el.isConnected};
        return original.call(this, el, x, y);
      };
    }""")
    console = page.locator('[data-pane="console"]')
    files = page.locator('[data-pane="files"]')

    async def drag_to(panel, target, *, after):
        grip = await panel.locator(".panel__grip").bounding_box()
        rect = await target.bounding_box()
        assert grip and rect
        x = rect["x"] + (rect["width"] - 8 if after else 8)
        y = rect["y"] + (rect["height"] - 8 if after else 8)
        await page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
        await page.mouse.down()
        await page.mouse.move(grip["x"] + grip["width"] / 2 + 10, grip["y"] + 10, steps=3)
        await page.mouse.move(x, y, steps=12)
        await page.mouse.move(x + 1, y + 1)
        await expect(panel).to_have_class("panel panel--dragging")

    await drag_to(console, files, after=True)
    await expect(files).to_have_attribute("data-drop-edge", "bottom")
    await expect(page.locator(".is-drop-active")).to_have_count(0)
    assert await page.evaluate("window.fixtureDragPreview") == {
        "width": 220, "height": 54, "title": "Console", "connected": True
    }
    screenshots = ROOT / ".localdev" / "ui-review"
    screenshots.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(screenshots / f"panel-drag-active-{width}-{reduced}.png"))
    await page.mouse.up()
    await expect(panels.last).to_have_attribute("data-pane", "console")
    await expect(page.locator(".panel--settling")).to_have_count(0)
    counts = await page.evaluate("window.fixtureDropAnimations")
    assert counts and (counts[-1] == 0 if reduced else counts[-1] > 0), counts
    assert await panels.evaluate_all(
        "els => els.every(el => getComputedStyle(el).transform === 'none')"
    )
    await page.screenshot(path=str(screenshots / f"panel-drag-settled-{width}-{reduced}.png"))
    await drag_to(console, panels.first, after=False)
    await expect(page.locator("[data-drop-edge]")).to_have_count(1)
    await page.mouse.up()
    await expect(panels.first).to_have_attribute("data-pane", "console")
    await expect(page.locator(".panel--settling")).to_have_count(0)
    await drag_to(console, files, after=True)
    await page.keyboard.press("Escape")
    await page.mouse.up()
    await expect(panels.first).to_have_attribute("data-pane", "console")
    await expect(
        page.locator(".panel--dragging, [data-drop-edge], .panel-drag-preview")
    ).to_have_count(0)
    await drag_to(console, files, after=True)
    await page.mouse.move(2, 2, steps=6)
    await expect(page.locator("[data-drop-edge]")).to_have_count(0)
    await page.mouse.up()
    await expect(panels.first).to_have_attribute("data-pane", "console")
    await expect(page.locator(".panel--dragging, .panel-drag-preview")).to_have_count(0)
    await page.get_by_role("button", name="Cancel", exact=True).click()
    await expect(console).to_have_attribute("data-collapsed", "false")
    if width == 1440 and not reduced:
        await page.get_by_label("More actions", exact=True).click()
        await page.get_by_role("button", name="Customize layout").click()
        players = page.locator('[data-pane="players"]')
        await drag_to(console, players, after=True)
        await expect(players).to_have_attribute("data-drop-edge", "right")
        await page.screenshot(path=str(screenshots / "panel-drag-expanded-active.png"))
        await page.mouse.up()
        await expect(panels.first).to_have_attribute("data-pane", "players")
        await expect(page.locator(".panel--settling")).to_have_count(0)
        await page.screenshot(path=str(screenshots / "panel-drag-expanded-settled.png"))
        await page.get_by_role("button", name="Cancel", exact=True).click()
        await expect(panels.first).to_have_attribute("data-pane", "console")
