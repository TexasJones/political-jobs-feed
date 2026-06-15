import re
import json
import html
import logging
import time
import hashlib
import os
import urllib.request
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
# Sources — only confirmed working boards
# ─────────────────────────────────────────────

GREENHOUSE_BOARDS = [
    # Civil rights & advocacy
    "aclu",
    "southernpovertylawcenter",
    "democracyforward",
    "humanrightswatch",
    # Political communications & campaigns
    "moveonorg",
    "gmmb",
    "berlinrosen",
    "industriouslabs",          # Climate policy campaigns
    # Public affairs firms
    "hillandknowlton",          # Hill & Knowlton
    "orchestra",                # Orchestra (BerlinRosen, Civitas Public Affairs, Glen Echo Group)
    "voxglobal",                # VOX Global — bipartisan public affairs, Omnicom
    "ketchumuscareers",         # Ketchum US — corporate reputation, earned media, public affairs
    # Political data & analytics
    "civisanalytics",           # Civis Analytics
    # Political media
    "axios",
    "semafor",
    "voxmedia",                 # Vox Media
]

GREENHOUSE_NAMES = {
    "aclu": "ACLU",
    "southernpovertylawcenter": "Southern Poverty Law Center",
    "democracyforward": "Democracy Forward",
    "humanrightswatch": "Human Rights Watch",
    "moveonorg": "MoveOn.org",
    "gmmb": "GMMB",
    "berlinrosen": "BerlinRosen",
    "industriouslabs": "Industrious Labs",
    "hillandknowlton": "Hill & Knowlton",
    "orchestra": "Orchestra",
    "voxglobal": "VOX Global",
    "ketchumuscareers": "Ketchum",
    "civisanalytics": "Civis Analytics",
    "axios": "Axios",
    "semafor": "Semafor",
    "voxmedia": "Vox Media",
}

LEVER_COMPANIES = [
    # Progressive political orgs
    "emilyslist",               # EMILY's List — confirmed working
    "dnc",                      # Democratic National Committee — returns 0 jobs (board exists)
    # Public affairs & comms firms
    "globalstrategygroup",      # Global Strategy Group — confirmed working
    # Political media & policy journalism
    "fiscalnote",               # FiscalNote / CQ Roll Call — confirmed working
    "thefp",                    # The Free Press — confirmed working
    # Environmental advocacy
    "sierraclub",               # Sierra Club — board exists (0 jobs currently)
]

LEVER_NAMES = {
    "emilyslist": "EMILY's List",
    "dnc": "Democratic National Committee",
    "globalstrategygroup": "Global Strategy Group",
    "fiscalnote": "FiscalNote",
    "thefp": "The Free Press",
    "sierraclub": "Sierra Club",
}

# Workable — none confirmed working yet; keeping structure for future additions
WORKABLE_COMPANIES = []

WORKDAY_COMPANIES = [
    {
        # Note: slug must match the PATH in the Workday URL exactly (case-sensitive)
        # Politico URL: politico.wd108.myworkdayjobs.com/POLITICO
        "slug": "POLITICO",
        "host": "politico.wd108.myworkdayjobs.com",
        "name": "Politico",
    },
]

# ─────────────────────────────────────────────
# Title blocklist — applies to ALL sources
# Split into substring and whole-word patterns
# to avoid false positives on legit public affairs titles
# ─────────────────────────────────────────────

