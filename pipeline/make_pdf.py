"""Convert a markdown report to a styled PDF. Usage: python3 make_pdf.py <report.md>"""
import sys, os, markdown
from weasyprint import HTML

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

def main():
    src = sys.argv[1]
    with open(src) as f:
        md = f.read()
    html_body = markdown.markdown(md, extensions=['extra'])
    html = f"<html><head><style>{CSS}</style></head><body>{html_body}</body></html>"
    out = os.path.splitext(src)[0] + ".pdf"
    HTML(string=html).write_pdf(out)
    print("PDF written:", out)

if __name__ == "__main__":
    main()
