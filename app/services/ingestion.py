"""Pulls listings from external job APIs and normalizes them into
Scanline's canonical schema. Adzuna shown as the reference implementation
since it has a free tier; add more sources by writing a fetch_* function
and a matching normalize_* function, then registering both below.
"""
import os
import re
import html
import hashlib
import httpx
from datetime import date
 
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY")
 
# Verified against Adzuna's actual, current documentation rather than
# assumed: the free tier is roughly 1,000 calls a month, about 33 a
# day. This app's own ingestion pipeline makes 13 job queries + 6
# athletic queries = 19 real Adzuna calls in a single scan - leaving
# very little headroom for a manual "check now" trigger on top of the
# scheduled daily scan without genuinely risking exceeding the real
# quota. Set a few calls below the ~33/day estimate since "roughly
# 1,000/month" is an approximation, not a guaranteed precise number.
ADZUNA_DAILY_CALL_LIMIT = 30
 
 
def check_and_reserve_quota(db, api_name: str, calls_needed: int, daily_limit: int) -> int:
    """Checks how many of the requested calls_needed can actually be
    made today without exceeding daily_limit for this specific API,
    reserving (incrementing the tracked count for) only that many -
    never silently exceeding a real, external rate limit just because
    the code wanted to make more calls than the budget allows.
 
    Uses an atomic INSERT...ON CONFLICT UPDATE (upsert) to increment
    the counter, not a python-level read-then-write. The read-then-
    write version had a genuine race condition: if the scheduled scan
    and a manual "check now" trigger fire close together, both could
    read the same starting count, both conclude they have room, and
    both proceed - silently exceeding the real daily limit on exactly
    the day (two things calling on the same day) this protection
    exists to handle. The atomic increment happens first (safe under
    concurrency by construction, not by hoping two requests don't
    overlap), then gets corrected back down after if it pushed the
    total over budget - the increment itself is what needs to be
    race-safe, not the "how much is left" check, which can happen
    after the fact.
 
    Returns the number of calls actually reserved (0 to calls_needed).
    The caller should only make this many calls, not the full
    requested amount, if the budget is already partially or fully
    consumed by an earlier call today (the scheduled scan, a manual
    trigger, or anything else sharing this same api_name).
    """
    from app.models.db_models import ApiQuotaTracker
    from sqlalchemy.dialects.postgresql import insert as pg_insert
 
    today = date.today().isoformat()
 
    stmt = pg_insert(ApiQuotaTracker).values(api_name=api_name, date=today, call_count=calls_needed)
    stmt = stmt.on_conflict_do_update(
        index_elements=["api_name", "date"],
        set_={"call_count": ApiQuotaTracker.call_count + calls_needed},
    ).returning(ApiQuotaTracker.call_count)
    new_total = db.execute(stmt).scalar()
    db.commit()
 
    if new_total <= daily_limit:
        return calls_needed  # the full request fit within budget
 
    over_by = new_total - daily_limit
    reserved = max(0, calls_needed - over_by)
    # Correct the tracked count back down to what was actually
    # granted - never leave it reflecting more than the real reserved
    # amount, or a later call this same day would be under-budgeted.
    db.query(ApiQuotaTracker).filter(
        ApiQuotaTracker.api_name == api_name, ApiQuotaTracker.date == today
    ).update({"call_count": ApiQuotaTracker.call_count - (calls_needed - reserved)})
    db.commit()
    return reserved
 
 
async def fetch_adzuna(query: str, location: str = "us", page: int = 1) -> list[dict]:
    """results_per_page raised from Adzuna's common default of 20 to
    50 (its public API supports this) - genuinely more efficient than
    adding extra page-fetches for the same result: 2.5x more real
    listings pulled per query, with the exact same number of API
    calls, not more of them.
    """
    url = f"https://api.adzuna.com/v1/api/jobs/{location}/search/{page}"
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": query,
        "results_per_page": 50,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("results", [])
 
 
def normalize_adzuna(raw: dict) -> dict:
    """HTML-entity decoding on title/org/description - found by
    stress-testing against realistic messy data rather than clean
    constructed listings: real aggregated postings routinely contain
    literal entities like "&amp;" (any company with "&" in its real
    name - AT&T, Procter & Gamble - would otherwise display as
    "AT&amp;T" verbatim to a real user).
    """
    return {
        "source": "adzuna",
        "external_id": str(raw.get("id")),
        "title": html.unescape(raw.get("title", "")).strip(),
        "org": html.unescape((raw.get("company") or {}).get("display_name", "Unknown")),
        "type": "job",  # Adzuna doesn't distinguish internships; refine via title keywords
        "location": (raw.get("location") or {}).get("display_name"),
        "description": html.unescape(raw.get("description", "")),
        "apply_url": raw.get("redirect_url"),
        "tags": [],  # populate via extract_tags()
        "deadline": None,  # Adzuna doesn't provide deadlines
    }
 
 