TITLE_BLOCKLIST_SUBSTRING = [
    # IT / Engineering
    "engineer", "developer", "software", "devops", "sysadmin",
    "cyber", "security operations", "endpoint", "network admin",
    "data scientist", "machine learning", "cloud architect",
    "information security", "information technology",
    "technical project manager", "technical program manager",
    "enterprise applications", "applications integration",
    "chief technology", "full stack", "fullstack", "it support",
    # Product / Program management
    "product manager", "program manager",
    # Finance / Accounting
    "accountant", "controller", "bookkeeper",
    "accounts payable", "accounts receivable", "payroll",
    "tax analyst", "reinsurance", "actuar", "cash application",
    "remittance", "commission processing",
    "total rewards", "director, accounting", "director of accounting",
    # HR / People Ops
    "human resources", "talent acquisition", "recruiter", "hris",
    "hr generalist", "hr manager", "hr coordinator", "hr business partner",
    "benefits administrator", "learning & development",
    "learning and development", "people and culture", "chief people",
    "compensation", "organizational effectiveness",
    # Fundraising / Development (nonprofit back-office)
    "stewardship", "major gifts", "annual fund", "development associate",
    # Legal (non-policy)
    "paralegal", "legal counsel", "general counsel", "staff attorney",
    "staff counsel", "oversight counsel",
    "legal director", "legal advisor", "chief legal", "deputy legal",
    "supervising attorney",
    # Design / Creative (non-comms)
    "graphic design", "graphic designer", "visual design",
    # Facilities / Operations / Security
    "facilities", "construction", "maintenance", "custodial",
    "office manager", "executive assistant", "confidential assistant",
    "chief operating", "protective services", "protective security",
    "director of security",
    # Sales / Customer service
    "customer service", "claims adjuster", "dealer performance",
    "district sales", "district manager", "vehicle protection",
    "sales specialist", "sales training", "call center",
    "contract processing", "sales manager", "client partnerships",
    "client success", "client engagement",
    # Admin / catch-alls
    "business analyst", "future opportunities", "general interest",
    "fellowship sponsorship", "karpatkin",
    "affiliate strategic",
    "hr intern", "audio/video intern", "newsroom engineering",
    # Healthcare
    "nurse", "physician", "medical", "clinical", "therapist",
    # USAJobs-specific noise
    "border protection", "customs", "cbp officer",
    "agriculture specialist", "victim advocate", "family advocacy",
    "clinical counselor", "psychologist", "social worker",
    "field service technician", "property specialist",
    "inspector general",
    "contracting officer", "procurement",
    "laboratory",
    "law enforcement", "correctional", "detention",
    "logistics", "supply chain", "warehouse",
]

# Whole-word regex patterns — only block when term stands alone,
# not when it's part of a legitimate public affairs title
# e.g. "intelligence analyst" is noise, "intelligence community liaison" is legit
TITLE_BLOCKLIST_WHOLE_WORD = [
    r"\bscientist\b",
    r"\bresearcher\b",
    r"\bresearch\s+analyst\b",
    r"\bresearch\s+coordinator\b",
    r"\bnavy\s+(?!legislative|affairs|policy)\w+",
    r"\barmy\s+(?!policy|affairs|corps)\w+",
    r"\bmarine\s+(?!policy|affairs)\w+",
    r"\bintelligence\s+analyst\b",
    r"\bintelligence\s+officer\b",
    r"\bimmigration\s+(?!policy|reform|advocacy)\w+",
    r"\bacquisition\s+(?!communications|outreach)\w+",
    r"\binvestigator\b",
    r"\bsenior\s+counsel\b",
    r"\blaw\s+enforcement\b",
    r"\bmilitary\s+(?!affairs|policy|relations)\w+",
    r"\bsecurity\s+clearance\b",
    r"\bit\s+director\b",
    r"\bit\s+manager\b",
    r"\bdba\b",
    r"\bdatabase\s+admin",
    r"\bchief\s+financial\b",
    r"\bdirector\s+of\s+finance\b",
    r"\bvp\s+of\s+finance\b",
    r"\bfinance\s+director\b",
    r"\bevent\s+coordinator\b",
    r"\bevent\s+manager\b",
]


def is_blocked(title: str) -> bool:
    t = title.lower()
    if any(term in t for term in TITLE_BLOCKLIST_SUBSTRING):
        return True
    if any(re.search(pattern, t) for pattern in TITLE_BLOCKLIST_WHOLE_WORD):
        return True
    # Block "Research Associate" unless it's a policy-qualified role
    if re.search(r"\bresearch\s+associate\b", t):
        policy_qualifiers = ["policy", "advocacy", "legislative", "political", "government"]
        if not any(w in t for w in policy_qualifiers):
            return True
    return False


