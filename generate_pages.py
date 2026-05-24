import re
import json
import html
import xml.etree.ElementTree as ET
from pathlib import Path

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

INPUT_FILE = "feed.xml"
BASE_URL = "https://jobs.thepolly.co"
OUTPUT_DIR = Path("docs/jobs")

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def safe(text):
    """HTML-escape for use in HTML attributes and body content."""
    return html.escape(text or "")

def jstr(text):
    """JSON-encode a string for use inside JSON-LD script blocks."""
    return json.dumps(text or "")[1:-1]  # strip surrounding quotes

def clean_slug(slug):
    """Collapse multiple hyphens and strip leading/trailing hyphens."""
    slug = slug.strip()
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug

def safe_url(url):
    """Only allow http/https URLs to prevent javascript: injection."""
    url = (url or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    return "#"

# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

tree = ET.parse(INPUT_FILE)
root = tree.getroot()

jobs = root.findall("job")

# ─────────────────────────────────────────────
# Generate individual job pages
# ─────────────────────────────────────────────

generated = 0

for job in jobs:

    title     = (job.findtext("title", "") or "").strip()
    company   = (job.findtext("company", "") or "").strip()
    desc      = (job.findtext("description", "") or "").strip()
    slug      = clean_slug(job.findtext("slug", "") or "")
    apply_url = safe_url(job.findtext("apply_url", ""))
    location  = (job.findtext("office_location", "") or "").strip()
    category  = (job.findtext("category", "") or "").strip()
    posted    = (job.findtext("date_posted", "") or "").strip()
    emp_type  = (job.findtext("employment_type", "") or "FULL_TIME").strip()

    if not slug:
        continue

    job_dir = OUTPUT_DIR / slug
    job_dir.mkdir(parents=True, exist_ok=True)

    canonical_url = f"{BASE_URL}/jobs/{slug}/"

    # Truncate description for meta without cutting mid-word
    desc_meta = desc[:160].rsplit(' ', 1)[0] if len(desc) > 160 else desc

    job_html = f"""<!doctype html>
<html lang="en">
<head>

    <meta charset="utf-8">

    <title>{safe(title)} | {safe(company)} | Polly</title>

    <meta name="viewport" content="width=device-width, initial-scale=1">

    <meta name="description"
          content="{safe(desc_meta)}">

    <link rel="canonical" href="{canonical_url}">

    <!-- Open Graph -->
    <meta property="og:title"
          content="{safe(title)} | {safe(company)}">

    <meta property="og:description"
          content="{safe(desc_meta)}">

    <meta property="og:url"
          content="{canonical_url}">

    <meta property="og:type"
          content="website">

    <!-- Google JobPosting Schema -->
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "JobPosting",
      "title": "{jstr(title)}",
      "description": "{jstr(desc)}",
      "datePosted": "{jstr(posted)}",
      "employmentType": "{jstr(emp_type)}",
      "hiringOrganization": {{
        "@type": "Organization",
        "name": "{jstr(company)}"
      }},
      "jobLocation": {{
        "@type": "Place",
        "address": {{
          "@type": "PostalAddress",
          "addressLocality": "{jstr(location)}"
        }}
      }},
      "applicantLocationRequirements": {{
        "@type": "Country",
        "name": "United States"
      }},
      "url": "{canonical_url}"
    }}
    </script>

</head>

<body style="
    font-family: Arial, sans-serif;
    max-width: 850px;
    margin: 40px auto;
    padding: 20px;
    line-height: 1.6;
">

    <div style="margin-bottom:30px;">
        <a href="/jobs/">&larr; Back to Jobs</a>
    </div>

    <h1>{safe(title)}</h1>

    <div style="
        margin-bottom:25px;
        color:#555;
        font-size:16px;
    ">
        <strong>{safe(company)}</strong><br>
        {safe(location)}<br>
        {safe(category)}
    </div>

    <hr>

    <div style="
        margin-top:25px;
        margin-bottom:35px;
        white-space:pre-wrap;
    ">
        {safe(desc)}
    </div>

    <a href="{apply_url}"
       target="_blank"
       rel="noopener noreferrer"
       style="
            display:inline-block;
            background:#111;
            color:#fff;
            padding:14px 22px;
            text-decoration:none;
            border-radius:6px;
            font-weight:bold;
       ">
        Apply Now
    </a>

</body>
</html>
"""

    with open(job_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(job_html)

    generated += 1

# ─────────────────────────────────────────────
# Generate jobs listing page
# ─────────────────────────────────────────────

job_cards = []

for job in jobs:

    title    = (job.findtext("title", "") or "").strip()
    slug     = clean_slug(job.findtext("slug", "") or "")
    company  = (job.findtext("company", "") or "").strip()
    location = (job.findtext("office_location", "") or "").strip()
    category = (job.findtext("category", "") or "").strip()

    if not slug:
        continue

    job_cards.append(f"""
    <div style="
        padding:24px 0;
        border-bottom:1px solid #e5e5e5;
    ">

        <h2 style="
            margin-bottom:8px;
            font-size:24px;
        ">
            <a href="/jobs/{slug}/"
               style="
                    color:#111;
                    text-decoration:none;
               ">
               {safe(title)}
            </a>
        </h2>

        <div style="
            color:#555;
            font-size:15px;
        ">
            <strong>{safe(company)}</strong>
            &nbsp;&bull;&nbsp;
            {safe(location)}
            &nbsp;&bull;&nbsp;
            {safe(category)}
        </div>

    </div>
    """)

jobs_index_html = f"""<!doctype html>
<html lang="en">
<head>

    <meta charset="utf-8">

    <title>Political & Public Affairs Jobs | Polly</title>

    <meta name="viewport" content="width=device-width, initial-scale=1">

    <meta name="description"
          content="Browse jobs in politics, public affairs, lobbying, advocacy, communications, campaigns, and government relations.">

    <link rel="canonical" href="{BASE_URL}/jobs/">

    <meta property="og:title" content="Political & Public Affairs Jobs | Polly">
    <meta property="og:description" content="Browse jobs in politics, public affairs, lobbying, advocacy, communications, campaigns, and government relations.">
    <meta property="og:url" content="{BASE_URL}/jobs/">
    <meta property="og:type" content="website">

</head>

<body style="
    font-family: Arial, sans-serif;
    max-width: 950px;
    margin: 40px auto;
    padding: 20px;
    line-height: 1.5;
">

    <h1 style="margin-bottom:10px;">
        Political & Public Affairs Jobs
    </h1>

    <p style="
        color:#555;
        margin-bottom:40px;
        font-size:18px;
    ">
        Curated jobs across public affairs, lobbying,
        policy, communications, advocacy, campaigns,
        and government relations.
    </p>

    {''.join(job_cards)}

</body>
</html>
"""

with open(OUTPUT_DIR / "index.html", "w", encoding="utf-8") as f:
    f.write(jobs_index_html)

# ─────────────────────────────────────────────
# Generate sitemap.xml
# ─────────────────────────────────────────────

sitemap_urls = [f"""  <url>
    <loc>{BASE_URL}/jobs/</loc>
  </url>"""]

for job in jobs:

    slug   = clean_slug(job.findtext("slug", "") or "")
    posted = (job.findtext("date_posted", "") or "").strip()

    if not slug:
        continue

    lastmod = f"\n    <lastmod>{safe(posted)}</lastmod>" if posted else ""

    sitemap_urls.append(f"""  <url>
    <loc>{BASE_URL}/jobs/{slug}/</loc>{lastmod}
  </url>""")

sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
""" + "\n".join(sitemap_urls) + "\n</urlset>\n"

with open("docs/sitemap.xml", "w", encoding="utf-8") as f:
    f.write(sitemap_xml)

# ─────────────────────────────────────────────
# Generate robots.txt
# ─────────────────────────────────────────────

robots_txt = f"""User-agent: *
Allow: /

Sitemap: {BASE_URL}/sitemap.xml
"""

with open("docs/robots.txt", "w", encoding="utf-8") as f:
    f.write(robots_txt)

print(f"Generated {generated} job pages")
print("Generated jobs index page")
print("Generated docs/sitemap.xml")
print("Generated docs/robots.txt")
