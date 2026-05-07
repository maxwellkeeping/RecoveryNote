from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    make_response,
    send_file,
    send_from_directory,
    abort,
)
import csv
import io
import json
import os
import re
import sys
import hashlib
from contextlib import contextmanager
from datetime import date
from functools import wraps

import psycopg2
import psycopg2.extras
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.utils import secure_filename
from tools import generate_docx

# --- Load .env if present ---
try:
    from dotenv import load_dotenv

    # Prefer project .env values for local development to avoid stale shell vars.
    load_dotenv(override=True)
except ImportError:
    print(
        "WARNING: python-dotenv not installed; .env support unavailable.",
        file=sys.stderr,
    )

APP_DIR = os.path.dirname(__file__)

# Config JSON files — override with DATA_DIR env var (defaults to app directory)
_DATA_DIR = os.environ.get("DATA_DIR", APP_DIR)
FG_PATH = os.path.join(_DATA_DIR, "field_groups.json")
LOOKUP_PATH = os.path.join(_DATA_DIR, "field_lookups.json")
LOOKUP_MAP = os.path.join(_DATA_DIR, "lookup_mappings.json")
UPLOADS_DIR = os.path.join(APP_DIR, "uploads")

# PostgreSQL connection string — set DATABASE_URL in environment.
# Read dynamically on each call so Key Vault references that resolve after
# startup are picked up, and so a missing value at boot doesn't crash the app.
DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
# expose sanitize helper to templates
app.jinja_env.globals["sanitize_name"] = lambda s: re.sub(
    r"[^0-9A-Za-z]+", "_", s
).strip("_")

# ── Flask-Login setup ────────────────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"


class User(UserMixin):
    def __init__(self, id, username, role, must_change_password=False):
        self.id = id
        self.username = username
        self.role = role
        self.must_change_password = must_change_password

    @property
    def is_admin(self):
        return self.role == "admin"


@login_manager.user_loader
def load_user(user_id):
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, username, role, must_change_password FROM users WHERE id = %s",
                (int(user_id),),
            )
            row = cur.fetchone()
        if row:
            return User(row[0], row[1], row[2], row[3])
    except Exception:
        pass
    return None


def admin_required(f):
    """Decorator: requires login + admin role."""

    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash("Admin access required.", "danger")
            return redirect(url_for("track"))
        return f(*args, **kwargs)

    return decorated


