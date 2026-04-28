from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
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
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

APP_DIR = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(APP_DIR, 'tools'))
import generate_docx

# Config JSON files — override with DATA_DIR env var (defaults to app directory)
_DATA_DIR = os.environ.get('DATA_DIR', APP_DIR)
FG_PATH = os.path.join(_DATA_DIR, 'field_groups.json')
LOOKUP_PATH = os.path.join(_DATA_DIR, 'field_lookups.json')
LOOKUP_MAP = os.path.join(_DATA_DIR, 'lookup_mappings.json')

# PostgreSQL connection string — set DATABASE_URL in environment.
# Read dynamically on each call so Key Vault references that resolve after
# startup are picked up, and so a missing value at boot doesn't crash the app.
DATABASE_URL = os.environ.get('DATABASE_URL')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
# expose sanitize helper to templates
app.jinja_env.globals['sanitize_name'] = lambda s: re.sub(r"[^0-9A-Za-z]+", '_', s).strip('_')

# ── Flask-Login setup ────────────────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'


class User(UserMixin):
    def __init__(self, id, username, role, must_change_password=False):
        self.id = id
        self.username = username
        self.role = role
        self.must_change_password = must_change_password

    @property
    def is_admin(self):
        return self.role == 'admin'


@login_manager.user_loader
def load_user(user_id):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT id, username, role, must_change_password FROM users WHERE id = %s", (int(user_id),))
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
            flash('Admin access required.', 'danger')
            return redirect(url_for('track'))
        return f(*args, **kwargs)
    return decorated


def hash_password(password):
    """Simple SHA-256 hash. Adequate for PoC; upgrade to bcrypt for production."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


@contextmanager
def db_cursor():
    """Yield a psycopg2 cursor; commits on clean exit, rolls back on error."""
    dsn = os.environ.get('DATABASE_URL') or DATABASE_URL
    conn = psycopg2.connect(dsn, connect_timeout=10)
    try:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


def init_db():
    """Create the submissions and users tables if they do not yet exist."""
    with db_cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id          SERIAL PRIMARY KEY,
                data        JSONB  NOT NULL,
                created_at  DATE   NOT NULL DEFAULT CURRENT_DATE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                    SERIAL PRIMARY KEY,
                username              VARCHAR(100) UNIQUE NOT NULL,
                password              VARCHAR(256) NOT NULL,
                role                  VARCHAR(20)  NOT NULL DEFAULT 'user',
                must_change_password  BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)
        # Migrate: add must_change_password column if missing (existing DBs)
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'must_change_password'
                ) THEN
                    ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT TRUE;
                END IF;
            END $$;
        """)
        # Seed default accounts if users table is empty
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO users (username, password, role, must_change_password) VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)",
                ('admin', hash_password('admin123'), 'admin', True,
                 'user', hash_password('user123'), 'user', True)
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
        allowed = ('change_password', 'logout', 'static')
        if request.endpoint not in allowed:
            flash('You must change your password before continuing.', 'warning')
            return redirect(url_for('change_password'))


def sanitize_name(s):
    return re.sub(r"[^0-9A-Za-z]+", '_', s).strip('_')


