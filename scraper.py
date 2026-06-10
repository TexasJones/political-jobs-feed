import re
import json
import html
import logging
import time
import hashlib
import os
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

from datetime import date, datetime, timezone, timedelta
from xml.dom import minidom

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://jobs.thepolly.co"

API_KEY = os.getenv("USAJOBS_API_KEY")
EMAIL = os.getenv("USAJOBS_EMAIL", "info@thepolly.co")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─────────────────────────────────────────────
# Sources
# ─────────────────────────────────────────────

GREENHOUSE_BOARDS = [
    # Civil rights & advocacy
    "aclu",
    "southernpovertylawcenter",
    "democracyforward",
    "humanrightswatch",
    "ppfa",                     # Planned Parenthood
    "nrdc",                     # Natural Resources Defense Council
    "publicadvocates",          # Public Advocates
    # Political communications & campaigns
    "moveonorg",
    "gmmb",
    "berlinrosen",
    "industriouslabs",          # Climate policy campaigns
    # Think tanks & policy
    "americanprogress",         # Center for American Progress
    "brookings",                # Brookings Institution
    # Political data & analytics
    "civisanalytics",           # Civis Analytics
]

GREENHOUSE_NAMES = {
    "aclu": "ACLU",
    "southernpovertylawcenter": "Southern Poverty Law Center",
    "democracyforward": "Democracy Forward",
    "humanrightswatch": "Human Rights Watch",
    "ppfa": "Planned Parenthood",
    "nrdc": "NRDC",
    "publicadvocates": "Public Advocates",
    "moveonorg": "MoveOn.org",
    "gmmb": "GMMB",
    "berlinrosen": "BerlinRosen",
    "industriouslabs": "Industrious Labs",
    "americanprogress": "Center for American Progress",
    "brookings": "Brookings Institution",
    "civisanalytics": "Civis Analytics",
}

LEVER_COMPANIES = [
    # Progressive political orgs
    "emilyslist",               # EMILY's List
    "colorofchange",            # Color of Change
    "unitedwedream",            # United We Dream
    "dnc",                      # Democratic National Committee
    # Public affairs & comms firms
    "skdk",                     # SKDK (top Dem public affairs firm)
    "globalstrategygroup",      # Global Strategy Group (polling + public affairs)
    "apcoholdings",             # APCO Worldwide
]

LEVER_NAMES = {
    "emilyslist": "EMILY's List",
    "colorofchange": "Color of Change",
    "unitedwedream": "United We Dream",
    "dnc": "Democratic National Committee",
    "skdk": "SKDK",
    "globalstrategygroup": "Global Strategy Group",
    "apcoholdings": "APCO Worldwide",
}

WORKABLE_COMPANIES = [
    "fp1-strategies",           # FP1 Strategies — Republican political consulting
]

WORKDAY_COMPANIES = [
    {
        "slug": "politico",
        "host": "politico.wd108.myworkdayjobs.com",
        "name": "Politico",
    },
]

USAJOBS_SEARCHES = [
    "public affairs specialist",
    "legislative affairs",
    "communications director",
    "press secretary",
    "congressional affairs",
]

USAJOBS_SERIES = ["1035", "1082"]

# ─────────────────────────────────────────────
# Title blocklist — applies to ALL sources
# Drops roles that don't belong on a public affairs job board
# ─────────────────────────────────────────────

