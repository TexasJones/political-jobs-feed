import re
import json
import logging
import time
from datetime import date, datetime
from xml.dom import minidom
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_KEY = "2KZ63NqUMqWDkwdbR+RFdrPdELoCFFGtOTGGIeZzgWo="
EMAIL = "politemps@gmail.com"

# ── Greenhouse org board tokens ───────────────────────────────────────────────
GREENHOUSE_BOARDS = [
    "aclu", "aclunc", "moveonorg", "sierraclub",
    "plannedparenthood", "ppfa", "emilyslist",
    "indivisible", "publiccitizen", "commoncause",
    "unitedwedream", "nextgenamerica", "whenweallvote",
    "rockthevote", "leaguewv", "naacpldf",
    "americanprogressaction", "centerforamericanprogress",
    "protectdemocracy", "democracydocket",
]

USAJOBS_SEARCHES = [
    "public affairs", "legislative affairs",
    "government relations", "policy analyst", "communications director",
]

def clean(raw):
    return re.sub(r"<[^>]+>", " ", raw or "").strip()

def guess_category(title, desc=""):
    t = (title + " " + desc).lower()
    if any(x in t for x in ["campaign","election","candidate","voter","canvass"]):
        return "Political Campaigns"
    if any(x in t for x in ["lobby","public affairs","government relations"]):
        return "Public Affairs & Lobbying"
    if any(x in t for x in ["policy","legislative","congress","federal","senate","house"]):
        return "Government & Policy"
    if any(x in t for x in ["nonprofit","advocacy","civic","organizer","grassroots"]):
        return "Nonprofit Advocacy"
    if any(x in t for x in ["communications","press","media","spokesperson"]):
        return "Communications & PR"
    return "Government & Policy"

jobs = []
seen = set()

