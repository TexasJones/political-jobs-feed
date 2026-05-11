import re
import logging
import json
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

SEARCHES = [
    "public affairs",
    "political affairs",
    "legislative affairs",
    "government relations",
    "policy analyst",
    "communications director",
    "advocacy",
    "field operations",
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

for term in SEARCHES:
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
                "title": title,
                "company": org,
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
        log.warning("Failed '%s': %s", term, ex)

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

log.info("Written %d jobs to feed.xml", len(jobs))
