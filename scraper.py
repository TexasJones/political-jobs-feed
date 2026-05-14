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

from datetime import date, datetime, timezone
from xml.dom import minidom

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://thepolly.co"

API_KEY = os.getenv("USAJOBS_API_KEY")
EMAIL = os.getenv("USAJOBS_EMAIL", "info@thepolly.co")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

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

LEVER_COMPANIES = [
    "berlinrosen",
    "bullypulpitinteractive",
    "skdk",
    "fgs-global",
    "purple-strategies",
    "rokk-solutions",
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


def fetch_url(url: str, timeout: int = 15) -> str:
    """Fetch a URL with browser-like headers. Returns decoded text."""
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


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

    # Normalize posted date — handles ISO strings and Unix ms timestamps
    if posted:
        posted = str(posted)
        if re.match(r"^\d{13}$", posted):
            # Lever returns Unix milliseconds
            posted = datetime.fromtimestamp(int(posted) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        else:
            posted = posted[:10]
    else:
        posted = str(date.today())

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
        "valid_through": "2027-12-31",
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
# Greenhouse — scrape public board HTML
# ─────────────────────────────────────────────

def fetch_greenhouse():
    log.info("=== Greenhouse ===")

    for board in GREENHOUSE_BOARDS:
        try:
            url = f"https://boards.greenhouse.io/{board}"
            page = fetch_url(url)

            # Each job is an <a> inside a .job-post <div> or <li>
            # Pattern: <a href="/board_slug/jobs/12345">Job Title</a>
            # Location is in a sibling <span class="location">...</span>

            # Find all job links on the board
            job_links = re.findall(
                r'href="(/[^"]+/jobs/(\d+))"[^>]*>\s*([^<]+?)\s*</a>',
                page
            )

            if not job_links:
                log.warning("Greenhouse %s: no jobs found in HTML (structure may have changed)", board)
                continue

            for path, job_id, title in job_links:
                title = title.strip()
                if not title:
                    continue

                apply_url = f"https://boards.greenhouse.io{path}"

                # Try to get location from the same page
                # Greenhouse wraps each posting in a <div class="job-post">
                # We look for the location near this job's link
                loc_pattern = re.compile(
                    re.escape(path) + r'.{0,300}?<span[^>]*class="[^"]*location[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
                    re.DOTALL
                )
                loc_match = loc_pattern.search(page)
                location = loc_match.group(1).strip() if loc_match else ""

                # Fetch individual job page for description
                desc = ""
                try:
                    job_page = fetch_url(apply_url)
                    # Description lives in <div id="content"> or <div class="job-post-description">
                    desc_match = re.search(
                        r'<div[^>]+(?:id="content"|class="[^"]*job-post-description[^"]*")[^>]*>(.*?)</div>',
                        job_page, re.DOTALL
                    )
                    if desc_match:
                        desc = desc_match.group(1)
                    time.sleep(0.4)
                except Exception as e:
                    log.warning("Greenhouse desc fetch failed %s/%s: %s", board, job_id, e)

                add_job(
                    "greenhouse",
                    job_id,
                    title,
                    board,
                    apply_url,
                    desc,
                    location,
                    str(date.today())
                )

            time.sleep(0.5)

        except Exception as e:
            log.warning("Greenhouse error %s: %s", board, e)

# ─────────────────────────────────────────────
# Lever — scrape public board HTML
# ─────────────────────────────────────────────

def fetch_lever():
    log.info("=== Lever ===")

    for company in LEVER_COMPANIES:
        try:
            url = f"https://jobs.lever.co/{company}"
            page = fetch_url(url)

            # Lever job links look like:
            # <a class="posting-title" href="https://jobs.lever.co/company/uuid">
            #   <h5>Job Title</h5>
            #   <span class="sort-by-location">New York, NY</span>
            # </a>

            # Find all posting blocks
            postings = re.findall(
                r'<a[^>]+class="[^"]*posting-title[^"]*"[^>]+href="(https://jobs\.lever\.co/'
                + re.escape(company) +
                r'/([a-f0-9\-]{36}))"[^>]*>(.*?)</a>',
                page, re.DOTALL
            )

            if not postings:
                log.warning("Lever %s: no postings found in HTML (structure may have changed)", company)
                continue

            for apply_url, job_id, block in postings:
                # Title is in <h5> inside the block
                title_match = re.search(r'<h5[^>]*>\s*([^<]+?)\s*</h5>', block)
                title = title_match.group(1).strip() if title_match else ""

                if not title:
                    continue

                # Location is in sort-by-location or location span
                loc_match = re.search(
                    r'<span[^>]*class="[^"]*(?:sort-by-location|location)[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
                    block
                )
                location = loc_match.group(1).strip() if loc_match else ""

                # Fetch individual posting for description
                desc = ""
                try:
                    job_page = fetch_url(apply_url)
                    # Lever descriptions are in <div class="section page-centered">
                    # or <div class="content"> inside the posting
                    desc_match = re.search(
                        r'<div[^>]+class="[^"]*section[^"]*page-centered[^"]*"[^>]*>(.*?)</div>\s*<div[^>]+class="[^"]*page-centered[^"]*"',
                        job_page, re.DOTALL
                    )
                    if not desc_match:
                        # fallback: grab the largest <div class="content"> block
                        desc_match = re.search(
                            r'<div[^>]+class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                            job_page, re.DOTALL
                        )
                    if desc_match:
                        desc = desc_match.group(1)
                    time.sleep(0.4)
                except Exception as e:
                    log.warning("Lever desc fetch failed %s/%s: %s", company, job_id, e)

                add_job(
                    "lever",
                    job_id,
                    title,
                    company,
                    apply_url,
                    desc,
                    location,
                    str(date.today())
                )

            time.sleep(0.5)

        except Exception as e:
            log.warning("Lever error %s: %s", company, e)

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
root.set("generated", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
root.set("count", str(len(jobs)))

for job in jobs:
    el = ET.SubElement(root, "job")
    for k, v in job.items():
        ET.SubElement(el, k).text = str(v)

xml_str = minidom.parseString(
    '<?xml version="1.0" encoding="UTF-8"?>' +
    ET.tostring(root, encoding="unicode")
).toprettyxml(indent="  ")

with open("feed.xml", "w", encoding="utf-8") as f:
    f.write(xml_str)

log.info("Written -> feed.xml")
