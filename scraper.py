import re
import json
import html
import logging
import time
import hashlib
from datetime import date, datetime
from xml.dom import minidom
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://thepolly.co"

API_KEY = "YOUR_API_KEY"
EMAIL = "politemps@gmail.com"

# ─────────────────────────────────────────────────────────────
# Canonical Organization Names
# ─────────────────────────────────────────────────────────────

ORG_NAMES = {
    "aclu": "ACLU",
    "aclunc": "ACLU Northern California",
    "moveonorg": "MoveOn",
    "sierraclub": "Sierra Club",
    "plannedparenthood": "Planned Parenthood",
    "ppfa": "Planned Parenthood Federation of America",
    "emilyslist": "EMILYs List",
    "indivisible": "Indivisible",
    "publiccitizen": "Public Citizen",
    "commoncause": "Common Cause",
    "unitedwedream": "United We Dream",
    "nextgenamerica": "NextGen America",
    "whenweallvote": "When We All Vote",
    "rockthevote": "Rock the Vote",
    "leaguewv": "League of Women Voters",
    "naacpldf": "NAACP Legal Defense Fund",
    "americanprogressaction": "American Progress Action",
    "centerforamericanprogress": "Center for American Progress",
    "protectdemocracy": "Protect Democracy",
    "democracydocket": "Democracy Docket",
    "gmmb": "GMMB",
    "berlinrosen": "BerlinRosen",
    "axios": "Axios",
    "fp1-strategies": "FP1 Strategies",
}

# ─────────────────────────────────────────────────────────────
# Boards
# ─────────────────────────────────────────────────────────────

GREENHOUSE_BOARDS = [
    "aclu",
    "moveonorg",
    "sierraclub",
    "emilyslist",
    "gmmb",
    "berlinrosen",
]

LEVER_BOARDS = [
    "sierraclub",
]

WORKABLE_BOARDS = [
    "fp1-strategies",
]

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
        "voter", "political director", "gotv",
        "election", "candidate"
    ],

    "Public Affairs & Lobbying": [
        "public affairs", "government relations",
        "lobby", "stakeholder", "advocacy"
    ],

    "Government & Policy": [
        "policy", "legislative", "congress",
        "senate", "house", "federal",
        "committee", "regulatory"
    ],

    "Communications & PR": [
        "communications", "media", "press",
        "digital", "social media", "spokesperson"
    ],

    "Nonprofit Advocacy": [
        "grassroots", "nonprofit", "organizing",
        "civic engagement", "coalition"
    ],
}

# ─────────────────────────────────────────────────────────────
# Tag Rules
# ─────────────────────────────────────────────────────────────

TAG_RULES = {
    "Climate Policy": ["climate", "environment", "clean energy"],
    "Healthcare": ["healthcare", "medicaid", "medicare"],
    "Democracy Reform": ["voting rights", "democracy"],
    "Communications": ["communications", "media", "press"],
    "Federal Policy": ["federal", "congress", "senate"],
}

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def clean(raw):
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")

def build_job_id(source, org, raw_id):
    return f"{source}-{org}-{raw_id}"

def detect_remote(location, desc=""):
    combined = f"{location} {desc}".lower()

    remote_terms = [
        "remote",
        "work from home",
        "distributed",
        "hybrid",
        "telework",
    ]

    return any(term in combined for term in remote_terms)

def guess_category(title, desc=""):
    combined = f"{title} {desc}".lower()

    scores = {}

    for category, keywords in CATEGORY_RULES.items():
        score = sum(1 for kw in keywords if kw in combined)
        scores[category] = score

    best = max(scores, key=scores.get)

    if scores[best] == 0:
        return "Government & Policy"

    return best

def extract_tags(title, desc=""):
    combined = f"{title} {desc}".lower()

    tags = []

    for tag, keywords in TAG_RULES.items():
        if any(k in combined for k in keywords):
            tags.append(tag)

    return tags

def canonical_company(board):
    return ORG_NAMES.get(board, board.replace("-", " ").title())

def build_slug(title, company):
    return slugify(f"{title}-{company}")

# ─────────────────────────────────────────────────────────────
# Core Job Pipeline
# ─────────────────────────────────────────────────────────────

jobs = []
seen = set()