# ─────────────────────────────────────────────
# Category rules
# ─────────────────────────────────────────────

CATEGORY_RULES = {
    "Political Campaigns": [
        "campaign", "field organizer", "canvass",
        "voter", "political director", "gotv", "election",
        "opposition research", "rapid response", "get out the vote",
    ],
    "Public Affairs & Lobbying": [
        "public affairs", "government relations", "lobby", "lobbying", "advocacy",
        "external affairs", "intergovernmental", "stakeholder",
        "state affairs", "federal affairs", "regulatory affairs",
    ],
    "Government & Policy": [
        "policy", "legislative", "congress", "senate", "house", "federal",
        "appropriations", "regulatory", "government affairs",
        "chief of staff", "deputy chief",
    ],
    "Communications & PR": [
        "communications", "media relations", "press secretary", "spokesperson",
        "public relations", "earned media", "digital strategy", "social media manager",
        "speechwriter", "speech writer", "digital director", "digital manager",
        "content strategist", "content manager", "messaging",
        "rapid response", "media strategist",
    ],
    "Nonprofit Advocacy": [
        "nonprofit", "grassroots", "organizing", "civic",
        "coalition", "outreach coordinator", "community organizer",
    ],
    "Political Media": [
        "reporter", "editor", "correspondent", "journalist", "newsroom",
        "newsletter", "columnist", "bureau chief", "anchor", "producer",
        "photojournalist", "videographer", "podcast",
    ],
}


