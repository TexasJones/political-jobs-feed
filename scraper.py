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
    "webershandwick",           # Weber Shandwick — includes Powell Tate public affairs unit
    "fleishmanhillard",         # FleishmanHillard — global PR/public affairs, Omnicom
    # Political data & analytics
    "civisanalytics",           # Civis Analytics
    "bluelabsanalyticsinc",     # BlueLabs — political/advocacy data science & analytics
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
    "webershandwick": "Weber Shandwick",
    "fleishmanhillard": "FleishmanHillard",
    "civisanalytics": "Civis Analytics",
    "bluelabsanalyticsinc": "BlueLabs",
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
    # AI policy, safety & governance
    "aisafety",                 # Center for AI Safety — confirmed working; also covers
                                 # policy engagement via their DC sister org, Center for
                                 # AI Safety Action Fund. Board mixes policy roles with
                                 # general org-ops roles — watch first run for noise.
]

LEVER_NAMES = {
    "emilyslist": "EMILY's List",
    "dnc": "Democratic National Committee",
    "globalstrategygroup": "Global Strategy Group",
    "fiscalnote": "FiscalNote",
    "thefp": "The Free Press",
    "sierraclub": "Sierra Club",
    "aisafety": "Center for AI Safety",
}

# Some Greenhouse boards cover multiple offices/countries, but we only want
# the US public affairs practice out of them (e.g. Weber Shandwick's board
# includes their German offices' generic healthcare/pharma PR postings,
# which aren't public affairs and aren't US-based). Boards listed here get
# filtered down to US-only postings via is_us_posting() below.
GREENHOUSE_US_ONLY_BOARDS = {
    "webershandwick",
}

# Signals that a Greenhouse posting is from a non-US (specifically German)
# office — checked against both location and title, since Weber Shandwick's
# German-market postings are consistently titled in German (Werkstudent,
# Berater, m/w/d) even when the location field itself is sparse.
NON_US_OFFICE_SIGNALS = [
    "germany", "deutschland", "berlin", "münchen", "munich", "frankfurt",
    "hamburg", "köln", "cologne", "düsseldorf", "stuttgart",
    "werkstudent", "berater", "m/w/d", "m/w/div", "praktikant",
]


def is_us_posting(location: str, title: str) -> bool:
    text = f"{location} {title}".lower()
    return not any(signal in text for signal in NON_US_OFFICE_SIGNALS)


# Ashby — public Job Board Posting API, no auth required.
# Find a company's board slug from its public careers URL:
#   https://jobs.ashbyhq.com/{slug}
ASHBY_BOARDS = [
    "bantamcommunications",   # Bantam Communications — energy/advocacy public affairs campaigns
    "morningconsult",         # Morning Consult — DC polling/decision intelligence for advocacy & policy clients
]

ASHBY_NAMES = {
    "bantamcommunications": "Bantam Communications",
    "morningconsult": "Morning Consult",
}

# Some Ashby boards belong to companies large enough that most of their
# postings are generic commercial roles (sales, account management,
# customer success) unrelated to public affairs — Morning Consult's board
# covers their whole commercial org, not just the DC advocacy/policy team.
# Unlike the Weber Shandwick case, there's no reliable exclusion keyword
# here (the qualifying posting itself is titled "Lead Account Director,
# Advocacy and Public Affairs" — blocking "account director" would remove
# the very job that justified adding the board). So instead of excluding
# on a keyword, boards listed here are included only if the title or
# description actually names a policy/advocacy/public-affairs focus.
ASHBY_REQUIRE_POLICY_KEYWORD_BOARDS = {
    "morningconsult",
}

POLICY_KEYWORD_SIGNALS = [
    "public affairs", "policy", "advocacy", "political",
    "government affairs", "government relations", "legislative", "lobbying",
]


def has_policy_signal(title: str, desc: str = "") -> bool:
    text = f"{title} {desc}".lower()
    return any(signal in text for signal in POLICY_KEYWORD_SIGNALS)

