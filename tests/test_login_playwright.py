import os
import re
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5000")


def _login_admin(page):
    page.goto(f"{BASE_URL}/admin/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "admin123")
    page.click('button[type="submit"]')

    # Fresh databases can force password change on first login.
    page.wait_for_url(re.compile(r".*/(track|change-password)"), timeout=10000)
    if page.url.endswith("/change-password"):
        page.fill('input[name="new_password"]', "admin123")
        page.fill('input[name="confirm_password"]', "admin123")
        page.click('button[type="submit"]')
        page.wait_for_url(re.compile(r".*/track"), timeout=10000)


def test_login_success():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        _login_admin(page)
        assert page.url.endswith("/track") or "logout" in page.content().lower()
        browser.close()