def add_job(
    source,
    raw_id,
    title,
    company,
    apply_url,
    description="",
    office_location="",
    posted=None,
):
    unique_id = build_job_id(source, slugify(company), raw_id)

    if unique_id in seen:
        return

    seen.add(unique_id)

    description = clean(description)[:1500]

    category = guess_category(title, description)

    tags = extract_tags(title, description)

    remote = detect_remote(office_location, description)

    slug = build_slug(title, company)

    canonical_url = f"{BASE_URL}/jobs/{slug}"

    posted = (posted or str(date.today()))[:10]

    parts = [p.strip() for p in office_location.split(",")]

    locality = parts[0] if len(parts) > 0 else ""
    region = parts[1] if len(parts) > 1 else ""

    jobs.append({
        "job_id": unique_id,
        "source": source,
        "title": title,
        "slug": slug,
        "canonical_url": canonical_url,
        "company": company,
        "description": description,
        "apply_url": apply_url,
        "category": category,
        "tags": ",".join(tags),
        "location_type": "remote" if remote else "onsite",
        "office_location": office_location,
        "address_locality": locality,
        "address_region": region,
        "employment_type": "FULL_TIME",
        "date_posted": posted,
        "valid_through": "2026-12-31",
        "direct_apply": "true",
    })

    log.info("  + %s @ %s", title, company)

# ─────────────────────────────────────────────────────────────
# USAJobs Example
# ─────────────────────────────────────────────────────────────

log.info("=== Fetching USAJobs ===")

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

            company = pos.get(
                "OrganizationName",
                "U.S. Federal Government"
            )

            apply_uris = pos.get("ApplyURI", [])

            apply_url = (
                apply_uris[0]
                if apply_uris
                else "https://www.usajobs.gov"
            )

            description = clean(
                pos.get("UserArea", {})
                .get("Details", {})
                .get("JobSummary", "")
            )

            locs = pos.get("PositionLocation", [])

            office = (
                locs[0].get("LocationName", "")
                if locs
                else ""
            )

            posted = (
                pos.get("PublicationStartDate")
                or str(date.today())
            )[:10]

            add_job(
                source="usajobs",
                raw_id=raw_id,
                title=title,
                company=company,
                apply_url=apply_url,
                description=description,
                office_location=office,
                posted=posted,
            )

        time.sleep(0.5)

    except Exception as ex:
        log.warning("USAJobs failed '%s': %s", term, ex)

# ─────────────────────────────────────────────────────────────
# Greenhouse Example
# ─────────────────────────────────────────────────────────────

log.info("=== Fetching Greenhouse ===")

for board in GREENHOUSE_BOARDS:

    try:

        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

        req = urllib.request.Request(url, headers={
            "User-Agent": "PoliticalJobsFeed/1.0"
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        items = data.get("jobs", [])

        for j in items:

            raw_id = str(j.get("id", ""))

            title = j.get("title", "")

            company = canonical_company(board)

            apply_url = j.get(
                "absolute_url",
                f"https://boards.greenhouse.io/{board}"
            )

            location = j.get("location", {}).get("name", "")

            description = clean(j.get("content", ""))

            posted = (
                j.get("updated_at")
                or str(date.today())
            )[:10]

            add_job(
                source="greenhouse",
                raw_id=raw_id,
                title=title,
                company=company,
                apply_url=apply_url,
                description=description,
                office_location=location,
                posted=posted,
            )

        time.sleep(0.3)

    except Exception as ex:
        log.warning("Greenhouse %s failed: %s", board, ex)

# ─────────────────────────────────────────────────────────────
# Build XML
# ─────────────────────────────────────────────────────────────

log.info("Total jobs: %d", len(jobs))

root = ET.Element("jobs")

root.set(
    "generated",
    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
)

root.set("count", str(len(jobs)))

for job in jobs:

    el = ET.SubElement(root, "job")

    for key, value in job.items():

        child = ET.SubElement(el, key)
        child.text = str(value)

xml = minidom.parseString(
    '<?xml version="1.0" encoding="UTF-8"?>' +
    ET.tostring(root, encoding="unicode")
).toprettyxml(indent="  ")

with open("feed.xml", "w", encoding="utf-8") as f:
    f.write(xml)

log.info("Written -> feed.xml")