# Rippling — public Job Board API, no auth required.
# Find a company's board slug from its public careers URL:
#   https://ats.rippling.com/{slug}/jobs
RIPPLING_BOARDS = [
    "indivisible-project-careers",   # Indivisible — confirmed working
]

RIPPLING_NAMES = {
    "indivisible-project-careers": "Indivisible",
}

# Workable — public API
WORKABLE_COMPANIES = [
    "fp1-strategies",                  # FP1 Strategies — political campaigns, PLUS Communications
    "bully-pulpit-international-1",    # Bully Pulpit International — public affairs, digital, research.
                                        # Board covers DC/NY/Chicago/LA/SF plus international offices
                                        # (Berlin, Brussels, London, Oslo, Zürich) and general agency
                                        # roles alongside public affairs work — watch first run for
                                        # non-US postings slipping through (no Workable-side country
                                        # filter exists yet, unlike GREENHOUSE_US_ONLY_BOARDS).
    "movement-labs",                   # Movement Labs — progressive digital/data/field incubator and
                                        # consulting firm; spans digital, field/campaign, and grassroots.
]

WORKABLE_NAMES = {
    "fp1-strategies": "FP1 Strategies",
    "bully-pulpit-international-1": "Bully Pulpit International",
    "movement-labs": "Movement Labs",
}

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
# Company logos — resolved via Clearbit's free logo API
# (https://logo.clearbit.com/{domain}), keyed on the display name we
# already assign each job (GREENHOUSE_NAMES, LEVER_NAMES, etc). This is
# what lets Job Boardly show the actual employer logo instead of falling
# back to its own ATS-detection icon (the Greenhouse "g" / Lever "employ"
# badge seen when a job has no logo field to draw from).
#
# Verify domains before fully trusting them — a few here are best-guesses
# and should be spot-checked against each company's real site the first
# time they show up in Job Boardly.
# ─────────────────────────────────────────────

COMPANY_DOMAINS = {
    "ACLU": "aclu.org",
    "Southern Poverty Law Center": "splcenter.org",
    "Democracy Forward": "democracyforward.org",
    "Human Rights Watch": "hrw.org",
    "MoveOn.org": "moveon.org",
    "GMMB": "gmmb.com",
    "BerlinRosen": "berlinrosen.com",
    "Industrious Labs": "industriouslabs.org",
    "Hill & Knowlton": "hillandknowlton.com",
    "Orchestra": "orchestra.co",
    "VOX Global": "voxglobal.com",
    "Ketchum": "ketchum.com",
    "Weber Shandwick": "webershandwick.com",
    "FleishmanHillard": "fleishmanhillard.com",
    "Civis Analytics": "civisanalytics.com",
    "BlueLabs": "bluelabs.com",
    "Axios": "axios.com",
    "Semafor": "semafor.com",
    "Vox Media": "voxmedia.com",
    "EMILY's List": "emilyslist.org",
    "Democratic National Committee": "democrats.org",
    "Global Strategy Group": "globalstrategygroup.com",
    "FiscalNote": "fiscalnote.com",
    "The Free Press": "thefp.com",
    "Sierra Club": "sierraclub.org",
    "Bantam Communications": "bantamcommunications.com",
    "Morning Consult": "morningconsult.com",
    "Indivisible": "indivisible.org",
    "FP1 Strategies": "fp1strategies.com",
    "Bully Pulpit International": "bpigroup.com",
    "Center for AI Safety": "safe.ai",
    "Movement Labs": "movementlabs.com",
    "Politico": "politico.com",
    "CapitolWorks": "capitolworks.com",
}

# Manual overrides for companies where Clearbit's domain guess is wrong, or
# where a self-hosted logo is preferred (e.g. hosted on GitHub Pages
# alongside feed.xml, same pattern as the OG image). Anything set here
# wins over the Clearbit lookup in get_company_logo().
COMPANY_LOGO_OVERRIDES = {
    # "CapitolWorks": "https://texasjones.github.io/political-jobs-feed/assets/capitolworks-logo.png",
}


