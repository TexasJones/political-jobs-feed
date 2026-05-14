import os
import re
import html
import logging
import xml.etree.ElementTree as ET
from datetime import datetime

# ─────────────────────────────
# Config
# ─────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = "docs"   # IMPORTANT: aligns with GitHub Pages /docs setup
JOBS_DIR = os.path.join(OUTPUT_DIR, "jobs")

BASE_URL = "https://thepolly.co"

os.makedirs(JOBS_DIR, exist_ok=True)

# ─────────────────────────────
# Helpers
# ─────────────────────────────

def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")

def clean(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# ─────────────────────────────
# Load feed.xml
# ─────────────────────────────

tree = ET.parse("feed.xml")
root = tree.getroot()

jobs = root.findall("job")

log.info("Loaded jobs: %d", len(jobs))

# ─────────────────────────────
# Generate job pages
# ─────────────────────────────

job_index_links = []

for job in jobs:
    title = job.find("title").text or ""
    company = job.find("company").text or ""
    desc = job.find("description").text or ""
    slug = job.find("slug").text or slugify(f"{title}-{company}")
    apply = job.find("apply_url").text or "#"
    location = job.find("office_location").text or ""

    desc = clean(desc)[:2000]

    job_url = f"/jobs/{slug}/"
    job_index_links.append((title, job_url))

    job_dir = os.path.join(JOBS_DIR, slug)
    os.makedirs(job_dir, exist_ok=True)

    html_page = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title} - {company}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="{title} at {company} in {location}">
</head>
<body>
    <a href="/">← Back to jobs</a>

    <h1>{title}</h1>
    <h2>{company}</h2>
    <p><strong>Location:</strong> {location}</p>

    <hr>

    <p>{desc}</p>

    <hr>

    <a href="{apply}" target="_blank">Apply Here</a>
</body>
</html>
"""

    with open(os.path.join(job_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_page)

    log.info("Created job page: %s", slug)

# ─────────────────────────────
# Generate homepage
# ─────────────────────────────

job_cards = "\n".join(
    f'<li><a href="{url}">{title}</a></li>'
    for title, url in job_index_links
)

index_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Polly Jobs Feed</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <h1>Polly Jobs</h1>
    <p>Updated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}</p>

    <ul>
        {job_cards}
    </ul>
</body>
</html>
"""

with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(index_html)

# ─────────────────────────────
# Copy feed.xml into docs/
# ─────────────────────────────

with open("feed.xml", "r", encoding="utf-8") as src:
    feed_data = src.read()

with open(os.path.join(OUTPUT_DIR, "feed.xml"), "w", encoding="utf-8") as dst:
    dst.write(feed_data)

log.info("DONE: job pages + index + feed generated")