def guess_category(title: str, desc: str = "") -> str:
    text = f"{title} {desc}".lower()
    scores = {cat: sum(k in text for k in kws) for cat, kws in CATEGORY_RULES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Government & Policy"


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


def guess_employment_type(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["intern", "fellowship", "fellow"]):
        return "INTERN"
    if any(k in t for k in ["temporary", "temp ", "term-limited", "contract"]):
        return "CONTRACTOR"
    if "part-time" in t or "part time" in t:
        return "PART_TIME"
    return "FULL_TIME"


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

    # Include raw_id in slug to prevent collisions when same company
    # posts multiple roles with identical titles
    slug = slugify(f"{title.strip()}-{company.strip()}-{raw_id}")
    canonical_url = f"{BASE_URL}/jobs/{slug}/"

    if posted:
        posted = str(posted)
        if re.match(r"^\d{13}$", posted):
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
        "title":           html.unescape(title.strip()),
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
# Greenhouse — official boards-api JSON endpoint
# GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
# More reliable than HTML scraping — returns clean paginated JSON
# ─────────────────────────────────────────────

def fetch_greenhouse():
    log.info("=== Greenhouse ===")

    for board in GREENHOUSE_BOARDS:
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
            log.info("Fetching %s", url)

            req = urllib.request.Request(url, headers={
                **BROWSER_HEADERS,
                "Accept": "application/json",
            })

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            display_name = GREENHOUSE_NAMES.get(board, board.title())
            job_list = data.get("jobs", [])
            found = 0

            for j in job_list:
                job_id = str(j.get("id", ""))
                title = j.get("title", "")
                location = (
                    j.get("location", {}).get("name", "")
                    if isinstance(j.get("location"), dict)
                    else ""
                )
                apply_url = j.get("absolute_url", f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}")
                desc = j.get("content", "") or ""
                if title and job_id:
                    add_job("greenhouse", job_id, title, display_name, apply_url, desc, location)
                    found += 1

            log.info("Greenhouse %s: %d jobs", board, found)
            time.sleep(0.3)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Greenhouse %s: board not found (404) — remove from list", board)
            else:
                log.warning("Greenhouse error %s: HTTP %s", board, e.code)
        except Exception as e:
            log.warning("Greenhouse error %s: %s", board, e)


# ─────────────────────────────────────────────
# Lever — official Postings API
# GET https://api.lever.co/v0/postings/{slug}?mode=json
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

                categories = j.get("categories", {})
                location = categories.get("location", "")
                if not location:
                    lists = j.get("lists", [])
                    location = lists[0].get("text", "") if lists else ""

                posted = str(j.get("createdAt", ""))

                if title and job_id:
                    add_job("lever", job_id, title, display_name, apply_url, desc, location, posted)
                    found += 1

            log.info("Lever %s: %d jobs", company, found)
            time.sleep(0.3)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Lever %s: board not found (404) — remove from list", company)
            else:
                log.warning("Lever error %s: HTTP %s", company, e.code)
        except Exception as e:
            log.warning("Lever error %s: %s", company, e)


# ─────────────────────────────────────────────
# Workable — public API
# ─────────────────────────────────────────────

def fetch_workable():
    if not WORKABLE_COMPANIES:
        return

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
                log.warning("Workable %s: board not found (404) — remove from list", company)
            else:
                log.warning("Workable error %s: HTTP %s", company, e.code)
        except Exception as e:
            log.warning("Workable error %s: %s", company, e)


# ─────────────────────────────────────────────
# Workday — stable internal REST API
# POST https://{host}/wday/cxs/{slug}/jobs
# IMPORTANT: slug must exactly match the path segment in the Workday URL
# e.g. politico.wd108.myworkdayjobs.com/POLITICO → slug = "POLITICO"
# ─────────────────────────────────────────────

def fetch_workday():
    log.info("=== Workday ===")

    for company in WORKDAY_COMPANIES:
        slug = company["slug"]
        host = company["host"]
        name = company["name"]

        try:
            url = f"https://{host}/wday/cxs/{slug}/jobs"
            log.info("Fetching %s", url)

            payload = json.dumps({
                "limit": 20,
                "offset": 0,
                "searchText": "",
                "appliedFacets": {},
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    **BROWSER_HEADERS,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            job_postings = data.get("jobPostings", [])
            total = data.get("total", len(job_postings))
            found = 0

            def process_posting(j):
                nonlocal found
                external_path = j.get("externalPath", "")
                # externalPath looks like "/job/Washington-DC/Policy-Analyst_JR-12345"
                job_id = external_path.split("_")[-1] if "_" in external_path else (
                    external_path.strip("/").replace("/", "-") or hashlib.md5(str(j).encode()).hexdigest()[:8]
                )
                title = j.get("title", "")
                location = j.get("locationsText", "")
                posted_raw = j.get("postedOn", "")
                # Workday returns ISO dates or human strings like "Posted 30+ Days Ago"
                posted = posted_raw[:10] if re.match(r"\d{4}-\d{2}-\d{2}", posted_raw) else str(date.today())
                apply_url = f"https://{host}/{slug}{external_path}" if external_path else f"https://{host}/{slug}/jobs"
                if title and job_id:
                    add_job("workday", job_id, title, name, apply_url, "", location, posted)
                    found += 1

            for j in job_postings:
                process_posting(j)

            log.info("Workday %s: %d/%d jobs fetched (page 1)", name, found, total)

            # Paginate if there are more results
            offset = 20
            while offset < total:
                payload = json.dumps({
                    "limit": 20,
                    "offset": offset,
                    "searchText": "",
                    "appliedFacets": {},
                }).encode("utf-8")
                req = urllib.request.Request(
                    url, data=payload,
                    headers={
                        **BROWSER_HEADERS,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                for j in data.get("jobPostings", []):
                    process_posting(j)
                offset += 20
                time.sleep(0.3)

            log.info("Workday %s: %d total jobs ingested", name, found)
            time.sleep(0.5)

        except urllib.error.HTTPError as e:
            log.warning("Workday error %s: HTTP %s — check slug matches URL path exactly", name, e.code)
        except Exception as e:
            log.warning("Workday error %s: %s", name, e)


# ─────────────────────────────────────────────
# Run pipeline
# ─────────────────────────────────────────────

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