def get_company_logo(company: str) -> str:
    if company in COMPANY_LOGO_OVERRIDES:
        return COMPANY_LOGO_OVERRIDES[company]
    domain = COMPANY_DOMAINS.get(company)
    if domain:
        return f"https://logo.clearbit.com/{domain}"
    return ""


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


def classify_location_type(location: str, desc: str = "") -> str:
    """
    Three-way location classification: remote / hybrid / onsite.
    Job Boardly's importer supports all three as distinct values (see its
    Location type fallback dropdown), but the previous binary remote/onsite
    check folded "hybrid" postings into "remote" — mislabeling roles that
    explicitly require in-office days. Checked in this order because a
    posting can mention both "remote" (e.g. in a benefits blurb) and
    "hybrid" (in the actual work arrangement); hybrid should win when both
    appear.
    """
    text = f"{location} {desc}".lower()
    if "hybrid" in text:
        return "hybrid"
    if any(k in text for k in ["remote", "work from home", "distributed", "telework"]):
        return "remote"
    return "onsite"


LOCATION_TYPE_LABELS = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "onsite": "Onsite",
}


def guess_employment_type(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["intern", "fellowship", "fellow"]):
        return "INTERN"
    if any(k in t for k in ["temporary", "temp ", "term-limited", "contract"]):
        return "CONTRACTOR"
    if "part-time" in t or "part time" in t:
        return "PART_TIME"
    return "FULL_TIME"


# Job Boardly's "Job type" field expects exact wording from its own fixed
# list (Full-time, Part-time, Contract, Temporary, Volunteer, Internship,
# Apprentice, Casual). Maps our internal codes to the ones we actually use.
JOB_BOARDLY_TYPE_LABELS = {
    "FULL_TIME":  "Full-time",
    "PART_TIME":  "Part-time",
    "CONTRACTOR": "Contract",
    "INTERN":     "Internship",
}


def fetch_url(url: str, timeout: int = 15, retries: int = 3,
              method: str = "GET", data: bytes = None,
              extra_headers: dict = None) -> str:
    """
    Shared retry-with-backoff fetch helper. All fetchers should route
    through this rather than calling urlopen() directly, so a single
    transient network blip doesn't silently zero out a whole source
    for the day.
    """
    headers = {**BROWSER_HEADERS, **(extra_headers or {})}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("Fetch attempt %d failed (HTTP %s) for %s, retrying in %ds...",
                        attempt + 1, e.code, url, wait)
            time.sleep(wait)
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("Fetch attempt %d failed (%s) for %s, retrying in %ds...",
                        attempt + 1, e, url, wait)
            time.sleep(wait)


# ─────────────────────────────────────────────
# Location limits
# Job Boardly's "Location limits" field restricts remote roles to a
# region/country. If left unmapped, it defaults remote jobs to "Worldwide."
#
# Every current source was originally US-based, so this used to be a flat
# hardcoded "United States" for every job. That broke once international
# postings started showing up (e.g. FleishmanHillard's Greenhouse board
# posting a Brussels internship) — those were getting mislabeled as US.
#
# guess_location_limit() checks the job's actual location string against a
# set of common non-US city/country signals and maps to the right country.
# Anything unmatched still falls back to "United States", since the large
# majority of our sources are genuinely US-based — extend this map as new
# international postings turn up.
#
# NOTE: matching is done with word-boundary regex, not plain substring —
# plain "in" checks let short keywords like "uk" match inside unrelated
# words (e.g. "Milwaukee", "Duke"), and "mexico" match inside "New Mexico".
# The US_STATE_EXCEPTIONS list handles the remaining collisions where a
# country name is also a legitimate US place name.
# ─────────────────────────────────────────────

