# RecoveryNote Local Development

## Environment Setup
1. Copy `.env.example` to `.env` and fill in your database credentials and secret key.
2. Install dependencies:
   ```sh
   pip install -r requirements.txt
   pip install python-dotenv playwright
   python -m playwright install
   ```

## Database Setup
- The app auto-creates tables and seeds default users (`admin`/`admin123`, `user`/`user123`) if the database is empty.
- To manually inspect or reset users, use `psql`:
  ```sh
  psql <your-db-url>
  SELECT * FROM users;
  DELETE FROM users;
  ```

## Running Tests
- Unit tests: `pytest`
- Playwright login test: `pytest tests/test_login_playwright.py`

## Code Quality Automation
1. Install dev tools:
  ```sh
  pip install -r requirements-dev.txt
  ```
2. Enable pre-commit hooks:
  ```sh
  pre-commit install
  ```
3. Run all checks locally:
  ```sh
  pre-commit run --all-files
  black --check .
  ruff check .
  mypy --ignore-missing-imports app.py tests tools
  pytest -q --ignore=tests/test_login_playwright.py
  ```

GitHub Actions now runs these checks on pushes and pull requests via `.github/workflows/ci.yml`.

## Azure Slot Release (Safe Deploy)
This repo includes a manual slot-release workflow in `.github/workflows/azure-slot-release.yml`.

### Prerequisites
1. App Service Plan must be Standard or higher (Basic B1 does not support slots).
2. Create staging slot:
  ```sh
  az appservice plan update --name recoverynote-plan --resource-group rg-recoverynote-dev --sku S1
  az webapp deployment slot create --name recoverynote-gyjdtex5 --resource-group rg-recoverynote-dev --slot staging --configuration-source recoverynote-gyjdtex5
  ```
3. Add repository secret `AZURE_WEBAPP_PUBLISH_PROFILE_STAGING` (publish profile for staging slot).
4. Add repository secret `AZURE_CREDENTIALS` (service principal JSON with permissions to swap slots).
  This requires RBAC permission to create role assignments on the subscription/resource group.

### Usage
1. Run GitHub workflow `Azure Slot Release`.
2. Choose `promote_to_production=false` to deploy and smoke-test staging only.
3. Re-run with `promote_to_production=true` to swap staging to production.

### Rollback
If needed, run another slot swap to move production back:
```sh
az webapp deployment slot swap --name recoverynote-gyjdtex5 --resource-group rg-recoverynote-dev --slot staging --target-slot production
```

## Troubleshooting
- If login fails, check `.env` and database connection.
- Errors are logged to the console for database issues.
