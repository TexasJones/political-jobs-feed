import re
import logging
from datetime import date, datetime
from xml.dom import minidom
import xml.etree.ElementTree as ET
import feedparser

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

OUTPUT_FILE = "feed.xml"

FEEDS = [
    "https://rss.indeed.com/rss?q=political+campaign&sort=date",
    "https://rss.indeed.com/rss?q=public+affairs+lobbying&sort=date",
    "https://rss.indeed.com/rss?q=government+policy+analyst&sort=date",
    "https://rss.indeed.com/rss?q=nonprofit+advocacy&sort=date",
    "https://rss.indeed.com/rss?q=communications+director+political&sort=date",
    "https://rss.indeed.com/rss?q=field+organizer&sort=date",
    "https://rss.indeed.com/rss?q=legislative+affairs&sort=date",
    "https://rss.indeed.com/rss?q=government+relations&sort=date",
]

KEYWORDS = [
    "political","campaign","public affairs","lobbying","lobbyist",
    "government relations","policy","advocacy","legislative","organizer",
    "civic","voter","election","press secretary","chief of staff",
    "communications director","PAC","nonprofit","district director",
]

def is_relevant(title, desc=""):
    h = (title + " " + desc).lower()
    return any(k in h for k in KEYWORDS)

def clean(raw):
    return re.sub(r"<[^>]+>", " ", raw or "").strip()

def guess_category(title, desc=""):
    t = (title + " " + desc).lower()
    if any(x in t for x in ["campaign","election","candidate","voter"]):
        return "Political Campaigns"
    if any(x in t for x in ["lobby","public affairs","government relations"]):
        return "Public Affairs & Lobbying"
    if any(x in t for x in ["policy","legislative","government","federal","state"]):
        return "Government & Policy"
    if any(x in t for x in ["nonprofit","advocacy","civic","organizer"]):
        return "Nonprofit Advocacy"
    if any(x in t for x in ["communications","press","media","pr "]):
        return "Communications & PR"
    return "Political Jobs"

jobs = []
seen = set()

for url in FEEDS:
    log.info("Fetching %s", url)
    try:
        feed = feedparser.parse(url)
        for e in feed.entries:
            title = e.get("title", "")
            summary = clean(e.get("summary", ""))
            link = e.get("link", "")
            company = feed.feed.get("title", "Unknown")
            p = e.get("published_parsed") or e.get("updated_parsed")
            posted = datetime(*p[:3]).strftime("%Y-%m-%d") if p else str(date.today())
            key = (title.lower().strip(), link)
            if key in seen or not is_relevant(title, summary):
                continue
            seen.add(key)
            jobs.append({
                "title": title,
                "company": company,
                "description": summary or "See full listing at apply URL.",
                "apply_url": link,
                "category": guess_category(title, summary),
                "date_posted": posted,
            })
            log.info("  + %s", title)
    except Exception as ex:
        log.warning("Failed %s: %s", url, ex)

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
    ET.SubElement(el, "location").text = "remote"
    ET.SubElement(el, "post_state").text = "published"
    ET.SubElement(el, "post_length").text = "30"

xml = minidom.parseString(
    '<?xml version="1.0" encoding="UTF-8"?>' +
    ET.tostring(root, encoding="unicode")
).toprettyxml(indent="  ")

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(xml)

log.info("Written -> %s", OUTPUT_FILE)