DEFAULT_LOCATION_LIMIT = "United States"

# US place names that would otherwise collide with a country keyword below
# (e.g. "New Mexico" contains the word "mexico"). Checked before the
# country map so these always resolve to United States.
US_STATE_EXCEPTIONS = [
    "new mexico",
]

NON_US_LOCATION_MAP = {
    "brussels": "Belgium",
    "belgium": "Belgium",
    "london": "United Kingdom",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "toronto": "Canada",
    "vancouver": "Canada",
    "canada": "Canada",
    "paris": "France",
    "france": "France",
    "berlin": "Germany",
    "germany": "Germany",
    "dublin": "Ireland",
    "ireland": "Ireland",
    "singapore": "Singapore",
    "sydney": "Australia",
    "melbourne": "Australia",
    "australia": "Australia",
    "mexico city": "Mexico",
    "mexico": "Mexico",
    "geneva": "Switzerland",
    "switzerland": "Switzerland",
    "amsterdam": "Netherlands",
    "netherlands": "Netherlands",
    "madrid": "Spain",
    "spain": "Spain",
    "rome": "Italy",
    "milan": "Italy",
    "italy": "Italy",
    "tokyo": "Japan",
    "japan": "Japan",
    "hong kong": "Hong Kong",
    "nairobi": "Kenya",
    "kenya": "Kenya",
    "johannesburg": "South Africa",
    "south africa": "South Africa",
}


def guess_location_limit(location: str) -> str:
    loc = (location or "").lower()

    # Check US place-name exceptions first so they never fall through to
    # the country map (e.g. "New Mexico" contains "mexico").
    for exc in US_STATE_EXCEPTIONS:
        if re.search(rf"\b{re.escape(exc)}\b", loc):
            return DEFAULT_LOCATION_LIMIT

    for keyword, country in NON_US_LOCATION_MAP.items():
        if re.search(rf"\b{re.escape(keyword)}\b", loc):
            return country

    return DEFAULT_LOCATION_LIMIT


jobs = []
seen = set()

# Some Greenhouse boards belong to holding companies that re-list their
# subsidiaries' own postings on a shared board — e.g. Orchestra's board
# covers BerlinRosen, Civitas Public Affairs, and Glen Echo Group, but
# BerlinRosen also has its own separate confirmed-working board. Scraping
# both surfaces the exact same job twice under two different company
# names, which the normal seen{} dedup (keyed on source-company-raw_id)
# doesn't catch since both the company label and raw ID differ.
#
# GREENHOUSE_NETWORK_GROUPS scopes a secondary dedup to just these known
# groups — keyed on (network, normalized title, normalized location) —
# rather than deduping globally by title+location, which would risk
# false-collapsing two unrelated firms that happen to post similarly
# titled roles in the same city.
GREENHOUSE_NETWORK_GROUPS = {
    "orchestra_network": {"orchestra", "berlinrosen"},
}

# Reverse lookup: board slug -> network name, built once at import time.
GREENHOUSE_BOARD_TO_NETWORK = {
    board: network
    for network, boards in GREENHOUSE_NETWORK_GROUPS.items()
    for board in boards
}

seen_network_content = set()


