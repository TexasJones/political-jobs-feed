import re
import json
import html
import logging
import time
import hashlib
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

from datetime import date, datetime
from xml.dom import minidom

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://thepolly.co"

API_KEY = os.getenv("USAJOBS_API_KEY")
EMAIL = os.getenv("USAJOBS_EMAIL", "info@thepolly.co")

# ─────────────────────────────────────────────
# Sources
# ─────────────────────────────────────────────

GREENHOUSE_BOARDS = [
    "aclu",
    "moveonorg",
    "sierraclub",
    "emilyslist",
    "gmmb",
    "berlinrosen",
]

USAJOBS_SEARCHES = [
    "public affairs",
    "government relations",
    "policy analyst",
    "communications director",
]

# ─────────────────────────────────────────────
# Lever Expansion (PR / Public Affairs / Comms)
# ─────────────────────────────────────────────

LEVER_COMPANIES = [
    "berlinrosen",
    "bullypulpitinteractive",
    "skdk",
    "fgs-global",
    "purple-strategies",
    "rokk-solutions"
]

# ─────────────────────────────────────────────
# Category logic
# ─────────────────────────────────────────────

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
        "communications", "media", "press", "spokesperson", "digital", "social"
    ],
    "Nonprofit Advocacy": [
        "nonprofit", "grassroots", "organizing", "civic"
    ],
}

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

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


def detect_remote(location: str, desc: str = "") -> bool:
    text = f"{location} {desc}".lower()
    return any(k in text for k in ["remote", "work from home", "hybrid", "distributed", "telework"])


def guess_category(title: str, desc: str = "") -> str:
    text = f"{title} {desc}".lower()
    scores = {cat: sum(k in text for k in kws) for cat, kws in CATEGORY_RULES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Government & Policy"


def build_job_id(source: str, raw_id: str) -> str:
    return f"{source}-{raw_id}"


jobs = []
seen = set()

# ─────────────────────────────────────────────
# Core ingestion
# ─────────────────────────────────────────────

def add_job(source, raw_id, title, company, apply_url,
            description="", location="", posted=None):

    job_id = build_job_id(source, f"{company}-{raw_id}")

    if job_id in seen:
        return
    seen.add(job_id)

    description = clean(description)[:1500]
    category = guess_category(title, description)
    remote = detect_remote(location, description)

    slug = slugify(f"{title}-{company}")
    canonical_url = f"{BASE_URL}/jobs/{slug}"

    posted = (posted or str(date.today()))[:10]

    jobs.append({
        "job_id": job_id,
        "title": title,
        "company": company,
        "slug": slug,
        "canonical_url": canonical_url,
        "description": description,
        "apply_url": apply_url,
        "category": category,
        "location_type": "remote" if remote else "onsite",
        "office_location": location,
        "employment_type": "FULL_TIME",
        "date_posted": posted,
        "valid_through": "2026-12-31",
        "source": source
    })

    log.info("+ %s @ %s", title, company)

# ─────────────────────────────────────────────
# USAJobs
# ─────────────────────────────────────────────

def fetch_usajobs():
    log.info("=== USAJobs ===")

    if not API_KEY:
        log.warning("Skipping USAJobs (no API key)")
        return

    for term in USAJOBS_SEARCHES:
        try:
            url = "https://data.usajobs.gov/api/search?" + urllib.parse.urlencode({
                "Keyword": term,
                "ResultsPerPage": 25
            })

            req = urllib.request.Request(url, headers={
                "Host": "data.usajobs.gov",
                "User-Agent": EMAIL,
                "Authorization-Key": API_KEY,
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            for item in data.get("SearchResult", {}).get("SearchResultItems", []):
                pos = item.get("MatchedObjectDescriptor", {})

                raw_id = pos.get("PositionID", hashlib.md5(str(item).encode()).hexdigest())
                title = pos.get("PositionTitle", "")
                company = pos.get("OrganizationName", "U.S. Federal Government")
                apply_url = pos.get("ApplyURI", [""])[0]
                desc = pos.get("UserArea", {}).get("Details", {}).get("JobSummary", "")

                locs = pos.get("PositionLocation", [])
                location = locs[0].get("LocationName", "") if locs else ""

                posted = (pos.get("PublicationStartDate") or str(date.today()))[:10]

                add_job("usajobs", raw_id, title, company, apply_url, desc, location, posted)

            time.sleep(0.5)

        except Exception as e:
            log.warning("USAJobs error: %s", e)

# ─────────────────────────────────────────────
# Greenhouse
# ─────────────────────────────────────────────

def fetch_greenhouse():
    log.info("=== Greenhouse ===")

    for board in GREENHOUSE_BOARDS:
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

            req = urllib.request.Request(url, headers={
                "User-Agent": "PollyFeed/1.0"
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            for j in data.get("jobs", []):
                add_job(
                    "greenhouse",
                    str(j.get("id")),
                    j.get("title", ""),
                    board,
                    j.get("absolute_url", ""),
                    j.get("content", ""),
                    j.get("location", {}).get("name", ""),
                    j.get("updated_at")
                )

            time.sleep(0.3)

        except Exception as e:
            log.warning("Greenhouse error %s: %s", board, e)

# ─────────────────────────────────────────────
# Lever (PR / Comms expansion)
# ─────────────────────────────────────────────

def fetch_lever():
    log.info("=== Lever ===")

    for company in LEVER_COMPANIES:
        try:
            url = f"https://api.lever.co/v0/postings/{company}?mode=json"

            req = urllib.request.Request(url, headers={
                "User-Agent": "PollyFeed/1.0"
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            for j in data:
                add_job(
                    "lever",
                    j.get("id", ""),
                    j.get("text", ""),
                    company,
                    j.get("hostedUrl", ""),
                    j.get("descriptionPlain", ""),
                    j.get("categories", {}).get("location", ""),
                    j.get("createdAt", "")
                )

        except Exception:
            continue

# ─────────────────────────────────────────────
# Run pipeline
# ─────────────────────────────────────────────

fetch_usajobs()
fetch_greenhouse()
fetch_lever()

# ─────────────────────────────────────────────
# Build XML feed
# ─────────────────────────────────────────────

log.info("Total jobs: %d", len(jobs))

root = ET.Element("jobs")
root.set("generated", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
root.set("count", str(len(jobs)))

for job in jobs:
    el = ET.SubElement(root, "job")
    for k, v in job.items():
        ET.SubElement(el, k).text = str(v)

xml = minidom.parseString(
    '<?xml version="1.0" encoding="UTF-8"?>' +
    ET.tostring(root, encoding="unicode")
).toprettyxml(indent="  ")

with open("feed.xml", "w", encoding="utf-8") as f:
    f.write(xml)

log.info("Written -> feed.xml")
