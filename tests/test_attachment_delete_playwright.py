import json
import os
import re
import shutil
from datetime import date

import pytest
from playwright.sync_api import sync_playwright

import app as app_module

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:5000")


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


def _create_submission_with_attachment(filename):
    payload = {
        "AGREEMENT_AUTHOR": "playwright.user",
        "COMMENTS": "Attachment delete e2e",
        "_created_at": date.today().isoformat(),
        "_attachments": [{"name": filename, "stored": filename}],
    }

    try:
        with app_module.db_cursor() as cur:
            cur.execute(
                "INSERT INTO submissions (data, created_at) VALUES (%s, %s) RETURNING id",
                (json.dumps(payload), date.today()),
            )
            submission_id = cur.fetchone()[0]
    except Exception as exc:
        pytest.skip(f"Could not create e2e submission fixture: {exc}")

    upload_dir = app_module._submission_upload_dir(submission_id)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "w", encoding="utf-8") as fh:
        fh.write("playwright attachment delete test")

    return submission_id


def _cleanup_submission(submission_id):
    if not submission_id:
        return

    try:
        with app_module.db_cursor() as cur:
            cur.execute("DELETE FROM submissions WHERE id = %s", (submission_id,))
    except Exception:
        pass

    try:
        shutil.rmtree(app_module._submission_upload_dir(submission_id), ignore_errors=True)
    except Exception:
        pass


def test_edit_attachment_delete_now_removes_attachment():
    filename = "playwright-delete-me.txt"
    submission_id = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        _login_admin(page)
        submission_id = _create_submission_with_attachment(filename)

        try:
            page.goto(f"{BASE_URL}/edit/{submission_id}")
            page.wait_for_selector(
                f'button.delete-attachment-now[value="{filename}"]', timeout=10000
            )

            download_selector = (
                f'a[href="/attachments/{submission_id}/{filename}"]'
            )
            assert page.locator(download_selector).count() == 1

            page.once("dialog", lambda dialog: dialog.accept())
            page.click(f'button.delete-attachment-now[value="{filename}"]')

            page.wait_for_url(re.compile(rf".*/edit/{submission_id}$"), timeout=10000)
            page.wait_for_selector("text=Attachment removed.", timeout=10000)
            assert page.locator(download_selector).count() == 0

            response = page.request.get(f"{BASE_URL}/submissions")
            assert response.ok
            rows = response.json()
            record = next((r for r in rows if r.get("id") == submission_id), None)
            assert record is not None
            assert (record.get("_attachments") or []) == []

            file_path = os.path.join(
                app_module._submission_upload_dir(submission_id), filename
            )
            assert not os.path.exists(file_path)
        finally:
            browser.close()
            _cleanup_submission(submission_id)


def test_edit_attachment_delete_now_can_be_undone():
    filename = "playwright-undo-me.txt"
    submission_id = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        _login_admin(page)
        submission_id = _create_submission_with_attachment(filename)

        try:
            page.goto(f"{BASE_URL}/edit/{submission_id}")
            page.wait_for_selector(
                f'button.delete-attachment-now[value="{filename}"]', timeout=10000
            )

            download_selector = f'a[href="/attachments/{submission_id}/{filename}"]'
            assert page.locator(download_selector).count() == 1

            page.once("dialog", lambda dialog: dialog.accept())
            page.click(f'button.delete-attachment-now[value="{filename}"]')

            page.wait_for_url(re.compile(rf".*/edit/{submission_id}$"), timeout=10000)
            page.wait_for_selector("text=Attachment removed.", timeout=10000)
            page.wait_for_selector('button[name="_undo_attachment_delete"]', timeout=10000)
            assert page.locator(download_selector).count() == 0

            page.click('button[name="_undo_attachment_delete"]')
            page.wait_for_url(re.compile(rf".*/edit/{submission_id}$"), timeout=10000)
            page.wait_for_selector("text=Attachment restored.", timeout=10000)
            assert page.locator(download_selector).count() == 1

            response = page.request.get(f"{BASE_URL}/submissions")
            assert response.ok
            rows = response.json()
            record = next((r for r in rows if r.get("id") == submission_id), None)
            assert record is not None

            attachments = record.get("_attachments") or []
            stored_names = {a.get("stored") for a in attachments if isinstance(a, dict)}
            assert filename in stored_names

            file_path = os.path.join(
                app_module._submission_upload_dir(submission_id), filename
            )
            assert os.path.exists(file_path)
        finally:
            browser.close()
            _cleanup_submission(submission_id)