def is_network_duplicate(board: str, title: str, location: str) -> bool:
    """
    Returns True (and records the key) if this title+location was already
    seen from another board in the same holding-company network. Boards
    are processed in GREENHOUSE_BOARDS order, so whichever board is listed
    first "wins" — GREENHOUSE_BOARDS lists berlinrosen before orchestra,
    so the more specific brand name is kept over the parent company's
    duplicate listing.
    """
    network = GREENHOUSE_BOARD_TO_NETWORK.get(board)
    if not network:
        return False
    key = (network, title.strip().lower(), location.strip().lower())
    if key in seen_network_content:
        return True
    seen_network_content.add(key)
    return False


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
    location_type = classify_location_type(location, description)
    employment_type = guess_employment_type(title)
    location_limit = guess_location_limit(location)
    logo_url = get_company_logo(company.strip())

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
        "location_type":   location_type,
        "office_location": location,
        "location_limit":  location_limit,
        # Compatibility alias — Job Boardly's "Location type" field needs an
        # exact-match value ("Remote" / "Onsite" / "Hybrid"). office_location
        # is messy free text and won't match cleanly, so we reuse the old,
        # unused "location" field name (already recognized by Job Boardly)
        # to carry a clean categorical value instead.
        "location":        LOCATION_TYPE_LABELS[location_type],
        # Compatibility alias — Job Boardly's importer has a stale, cached
        # field list left over from an older feed schema (it still knows
        # "post_state" but has never rescanned to discover "location_limit").
        # Duplicating the value here lets it be mapped without recreating
        # the importer. Safe to remove once Job Boardly rescans the feed.
        "post_state":      location_limit,
        "employment_type": employment_type,
        # Compatibility alias — Job Boardly's stale field cache recognizes
        # "type" but not "employment_type". Same pattern as location/post_state.
        "type":            JOB_BOARDLY_TYPE_LABELS.get(employment_type, "Full-time"),
        "date_posted":     posted,
        "valid_through":   valid_through,
        "source":          source,
        # Company logo — resolved via get_company_logo() (Clearbit lookup
        # or manual override). Three field-name aliases are included since
        # it's not yet confirmed which one Job Boardly's importer maps to;
        # once confirmed in the field-mapping screen, delete the other two.
        "logo":            logo_url,
        "image":           logo_url,
        "company_logo":    logo_url,
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

            raw = fetch_url(url, extra_headers={"Accept": "application/json"})
            data = json.loads(raw)

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

                if board in GREENHOUSE_US_ONLY_BOARDS and not is_us_posting(location, title):
                    log.info("Skipping (non-US office): %s @ %s [%s]", title, display_name, location)
                    continue

                if is_network_duplicate(board, title, location):
                    log.info("Skipping (network duplicate): %s @ %s [%s]", title, display_name, location)
                    continue

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

            raw = fetch_url(url, extra_headers={"Accept": "application/json"})
            postings = json.loads(raw)

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
# Ashby — public Job Board Posting API
# GET https://api.ashbyhq.com/posting-api/job-board/{boardName}
# No auth required for public boards. Returns { "jobs": [...] }.
# ─────────────────────────────────────────────

def fetch_ashby():
    if not ASHBY_BOARDS:
        return

    log.info("=== Ashby ===")

    for board in ASHBY_BOARDS:
        try:
            url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
            log.info("Fetching %s", url)

            raw = fetch_url(url, extra_headers={"Accept": "application/json"})
            data = json.loads(raw)

            display_name = ASHBY_NAMES.get(board, board.replace("-", " ").title())
            job_list = data.get("jobs", [])
            found = 0

            for j in job_list:
                job_id = str(j.get("id", ""))
                title = j.get("title", "")

                # Ashby's field naming has varied across board versions —
                # check both observed variants defensively.
                location = j.get("location") or j.get("locationName") or ""

                desc = j.get("descriptionHtml", "") or j.get("descriptionPlain", "")
                apply_url = (
                    j.get("applyUrl")
                    or j.get("jobUrl")
                    or f"https://jobs.ashbyhq.com/{board}/{job_id}"
                )
                posted = j.get("publishedAt", "")

                if board in ASHBY_REQUIRE_POLICY_KEYWORD_BOARDS and not has_policy_signal(title, desc):
                    log.info("Skipping (no policy/advocacy signal): %s @ %s", title, display_name)
                    continue

                if title and job_id:
                    add_job("ashby", job_id, title, display_name, apply_url, desc, location, posted)
                    found += 1

            log.info("Ashby %s: %d jobs", board, found)
            time.sleep(0.3)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Ashby %s: board not found (404) — remove from list", board)
            else:
                log.warning("Ashby error %s: HTTP %s", board, e.code)
        except Exception as e:
            log.warning("Ashby error %s: %s", board, e)