def load_field_groups():
    with open(FG_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    groups = data.get('groups', {})
    mandatory = set(data.get('proposed_mandatory', []))
    field_hints = data.get('field_hints', {})
    # load lookups and mapping if present
    lookups = {}
    cascade_field_map = {}  # { dependent_label: parent_label }
    if os.path.exists(LOOKUP_PATH):
        with open(LOOKUP_PATH, 'r', encoding='utf-8') as lf:
            raw = json.load(lf)
            cascade_field_map = raw.pop('_cascade_fields', {})
            for k, v in raw.items():
                nk = k.replace('\n', ' ').strip()
                lookups[nk] = v
    mapping = {}
    if os.path.exists(LOOKUP_MAP):
        try:
            with open(LOOKUP_MAP, 'r', encoding='utf-8') as mf:
                mapping = json.load(mf)
        except Exception:
            mapping = {}
    # normalize groups into list of (group_name, [ {label,name,required,...} ])
    out = []
    for gname, fields in groups.items():
        items = []
        for h in fields:
            if not h:
                continue
            label = h.replace('\n', ' ')
            mapped_key = mapping.get(label)
            options = None
            cascade_data = None
            parent_label = cascade_field_map.get(label)
            cascade_from = sanitize_name(parent_label) if parent_label else None
            if mapped_key:
                lookup_val = lookups.get(mapped_key)
            else:
                lookup_val = lookups.get(label)
            if cascade_from:
                # This is a cascade child — get cascade data from parent's lookup
                parent_mapped = mapping.get(parent_label)
                parent_lookup = lookups.get(parent_mapped) if parent_mapped else lookups.get(parent_label)
                if isinstance(parent_lookup, dict):
                    cascade_data = parent_lookup
                    options = []  # options populated dynamically via JS
            elif isinstance(lookup_val, dict):
                # This is a cascade parent — show top-level keys as options
                options = list(lookup_val.keys())
            else:
                options = lookup_val
            if isinstance(options, list):
                def _fix_govtech(s):
                    if 'GovTech ON - Cyber Security' in s and '(CSD)' not in s:
                        return s.replace('GovTech ON - Cyber Security', 'GovTech ON - Cyber Security (CSD)')
                    if 'GovTech ON - Technology Policy & Standards Development' in s and '(TPSD)' not in s:
                        return s.replace('GovTech ON - Technology Policy & Standards Development', 'GovTech ON - Technology Policy & Standards Development (TPSD)')
                    return s
                options = [_fix_govtech(x) for x in options]
            hint_data = field_hints.get(label, {})
            items.append({
                'label': hint_data.get('display_label', label),
                'name': sanitize_name(h),
                'required': h in mandatory,
                'options': options,
                'cascade_data': cascade_data,
                'cascade_from': cascade_from,
                'placeholder': hint_data.get('placeholder', ''),
                'hint': hint_data.get('hint', ''),
                'compound': hint_data.get('compound', ''),
                'input_type': hint_data.get('input_type', 'text'),
                'input_min': hint_data.get('min', ''),
                'input_max': hint_data.get('max', ''),
                'input_step': hint_data.get('step', ''),
                'input_mask': hint_data.get('input_mask', ''),
            })
        if items:
            out.append((gname, items))
    return out


@app.route('/map-lookups', methods=['GET', 'POST'])
@admin_required
def map_lookups():
    groups = load_field_groups()
    labels = []
    for g, items in groups:
        for it in items:
            labels.append(it['label'])

    lookups = {}
    if os.path.exists(LOOKUP_PATH):
        with open(LOOKUP_PATH, 'r', encoding='utf-8') as lf:
            raw = json.load(lf)
            lookups = {k.replace('\n', ' ').strip(): v for k, v in raw.items()}

    mapping = {}
    if os.path.exists(LOOKUP_MAP):
        with open(LOOKUP_MAP, 'r', encoding='utf-8') as mf:
            try:
                mapping = json.load(mf)
            except Exception:
                mapping = {}

    if request.method == 'POST':
        newmap = {}
        for form_key, sel in request.form.items():
            if not sel:
                continue
            for label in labels:
                if sanitize_name(label) == form_key:
                    newmap[label] = sel
                    break
        with open(LOOKUP_MAP, 'w', encoding='utf-8') as mf:
            json.dump(newmap, mf, indent=2, ensure_ascii=False)
        flash('Lookup mappings saved.', 'success')
        return redirect(url_for('map_lookups'))

    return render_template('map_lookups.html', labels=labels, lookups=list(lookups.keys()), mapping=mapping)


# ── Authentication routes ────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('track'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT id, username, password, role FROM users WHERE username = %s",
                    (username,)
                )
                row = cur.fetchone()
        except Exception:
            row = None
        if row and row[2] == hash_password(password):
            user = User(row[0], row[1], row[3])
            login_user(user)
            # Check if user must change password
            try:
                with db_cursor() as cur2:
                    cur2.execute("SELECT must_change_password FROM users WHERE id = %s", (user.id,))
                    mcp = cur2.fetchone()
                if mcp and mcp[0]:
                    return redirect(url_for('change_password'))
            except Exception:
                pass
            next_page = request.args.get('next')
            return redirect(next_page or url_for('track'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        new_pw = request.form.get('new_password', '').strip()
        confirm_pw = request.form.get('confirm_password', '').strip()
        if not new_pw or len(new_pw) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('change_password.html')
        if new_pw != confirm_pw:
            flash('Passwords do not match.', 'danger')
            return render_template('change_password.html')
        try:
            with db_cursor() as cur:
                cur.execute(
                    "UPDATE users SET password = %s, must_change_password = FALSE WHERE id = %s",
                    (hash_password(new_pw), current_user.id)
                )
            flash('Password changed successfully.', 'success')
            return redirect(url_for('track'))
        except Exception:
            flash('Could not update password.', 'danger')
    return render_template('change_password.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'info')
    return redirect(url_for('login'))


# ── Application routes ───────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
@login_required
def form():
    groups = load_field_groups()
    return render_template('form.html', groups=groups, values={}, edit_index=None)


@app.route('/edit/<int:id>', methods=['GET'])
@login_required
def edit(id):
    with db_cursor() as cur:
        cur.execute("SELECT data FROM submissions WHERE id = %s", (id,))
        row = cur.fetchone()
    if row is None:
        flash('Submission not found.', 'danger')
        return redirect(url_for('track'))
    groups = load_field_groups()
    return render_template('form.html', groups=groups, values=row[0], edit_index=id)


@app.route('/submit', methods=['POST'])
@login_required
def submit():
    groups = load_field_groups()
    missing = []
    values = {}
    for gname, items in groups:
        for it in items:
            v = request.form.get(it['name'], '').strip()
            values[it['name']] = v
            if it['required'] and v == '':
                missing.append(it['label'])

    if missing:
        flash('Missing required fields: ' + ', '.join(missing), 'danger')
        return redirect(url_for('form'))

    values['_created_at'] = date.today().isoformat()
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO submissions (data, created_at) VALUES (%s, %s) RETURNING id",
            (json.dumps(values), date.today())
        )
        new_id = cur.fetchone()[0]

    if request.form.get('_action') == 'save_and_generate':
        flash('Submission saved.', 'success')
        return redirect(url_for('generate', id=new_id))

    flash('Submission saved.', 'success')
    return redirect(url_for('track'))


@app.route('/update/<int:id>', methods=['POST'])
@login_required
def update(id):
    with db_cursor() as cur:
        cur.execute("SELECT data FROM submissions WHERE id = %s", (id,))
        row = cur.fetchone()
    if row is None:
        flash('Submission not found.', 'danger')
        return redirect(url_for('track'))
    groups = load_field_groups()
    missing = []
    values = {}
    for gname, items in groups:
        for it in items:
            v = request.form.get(it['name'], '').strip()
            values[it['name']] = v
            if it['required'] and v == '':
                missing.append(it['label'])
    if missing:
        flash('Missing required fields: ' + ', '.join(missing), 'danger')
        return render_template('form.html', groups=groups, values=values, edit_index=id)
    values['_created_at'] = row[0].get('_created_at', date.today().isoformat())
    with db_cursor() as cur:
        cur.execute(
            "UPDATE submissions SET data = %s WHERE id = %s",
            (json.dumps(values), id)
        )
    flash('Agreement updated.', 'success')
    return redirect(url_for('track'))


@app.route('/generate/<int:id>', methods=['GET'])
@login_required
def generate(id):
    """Generate a filled Recovery Note docx for the submission with the given id."""
    with db_cursor() as cur:
        cur.execute("SELECT data FROM submissions WHERE id = %s", (id,))
        row = cur.fetchone()
    if row is None:
        flash('Submission not found.', 'danger')
        return redirect(url_for('form'))
    data = row[0]
    out = generate_docx.generate(data)
    agreement_id = (data.get('AGREEMENT_ID', 'RecoveryNote') or 'RecoveryNote').replace('/', '-')
    response = send_file(
        out,
        as_attachment=True,
        download_name=f'{agreement_id}.docx',
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    @response.call_on_close
    def _cleanup():
        try:
            os.unlink(out)
        except OSError:
            pass
    return response


@app.route('/generate', methods=['GET'])
@login_required
def generate_latest():
    """Generate the most recent submission."""
    with db_cursor() as cur:
        cur.execute("SELECT id FROM submissions ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        flash('No submissions found.', 'danger')
        return redirect(url_for('form'))
    return redirect(url_for('generate', id=row[0]))


@app.route('/submissions', methods=['GET'])
def submissions_api():
    with db_cursor() as cur:
        cur.execute("SELECT id, data FROM submissions ORDER BY id")
        rows = cur.fetchall()
    return jsonify([{'id': r[0], **r[1]} for r in rows])


@app.route('/track', methods=['GET'])
@login_required
def track():
    with db_cursor() as cur:
        cur.execute("SELECT id, data FROM submissions ORDER BY id")
        rows = cur.fetchall()
    records = [{'id': r[0], **r[1]} for r in rows]
    return render_template('track.html', rows=records)


@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    with db_cursor() as cur:
        cur.execute("DELETE FROM submissions WHERE id = %s RETURNING id", (id,))
        deleted = cur.fetchone()
    if deleted:
        flash('Record deleted.', 'success')
    else:
        flash('Record not found.', 'danger')
    return redirect(url_for('track'))


@app.route('/api/next-seq', methods=['GET'])
def next_seq():
    """Return the next available 3-digit sequence for a given ID prefix."""
    prefix = request.args.get('prefix', '').strip()
    if not prefix:
        return jsonify({'seq': 1})
    field = sanitize_name('AGREEMENT ID')
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT data->>%s FROM submissions WHERE data->>%s LIKE %s",
                (field, field, prefix + '%')
            )
            rows = cur.fetchall()
        existing = []
        for (val,) in rows:
            if val and val.startswith(prefix):
                tail = val[len(prefix):]
                if tail.isdigit() and len(tail) == 3:
                    existing.append(int(tail))
    except Exception:
        existing = []
    nxt = (max(existing) + 1) if existing else 1
    return jsonify({'seq': nxt})


@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html')


@app.route('/admin/users')
@admin_required
def admin_users():
    with db_cursor() as cur:
        cur.execute("SELECT id, username, role FROM users ORDER BY username")
        users = cur.fetchall()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/add', methods=['POST'])
@admin_required
def admin_users_add():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'user')
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('admin_users'))
    if role not in ('admin', 'user'):
        role = 'user'
    try:
        with db_cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password, role, must_change_password) VALUES (%s, %s, %s, TRUE)",
                (username, hash_password(password), role)
            )
        flash(f'User "{username}" created.', 'success')
    except Exception:
        flash(f'Could not create user "{username}" (may already exist).', 'danger')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_users_delete(user_id):
    if user_id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin_users'))
    try:
        with db_cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        flash('User deleted.', 'success')
    except Exception:
        flash('Could not delete user.', 'danger')
    return redirect(url_for('admin_users'))


if __name__ == '__main__':
    app.run(debug=True)