# Search terms covering real sporting-career job categories: coaching,
# athletic training, sports administration/management, and recreation.
# There is no free public API for athletic SCHOLARSHIPS specifically
# (NCSA and similar recruiting platforms are proprietary, no developer
# access) - this is the honest, real alternative: querying the same
# Adzuna connection already in use, but for real sports-career jobs
# instead of scholarships. Scholarship-type listings still need to go
# through /listings/manual until a real scholarship data source exists.
ATHLETIC_CAREER_QUERIES = [
    "athletic coach",
    "athletic trainer",
    "sports coordinator",
    "sports management",
    "recreation coordinator",
    "strength and conditioning coach",
]
 
 
async def fetch_athletic_career_jobs(location: str = "us", max_queries: int | None = None) -> list[dict]:
    """Pulls real sporting-career job listings from Adzuna - the same
    connection already used for general jobs, just queried with
    sports-specific terms. This is real data, not mocked.
 
    max_queries caps how many of ATHLETIC_CAREER_QUERIES actually get
    called - None (the default) means all of them, preserving
    existing behavior for any caller that doesn't need quota
    awareness. Callers sharing a real, limited daily call budget
    across multiple query sources (see check_and_reserve_quota) pass
    a specific number instead.
    """
    queries = ATHLETIC_CAREER_QUERIES if max_queries is None else ATHLETIC_CAREER_QUERIES[:max_queries]
    all_results = []
    for query in queries:
        try:
            results = await fetch_adzuna(query, location=location)
            all_results.extend(results)
        except Exception:
            continue  # one query failing shouldn't block the others
    return all_results
 
 
