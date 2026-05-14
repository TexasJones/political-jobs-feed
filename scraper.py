import re
import json
import html
import logging
import time
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

from datetime import date, datetime
from xml.dom import minidom

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://thepolly.co"

API_KEY = "YOUR_USAJOBS_API_KEY"
EMAIL = "politemps@gmail.com"

# ─────────────────────────────────────────────────────────────
# Organization Canonicalization
# ─────────────────────────────────────────────────────────────

ORG_NAMES = {
    "aclu": "ACLU",
    "moveonorg": "MoveOn",
    "sierraclub": "Sierra Club",
    "emilyslist": "EMILYs List",
    "ppfa": "Planned Parenthood Federation of America",
    "centerforamericanprogress": "Center for American Progress",
    "gmmb": "GMMB",
    "berlinrosen": "BerlinRosen",
    "axios": "Axios",
    "fp1-strategies": "FP1 Strategies",
}

# ─────────────────────────────────────────────────────────────
# Data Sources
# ─────────────────────────────────────────────────────────────

GREENHOUSE_BOARDS = [
    "aclu",
    "moveonorg",
    "sierraclub",
    "emilyslist",
    "gmmb",
    "berlinrosen",
]

LEVER_BOARDS = ["sierraclub"]

WORKABLE_BOARDS = ["fp1-strategies"]

USAJOBS_SEARCHES = [
    "public affairs",
    "government relations",
    "policy analyst",
    "communications director",
]

# ─────────────────────────────────────────────────────────────
# Category Rules
# ─────────────────────────────────────────────────────────────

CATEGORY_RULES = {
    "Political Campaigns": [
        "campaign", "field organizer", "canvass",
        "voter", "political director", "gotv", "election"
    ],
    "Public Affairs & Lobbying": [
        "public affairs", "government relations", "lobby", "advocacy"
    ],
    "Government & Policy": [
        "policy", "legislative", "congress", "senate", "house", "federal"
    ],
    "Communications & PR": [
        "communications", "media", "press", "spokesperson", "digital"
    ],
    "Nonprofit Advocacy": [
        "nonprofit", "grassroots", "organizing", "civic"
    ],
}

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")

def canonical_company(board: str) -> str:
    return ORG_NAMES.get(board, board.replace("-", " ").title())

def build_job_id(source: str, org: str, raw_id: str) -> str:
    return f"{source}-{org}-{raw_id}"

def detect_remote(location: str, desc: str = "") -> bool:
    text = f"{location} {desc}".lower()
    return any(k in text for k in [
        "remote", "work from home", "hybrid", "distributed", "telework"
    ])

def guess_category(title: str, desc: str = "") -> str:
    text = f"{title} {desc}".lower()
    scores = {}

    for cat, kws in CATEGORY_RULES.items():
        scores[cat] = sum(1 for k in kws if k in text)

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Government & Policy"

def build_slug(title: str, company: str) -> str:
    return slugify(f"{title}-{company}")

jobs = []
seen = set()

# ─────────────────────────────────────────────────────────────
# Job Pipeline
# ─────────────────────────────────────────────────────────────

def add_job(source, raw_id, title, company, apply_url,
            description="", office_location="", posted=None):

    company_slug = slugify(company)
    job_id = build_job_id(source, company_slug, raw_id)

    if job_id in seen:
        return

    seen.add(job_id)

    description = clean(description)[:1500]
    category = guess_category(title, description)
    remote = detect_remote(office_location, description)

    slug = build_slug(title, company)
    canonical_url = f"{BASE_URL}/jobs/{slug}"

    posted = (posted or str(date.today()))[:10]

    parts = [p.strip() for p in office_location.split(",")]
    locality = parts[0] if len(parts) > 0 else ""
    region = parts[1] if len(parts) > 1 else ""

    jobs.append({
        "job_id": job_id,
        "source": source,
        "title": title,
        "company": company,
        "slug": slug,
        "canonical_url": canonical_url,
        "description": description,
        "apply_url": apply_url,
        "category": category,
        "location_type": "remote" if remote else "onsite",
        "office_location": office_location,
        "address_locality": locality,
        "address_region": region,
        "employment_type": "FULL_TIME",
        "date_posted": posted,
        "valid_through": "2026-12-31",
    })

    log.info("  + %s @ %s", title, company)

# ─────────────────────────────────────────────────────────────
# USAJobs
# ─────────────────────────────────────────────────────────────

log.info("=== USAJobs ===")

for term in USAJOBS_SEARCHES:

    try:
        params = urllib.parse.urlencode({
            "Keyword": term,
            "ResultsPerPage": 25
        })

        url = f"https://data.usajobs.gov/api/search?{params}"

        req = urllib.request.Request(url, headers={
            "Host": "data.usajobs.gov",
            "User-Agent": EMAIL,
            "Authorization-Key": API_KEY,
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        items = data.get("SearchResult", {}).get("SearchResultItems", [])

        for item in items:
            pos = item.get("MatchedObjectDescriptor", {})

            raw_id = pos.get("PositionID", hashlib.md5(str(item).encode()).hexdigest())

            title = pos.get("PositionTitle", "")
            company = pos.get("OrganizationName", "U.S. Federal Government")

            apply_url = pos.get("ApplyURI", ["https://www.usajobs.gov"])[0]

            desc = clean(pos.get("UserArea", {}).get("Details", {}).get("JobSummary", ""))

            locs = pos.get("PositionLocation", [])
            office = locs[0].get("LocationName", "") if locs else ""

            posted = (pos.get("PublicationStartDate") or str(date.today()))[:10]

            add_job("usajobs", raw_id, title, company, apply_url, desc, office, posted)

        time.sleep(0.5)

    except Exception as e:
        log.warning("USAJobs error: %s", e)

# ─────────────────────────────────────────────────────────────
# Greenhouse
# ─────────────────────────────────────────────────────────────

log.info("=== Greenhouse ===")

for board in GREENHOUSE_BOARDS:

    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

        req = urllib.request.Request(url, headers={
            "User-Agent": "PoliticalJobsFeed/1.0"
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        for j in data.get("jobs", []):

            raw_id = str(j.get("id"))
            title = j.get("title", "")
            company = canonical_company(board)

            apply_url = j.get(
                "absolute_url",
                f"https://boards.greenhouse.io/{board}"
            )

            desc = clean(j.get("content", ""))
            location = j.get("location", {}).get("name", "")

            posted = (j.get("updated_at") or str(date.today()))[:10]

            add_job("greenhouse", raw_id, title, company,
                    apply_url, desc, location, posted)

        time.sleep(0.3)

    except Exception as e:
        log.warning("Greenhouse error %s: %s", board, e)

# ─────────────────────────────────────────────────────────────
# Build XML Feed
# ─────────────────────────────────────────────────────────────

log.info("Total jobs: %d", len(jobs))

root = ET.Element("jobs")
root.set("generated", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
root.set("count", str(len(jobs)))

for job in jobs:
    el = ET.SubElement(root, "job")
    for k, v in job.items():
        ET.SubElement(el, k).text = str(v)

xml = minidom.parseString(
    '<?xml version="1.0" encoding="UTF-8"?>'
    + ET.tostring(root, encoding="unicode")
).toprettyxml(indent="  ")

with open("feed.xml", "w", encoding="utf-8") as f:
    f.write(xml)

log.info("Written -> feed.xml")
