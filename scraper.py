import logging
from datetime import date, datetime
from xml.dom import minidom
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

jobs = [
    {"title":"Campaign Manager","company":"Progressive Victory PAC","description":"Lead field operations for 2026 midterm campaigns across swing districts.","apply_url":"https://www.idealist.org/jobs","location":"remote","office_location":"Washington, DC","category":"Political Campaigns"},
    {"title":"Policy Analyst","company":"Center for American Progress","description":"Research and draft policy briefs on economic and social issues.","apply_url":"https://www.americanprogress.org/jobs","location":"onsite","office_location":"Washington, DC","category":"Government & Policy"},
    {"title":"Government Relations Manager","company":"National Advocacy Group","description":"Manage relationships with federal and state legislators on key policy issues.","apply_url":"https://www.idealist.org/jobs","location":"hybrid","office_location":"Washington, DC","category":"Public Affairs & Lobbying"},
    {"title":"Field Organizer","company":"Grassroots Action Network","description":"Recruit and train volunteers for voter registration and canvassing operations.","apply_url":"https://www.workforgood.org/jobs","location":"remote","office_location":"Austin, TX","category":"Nonprofit Advocacy"},
    {"title":"Communications Director","company":"Senate Campaign Committee","description":"Develop and execute communications strategy for Senate candidates.","apply_url":"https://www.idealist.org/jobs","location":"onsite","office_location":"New York, NY","category":"Communications & PR"},
    {"title":"Legislative Affairs Specialist","company":"U.S. Department of Energy","description":"Coordinate legislative strategy and congressional relations for federal agency.","apply_url":"https://www.usajobs.gov","location":"onsite","office_location":"Washington, DC","category":"Government & Policy"},
    {"title":"Digital Campaign Manager","company":"Blue Wave Consulting","description":"Manage digital advertising and social media for political campaigns.","apply_url":"https://www.idealist.org/jobs","location":"remote","office_location":"Chicago, IL","category":"Political Campaigns"},
    {"title":"Public Affairs Director","company":"Fortune 500 Energy Company","description":"Lead public affairs strategy and manage relationships with government stakeholders.","apply_url":"https://www.linkedin.com/jobs","location":"hybrid","office_location":"Houston, TX","category":"Public Affairs & Lobbying"},
    {"title":"Voter Registration Coordinator","company":"Rock the Vote","description":"Coordinate national voter registration drives targeting young voters.","apply_url":"https://www.workforgood.org/jobs","location":"remote","office_location":"Remote","category":"Nonprofit Advocacy"},
    {"title":"Press Secretary","company":"Governor Campaign","description":"Serve as primary spokesperson and manage media relations for gubernatorial campaign.","apply_url":"https://www.idealist.org/jobs","location":"onsite","office_location":"Miami, FL","category":"Communications & PR"},
    {"title":"Opposition Research Analyst","company":"Democratic Congressional Campaign Committee","description":"Conduct research on Republican candidates and produce research memos.","apply_url":"https://www.dccc.org/jobs","location":"onsite","office_location":"Washington, DC","category":"Political Campaigns"},
    {"title":"State Legislative Director","company":"ACLU","description":"Direct state-level legislative advocacy and lobbying efforts across 10 states.","apply_url":"https://www.aclu.org/jobs","location":"hybrid","office_location":"New York, NY","category":"Nonprofit Advocacy"},
    {"title":"Political Fundraising Manager","company":"ActBlue","description":"Manage fundraising operations and donor relations for Democratic campaigns.","apply_url":"https://www.idealist.org/jobs","location":"remote","office_location":"Cambridge, MA","category":"Political Campaigns"},
    {"title":"Senior Policy Advisor","company":"U.S. Senate Office","description":"Provide policy analysis and advice to Senator on healthcare and education issues.","apply_url":"https://www.usajobs.gov","location":"onsite","office_location":"Washington, DC","category":"Government & Policy"},
    {"title":"Advocacy Campaign Manager","company":"Sierra Club","description":"Design and execute advocacy campaigns on environmental policy and legislation.","apply_url":"https://www.sierraclub.org/jobs","location":"hybrid","office_location":"San Francisco, CA","category":"Nonprofit Advocacy"},
]

today = str(date.today())
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
    ET.SubElement(el, "date_posted").text = today

xml = minidom.parseString(
    '<?xml version="1.0" encoding="UTF-8"?>' +
    ET.tostring(root, encoding="unicode")
).toprettyxml(indent="  ")

with open("feed.xml", "w", encoding="utf-8") as f:
    f.write(xml)

log.info("Written %d jobs to feed.xml", len(jobs))