# ── USAJobs ─────────────────────────────────────────────────────────────[...]
log.info("=== Fetching USAJobs ===")
for term in USAJOBS_SEARCHES:
    try:
        params = urllib.parse.urlencode({"Keyword": term, "ResultsPerPage": 25})
        url = f"https://data.usajobs.gov/api/search?{params}"
        req = urllib.request.Request(url, headers={
            "Host": "data.usajobs.gov",
            "User-Agent": EMAIL,
            "Authorization-Key": API_KEY,
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        items = data.get("SearchResult", {}).get("SearchResultItems", [])
        log.info("'%s' -> %d results", term, len(items))
        for item in items:
            pos = item.get("MatchedObjectDescriptor", {})
            job_id = pos.get("PositionID", "")
            if job_id in seen:
                continue
            seen.add(job_id)
            title = pos.get("PositionTitle", "")
            org = pos.get("OrganizationName", "U.S. Federal Government")
            apply_uris = pos.get("ApplyURI", [])
            apply_url = apply_uris[0] if apply_uris else "https://www.usajobs.gov"
            posted = (pos.get("PublicationStartDate") or str(date.today()))[:10]
            desc = clean(pos.get("UserArea", {}).get("Details", {}).get("JobSummary", ""))
            locs = pos.get("PositionLocation", [])
            is_remote = any("anywhere" in (l.get("LocationName") or "").lower() for l in locs)
            office = locs[0].get("LocationName", "") if locs else ""
            jobs.append({
                "title": title, "company": org,
                "description": desc or f"See full listing at {apply_url}",
                "apply_url": apply_url,
                "location": "remote" if is_remote else "onsite",
                "office_location": office,
                "category": guess_category(title, desc),
                "date_posted": posted,
            })
            log.info("  + %s", title)
        time.sleep(0.5)
    except Exception as ex:
        log.warning("USAJobs failed '%s': %s", term, ex)

# ── Greenhouse ────────────────────────────────────────────────────────────[...]
log.info("=== Fetching Greenhouse boards ===")
for board in GREENHOUSE_BOARDS:
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        req = urllib.request.Request(url, headers={"User-Agent": "PoliticalJobsFeed/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        items = data.get("jobs", [])
        log.info("%s -> %d jobs", board, len(items))
        for j in items:
            job_id = str(j.get("id", ""))
            if job_id in seen:
                continue
            seen.add(job_id)
            title = j.get("title", "")
            apply_url = j.get("absolute_url", f"https://boards.greenhouse.io/{board}")
            location = j.get("location", {}).get("name", "")
            is_remote = "remote" in location.lower()
            desc = clean(j.get("content", ""))[:500]
            posted = (j.get("updated_at") or str(date.today()))[:10]
            jobs.append({
                "title": title,
                "company": board.replace("org","").replace("action","").title(),
                "description": desc or f"See full listing at {apply_url}",
                "apply_url": apply_url,
                "location": "remote" if is_remote else "onsite",
                "office_location": location,
                "category": guess_category(title, desc),
                "date_posted": posted,
            })
            log.info("  + %s", title)
        time.sleep(0.3)
    except Exception as ex:
        log.warning("Greenhouse %s failed: %s", board, ex)

# ── Arena ─────────────────────────────────────────────────────────────[...]
log.info("=== Fetching Arena jobs ===")
try:
    import html.parser

    class ArenaParser(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.jobs = []
            self.capture = False
            self.current_text = ""
            self.current_link = ""

        def handle_starttag(self, tag, attrs):
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            if tag == "a" and "/jobs/" in href:
                self.current_link = href
                self.capture = True
                self.current_text = ""

        def handle_data(self, data):
            if self.capture:
                self.current_text += data.strip()

        def handle_endtag(self, tag):
            if tag == "a" and self.capture and self.current_link:
                title = self.current_text.strip().replace("Featured", "").strip()
                # Clean up junk headers like "Read more about X at Job Post"
                title = re.sub(r"^Read more about\s+", "", title, flags=re.IGNORECASE)
                title = re.sub(r"\s+at\s+Job Post\s*$", "", title, flags=re.IGNORECASE)
                title = title.strip()
                if title and len(title) > 3:
                    self.jobs.append({"title": title, "url": self.current_link})
                self.capture = False
                self.current_text = ""
                self.current_link = ""

    headers = {"User-Agent": "Mozilla/5.0 (compatible; PoliticalJobsFeed/1.0)"}
    req = urllib.request.Request("https://careers.arena.run/jobs", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        html_content = resp.read().decode("utf-8", errors="ignore")

    parser = ArenaParser()
    parser.feed(html_content)
    log.info("Arena found %d job links", len(parser.jobs))

    for j in parser.jobs[:50]:
        title = j["title"]
        apply_url = j["url"]
        key = (title.lower().strip(), apply_url)
        if key in seen:
            continue
        seen.add(key)
        url_parts = apply_url.split("/")
        company = "Political Organization"
        if "companies" in url_parts:
            idx = url_parts.index("companies")
            if idx + 1 < len(url_parts):
                raw = url_parts[idx + 1].replace("-2", "").replace("-", " ").strip().title()
                company = raw if raw else "Political Organization"
        
        # Construct full absolute URL
        full_apply_url = f"https://careers.arena.run{apply_url}" if not apply_url.startswith("http") else apply_url
        
        jobs.append({
            "title": title, "company": company,
            "description": "See full listing at Arena job board.",
            "apply_url": full_apply_url,
            "location": "remote",
            "office_location": "",
            "category": guess_category(title),
            "date_posted": str(date.today()),
        })
        log.info("  + %s @ %s", title, company)

except Exception as ex:
    log.warning("Arena scrape failed: %s", ex)

# ── Build XML ────────────────────────────────────────────────────────────[...]
log.info("Total jobs: %d", len(jobs))

root = ET.Element("jobs")
root.set("generated", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
root.set("count", str(len(jobs)))

for j in jobs:
    el = ET.SubElement(root, "job")
    for k, v in j.items():
        c = ET.SubElement(el, k)
        c.text = str(v)
    ET.SubElement(el, "type").text = "fulltime"
    ET.SubElement(el, "post_state").text = "published"
    ET.SubElement(el, "post_length").text = "30"

xml = minidom.parseString(
    '<?xml version="1.0" encoding="UTF-8"?>' +
    ET.tostring(root, encoding="unicode")
).toprettyxml(indent="  ")

with open("feed.xml", "w", encoding="utf-8") as f:
    f.write(xml)

log.info("Written -> feed.xml")
