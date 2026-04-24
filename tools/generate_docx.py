"""Generate a filled Recovery Note Word document from submission data."""
import os
import re
import tempfile
from datetime import date

from docx import Document

# Path to the Word template — relative to this file's directory (tools/)
_TEMPLATE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Recovery Note (RN) with the Fields mapped.docx')
)


def _para_full_text(para):
    """Return the concatenated text of all runs in a paragraph."""
    return ''.join(r.text for r in para.runs)


def _set_para_text(para, text):
    """Replace all runs in a paragraph with a single run holding *text*."""
    text = text or ''
    if not para.runs:
        para.add_run(text)
        return
    para.runs[0].text = text
    for run in para.runs[1:]:
        run._r.getparent().remove(run._r)


def _fill_cell(cell, text):
    """Set the first paragraph of a table cell to *text*."""
    if cell.paragraphs:
        _set_para_text(cell.paragraphs[0], text or '')


def _fill_ifis_row(row, code):
    """
    Fill the IFIS table row one character per data cell.
    Cells whose current text is '-' are separators — left unchanged.
    """
    chars = re.sub(r'[^0-9A-Za-z]', '', code) if code else ''
    char_idx = 0
    for cell in row.cells:
        if cell.text.strip() == '-':
            continue
        _fill_cell(cell, chars[char_idx] if char_idx < len(chars) else '')
        char_idx += 1


def generate(data):
    """
    Fill the Recovery Note template with submission data.

    Parameters
    ----------
    data : dict
        Submission data keyed by sanitised field names (as stored in the DB).

    Returns
    -------
    str
        Absolute path to a temporary .docx file.  The caller is responsible
        for deleting it after the response has been sent.
    """
    d = data or {}
    doc = Document(_TEMPLATE)

    # ── Table 0: key header fields ────────────────────────────────────────────
    t0 = doc.tables[0]

    # Row 0: Date
    _fill_cell(t0.rows[0].cells[1], d.get('_created_at', date.today().isoformat()))

    # Row 1: Agreement ID
    _fill_cell(t0.rows[1].cells[1], d.get('AGREEMENT_ID', ''))

    # Row 2: Agreement Name / Description
    _fill_cell(t0.rows[2].cells[1], d.get('AGREEMENT_NAME_DESCRIPTION', ''))

    # Row 3: Previous Recovery Agreement
    _fill_cell(t0.rows[3].cells[1], d.get('PREVIOUS_AGREEMENT', ''))

    # Row 4: Term — start / end dates
    start = d.get('START_DATE_YYYY_MM_DD', '')
    end = d.get('END_DATE_YYYY_MM_DD', '')
    _fill_cell(t0.rows[4].cells[1], f'Start Date: {start}   End Date: {end}')

    # ── Paragraph "Column R" → Comments ──────────────────────────────────────
    comments = d.get('COMMENTS', '')
    for para in doc.paragraphs:
        if 'Column R' in _para_full_text(para):
            _set_para_text(para, comments)
            break

    # ── Table 1: financial recovery details ───────────────────────────────────
    t1 = doc.tables[1]
    row1 = t1.rows[1]
    _fill_cell(row1.cells[0], d.get('ITS_SERVICE', '').replace('\n', ' ').strip())
    _fill_cell(row1.cells[1], d.get('ITS_SERVICE_TYPE', '').replace('\n', ' ').strip())
    _fill_cell(row1.cells[2], d.get('AGREEMENT_TYPE', ''))
    _fill_cell(row1.cells[3], d.get('MONTH_BILLED', ''))
    amount = d.get('MONTHLY_RECURRING') or d.get('ANNUAL') or d.get('ONE_TIME') or ''
    _fill_cell(row1.cells[4], str(amount) if amount else '')

    # ── Table 2: IFIS breakdown ───────────────────────────────────────────────
    t2 = doc.tables[2]
    _fill_ifis_row(t2.rows[1], d.get('IFIS_CODE', ''))

    # ── Paragraph "Column X" → full IFIS code ─────────────────────────────────
    for para in doc.paragraphs:
        if 'Column X' in _para_full_text(para):
            _set_para_text(para, d.get('IFIS_CODE', ''))
            break

    # ── Cluster / approver section ─────────────────────────────────────────────
    cluster = d.get('SERVICE_OWNER', '')
    for para in doc.paragraphs:
        if _para_full_text(para).strip() == 'Name of Cluster':
            _set_para_text(para, cluster)
            break

    # ── Write to a temporary file ──────────────────────────────────────────────
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.docx')
    tmp.close()
    doc.save(tmp.name)
    return tmp.name
