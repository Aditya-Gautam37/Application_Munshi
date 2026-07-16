"""Convert the three handover markdown files to PDF via Chrome headless.

Run from the docs/ folder:
    python3 _build_pdfs.py

Output: <name>.pdf alongside each <name>.md.
"""

import os
import subprocess
import sys
from pathlib import Path

try:
    import markdown
except ImportError:
    print("Install: pip install --user markdown")
    sys.exit(1)


HERE = Path(__file__).parent.resolve()
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


CSS = """
@page {
  size: A4;
  margin: 18mm 16mm 18mm 16mm;
  @bottom-center { content: counter(page) " / " counter(pages); }
}
* { box-sizing: border-box; }
html, body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
  color: #1a202c;
  margin: 0;
}
h1 {
  font-size: 22pt;
  margin: 0 0 0.4em 0;
  color: #283593;
  border-bottom: 3px solid #3949ab;
  padding-bottom: 0.2em;
  page-break-after: avoid;
}
h2 {
  font-size: 16pt;
  margin: 1.6em 0 0.4em 0;
  color: #3949ab;
  page-break-after: avoid;
}
h3 {
  font-size: 13pt;
  margin: 1.2em 0 0.3em 0;
  color: #283593;
  page-break-after: avoid;
}
h4 {
  font-size: 11.5pt;
  margin: 1em 0 0.3em 0;
  color: #1a202c;
  page-break-after: avoid;
}
p { margin: 0.4em 0; orphans: 3; widows: 3; }
ul, ol { margin: 0.4em 0 0.4em 1.4em; padding: 0; }
li { margin: 0.15em 0; }
code {
  font-family: 'SF Mono', Menlo, Consolas, 'Courier New', monospace;
  font-size: 9.5pt;
  background: #f4f5f9;
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid #e0e3eb;
}
pre {
  background: #f4f5f9;
  border: 1px solid #e0e3eb;
  border-radius: 6px;
  padding: 10px 12px;
  font-family: 'SF Mono', Menlo, Consolas, monospace;
  font-size: 9pt;
  line-height: 1.45;
  overflow-x: auto;
  page-break-inside: avoid;
}
pre code {
  background: transparent;
  border: 0;
  padding: 0;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 0.6em 0;
  font-size: 9.5pt;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid #e0e3eb;
  padding: 5px 8px;
  text-align: left;
  vertical-align: top;
}
th {
  background: #f4f5f9;
  font-weight: 600;
  color: #283593;
}
tr:nth-child(even) td { background: #fafbfd; }
blockquote {
  border-left: 4px solid #3949ab;
  background: #f0f2fa;
  padding: 8px 14px;
  margin: 0.6em 0;
  color: #283593;
  page-break-inside: avoid;
}
hr {
  border: 0;
  border-top: 1px solid #e0e3eb;
  margin: 1.4em 0;
}
strong { color: #1a202c; }
em { color: #283593; }
a { color: #3949ab; text-decoration: none; }
a:hover { text-decoration: underline; }
.toc-marker { page-break-before: always; }
"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


def md_to_html(md_path: Path) -> Path:
    text = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc"],
    )
    title = md_path.stem.replace("_", " ").title()
    full = HTML_TEMPLATE.format(title=title, css=CSS, body=html_body)
    html_path = md_path.with_suffix(".html")
    html_path.write_text(full, encoding="utf-8")
    return html_path


def html_to_pdf(html_path: Path) -> Path:
    pdf_path = html_path.with_suffix(".pdf")
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={pdf_path}",
        f"file://{html_path.resolve()}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0 or not pdf_path.exists():
        print(f"  STDERR: {result.stderr[:500]}")
        raise RuntimeError(f"Chrome failed to render {html_path}")
    return pdf_path


def main():
    files = ["TECHNICAL_HANDOVER.md", "DATA_DICTIONARY.md", "OPS_RUNBOOK.md",
             "ANKUR_TEST_SCRIPT.md", "PUBLISH_TO_GITHUB.md"]
    for fname in files:
        md = HERE / fname
        if not md.exists():
            print(f"SKIP (missing): {fname}")
            continue
        print(f"Building {fname}...")
        html = md_to_html(md)
        pdf = html_to_pdf(html)
        size_kb = pdf.stat().st_size // 1024
        print(f"  → {pdf.name} ({size_kb} KB)")
        # Clean up the intermediate HTML
        html.unlink()
    print("\nDone. Open PDFs from the docs/ folder.")


if __name__ == "__main__":
    main()
