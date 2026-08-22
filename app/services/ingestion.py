"""Pulls listings from external job APIs and normalizes them into
Scanline's canonical schema. Adzuna shown as the reference implementation
since it has a free tier; add more sources by writing a fetch_* function
and a matching normalize_* function, then registering both below.
"""
import os
import re
import httpx
 
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
 
 
async def fetch_adzuna(query: str, location: str = "us", page: int = 1) -> list[dict]:
    url = f"https://api.adzuna.com/v1/api/jobs/{location}/search/{page}"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": query,
        "results_per_page": 20,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("results", [])
 
 
def normalize_adzuna(raw: dict) -> dict:
    return {
        "source": "adzuna",
        "external_id": str(raw.get("id")),
        "title": raw.get("title", "").strip(),
        "org": (raw.get("company") or {}).get("display_name", "Unknown"),
        "type": "job",  # Adzuna doesn't distinguish internships; refine via title keywords
        "location": (raw.get("location") or {}).get("display_name"),
        "description": raw.get("description", ""),
        "apply_url": raw.get("redirect_url"),
        "tags": [],  # populate via extract_tags()
        "deadline": None,  # Adzuna doesn't provide deadlines
    }
 
 
def dedupe_listings(listings: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for l in listings:
        key = (l["source"], l["external_id"])
        if key not in seen:
            seen.add(key)
            out.append(l)
    return out
 
 
async def extract_tags(description: str, anthropic_client) -> list[str]:
    """Uses Claude to pull structured skill/domain tags out of a raw
    job description. Keep the prompt tight - this runs per-listing at scale.
    """
    if not description:
        return []
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": (
                "Extract 4-8 lowercase, single/double-word skill or domain tags "
                "from this job description. Return ONLY a comma-separated list, "
                "nothing else.\n\n" + description[:2000]
            ),
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    return [t.strip() for t in text.split(",") if t.strip()]
 
 
# ---------------------------------------------------------------------------
# SimplifyJobs Summer Internships list - a free, community-maintained,
# hourly-updated public data source, structured as a markdown table.
# No Claude call needed here: tags are derived from simple keyword
# matching against role titles, which works well for short, predictable
# internship titles and keeps this source completely free to run.
# ---------------------------------------------------------------------------
 
SIMPLIFY_RAW_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"
 
TAG_KEYWORDS = [
    "software", "backend", "frontend", "fullstack", "full-stack", "mobile",
    "data", "machine learning", "ai", "ml", "product", "hardware", "quant",
    "quantitative", "research", "security", "cloud", "devops", "embedded",
    "network", "infrastructure", "android", "ios", "web", "database",
]
 
 
async def fetch_simplify_internships() -> str:
    """Returns the raw markdown text of the internship list."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(SIMPLIFY_RAW_URL, timeout=15)
        resp.raise_for_status()
        return resp.text
 
 
def _extract_first_real_url(cell_text: str) -> str | None:
    """Pulls the first non-image URL out of a markdown table cell
    (the Apply column contains badge-image links; we want the actual
    application URL, not the badge image URL)."""
    urls = re.findall(r"\]\((https?://[^)\s]+)\)", cell_text)
    for u in urls:
        if "camo.githubusercontent.com" not in u:
            return u
    return None
 
 
def _clean_markdown(text: str) -> str:
    """Strips markdown link/bold/emoji syntax down to plain text."""
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)      # images
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)  # links -> link text
    text = re.sub(r"[*_`]", "", text)                # bold/italic/code
    text = re.sub(r"[\U0001F525\U0001F393\U0001F6C2\U0001F1FA\U0001F1F8\U0001F512]", "", text)  # legend emoji (fire/grad-cap/passport/US-flag/lock)
    return text.strip()
 
 
def parse_simplify_markdown(markdown_text: str) -> list[dict]:
    """Parses the SimplifyJobs README table into normalized listing dicts."""
    listings = []
    current_company = None
    for line in markdown_text.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---") or "Company" in line and "Role" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        company_cell, role_cell, location_cell, apply_cell = cells[0], cells[1], cells[2], cells[3]
 
        company = _clean_markdown(company_cell)
        if company in ("\u21B3", ""):
            company = current_company
        else:
            current_company = company
        if not company:
            continue
 
        role = _clean_markdown(role_cell)
        location = _clean_markdown(location_cell)
        apply_url = _extract_first_real_url(apply_cell)
        if not role or not apply_url:
            continue
 
        role_lower = role.lower()
        tags = [kw for kw in TAG_KEYWORDS if kw in role_lower] or ["internship"]
 
        listings.append({
            "source": "simplify",
            "external_id": apply_url,  # apply URLs are effectively unique per posting
            "title": role,
            "org": company,
            "type": "internship",
            "location": location or None,
            "description": f"{role} at {company}",
            "tags": tags,
            "deadline": None,  # this source doesn't publish explicit deadlines
            "apply_url": apply_url,
        })
    return listings
 
 
# ---------------------------------------------------------------------------
# ScholarshipAPI - college/fellowship data source.
# Honest limitation: as of this writing, ScholarshipAPI only covers
# Australia and New Zealand universities. It will return real, live
# data - just not US-specific results yet. Kept here so it's ready
# to use for AU/NZ users now, or the moment US coverage goes live.
# Requires a free API key from scholarshipapi.com (SCHOLARSHIP_API_KEY).
# ---------------------------------------------------------------------------
 
SCHOLARSHIP_API_KEY = os.getenv("SCHOLARSHIP_API_KEY")
SCHOLARSHIP_API_URL = "https://api.scholarshipapi.com/v1/search"
 
 
async def fetch_scholarships(query: str = "scholarship", limit: int = 20) -> list[dict]:
    if not SCHOLARSHIP_API_KEY:
        return []
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            SCHOLARSHIP_API_URL,
            headers={
                "Authorization": f"Bearer {SCHOLARSHIP_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"q": query, "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("hits", [])
 
 
def normalize_scholarship(raw: dict) -> dict:
    """Maps a ScholarshipAPI hit to Scanline's canonical listing shape.
    NOTE: the public docs snippet did not show an explicit apply-URL
    field, so this checks a few likely field names and falls back to
    None if none are present - verify against a real response once
    you have an API key, and adjust the field name here if needed.
    """
    close_date_ms = raw.get("closeDate")
    deadline = None
    if close_date_ms:
        from datetime import datetime
        deadline = datetime.utcfromtimestamp(close_date_ms / 1000).date()
 
    university = raw.get("university", "")
    location = university.split("/")[0].upper() if "/" in university else university
 
    category = raw.get("primaryCategory")
    tags = [category.lower()] if category else ["scholarship"]
 
    apply_url = raw.get("url") or raw.get("applyUrl") or raw.get("link")
 
    name = raw.get("name", "Untitled scholarship")
    return {
        "source": "scholarshipapi",
        "external_id": f"{name}-{university}",
        "title": name,
        "org": university or "Unknown institution",
        "type": "college",
        "location": location or None,
        "description": raw.get("summary", "") or name,
        "tags": tags,
        "deadline": deadline,
        "apply_url": apply_url or "https://scholarshipapi.com",  # honest fallback, see note above
    }
