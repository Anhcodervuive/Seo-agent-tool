"""Convert markdown reports to styled PDFs."""
import os
import sys

import markdown

CSS = """
@page { size: A4; margin: 2cm; }
body { font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; color: #1a1a1a; line-height: 1.5; font-size: 12px; }
h1 { color: #0f172a; font-size: 24px; border-bottom: 3px solid #2563eb; padding-bottom: 8px; }
h2 { color: #1e40af; font-size: 16px; margin-top: 24px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
strong { color: #0f172a; }
em { color: #64748b; }
ul { margin: 8px 0; }
li { margin: 4px 0; }
"""

def markdown_to_html(md_text):
    html_body = markdown.markdown(md_text, extensions=['extra'])
    return f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html_body}</body></html>"

def markdown_file_to_pdf_bytes(src):
    from weasyprint import HTML

    with open(src, encoding="utf-8") as f:
        md = f.read()
    html = markdown_to_html(md)
    return HTML(string=html).write_pdf()

def markdown_file_to_pdf_file(src, out=None):
    if out is None:
        out = os.path.splitext(src)[0] + ".pdf"
    pdf_bytes = markdown_file_to_pdf_bytes(src)
    with open(out, "wb") as f:
        f.write(pdf_bytes)
    return out

def main():
    src = sys.argv[1]
    out = markdown_file_to_pdf_file(src)
    print("PDF written:", out)

if __name__ == "__main__":
    main()
