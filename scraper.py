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
#
# Greenhouse migrated to job-boards.greenhouse.io
# Lever boards confirmed at jobs.lever.co
# ─────────────────────────────────────────────

GREENHOUSE_BOARDS = [
    "aclu",
    "moveonorg",
    "gmmb",
    "berlinrosen",
    "humanrightswatch",
    "communitychange",
    "democracyforward",
    "southernpovertylawcenter",
]

LEVER_COMPANIES = [
    "sierraclub",
    "emilyslist",
]

USAJOBS_SEARCHES = [
    "public affairs",
    "communications director",
]

# USAJobs job series codes to filter by (communications & policy roles only):
# 1035 = Public Affairs, 0301 = Misc Admin & Program, 1082 = Writing/Editing, 1001 = General Arts & Info
USAJOBS_SERIES = ["1035", "0301", "1082", "1001"]

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
                "ResultsPerPage": 10,
                "JobCategoryCode": ";".join(USAJOBS_SERIES),
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
# Greenhouse — scrape job-boards.greenhouse.io
# (Greenhouse migrated away from boards.greenhouse.io)
# ─────────────────────────────────────────────

def fetch_greenhouse():
    log.info("=== Greenhouse ===")

    for board in GREENHOUSE_BOARDS:
        try:
            url = f"https://job-boards.greenhouse.io/{board}"
            log.info("Fetching %s", url)
            page = fetch_url(url)

            # job-boards.greenhouse.io embeds job data as JSON in a <script> tag:
            # <script type="application/json" data-js="gh-jobs">[ ... ]</script>
            json_match = re.search(
                r'<script[^>]+data-js=["\']gh-jobs["\'][^>]*>(.*?)</script>',
                page, re.DOTALL
            )

            if json_match:
                try:
                    job_list = json.loads(json_match.group(1))
                    for j in job_list:
                        job_id = str(j.get("id", ""))
                        title = j.get("title", "")
                        location = j.get("location", {}).get("name", "") if isinstance(j.get("location"), dict) else str(j.get("location", ""))
                        apply_url = j.get("absolute_url", f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}")
                        desc = j.get("content", "") or j.get("description", "")

                        if title and job_id:
                            add_job("greenhouse", job_id, title, board, apply_url, desc, location)
                    log.info("Greenhouse %s: %d jobs from JSON", board, len(job_list))
                    time.sleep(0.3)
                    continue
                except json.JSONDecodeError:
                    pass

            # Fallback: parse HTML links
            job_links = re.findall(
                r'href="[^"]*?/jobs/(\d+)"[^>]*>\s*<[^>]+>\s*([^<]{3,100}?)\s*</',
                page
            )

            if not job_links:
                log.warning("Greenhouse %s: no jobs found — page structure unknown", board)
                log.warning("Greenhouse %s page preview: %s", board, page[:500])
                continue

            for job_id, title in job_links:
                if not title:
                    continue
                title = clean(title)
                apply_url = f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}"
                add_job("greenhouse", job_id, title, board, apply_url, "", "")

            time.sleep(0.5)

        except Exception as e:
            log.warning("Greenhouse error %s: %s", board, e)

# ─────────────────────────────────────────────
# Lever — scrape jobs.lever.co public board
# ─────────────────────────────────────────────

def fetch_lever():
    log.info("=== Lever ===")

    for company in LEVER_COMPANIES:
        try:
            url = f"https://jobs.lever.co/{company}"
            log.info("Fetching %s", url)
            page = fetch_url(url)

            # Try JSON-LD first
            jsonld_match = re.search(
                r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                page, re.DOTALL
            )
            if jsonld_match:
                try:
                    data = json.loads(jsonld_match.group(1))
                    items = data if isinstance(data, list) else [data]
                    found = 0
                    for item in items:
                        if item.get("@type") == "JobPosting":
                            job_id = hashlib.md5(item.get("url", "").encode()).hexdigest()[:12]
                            title = item.get("title", "")
                            location = item.get("jobLocation", {}).get("address", {}).get("addressLocality", "")
                            apply_url = item.get("url", "")
                            desc = item.get("description", "")
                            if title:
                                add_job("lever", job_id, title, company, apply_url, desc, location)
                                found += 1
                    if found:
                        log.info("Lever %s: %d jobs from JSON-LD", company, found)
                        time.sleep(0.3)
                        continue
                except json.JSONDecodeError:
                    pass

            # Fallback: scrape HTML for posting UUIDs
            postings = re.findall(
                r'href="(https://jobs\.lever\.co/' + re.escape(company) + r'/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}))"',
                page
            )

            if not postings:
                log.warning("Lever %s: no postings found in HTML", company)
                log.warning("Lever %s page preview: %s", company, page[:500])
                continue

            seen_ids = set()
            for apply_url, job_id in postings:
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                title_match = re.search(
                    re.escape(apply_url) + r'[^>]*>.*?<h5[^>]*>\s*([^<]{3,120}?)\s*</h5>',
                    page, re.DOTALL
                )
                title = clean(title_match.group(1)) if title_match else ""

                loc_match = re.search(
                    re.escape(apply_url) + r'.{0,400}?<span[^>]*sort-by-location[^>]*>\s*([^<]+?)\s*</span>',
                    page, re.DOTALL
                )
                location = clean(loc_match.group(1)) if loc_match else ""

                if title:
                    add_job("lever", job_id, title, company, apply_url, "", location)

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