def normalize_athletic_job(raw: dict) -> dict:
    """Same shape as normalize_adzuna, but tagged as 'athletic' so it
    surfaces correctly in the Athlete dashboard and its matching engine.
    """
    normalized = normalize_adzuna(raw)
    normalized["type"] = "athletic"
    return normalized
 
 
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
# Scholarship/fellowship discovery. Used to be ScholarshipAPI - removed
# for two real, honest reasons: (1) as originally documented here, it
# only covered Australia and New Zealand universities, not the US
# this platform is built around, and (2) its response schema was only
# ever guessed from public docs snippets, never verified against a
# real API call - see the git history for the old normalize_scholarship
# if you want the details. Replaced with discover_scholarships_via_search()
# below, which uses real web search instead of depending on a
# third-party REST API with unverified coverage and an unverified schema.
# ---------------------------------------------------------------------------
 
 
async def discover_scholarships_via_search(anthropic_client, query: str) -> list[dict]:
    """Replaces the ScholarshipAPI-dependent path that used to live
    here. Two real, honest reasons it needed replacing: it only ever
    covered Australia and New Zealand universities (this platform is
    built around the US), and separately, its response schema was
    only ever guessed from public docs snippets, never verified
    against a real API call. Either one alone would explain it not
    working for real users here.
 
    This uses the same proven real-web-search pattern already working
    elsewhere in this app (market_research.py's research_company)
    instead of depending on a third-party REST API with unverified
    coverage and an unverified schema - every field returned here
    came from an actual search result, not a guessed field mapping.
    """
    prompt = (
        f"Search for real, current scholarship or fellowship opportunities related to \"{query}\" that are "
        "genuinely open for applications right now (not expired, not from a previous year unless still "
        "accepting applications). Find up to 5 real, specific opportunities.\n\n"
        "Quality matters more than quantity here:\n"
        "- Only include an opportunity if you found it on an authoritative source - the scholarship's own "
        "page, the sponsoring organization's official site, or a well-known, reputable scholarship "
        "database. Do NOT include something you only saw mentioned in a generic listicle, a 'top 10 "
        "scholarships' roundup article, or a forum post repeating unverified claims.\n"
        "- Never invent or estimate a deadline, amount, or URL you didn't actually find. If a real source "
        "doesn't clearly state the deadline, leave it null rather than guessing - a missing field is far "
        "better than a wrong one.\n"
        "- If you find fewer than 5 that meet this bar, return fewer. Do not pad the list to reach 5, and "
        "do not lower your standard just to have more results.\n\n"
        "Return a JSON array where each item has exactly these keys:\n"
        "- title: the real, specific name of the scholarship or fellowship\n"
        "- org: the real organization offering it\n"
        "- description: 1-2 real sentences on what it's for and who's eligible, from what you actually found\n"
        "- deadline: the real application deadline if a source clearly stated one, in YYYY-MM-DD format, else null\n"
        "- apply_url: the real URL to the scholarship's own page or the sponsoring org's official site - not "
        "a roundup article that merely mentions it\n"
        "- confidence: \"high\" if an authoritative source directly and clearly confirmed these details, "
        "\"moderate\" if the source was reasonably clear but not fully authoritative or slightly dated, "
        "\"low\" if you're genuinely uncertain about any key detail - be honest here, this isn't a place "
        "to round up\n\n"
        "Return ONLY the JSON array, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    import json
    try:
        results = json.loads(text)
    except json.JSONDecodeError:
        return []  # fail gracefully rather than crash the whole scan over one malformed response
    return results if isinstance(results, list) else []
 
 
def _scholarship_passes_quality_check(raw: dict) -> tuple[bool, str]:
    """A real, deterministic second layer of defense - never just
    trusts Claude's own self-reported confidence blindly. Every check
    here is independently verifiable and fully testable without
    needing a live search call, unlike the search itself.
 
    Returns (passes, reason) - reason explains why it failed, useful
    for debugging what a real scan actually rejected and why. Mirrors
    the same "results only come when they're good" quality-gate
    principle already applied to candidate match scores elsewhere in
    this app (see matching.py's PRESENTABLE_MIN_SCORE).
    """
    confidence = (raw.get("confidence") or "").lower()
    if confidence == "low":
        return False, "self-reported low confidence"
 
    title = (raw.get("title") or "").strip()
    if not title:
        return False, "empty title"
    if len(title) < 8:
        return False, "title too short to be a real, specific name"
    generic_titles = {"scholarship", "scholarships", "fellowship", "fellowships", "grant", "grants"}
    if title.lower() in generic_titles:
        return False, "title is a generic category word, not a specific real name"
 
    apply_url = (raw.get("apply_url") or "").strip()
    if not apply_url:
        return False, "no real apply_url found"
    if not (apply_url.startswith("http://") or apply_url.startswith("https://")):
        return False, "apply_url doesn't look like a real URL"
    if "." not in apply_url.split("//", 1)[-1]:
        return False, "apply_url has no real-looking domain"
 
    deadline_str = raw.get("deadline")
    if deadline_str:
        try:
            deadline = date.fromisoformat(deadline_str)
        except (ValueError, TypeError):
            return False, "deadline is not a valid date"
        days_from_now = (deadline - date.today()).days
        if days_from_now < -7:
            return False, f"deadline is {-days_from_now} days in the past - likely a stale search result"
        if days_from_now > 730:
            return False, "deadline is more than 2 years out - unlikely to be a genuinely current opportunity"
 
    return True, ""
 
 
def normalize_scholarship_from_search(raw: dict) -> dict | None:
    """Normalizes a search-derived scholarship result into Scanline's
    canonical listing shape. Every field here came from a real,
    web-search-grounded result, not a guessed third-party schema.
    Returns None (skip) for anything that doesn't clear
    _scholarship_passes_quality_check() - an unverified or low-
    confidence "opportunity" isn't worth showing a real user, and
    silently falling back to a generic placeholder (the old ScholarshipAPI
    behavior) is worse than just not showing it.
    """
    passes, _reason = _scholarship_passes_quality_check(raw)
    if not passes:
        return None
 
    deadline = None
    if raw.get("deadline"):
        try:
            deadline = date.fromisoformat(raw["deadline"])
        except (ValueError, TypeError):
            deadline = None
 
    title = raw["title"].strip()
    org = (raw.get("org") or "Unknown").strip()
 
    # external_id needs to be stable across scans so the same real
    # scholarship doesn't get re-inserted as a duplicate every time a
    # search happens to surface it again - hash title+org since a
    # search result has no natural stable ID the way a REST API would
    # normally provide one.
    external_id = hashlib.sha256(f"{title}|{org}".encode()).hexdigest()[:16]
 
    return {
        "source": "web_search_scholarship",
        "external_id": external_id,
        "title": title,
        "org": org,
        "type": "college",
        "location": "Remote",  # scholarships/fellowships aren't physically location-bound the way jobs are
        "description": raw.get("description", "") or title,
        "tags": [],  # populated via extract_tags(), same as every other source
        "deadline": deadline,
        "apply_url": raw["apply_url"],
    }
 