TITLE_BLOCKLIST = [
    # IT / Engineering
    "engineer", "developer", "software", "devops", "sysadmin",
    "cyber", "security operations", "endpoint", "network admin",
    "data scientist", "machine learning", "cloud architect",
    "information security", "information technology",
    "technical project manager", "technical program manager",
    "enterprise applications", "applications integration",
    # Finance / Accounting
    "accountant", "controller", "bookkeeper",
    "accounts payable", "accounts receivable", "payroll",
    # HR / People Ops
    "human resources", "talent acquisition", "recruiter", "hris",
    "benefits administrator", "learning & development",
    "learning and development", "people and culture", "chief people",
    # Legal (non-policy)
    "paralegal", "legal counsel", "general counsel", "staff attorney",
    "staff counsel", "senior counsel", "oversight counsel",
    "legal director", "legal advisor", "chief legal", "deputy legal",
    # Design / Creative (non-comms)
    "graphic design", "graphic designer", "visual design",
    # Facilities / Operations / Security
    "facilities", "construction", "maintenance", "custodial",
    "office manager", "executive assistant", "confidential assistant",
    "chief operating", "protective services", "protective security",
    # Admin catch-alls
    "business analyst", "future opportunities", "general interest",
    "fellowship sponsorship",
    # Healthcare
    "nurse", "physician", "medical", "clinical", "therapist",
    # USAJobs-specific noise
    "border protection", "customs", "immigration", "cbp officer",
    "agriculture specialist", "victim advocate", "family advocacy",
    "clinical counselor", "psychologist", "social worker",
    "field service technician", "property specialist",
    "security clearance", "intelligence", "inspector general",
    "contracting officer", "acquisition", "procurement",
    "scientist", "research", "laboratory",
    "law enforcement", "correctional", "detention",
    "military", "army", "navy", "marine", "air force",
    "logistics", "supply chain", "warehouse",
]

# ─────────────────────────────────────────────
# Category rules
# ─────────────────────────────────────────────