def hash_password(password):
    """Simple SHA-256 hash. Adequate for PoC; upgrade to bcrypt for production."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


@contextmanager
def db_cursor():
    """Yield a psycopg2 cursor; commits on clean exit, rolls back on error. Improved error logging."""
    dsn = os.environ.get("DATABASE_URL") or DATABASE_URL
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
    except Exception as e:
        print(f"ERROR: Could not connect to database: {e}", file=sys.stderr)
        raise
    try:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"ERROR: Database operation failed: {e}", file=sys.stderr)
            raise
        finally:
            cur.close()
    finally:
        conn.close()


def init_db():
    """Create the submissions and users tables if they do not yet exist."""
    with db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id          SERIAL PRIMARY KEY,
                data        JSONB  NOT NULL,
                created_at  DATE   NOT NULL DEFAULT CURRENT_DATE
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id                    SERIAL PRIMARY KEY,
                username              VARCHAR(100) UNIQUE NOT NULL,
                password              VARCHAR(256) NOT NULL,
                role                  VARCHAR(20)  NOT NULL DEFAULT 'user',
                must_change_password  BOOLEAN NOT NULL DEFAULT TRUE
            )
        """
        )
        # Migrate: add must_change_password column if missing (existing DBs)
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'must_change_password'
                ) THEN
                    ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT TRUE;
                END IF;
            END $$;
        """
        )
        # Flat view for Power BI / reporting (CREATE OR REPLACE so it upgrades on restart)
        cur.execute(
            """
            CREATE OR REPLACE VIEW submissions_flat AS
            SELECT
                s.id,
                s.created_at,
                s.data->>'AGREEMENT_ID'                    AS agreement_id,
                s.data->>'AGREEMENT_NAME_DESCRIPTION'      AS agreement_name_description,
                s.data->>'AGREEMENT_TYPE'                  AS agreement_type,
                s.data->>'AGREEMENT_AUTHOR'                AS agreement_author,
                s.data->>'STATUS'                          AS status,
                s.data->>'CLIENT_CONTACT_NAME'             AS client_contact_name,
                s.data->>'PREVIOUS_AGREEMENT'              AS previous_agreement,
                s.data->>'eApprovals_Package_ID_253_YYYY'  AS eapprovals_package_id,
                (s.data->>'START_DATE_YYYY_MM_DD')::DATE   AS start_date,
                (s.data->>'END_DATE_YYYY_MM_DD')::DATE     AS end_date,
                (s.data->>'ONE_TIME')::NUMERIC             AS one_time,
                (s.data->>'ANNUAL')::NUMERIC               AS annual,
                (s.data->>'MONTHLY_RECURRING')::NUMERIC    AS monthly_recurring,
                (s.data->>'TOTAL_RECOVERY')::NUMERIC       AS total_recovery,
                (s.data->>'ACTIVE_CARRY_TO_NEXT_FY')::NUMERIC AS active_carry_to_next_fy,
                (s.data->>'FISCAL_YEAR_MONTHS')::INTEGER   AS fiscal_year_months,
                (s.data->>'AGREEMENT_MONTHS_optional')::INTEGER AS agreement_months,
                s.data->>'MONTH_BILLED'                    AS month_billed,
                s.data->>'NEXT_FISCAL_RENEWAL'             AS next_fiscal_renewal,
                s.data->>'SERVICE_OWNER'                   AS service_owner,
                s.data->>'ITS_SERVICE'                     AS its_service,
                s.data->>'ITS_SERVICE_TYPE'                AS its_service_type,
                s.data->>'SOLUTION_CI'                     AS solution_ci,
                s.data->>'IFIS_CODE'                       AS ifis_code,
                s.data->>'SERVICE_OWNER_CONTACT_NAME'      AS service_owner_contact_name,
                s.data->>'COMMENTS'                        AS comments
            FROM submissions s;
        """
        )

        # Seed default accounts if users table is empty
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO users (username, password, role, must_change_password) VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)",
                (
                    "admin",
                    hash_password("admin123"),
                    "admin",
                    True,
                    "user",
                    hash_password("user123"),
                    "user",
                    True,
                ),
            )


_db_initialized = False


@app.before_request
def ensure_db():
    """Lazily initialise the database on the first request instead of at
    startup so a slow or temporarily-unavailable database does not prevent
    the gunicorn worker from booting.
    """
    global _db_initialized
    if not _db_initialized:
        try:
            init_db()
            _db_initialized = True
        except Exception as _db_err:
            print(f"WARNING: database init failed: {_db_err}", file=sys.stderr)


@app.before_request
def enforce_password_change():
    """Redirect users who must change their password to the change-password page."""
    if current_user.is_authenticated and current_user.must_change_password:
        allowed = ("change_password", "logout", "static")
        if request.endpoint not in allowed:
            flash("You must change your password before continuing.", "warning")
            return redirect(url_for("change_password"))


def sanitize_name(s):
    return re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_")


def _parse_amount(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _comments_amount(values):
    for key in ("TOTAL_RECOVERY", "MONTHLY_RECURRING", "ANNUAL", "ONE_TIME"):
        amount = _parse_amount((values or {}).get(key, ""))
        if amount is not None:
            return f"${amount:,.2f}"
    return "<$>"


def build_comments_text(values=None):
    values = values or {}
    cluster = (values.get("SERVICE_OWNER", "") or "").strip() or "<CLUSTER>"
    amount = _comments_amount(values)
    return (
        "Please accept this Recovery Note (RN) as authorization for GovTechON (GTO), "
        "Infrastructure Technology Operations Division (ITOD) to invoice "
        f"{cluster}, <MINISTRY> the amount of {amount} under the cost center identified "
        "for <SPECIFY>.\n\n"
        "<PROVIDE DETAILS ON THE BUSINESS SOLUTION, RATIONALE, WIA/PROJECT AT A HIGH LEVEL "
        "AND 2 TO 3 SENTENCES AT THE MOST>"
    )


def save_attachments(submission_id, files, existing=None):
    """Save uploaded files under uploads/<submission_id>/ and return metadata list."""
    existing = existing or []
    if not files:
        return existing

    target_dir = os.path.join(UPLOADS_DIR, str(submission_id))
    os.makedirs(target_dir, exist_ok=True)

    out = list(existing)
    existing_names = {x.get("stored", "") for x in out}
    for f in files:
        if not f or not getattr(f, "filename", ""):
            continue
        original = f.filename
        base = secure_filename(original)
        if not base:
            continue

        stem, ext = os.path.splitext(base)
        candidate = base
        n = 1
        while candidate in existing_names or os.path.exists(
            os.path.join(target_dir, candidate)
        ):
            candidate = f"{stem}_{n}{ext}"
            n += 1

        f.save(os.path.join(target_dir, candidate))
        existing_names.add(candidate)
        out.append({"name": original, "stored": candidate})

    return out


def _norm_label(s):
    return re.sub(r"\s+", " ", (s or "").replace("\n", " ")).strip()


def read_lookup_config():
    """Load lookup values and metadata from field_lookups.json."""
    raw = {}
    if os.path.exists(LOOKUP_PATH):
        with open(LOOKUP_PATH, "r", encoding="utf-8") as lf:
            raw = json.load(lf)

    cascade_field_map = {
        _norm_label(k): _norm_label(v)
        for k, v in (raw.get("_cascade_fields", {}) or {}).items()
    }

    inactive_map = {}
    for key, vals in (raw.get("_inactive", {}) or {}).items():
        nk = _norm_label(key)
        if not isinstance(vals, list):
            continue
        inactive_map[nk] = [_norm_label(v) for v in vals if _norm_label(v)]

    lookups = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        lookups[_norm_label(key)] = value

    return lookups, cascade_field_map, inactive_map


def write_lookup_config(lookups, cascade_field_map, inactive_map):
    payload = {}
    for key in sorted(lookups.keys()):
        payload[key] = lookups[key]
    if cascade_field_map:
        payload["_cascade_fields"] = cascade_field_map

    cleaned_inactive = {}
    for key, vals in inactive_map.items():
        uniq = sorted({_norm_label(v) for v in vals if _norm_label(v)})
        if uniq:
            cleaned_inactive[_norm_label(key)] = uniq
    if cleaned_inactive:
        payload["_inactive"] = cleaned_inactive

    with open(LOOKUP_PATH, "w", encoding="utf-8") as lf:
        json.dump(payload, lf, indent=2, ensure_ascii=False)


def _active_lookup_value(lookup_key, lookup_val, inactive_map):
    if isinstance(lookup_val, list):
        inactive = set(inactive_map.get(_norm_label(lookup_key), []))
        return [x for x in lookup_val if _norm_label(x) not in inactive]
    if isinstance(lookup_val, dict):
        parent_inactive = set(inactive_map.get(_norm_label(lookup_key), []))
        out = {}
        for parent, children in lookup_val.items():
            if _norm_label(parent) in parent_inactive:
                continue
            if isinstance(children, list):
                child_key = _norm_label(f"{lookup_key}::{parent}")
                child_inactive = set(inactive_map.get(child_key, []))
                out[parent] = [c for c in children if _norm_label(c) not in child_inactive]
            else:
                out[parent] = children
        return out
    return lookup_val


def _add_lookup_option(lookups, lookup_key, value, cascade_parent=""):
    lookup_key = _norm_label(lookup_key)
    value = _norm_label(value)
    cascade_parent = _norm_label(cascade_parent)
    if not lookup_key or not value:
        return False, "Lookup key and value are required."

    current = lookups.get(lookup_key)
    if cascade_parent:
        if not isinstance(current, dict):
            return False, "Selected lookup is not a cascading lookup."
        children = current.get(cascade_parent)
        if children is None:
            current[cascade_parent] = []
            children = current[cascade_parent]
        if not isinstance(children, list):
            return False, "Cascade parent does not contain a list of options."
        if value not in children:
            children.append(value)
        return True, "Option added."

    if current is None:
        lookups[lookup_key] = [value]
        return True, "Option added."
    if not isinstance(current, list):
        return False, "Selected lookup is not a simple list."
    if value not in current:
        current.append(value)
    return True, "Option added."


def _toggle_lookup_option(inactive_map, lookup_key, value, cascade_parent="", hide=True):
    lookup_key = _norm_label(lookup_key)
    value = _norm_label(value)
    cascade_parent = _norm_label(cascade_parent)
    if not lookup_key or not value:
        return False, "Lookup key and value are required."

    state_key = _norm_label(f"{lookup_key}::{cascade_parent}") if cascade_parent else lookup_key
    state = set(inactive_map.get(state_key, []))
    if hide:
        state.add(value)
    else:
        state.discard(value)
    if state:
        inactive_map[state_key] = sorted(state)
    elif state_key in inactive_map:
        del inactive_map[state_key]
    return True, "Option updated."


COPY_REMOVE_FIELDS = ("AGREEMENT_ID", "_created_at", "_attachments", "_upload_id")
DEFAULT_COPY_CLEAR_FIELDS = {
    "END_DATE_YYYY_MM_DD",
    "TERMINATION_DATE_YYYY_MM_DD",
    "TERMINATION_REASON",
    "TERMINATION_NOTES",
    "CLOSURE_DATE_YYYY_MM_DD",
    "CLOSURE_REASON",
    "CLOSURE_NOTES",
    "CLOSED_DATE_YYYY_MM_DD",
    "CLOSE_DATE_YYYY_MM_DD",
    "CLOSE_REASON",
    "CLOSE_NOTES",
    "EXPIRY_DATE_YYYY_MM_DD",
    "EXPIRED_DATE_YYYY_MM_DD",
    "EXPIRY_REASON",
    "EXPIRY_NOTES",
}


def get_copy_clear_fields():
    """Resolve copy-clear field names from field_groups.json when configured."""
    try:
        with open(FG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set(DEFAULT_COPY_CLEAR_FIELDS)

    if "copy_clear_fields" not in data:
        return set(DEFAULT_COPY_CLEAR_FIELDS)

    configured = data.get("copy_clear_fields")
    if not isinstance(configured, list):
        return set(DEFAULT_COPY_CLEAR_FIELDS)

    out = set()
    for field in configured:
        text = str(field or "").strip()
        if not text:
            continue
        out.add(text)
        out.add(sanitize_name(text))
    return out


def prepare_copy_values(source_values):
    """Prepare values for a copied agreement as a new draft submission."""
    copied = dict(source_values or {})
    source_agreement_id = (copied.get("AGREEMENT_ID") or "").strip()

    for key in COPY_REMOVE_FIELDS:
        copied.pop(key, None)

    copied["STATUS"] = "Draft"
    if source_agreement_id:
        copied["PREVIOUS_AGREEMENT"] = source_agreement_id

    for key in get_copy_clear_fields():
        if key in copied:
            copied[key] = ""

    return copied


def load_field_groups():
    with open(FG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    groups = data.get("groups", {})
    mandatory = set(data.get("proposed_mandatory", []))
    field_hints = data.get("field_hints", {})

    field_hints_norm = {_norm_label(k): v for k, v in field_hints.items()}
    lookups, cascade_field_map, inactive_map = read_lookup_config()
    mapping = {}
    if os.path.exists(LOOKUP_MAP):
        try:
            with open(LOOKUP_MAP, "r", encoding="utf-8") as mf:
                raw_mapping = json.load(mf)
                mapping = {
                    _norm_label(k): _norm_label(v) for k, v in raw_mapping.items()
                }
        except Exception:
            mapping = {}
    # normalize groups into list of (group_name, [ {label,name,required,...} ])
    out = []
    month_field_sources = {
        "FISCAL YEAR # MONTHS": {
            "primary": "# FISCAL MONTHS",
            "fallback": "# FISCAL MONTHS",
            "cap": 12,
        },
        "AGREEMENT # MONTHS (optional)": {
            "primary": "# AGREEMENT MONTHS",
            "fallback": "# FISCAL MONTHS",
            "cap": None,
        },
    }
    for gname, fields in groups.items():
        items = []
        for h in fields:
            if not h:
                continue
            label = _norm_label(h)
            mapped_key = mapping.get(label)
            resolved_lookup_key = mapped_key or label
            if not mapped_key and label in month_field_sources:
                source_cfg = month_field_sources[label]
                primary_key = source_cfg["primary"]
                fallback_key = source_cfg.get("fallback")
                if primary_key in lookups:
                    resolved_lookup_key = primary_key
                elif fallback_key and fallback_key in lookups:
                    resolved_lookup_key = fallback_key
            options = None
            cascade_data = None
            parent_label = cascade_field_map.get(label)
            cascade_from = sanitize_name(parent_label) if parent_label else None
            lookup_val = lookups.get(resolved_lookup_key)
            if cascade_from:
                # This is a cascade child — get cascade data from parent's lookup
                parent_mapped = mapping.get(parent_label)
                parent_lookup_key = parent_mapped or parent_label
                parent_lookup = (
                    lookups.get(parent_mapped)
                    if parent_mapped
                    else lookups.get(parent_label)
                )
                if isinstance(parent_lookup, dict):
                    cascade_data = _active_lookup_value(
                        parent_lookup_key, parent_lookup, inactive_map
                    )
                    options = []  # options populated dynamically via JS
            elif isinstance(lookup_val, dict):
                # This is a cascade parent — show top-level keys as options
                options = list(
                    _active_lookup_value(
                        resolved_lookup_key, lookup_val, inactive_map
                    ).keys()
                )
            else:
                options = _active_lookup_value(
                    resolved_lookup_key, lookup_val, inactive_map
                )
            if isinstance(options, list):

                def _fix_govtech(s):
                    if "GovTech ON - Cyber Security" in s and "(CSD)" not in s:
                        return s.replace(
                            "GovTech ON - Cyber Security",
                            "GovTech ON - Cyber Security (CSD)",
                        )
                    if (
                        "GovTech ON - Technology Policy & Standards Development" in s
                        and "(TPSD)" not in s
                    ):
                        return s.replace(
                            "GovTech ON - Technology Policy & Standards Development",
                            "GovTech ON - Technology Policy & Standards Development (TPSD)",
                        )
                    return s

                options = [_fix_govtech(x) for x in options]
            hint_data = field_hints.get(label) or field_hints_norm.get(
                _norm_label(label), {}
            )
            input_type = hint_data.get("input_type", "text")
            input_min = hint_data.get("min", "")
            input_max = hint_data.get("max", "")
            placeholder = hint_data.get("placeholder", "")

            # For month count inputs, keep max aligned with numeric lookup values.
            if input_type == "number" and isinstance(lookup_val, list):
                numeric_vals = []
                for raw in lookup_val:
                    text = str(raw or "").strip()
                    if not text or not re.fullmatch(r"-?\d+", text):
                        numeric_vals = []
                        break
                    numeric_vals.append(int(text))
                if numeric_vals:
                    derived_max = max(numeric_vals)
                    if label in month_field_sources:
                        cap = month_field_sources[label].get("cap")
                        if isinstance(cap, int) and cap > 0:
                            derived_max = min(derived_max, cap)
                    if derived_max > 0:
                        input_max = str(derived_max)
                        min_text = str(input_min).strip() or "1"
                        placeholder = f"{min_text} - {input_max}"

            items.append(
                {
                    "label": hint_data.get("display_label", label),
                    "source_label": label,
                    "name": sanitize_name(h),
                    "required": h in mandatory,
                    "options": options,
                    "cascade_data": cascade_data,
                    "cascade_from": cascade_from,
                    "placeholder": placeholder,
                    "hint": hint_data.get("hint", ""),
                    "compound": hint_data.get("compound", ""),
                    "input_type": input_type,
                    "input_min": input_min,
                    "input_max": input_max,
                    "input_step": hint_data.get("step", ""),
                    "input_mask": hint_data.get("input_mask", ""),
                }
            )
        if items:
            out.append((gname, items))
    return out


@app.route("/export/csv")
@admin_required
def export_csv():
    """Download all submissions as a flat CSV file (admin only)."""
    groups = load_field_groups()
    field_names = [it["name"] for _, items in groups for it in items]
    headers = ["id", "created_at"] + field_names

    with db_cursor() as cur:
        cur.execute("SELECT id, created_at, data FROM submissions ORDER BY id")
        rows = cur.fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row_id, created_at, data in rows:
        d = data if isinstance(data, dict) else json.loads(data)
        writer.writerow([row_id, created_at] + [d.get(f, "") for f in field_names])

    response = make_response(buf.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        "attachment; filename=submissions_export.csv"
    )
    return response


@app.route("/map-lookups", methods=["GET", "POST"])
@admin_required
def map_lookups():
    lookups, cascade_map, inactive_map = read_lookup_config()
    field_usage = {}

    try:
        with open(FG_PATH, "r", encoding="utf-8") as f:
            groups_data = json.load(f).get("groups", {})
    except Exception:
        groups_data = {}

    mapping = {}
    if os.path.exists(LOOKUP_MAP):
        try:
            with open(LOOKUP_MAP, "r", encoding="utf-8") as mf:
                raw_mapping = json.load(mf)
                mapping = {
                    _norm_label(k): _norm_label(v) for k, v in raw_mapping.items()
                }
        except Exception:
            mapping = {}

    for fields in groups_data.values():
        if not isinstance(fields, list):
            continue
        for label in fields:
            nlabel = _norm_label(label)
            if not nlabel:
                continue
            resolved_lookup = mapping.get(nlabel, nlabel)
            field_usage.setdefault(resolved_lookup, set()).add(nlabel)

    for child_label, parent_label in cascade_map.items():
        parent = _norm_label(parent_label)
        child = _norm_label(child_label)
        if not parent or not child:
            continue
        parent_lookup = mapping.get(parent, parent)
        field_usage.setdefault(parent_lookup, set()).add(child)

    if request.method == "POST":
        action = request.form.get("_action", "")

        lookup_key = request.form.get("lookup_key", "")
        lookup_value = request.form.get("lookup_value", "")
        cascade_parent = request.form.get("cascade_parent", "")

        if action == "lookup_add":
            ok, msg = _add_lookup_option(lookups, lookup_key, lookup_value, cascade_parent)
            if ok:
                _toggle_lookup_option(
                    inactive_map,
                    lookup_key,
                    lookup_value,
                    cascade_parent=cascade_parent,
                    hide=False,
                )
                write_lookup_config(lookups, cascade_map, inactive_map)
                flash(msg, "success")
            else:
                flash(msg, "danger")
            return redirect(url_for("map_lookups"))

        if action in ("lookup_hide", "lookup_unhide"):
            ok, msg = _toggle_lookup_option(
                inactive_map,
                lookup_key,
                lookup_value,
                cascade_parent=cascade_parent,
                hide=(action == "lookup_hide"),
            )
            if ok:
                write_lookup_config(lookups, cascade_map, inactive_map)
                flash(msg, "success")
            else:
                flash(msg, "danger")
            return redirect(url_for("map_lookups"))

        flash("Unknown lookup action.", "danger")
        return redirect(url_for("map_lookups"))

    lookup_items = []
    for key in sorted(lookups.keys()):
        value = lookups[key]
        if isinstance(value, list):
            inactive = set(inactive_map.get(_norm_label(key), []))
            options = [
                {"value": v, "active": _norm_label(v) not in inactive} for v in value
            ]
            lookup_items.append(
                {
                    "key": key,
                    "kind": "list",
                    "options": options,
                    "parents": [],
                    "used_by": sorted(field_usage.get(key, set())),
                }
            )
        elif isinstance(value, dict):
            parent_inactive = set(inactive_map.get(_norm_label(key), []))
            parents = []
            for parent_name, children in value.items():
                child_state_key = _norm_label(f"{key}::{parent_name}")
                child_inactive = set(inactive_map.get(child_state_key, []))
                child_options = []
                if isinstance(children, list):
                    child_options = [
                        {
                            "value": c,
                            "active": _norm_label(c) not in child_inactive,
                        }
                        for c in children
                    ]
                parents.append(
                    {
                        "name": parent_name,
                        "active": _norm_label(parent_name) not in parent_inactive,
                        "children": child_options,
                    }
                )
            lookup_items.append(
                {
                    "key": key,
                    "kind": "cascade",
                    "options": [],
                    "parents": parents,
                    "used_by": sorted(field_usage.get(key, set())),
                }
            )

    return render_template(
        "map_lookups.html",
        lookup_items=lookup_items,
    )


# ── Authentication routes ────────────────────────────────────────────────────


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("track"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT id, username, password, role, must_change_password FROM users WHERE username = %s",
                    (username,),
                )
                row = cur.fetchone()
        except Exception as e:
            print(f"ERROR: Login failed due to database error: {e}", file=sys.stderr)
            flash(
                "Login is temporarily unavailable. Please verify your database connection.",
                "danger",
            )
            return render_template("login.html")
        if row and row[2] == hash_password(password):
            user = User(row[0], row[1], row[3], bool(row[4]))
            login_user(user)
            if user.must_change_password:
                return redirect(url_for("change_password"))
            next_page = request.args.get("next")
            return redirect(next_page or url_for("track"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        new_pw = request.form.get("new_password", "").strip()
        confirm_pw = request.form.get("confirm_password", "").strip()
        if not new_pw or len(new_pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("change_password.html")
        if new_pw != confirm_pw:
            flash("Passwords do not match.", "danger")
            return render_template("change_password.html")
        try:
            with db_cursor() as cur:
                cur.execute(
                    "UPDATE users SET password = %s, must_change_password = FALSE WHERE id = %s",
                    (hash_password(new_pw), current_user.id),
                )
            flash("Password changed successfully.", "success")
            return redirect(url_for("track"))
        except Exception:
            flash("Could not update password.", "danger")
    return render_template("change_password.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


# ── Application routes ───────────────────────────────────────────────────────


@app.route("/", methods=["GET"])
@login_required
def form():
    groups = load_field_groups()
    values = {"COMMENTS": build_comments_text({})}
    copy_from = request.args.get("copy_from", type=int)
    if copy_from is not None:
        with db_cursor() as cur:
            cur.execute("SELECT data FROM submissions WHERE id = %s", (copy_from,))
            row = cur.fetchone()
        if row is None:
            flash("Source submission for copy was not found.", "danger")
            return redirect(url_for("track"))
        source_values = dict(row[0]) if isinstance(row[0], dict) else {}
        values = prepare_copy_values(source_values)
        if not (values.get("COMMENTS") or "").strip():
            values["COMMENTS"] = build_comments_text(values)
        flash("Copy loaded. Update the new Agreement ID before saving.", "info")
    return render_template(
        "form.html", groups=groups, values=values, edit_index=None, attachments=[]
    )


@app.route("/copy/<int:id>", methods=["GET"])
@login_required
def copy_submission(id):
    return redirect(url_for("form", copy_from=id))


@app.route("/edit/<int:id>", methods=["GET"])
@login_required
def edit(id):
    with db_cursor() as cur:
        cur.execute("SELECT data FROM submissions WHERE id = %s", (id,))
        row = cur.fetchone()
    if row is None:
        flash("Submission not found.", "danger")
        return redirect(url_for("track"))
    groups = load_field_groups()
    values = dict(row[0]) if isinstance(row[0], dict) else {}
    if not (values.get("COMMENTS") or "").strip():
        values["COMMENTS"] = build_comments_text(values)
    attachments = values.get("_attachments", [])
    return render_template(
        "form.html",
        groups=groups,
        values=values,
        edit_index=id,
        attachments=attachments,
    )


@app.route("/submit", methods=["POST"])
@login_required
def submit():
    groups = load_field_groups()
    missing = []
    values = {}
    for gname, items in groups:
        for it in items:
            v = request.form.get(it["name"], "").strip()
            values[it["name"]] = v
            if it["required"] and v == "":
                missing.append(it["label"])

    if missing:
        flash("Missing required fields: " + ", ".join(missing), "danger")
        return redirect(url_for("form"))

    if not (values.get("COMMENTS") or "").strip():
        values["COMMENTS"] = build_comments_text(values)

    values["_created_at"] = date.today().isoformat()
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO submissions (data, created_at) VALUES (%s, %s) RETURNING id",
            (json.dumps(values), date.today()),
        )
        new_id = cur.fetchone()[0]

    # Optional attachments: save files and persist metadata on the submission.
    attachments = save_attachments(new_id, request.files.getlist("attachments"))
    if attachments:
        values["_attachments"] = attachments
        with db_cursor() as cur:
            cur.execute(
                "UPDATE submissions SET data = %s WHERE id = %s",
                (json.dumps(values), new_id),
            )

    if request.form.get("_action") == "save_and_generate":
        flash("Submission saved.", "success")
        return redirect(url_for("generate", id=new_id))

    flash("Submission saved.", "success")
    return redirect(url_for("track"))


@app.route("/update/<int:id>", methods=["POST"])
@login_required
def update(id):
    with db_cursor() as cur:
        cur.execute("SELECT data FROM submissions WHERE id = %s", (id,))
        row = cur.fetchone()
    if row is None:
        flash("Submission not found.", "danger")
        return redirect(url_for("track"))
    groups = load_field_groups()
    missing = []
    values = {}
    for gname, items in groups:
        for it in items:
            v = request.form.get(it["name"], "").strip()
            values[it["name"]] = v
            if it["required"] and v == "":
                missing.append(it["label"])
    if missing:
        flash("Missing required fields: " + ", ".join(missing), "danger")
        return render_template(
            "form.html",
            groups=groups,
            values=values,
            edit_index=id,
            attachments=row[0].get("_attachments", []),
        )

    if not (values.get("COMMENTS") or "").strip():
        values["COMMENTS"] = build_comments_text(values)
    values["_created_at"] = row[0].get("_created_at", date.today().isoformat())
    attachments = save_attachments(
        id,
        request.files.getlist("attachments"),
        existing=row[0].get("_attachments", []),
    )
    if attachments:
        values["_attachments"] = attachments
    with db_cursor() as cur:
        cur.execute(
            "UPDATE submissions SET data = %s WHERE id = %s", (json.dumps(values), id)
        )
    flash("Agreement updated.", "success")
    return redirect(url_for("track"))


@app.route("/generate/<int:id>", methods=["GET"])
@login_required
def generate(id):
    """Generate a filled Recovery Note docx for the submission with the given id."""
    with db_cursor() as cur:
        cur.execute("SELECT data FROM submissions WHERE id = %s", (id,))
        row = cur.fetchone()
    if row is None:
        flash("Submission not found.", "danger")
        return redirect(url_for("form"))
    data = row[0]
    out = generate_docx.generate(data)
    agreement_id = (data.get("AGREEMENT_ID", "RecoveryNote") or "RecoveryNote").replace(
        "/", "-"
    )
    response = send_file(
        out,
        as_attachment=True,
        download_name=f"{agreement_id}.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    @response.call_on_close
    def _cleanup():
        try:
            os.unlink(out)
        except OSError:
            pass

    return response


@app.route("/generate", methods=["GET"])
@login_required
def generate_latest():
    """Generate the most recent submission."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM submissions ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        flash("No submissions found.", "danger")
        return redirect(url_for("form"))
    return redirect(url_for("generate", id=row[0]))