# ─────────────────────────────────────────────
# Rippling — public Job Board API
# GET https://ats.rippling.com/api/v2/board/{board_slug}/jobs?page=0&pageSize=50
# No auth required. Listing endpoint returns titles/departments/locations
# but not descriptions or posted dates — same tradeoff as Greenhouse,
# where date_posted falls back to the scrape date.
#
# IMPORTANT: the listing endpoint also omits job descriptions entirely
# (unlike Greenhouse/Lever/Ashby, which include them inline). Rippling
# requires a secondary per-job detail call to get the description body —
# handled below via fetch_rippling_job_detail().
#
# NOTE: this is Rippling's own native ATS API (ats.rippling.com), which is
# a different product from "rippling-ats.com" — a legacy domain Rippling
# kept after acquiring HiringThing. Sites on rippling-ats.com (e.g. Rising
# Tide Interactive) run on HiringThing's platform, not this one, and won't
# resolve against this endpoint. If a board slug 404s here despite the
# company's careers page looking like Rippling, check which product it's
# actually on before assuming the slug is wrong.
# ─────────────────────────────────────────────

def fetch_rippling_job_detail(board: str, job_id: str) -> str:
    """
    Rippling's list endpoint doesn't return job descriptions, so each job
    needs its own detail fetch. Returns the description HTML/text, or ""
    if the detail call fails (a missing description shouldn't drop the
    job — it should still show up, just without body copy).
    """
    try:
        url = f"https://ats.rippling.com/api/v2/board/{board}/jobs/{job_id}"
        raw = fetch_url(url, extra_headers={"Accept": "application/json"})
        data = json.loads(raw)
        return data.get("description", "") or data.get("descriptionHtml", "") or ""
    except Exception as e:
        log.warning("Rippling detail fetch failed for job %s: %s", job_id, e)
        return ""


def fetch_rippling():
    if not RIPPLING_BOARDS:
        return

    log.info("=== Rippling ===")

    for board in RIPPLING_BOARDS:
        try:
            display_name = RIPPLING_NAMES.get(board, board.replace("-", " ").title())
            found = 0
            page = 0

            while True:
                url = f"https://ats.rippling.com/api/v2/board/{board}/jobs?page={page}&pageSize=50"
                log.info("Fetching %s", url)

                raw = fetch_url(url, extra_headers={"Accept": "application/json"})
                data = json.loads(raw)

                for j in data.get("items", []):
                    job_id = j.get("id", "")
                    title = j.get("name", "")
                    apply_url = j.get("url", "")

                    locations = j.get("locations", [])
                    location = locations[0].get("name", "") if locations else ""

                    desc = fetch_rippling_job_detail(board, job_id) if job_id else ""

                    if title and job_id:
                        add_job("rippling", job_id, title, display_name, apply_url, desc, location)
                        found += 1
                        time.sleep(0.2)

                total_pages = data.get("totalPages", 1)
                page += 1
                if page >= total_pages:
                    break
                time.sleep(0.3)

            log.info("Rippling %s: %d jobs", board, found)
            time.sleep(0.3)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.warning("Rippling %s: board not found (404) — remove from list", board)
            else:
                log.warning("Rippling error %s: HTTP %s", board, e.code)
        except Exception as e:
            log.warning("Rippling error %s: %s", board, e)