CATEGORY_RULES = {
    "Political Campaigns": [
        "campaign", "field organizer", "canvass",
        "voter", "political director", "gotv", "election",
    ],
    "Public Affairs & Lobbying": [
        "public affairs", "government relations", "lobby", "lobbying", "advocacy",
    ],
    "Government & Policy": [
        "policy", "legislative", "congress", "senate", "house", "federal",
    ],
    "Communications & PR": [
        "communications", "media relations", "press secretary", "spokesperson",
        "public relations", "earned media", "digital strategy", "social media manager",
    ],
    "Nonprofit Advocacy": [
        "nonprofit", "grassroots", "organizing", "civic",
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


def truncate(text: str, max_chars: int = 1500) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0]


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


def detect_remote(location: str, desc: str = "") -> bool:
    text = f"{location} {desc}".lower()
    return any(k in text for k in ["remote", "work from home", "hybrid", "distributed", "telework"])


def guess_category(title: str, desc: str = "") -> str:
    text = f"{title} {desc}".lower()
    scores = {cat: sum(k in text for k in kws) for cat, kws in CATEGORY_RULES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Government & Policy"


def guess_employment_type(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["intern", "fellowship", "fellow"]):
        return "INTERN"
    if any(k in t for k in ["temporary", "temp ", "term-limited", "contract"]):
        return "CONTRACTOR"
    if "part-time" in t or "part time" in t:
        return "PART_TIME"
    return "FULL_TIME"


def is_blocked(title: str) -> bool:
    t = title.lower()
    return any(term in t for term in TITLE_BLOCKLIST)


def fetch_url(url: str, timeout: int = 15, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("Fetch attempt %d failed (HTTP %s), retrying in %ds...", attempt + 1, e.code, wait)
            time.sleep(wait)
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("Fetch attempt %d failed (%s), retrying in %ds...", attempt + 1, e, wait)
            time.sleep(wait)


jobs = []
seen = set()

# ─────────────────────────────────────────────
# Core ingestion
# ─────────────────────────────────────────────

def add_job(source, raw_id, title, company, apply_url,
            description="", location="", posted=None):

    # Drop irrelevant roles before doing anything else
    if is_blocked(title):
        log.info("Skipping (blocklist): %s @ %s", title, company)
        return

    job_id = f"{source}-{company}-{raw_id}"

    if job_id in seen:
        return
    seen.add(job_id)

    description = truncate(clean(description))
    category = guess_category(title, description)
    remote = detect_remote(location, description)
    employment_type = guess_employment_type(title)

    slug = slugify(f"{title.strip()}-{company.strip()}")
    canonical_url = f"{BASE_URL}/jobs/{slug}/"

    if posted:
        posted = str(posted)
        if re.match(r"^\d{13}$", posted):
            # Lever returns Unix milliseconds
            posted = datetime.fromtimestamp(int(posted) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        else:
            posted = posted[:10]
    else:
        posted = str(date.today())

    try:
        posted_date = datetime.strptime(posted, "%Y-%m-%d").date()
    except ValueError:
        posted_date = date.today()
    valid_through = str(posted_date + timedelta(days=90))

    jobs.append({
        "job_id":          job_id,
        "title":           title.strip(),
        "company":         company.strip(),
        "slug":            slug,
        "canonical_url":   canonical_url,
        "description":     description,
        "apply_url":       apply_url,
        "category":        category,
        "location_type":   "remote" if remote else "onsite",
        "office_location": location,
        "employment_type": employment_type,
        "date_posted":     posted,
        "valid_through":   valid_through,
        "source":          source,
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
# Greenhouse — uses official Job Board API
# endpoint: job-boards.greenhouse.io/{token}
# ─────────────────────────────────────────────

def fetch_greenhouse():
    log.info("=== Greenhouse ===")

    for board in GREENHOUSE_BOARDS:
        try:
            url = f"https://job-boards.greenhouse.io/{board}"
            log.info("Fetching %s", url)
            page = fetch_url(url)

            # Greenhouse embeds job data as JSON in a <script data-js="gh-jobs"> tag
            json_match = re.search(
                r'<script[^>]+data-js=["\']gh-jobs["\'][^>]*>(.*?)</script>',
                page, re.DOTALL
            )

            if json_match:
                try:
                    job_list = json.loads(json_match.group(1))
                    display_name = GREENHOUSE_NAMES.get(board, board.title())
                    for j in job_list:
                        job_id = str(j.get("id", ""))
                        title = j.get("title", "")
                        location = (
                            j.get("location", {}).get("name", "")
                            if isinstance(j.get("location"), dict)
                            else str(j.get("location", ""))
                        )
                        apply_url = j.get("absolute_url", f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}")
                        desc = j.get("content", "") or j.get("description", "")
                        if title and job_id:
                            add_job("greenhouse", job_id, title, display_name, apply_url, desc, location)
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
                log.warning("Greenhouse %s: no jobs found", board)
                continue

            display_name = GREENHOUSE_NAMES.get(board, board.title())
            for job_id, title in job_links:
                if title:
                    title = clean(title)
                    apply_url = f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}"
                    add_job("greenhouse", job_id, title, display_name, apply_url, "", "")

            time.sleep(0.5)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Greenhouse %s: board not found (404)", board)
            else:
                log.warning("Greenhouse error %s: HTTP %s", board, e.code)
        except Exception as e:
            log.warning("Greenhouse error %s: %s", board, e)

# ─────────────────────────────────────────────
# Lever — uses official Postings API
# endpoint: api.lever.co/v0/postings/{slug}?mode=json
# Documented at github.com/lever/postings-api
# ─────────────────────────────────────────────

def fetch_lever():
    log.info("=== Lever ===")

    for company in LEVER_COMPANIES:
        try:
            url = f"https://api.lever.co/v0/postings/{company}?mode=json"
            log.info("Fetching %s", url)

            req = urllib.request.Request(url, headers={
                **BROWSER_HEADERS,
                "Accept": "application/json",
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                postings = json.loads(resp.read().decode())

            display_name = LEVER_NAMES.get(company, company.title())
            found = 0

            for j in postings:
                job_id = j.get("id", "")
                title = j.get("text", "")
                apply_url = j.get("hostedUrl", j.get("applyUrl", ""))
                desc = j.get("descriptionPlain", "") or j.get("description", "")

                # Location: categories.location or lists[0].text
                categories = j.get("categories", {})
                location = categories.get("location", "")
                if not location:
                    lists = j.get("lists", [])
                    location = lists[0].get("text", "") if lists else ""

                # Posted: createdAt is Unix milliseconds
                posted = str(j.get("createdAt", ""))

                if title and job_id:
                    add_job("lever", job_id, title, display_name, apply_url, desc, location, posted)
                    found += 1

            log.info("Lever %s: %d jobs", company, found)
            time.sleep(0.3)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Lever %s: board not found (404)", company)
            else:
                log.warning("Lever error %s: HTTP %s", company, e.code)
        except Exception as e:
            log.warning("Lever error %s: %s", company, e)

# ─────────────────────────────────────────────
# Workable — uses public API
# endpoint: apply.workable.com/api/v3/accounts/{slug}/jobs
# ─────────────────────────────────────────────

def fetch_workable():
    log.info("=== Workable ===")

    for company in WORKABLE_COMPANIES:
        try:
            url = f"https://apply.workable.com/api/v3/accounts/{company}/jobs"
            log.info("Fetching %s", url)

            req = urllib.request.Request(url, headers={
                **BROWSER_HEADERS,
                "Accept": "application/json",
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            found = 0
            for j in data.get("results", []):
                job_id = j.get("shortcode", j.get("id", ""))
                title = j.get("title", "")
                location = j.get("location", {})
                loc_str = ", ".join(filter(None, [location.get("city", ""), location.get("region", "")]))
                apply_url = f"https://apply.workable.com/{company}/j/{job_id}/"
                desc = j.get("description", "") or j.get("full_description", "")
                posted = (j.get("published_on") or str(date.today()))[:10]

                if title and job_id:
                    add_job("workable", job_id, title, company.replace("-", " ").title(), apply_url, desc, loc_str, posted)
                    found += 1

            log.info("Workable %s: %d jobs", company, found)
            time.sleep(0.3)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Workable %s: board not found (404)", company)
            else:
                log.warning("Workable error %s: HTTP %s", company, e.code)
        except Exception as e:
            log.warning("Workable error %s: %s", company, e)

# ─────────────────────────────────────────────
# Workday — scrapes public job board pages
# ─────────────────────────────────────────────

def fetch_workday():
    log.info("=== Workday ===")

    for company in WORKDAY_COMPANIES:
        slug = company["slug"]
        host = company["host"]
        name = company["name"]

        try:
            url = f"https://{host}/{slug}/jobs"
            log.info("Fetching %s", url)
            page = fetch_url(url)

            json_match = re.search(r'"jobPostings"\s*:\s*(\[.*?\])\s*[,}]', page, re.DOTALL)

            if not json_match:
                json_match = re.search(
                    r'var\s+appConfig\s*=\s*(\{.*?\});\s*(?:var|window)',
                    page, re.DOTALL
                )

            if json_match:
                try:
                    job_list = json.loads(json_match.group(1))
                    found = 0
                    for j in job_list:
                        job_id = j.get("externalPath", j.get("bulletFields", [""])[0])
                        title = j.get("title", "")
                        location = j.get("locationsText", "")
                        posted = (j.get("postedOn") or str(date.today()))[:10]
                        apply_url = f"https://{host}/{slug}/job/{job_id}" if job_id else f"https://{host}/{slug}/jobs"
                        if title:
                            add_job("workday", str(job_id), title, name, apply_url, "", location, posted)
                            found += 1
                    log.info("Workday %s: %d jobs", name, found)
                    time.sleep(0.3)
                    continue
                except (json.JSONDecodeError, KeyError):
                    pass

            log.warning("Workday %s: could not parse job data", name)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Workday %s: board not found (404)", name)
            else:
                log.warning("Workday error %s: HTTP %s", name, e.code)
        except Exception as e:
            log.warning("Workday error %s: %s", name, e)

# ─────────────────────────────────────────────
# Run pipeline
# ─────────────────────────────────────────────

fetch_usajobs()
fetch_greenhouse()
fetch_lever()
fetch_workable()
fetch_workday()

# ─────────────────────────────────────────────
# Build XML feed
# ─────────────────────────────────────────────

log.info("Total jobs after filtering: %d", len(jobs))

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
