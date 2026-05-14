import os
import xml.etree.ElementTree as ET

OUTPUT_DIR = "jobs"

os.makedirs(OUTPUT_DIR, exist_ok=True)

tree = ET.parse("feed.xml")
root = tree.getroot()

for job in root.findall("job"):
    title = job.find("title").text
    company = job.find("company").text
    desc = job.find("description").text
    slug = job.find("slug").text
    apply = job.find("apply_url").text
    location = job.find("office_location").text

    html = f"""
    <html>
    <head>
        <title>{title}</title>
    </head>
    <body>
        <h1>{title}</h1>
        <p><strong>Company:</strong> {company}</p>
        <p><strong>Location:</strong> {location}</p>
        <hr>
        <p>{desc}</p>
        <a href="{apply}">Apply Here</a>
    </body>
    </html>
    """

    with open(f"{OUTPUT_DIR}/{slug}.html", "w", encoding="utf-8") as f:
        f.write(html)

print("Pages generated:", len(root.findall("job")))