# ─────────────────────────────────────────────
# Workable — public API
#
# Two account generations exist and return jobs through different public
# endpoints:
#   - Classic accounts:  https://apply.workable.com/api/v3/accounts/{slug}/jobs
#     (results under "results")
#   - Newer accounts on Workable's "Jobs by Workable" candidate experience
#     (recognizable by careers pages like jobs.workable.com/company/{opaque
#     id}/...) don't return data through the v3 endpoint even though their
#     classic apply.workable.com/{slug}/ page still resolves for browsers.
#     These need the documented public widget endpoint instead:
#     https://www.workable.com/api/accounts/{slug}?details=true
#     (results under "jobs")
#
# fetch_workable_jobs_raw() tries v3 first (it's what's confirmed working
# for our original accounts) and only falls back to the widget endpoint if
# v3 comes back empty, so existing working sources take the fast path and
# only newer-platform accounts (e.g. Movement Labs) pay the extra request.
# ─────────────────────────────────────────────

def fetch_workable_jobs_raw(company: str):
    """
    Returns (list_of_raw_job_dicts, endpoint_used) for a Workable account.
    endpoint_used is "v3" or "widget", or None if both attempts failed —
    useful for logging which shape of job dict downstream code is holding.
    """
    try:
        url = f"https://apply.workable.com/api/v3/accounts/{company}/jobs"
        log.info("Fetching %s", url)
        raw = fetch_url(url, extra_headers={"Accept": "application/json"})
        data = json.loads(raw)
        results = data.get("results", [])
        if results:
            return results, "v3"
    except urllib.error.HTTPError as e:
        if e.code != 404:
            log.warning("Workable v3 error %s: HTTP %s", company, e.code)
    except Exception as e:
        log.warning("Workable v3 fetch failed for %s: %s", company, e)

    # Fall back to the widget endpoint — covers accounts on Workable's
    # newer platform where v3 returns an empty (but valid) results list.
    try:
        url = f"https://www.workable.com/api/accounts/{company}?details=true"
        log.info("Fetching %s (fallback)", url)
        raw = fetch_url(url, extra_headers={"Accept": "application/json"})
        data = json.loads(raw)
        return data.get("jobs", []), "widget"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.warning("Workable %s: board not found (404) on both endpoints — remove from list", company)
        else:
            log.warning("Workable widget error %s: HTTP %s", company, e.code)
    except Exception as e:
        log.warning("Workable widget fetch failed for %s: %s", company, e)

    return [], None


def fetch_workable():
    if not WORKABLE_COMPANIES:
        return

    log.info("=== Workable ===")

    for company in WORKABLE_COMPANIES:
        try:
            job_list, endpoint = fetch_workable_jobs_raw(company)
            display_name = WORKABLE_NAMES.get(company, company.replace("-", " ").title())
            found = 0

            for j in job_list:
                # shortcode/id may come back as an int — always stringify
                # since job_id flows into slug/string formatting downstream.
                job_id = str(j.get("shortcode", j.get("id", "")))
                title = j.get("title", "")

                # Location shape differs between endpoints: v3 gives
                # {city, region}; widget sometimes gives a flat
                # "location_str" instead. Check both.
                location = j.get("location", {}) or {}
                loc_str = (
                    location.get("location_str")
                    or ", ".join(filter(None, [location.get("city", ""), location.get("region", "")]))
                )

                # Widget-endpoint jobs carry their own apply link (url /
                # application_url / shortlink); v3 jobs don't, so we
                # construct the standard apply.workable.com pattern instead.
                apply_url = (
                    j.get("application_url")
                    or j.get("url")
                    or j.get("shortlink")
                    or f"https://apply.workable.com/{company}/j/{job_id}/"
                )

                desc = j.get("full_description", "") or j.get("description", "")
                posted = (j.get("published_on") or str(date.today()))[:10]

                if title and job_id:
                    add_job("workable", job_id, title, display_name, apply_url, desc, loc_str, posted)
                    found += 1

            log.info("Workable %s: %d jobs (via %s)", company, found, endpoint or "no working endpoint")
            time.sleep(0.3)

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

            raw = fetch_url(
                url, method="POST", data=payload,
                extra_headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            data = json.loads(raw)

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
                raw = fetch_url(
                    url, method="POST", data=payload,
                    extra_headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                data = json.loads(raw)
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
fetch_ashby()
fetch_rippling()
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
