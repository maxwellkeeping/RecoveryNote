import os
import re

import pytest
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5000")


AGREEMENT_PATTERN = re.compile(r"^[A-Z]+-\d{8}-RN\d+$")


def _login_admin(page):
    page.goto(f"{BASE_URL}/admin/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "admin123")
    page.click('button[type="submit"]')

    page.wait_for_url(re.compile(r".*/(track|change-password)"), timeout=10000)
    if page.url.endswith("/change-password"):
        page.fill('input[name="new_password"]', "admin123")
        page.fill('input[name="confirm_password"]', "admin123")
        page.click('button[type="submit"]')
        page.wait_for_url(re.compile(r".*/track"), timeout=10000)


def test_edit_mode_agreement_id_does_not_duplicate_fy():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Authenticate using the local admin path used in local/dev environments.
        _login_admin(page)

        # Find a submission that has an Agreement ID we can validate in edit mode.
        resp = page.request.get(f"{BASE_URL}/submissions")
        assert resp.ok, "Could not fetch submissions for regression setup."
        rows = resp.json()

        candidate = None
        for row in rows:
            aid = (row or {}).get("AGREEMENT_ID")
            if aid and AGREEMENT_PATTERN.match(aid):
                candidate = row
                break

        if candidate is None:
            browser.close()
            pytest.skip("No submission with a parsable AGREEMENT_ID found for regression check.")

        page.goto(f"{BASE_URL}/edit/{candidate['id']}")
        page.wait_for_selector("#field-AGREEMENT_ID")

        original_id = page.input_value("#field-AGREEMENT_ID")
        assert AGREEMENT_PATTERN.match(original_id), "Edit form did not load a valid AGREEMENT_ID."

        fy_value = page.input_value("#aid-fyend")
        assert fy_value and len(fy_value) == 2, "FY control did not initialize as expected."

        fy_options = page.eval_on_selector_all(
            "#aid-fyend option", "opts => opts.map(o => o.value)"
        )
        alt_fy = next((v for v in fy_options if v and v != fy_value), None)

        if alt_fy:
            page.select_option("#aid-fyend", alt_fy)
            page.select_option("#aid-fyend", fy_value)
        else:
            # Ensure compose() is exercised even if only one FY option exists.
            page.eval_on_selector(
                "#aid-fyend",
                "el => el.dispatchEvent(new Event('change', { bubbles: true }))",
            )

        recomposed_id = page.input_value("#field-AGREEMENT_ID")
        assert (
            recomposed_id == original_id
        ), f"AGREEMENT_ID changed unexpectedly after FY recomposition: {original_id} -> {recomposed_id}"

        browser.close()