@app.route("/attachments/<int:id>/<path:filename>", methods=["GET"])
@login_required
def download_attachment(id, filename):
    with db_cursor() as cur:
        cur.execute("SELECT data FROM submissions WHERE id = %s", (id,))
        row = cur.fetchone()
    if row is None:
        abort(404)

    attachments = row[0].get("_attachments", []) if isinstance(row[0], dict) else []
    allowed = {a.get("stored") for a in attachments if isinstance(a, dict)}
    if filename not in allowed:
        abort(404)

    return send_from_directory(
        os.path.join(UPLOADS_DIR, str(id)), filename, as_attachment=True
    )


@app.route("/submissions", methods=["GET"])
def submissions_api():
    with db_cursor() as cur:
        cur.execute("SELECT id, data FROM submissions ORDER BY id")
        rows = cur.fetchall()
    return jsonify([{"id": r[0], **r[1]} for r in rows])


@app.route("/track", methods=["GET"])
@login_required
def track():
    with db_cursor() as cur:
        cur.execute("SELECT id, data FROM submissions ORDER BY id")
        rows = cur.fetchall()
    records = [{"id": r[0], **r[1]} for r in rows]
    return render_template("track.html", rows=records)


@app.route("/delete/<int:id>", methods=["POST"])
@login_required
def delete(id):
    with db_cursor() as cur:
        cur.execute("DELETE FROM submissions WHERE id = %s RETURNING id", (id,))
        deleted = cur.fetchone()
    if deleted:
        flash("Record deleted.", "success")
    else:
        flash("Record not found.", "danger")
    return redirect(url_for("track"))


