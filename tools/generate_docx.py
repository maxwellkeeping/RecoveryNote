import json
from docx import Document

FG_JSON = 'field_groups.json'
OUT_DOCX = 'Field_Groupings.docx'

with open(FG_JSON, 'r', encoding='utf-8') as f:
    data = json.load(f)

doc = Document()
doc.add_heading('Field Groupings for Recovery Note App', level=1)

doc.add_paragraph(f"Sheet: {data.get('sheet', '')}")

doc.add_heading('Field Groupings', level=2)
for group in ['Agreement', 'Contact', 'Dates', 'Notes', 'Other']:
    items = data.get('groups', {}).get(group, [])
    if items:
        doc.add_heading(group, level=3)
        for it in items:
            doc.add_paragraph(it or '', style='List Bullet')

if data.get('proposed_mandatory'):
    doc.add_heading('Proposed Mandatory Fields', level=2)
    for it in data['proposed_mandatory']:
        doc.add_paragraph(it or '', style='List Bullet')

doc.save(OUT_DOCX)
print('Wrote', OUT_DOCX)
