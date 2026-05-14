import os
import xml.etree.ElementTree as ET
from pathlib import Path
import html

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

INPUT_FILE = "feed.xml"
OUTPUT_DIR = Path("docs/jobs")

# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

tree = ET.parse(INPUT_FILE)
root = tree.getroot()

def safe(text):
    return html.escape(text or "")

jobs = root.findall("job")

# ─────────────────────────────────────────────
# Generate job pages
# ─────────────────────────────────────────────

for job in jobs:
    title = job.findtext("title", "")
    company = job.findtext("company", "")
    desc = job.findtext("description", "")
    slug = job.findtext("slug", "")
    apply = job.findtext("apply_url", "")
    location = job.findtext("office_location", "")

    if not slug:
        continue

    job_dir = OUTPUT_DIR / slug
    job_dir.mkdir(parents=True, exist_ok=True)

    file_path = job_dir / "index.html"

    html_content = f"""<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{safe(title)} | {safe(company)}</title>
    <meta name="description" content="{safe(desc[:160])}">
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <link rel="canonical" href="https://jobs.thepolly.co/jobs/{slug}/">
</head>

<body style="font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto;">

    <a href="/">&larr; Back to Jobs</a>

    <h1>{safe(title)}</h1>

    <p><strong>Company:</strong> {safe(company)}</p>
    <p><strong>Location:</strong> {safe(location)}</p>

    <hr>

    <div>
        {safe(desc)}
    </div>

    <hr>

    <p>
        <a href="{apply}" target="_blank" rel="noopener">
            Apply Here
        </a>
    </p>

</body>
</html>
"""

    file_path.write_text(html_content, encoding="utf-8")

print(f"Generated {len(jobs)} job pages in {OUTPUT_DIR}")