@app.route("/api/next-seq", methods=["GET"])
def next_seq():
    """Return the next available 3-digit sequence for a given ID prefix."""
    prefix = request.args.get("prefix", "").strip()
    if not prefix:
        return jsonify({"seq": 1})
    field = sanitize_name("AGREEMENT ID")
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT data->>%s FROM submissions WHERE data->>%s LIKE %s",
                (field, field, prefix + "%"),
            )
            rows = cur.fetchall()
        existing = []
        for (val,) in rows:
            if val and val.startswith(prefix):
                tail = val[len(prefix) :]
                if tail.isdigit() and len(tail) == 3:
                    existing.append(int(tail))
    except Exception:
        existing = []
    nxt = (max(existing) + 1) if existing else 1
    return jsonify({"seq": nxt})


@app.route("/admin")
@admin_required
def admin():
    return render_template("admin.html")


@app.route("/admin/users")
@admin_required
def admin_users():
    with db_cursor() as cur:
        cur.execute("SELECT id, username, role FROM users ORDER BY username")
        users = cur.fetchall()
    return render_template("admin_users.html", users=users)


@app.route("/admin/users/add", methods=["POST"])
@admin_required
def admin_users_add():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "user")
    if not username or not password:
        flash("Username and password are required.", "danger")
        return redirect(url_for("admin_users"))
    if role not in ("admin", "user"):
        role = "user"
    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password, role, must_change_password) VALUES (%s, %s, %s, TRUE)",
                (username, hash_password(password), role),
            )
        flash(f'User "{username}" created.', "success")
    except Exception:
        flash(f'Could not create user "{username}" (may already exist).', "danger")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@admin_required
def admin_users_delete(user_id):
    if user_id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_users"))
    try:
        with db_cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        flash("User deleted.", "success")
    except Exception:
        flash("Could not delete user.", "danger")
    return redirect(url_for("admin_users"))


if __name__ == "__main__":
    app.run(debug=True)
