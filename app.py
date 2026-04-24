from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import json
import os
import re

APP_DIR = os.path.dirname(__file__)
FG_PATH = os.path.join(APP_DIR, 'field_groups.json')
SUBMISSIONS = os.path.join(APP_DIR, 'submissions.json')
LOOKUP_PATH = os.path.join(APP_DIR, 'field_lookups.json')
LOOKUP_MAP = os.path.join(APP_DIR, 'lookup_mappings.json')

app = Flask(__name__)
app.secret_key = 'dev-secret'
# expose sanitize helper to templates
app.jinja_env.globals['sanitize_name'] = lambda s: re.sub(r"[^0-9A-Za-z]+", '_', s).strip('_')


def sanitize_name(s):
    # create a safe input name from header text
    return re.sub(r"[^0-9A-Za-z]+", '_', s).strip('_')


def load_field_groups():
    with open(FG_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    groups = data.get('groups', {})
    mandatory = set(data.get('proposed_mandatory', []))
    # load lookups and mapping if present
    lookups = {}
    if os.path.exists(LOOKUP_PATH):
        with open(LOOKUP_PATH, 'r', encoding='utf-8') as lf:
            raw = json.load(lf)
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
    # normalize groups into list of (group_name, [ {label,name,required} ])
    out = []
    for gname, fields in groups.items():
        items = []
        for h in fields:
            if not h:
                continue
            label = h.replace('\n', ' ')
            # mapping may point label -> lookup key
            mapped_key = mapping.get(label)
            options = None
            if mapped_key:
                options = lookups.get(mapped_key)
            else:
                # fallback by exact header match
                options = lookups.get(label)
            items.append({
                'label': label,
                'name': sanitize_name(h),
                'required': h in mandatory,
                'options': options,
            })
        if items:
            out.append((gname, items))
    return out


@app.route('/map-lookups', methods=['GET', 'POST'])
def map_lookups():
    # load current headers
    groups = load_field_groups()
    # flatten labels
    labels = []
    for g, items in groups:
        for it in items:
            labels.append(it['label'])

    # load available lookups
    lookups = {}
    if os.path.exists(LOOKUP_PATH):
        with open(LOOKUP_PATH, 'r', encoding='utf-8') as lf:
            raw = json.load(lf)
            lookups = {k.replace('\n', ' ').strip(): v for k, v in raw.items()}

    # load existing mapping
    mapping = {}
    if os.path.exists(LOOKUP_MAP):
        with open(LOOKUP_MAP, 'r', encoding='utf-8') as mf:
            try:
                mapping = json.load(mf)
            except Exception:
                mapping = {}

    if request.method == 'POST':
        # save mappings: map submitted form keys back to labels using sanitize_name
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


@app.route('/', methods=['GET'])
def form():
    groups = load_field_groups()
    return render_template('form.html', groups=groups)


@app.route('/submit', methods=['POST'])
def submit():
    groups = load_field_groups()
    # validate required
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

    # persist submission
    all_subs = []
    if os.path.exists(SUBMISSIONS):
        with open(SUBMISSIONS, 'r', encoding='utf-8') as f:
            try:
                all_subs = json.load(f)
            except Exception:
                all_subs = []
    all_subs.append(values)
    with open(SUBMISSIONS, 'w', encoding='utf-8') as f:
        json.dump(all_subs, f, indent=2)

    flash('Submission saved.', 'success')
    return redirect(url_for('form'))


@app.route('/submissions', methods=['GET'])
def submissions():
    if os.path.exists(SUBMISSIONS):
        with open(SUBMISSIONS, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = []
    return jsonify(data)


if __name__ == '__main__':
    app.run(debug=True)
