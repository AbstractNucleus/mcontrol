"""Browser checks for jar selection and actionable migration errors; no live services."""

import os

import pytest
from playwright.async_api import expect

from mcontrol.templates import templates
from tests.browser.test_workspace import mock_url as mock_url
from tests.browser.test_workspace import page as page

pytestmark = pytest.mark.skipif(
    os.environ.get("MCONTROL_BROWSER_TESTS") != "1", reason="opt-in local mock browser tests"
)


async def test_migration_empty_picker_explains_where_to_add_jar(page, mock_url):
    await page.goto(mock_url + "/servers/atm10")
    await page.get_by_role("button", name="Settings", exact=True).click()
    picker = page.locator('#migrate-card select[name="server_jar"]')
    await expect(picker).to_be_visible()
    await expect(picker).to_contain_text("No .jar files found")
    await expect(page.locator("#migrate-card")).to_contain_text("server/")


async def test_migration_picker_and_conflict_keep_actionable_error_visible(page, mock_url):
    form = {"memory_budget_gb": 8, "port": 25567, "server_jar": "paper.jar",
            "java_version": 21, "jvm_extra_args": ""}
    message = "Custom startup arguments require review before migration. No files were changed."

    def card(error=None):
        return templates.get_template("_migrate_card.html").render(
            server={"name": "vault-hunters"}, form=form, errors={}, error_banner=error,
            running=False, legacy_filenames=["Dockerfile", ".env"], memory_min_gb=3,
            java_versions=[17, 21, 25], default_java_version=21,
            jar_options=["fabric.jar", "paper.jar"],
        )

    async def intercept(route):
        if route.request.method == "POST":
            assert "server_jar=fabric.jar" in route.request.post_data
            form["server_jar"] = "fabric.jar"
            await route.fulfill(status=409, content_type="text/html", body=card(message))
        else:
            await route.fulfill(status=200, content_type="text/html", body=card())

    await page.route("**/servers/vault-hunters/migrate", intercept)
    await page.goto(mock_url + "/servers/vault-hunters")
    await page.get_by_role("button", name="Settings", exact=True).click()
    picker = page.locator('#migrate-card select[name="server_jar"]')
    await expect(picker).to_have_value("paper.jar")
    await picker.select_option("fabric.jar")
    await page.locator('#migrate-card button[type="submit"]').click()
    await expect(page.locator(".migrate-card__error")).to_have_text(message)
    await expect(picker).to_have_value("fabric.jar")
