import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import anthropic
 
from app.db import get_db
from app.models.db_models import ResumeEntry, ResumeDocument, Profile
 
router = APIRouter(prefix="/resume", tags=["resume"])
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
 
 
class ResumeEntryIn(BaseModel):
    user_id: str
    entry_type: str  # work / education / project
    title: str
    org: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    raw_description: str
    display_order: int = 0
 
 
class ResumeEntryUpdate(BaseModel):
    entry_type: str | None = None
    title: str | None = None
    org: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    raw_description: str | None = None
    display_order: int | None = None
 
 
@router.post("/entries")
def create_entry(payload: ResumeEntryIn, db: Session = Depends(get_db)):
    """Adds one real, user-provided fact about their experience - the
    only kind of input this feature accepts. Nothing here is ever
    generated; raw_description is always the person's own words.
    """
    entry = ResumeEntry(
        user_id=payload.user_id, entry_type=payload.entry_type, title=payload.title,
        org=payload.org, start_date=payload.start_date, end_date=payload.end_date,
        raw_description=payload.raw_description, display_order=payload.display_order,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": str(entry.id)}
 
 
@router.get("/entries/{user_id}")
def list_entries(user_id: str, db: Session = Depends(get_db)):
    entries = (
        db.query(ResumeEntry)
        .filter(ResumeEntry.user_id == user_id)
        .order_by(ResumeEntry.display_order, ResumeEntry.created_at)
        .all()
    )
    return {
        "entries": [
            {
                "id": str(e.id), "entry_type": e.entry_type, "title": e.title, "org": e.org,
                "start_date": e.start_date, "end_date": e.end_date,
                "raw_description": e.raw_description, "display_order": e.display_order,
            }
            for e in entries
        ]
    }
 
 
@router.patch("/entries/{entry_id}")
def update_entry(entry_id: str, payload: ResumeEntryUpdate, db: Session = Depends(get_db)):
    entry = db.query(ResumeEntry).filter(ResumeEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    entry.updated_at = datetime.utcnow()
    db.commit()
    return {"updated": True}
 
 
@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.query(ResumeEntry).filter(ResumeEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"deleted": True}
 
 
@router.post("/generate/{user_id}")
def generate_resume(user_id: str, db: Session = Depends(get_db)):
    """Polishes the person's own real entries into resume language -
    never generates work history from scratch. Requires at least one
    real entry; there is no fallback that invents one.
    """
    from app.services.resume_builder import polish_resume_entry, generate_resume_summary
 
    entries = (
        db.query(ResumeEntry)
        .filter(ResumeEntry.user_id == user_id)
        .order_by(ResumeEntry.display_order, ResumeEntry.created_at)
        .all()
    )
    if not entries:
        raise HTTPException(status_code=400, detail="Add at least one real work, education, or project entry before generating a resume.")
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    profile_dict = {"northstar": profile.northstar if profile else ""}
 
    entry_dicts = [
        {"id": str(e.id), "entry_type": e.entry_type, "title": e.title, "org": e.org,
         "start_date": e.start_date, "end_date": e.end_date, "raw_description": e.raw_description}
        for e in entries
    ]
 
    try:
        polished_entries = []
        entries_snapshot = []
        for e in entry_dicts:
            result = polish_resume_entry(client, e)
            polished_entries.append({
                "entry_id": e["id"], "title": e["title"], "org": e["org"],
                "dates": f'{e["start_date"] or ""} - {e["end_date"] or ""}'.strip(" -"),
                "bullets": result["bullets"], "flagged_numbers": result["flagged_numbers"],
            })
            entries_snapshot.append({"entry_id": e["id"], "raw_description": e["raw_description"]})
        summary_line = generate_resume_summary(client, profile_dict, entry_dicts)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate the resume just now: {e}")
 
    doc = db.query(ResumeDocument).filter(ResumeDocument.user_id == user_id).first()
    if doc:
        doc.summary_line = summary_line
        doc.polished_entries = polished_entries
        doc.entries_snapshot = entries_snapshot
        doc.generated_at = datetime.utcnow()
    else:
        doc = ResumeDocument(
            user_id=user_id, summary_line=summary_line,
            polished_entries=polished_entries, entries_snapshot=entries_snapshot,
        )
        db.add(doc)
    db.commit()
 
    any_flags = any(pe["flagged_numbers"] for pe in polished_entries)
    return {
        "summary_line": summary_line,
        "entries": polished_entries,
        "review_note": "One or more bullets include a number that wasn't in what you originally wrote - double check those before using this." if any_flags else None,
    }
 
 
@router.get("/{user_id}")
def get_resume(user_id: str, db: Session = Depends(get_db)):
    doc = db.query(ResumeDocument).filter(ResumeDocument.user_id == user_id).first()
    if not doc:
        return {"summary_line": None, "entries": [], "generated_at": None}
    return {"summary_line": doc.summary_line, "entries": doc.polished_entries, "generated_at": doc.generated_at.isoformat() if doc.generated_at else None}
 
 
@router.get("/{user_id}/ats-check")
def get_ats_alignment(user_id: str, db: Session = Depends(get_db)):
    """Real, deterministic keyword coverage between the resume's
    actual content and the person's stated goal/skills - reuses the
    same synonym-aware matching already proven in the core matching
    engine, so this stays in sync with that fix rather than drifting
    from a second, separately-maintained copy of the same logic.
    """
    from app.services.resume_builder import check_ats_alignment
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    entry_dicts = [{"title": e.title, "raw_description": e.raw_description} for e in entries]
    profile_dict = {"northstar": profile.northstar if profile else "", "skills": profile.skills if profile else ""}
    return check_ats_alignment(profile_dict, entry_dicts)
 
 
@router.get("/{user_id}/tailor/{listing_id}")
def tailor_resume_for_listing(user_id: str, listing_id: str, db: Session = Depends(get_db)):
    """Which of the person's real entries are most worth leading with
    for this specific listing. Never changes what an entry says, only
    how they're ordered - the honest content is identical regardless
    of which job this is for.
    """
    from app.services.resume_builder import rank_entries_for_listing
    from app.models.db_models import Listing
 
    entries = (
        db.query(ResumeEntry)
        .filter(ResumeEntry.user_id == user_id)
        .order_by(ResumeEntry.display_order, ResumeEntry.created_at)
        .all()
    )
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
 
    entry_dicts = [
        {"id": str(e.id), "title": e.title, "org": e.org, "start_date": e.start_date,
         "end_date": e.end_date, "raw_description": e.raw_description}
        for e in entries
    ]
    ranked = rank_entries_for_listing(entry_dicts, {"tags": listing.tags or []})
    return {"entries": ranked}
 
 
@router.get("/{user_id}/skills")
def get_skills_section(user_id: str, db: Session = Depends(get_db)):
    """Only ever lists skills the person explicitly typed as their
    own; anything genuinely implied by their real entries but not
    already in that list comes back separately as a suggestion, never
    auto-added to the claimed list. See build_skills_section's
    docstring for why a skills section is more fabrication-sensitive
    than a bullet point, not less.
    """
    from app.services.resume_builder import build_skills_section
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    entry_dicts = [{"raw_description": e.raw_description} for e in entries]
    profile_dict = {"skills": profile.skills if profile else ""}
    return build_skills_section(profile_dict, entry_dicts)
 
 
class SkillAddIn(BaseModel):
    skill: str
 
 
@router.post("/{user_id}/skills/add")
def add_suggested_skill(user_id: str, body: SkillAddIn, db: Session = Depends(get_db)):
    """The only sanctioned way a suggested_additions entry moves into
    the person's explicit, claimed skills list - a deliberate action
    on a specific skill, never an automatic promotion. There's no
    general profile-edit endpoint elsewhere in this codebase; this is
    intentionally narrow (just this one field, just this one
    operation) rather than a broader endpoint this UI action doesn't
    need. Returns the freshly recomputed skills section so the caller
    can re-render immediately without a second round trip.
    """
    from app.services.resume_builder import add_skill_to_skills_string, build_skills_section
 
    profile = db.query(Profile).filter(Profile.user_id == user_id, Profile.is_current == True).first()  # noqa: E712
    if not profile:
        raise HTTPException(status_code=404, detail="No current profile found for this user")
 
    profile.skills = add_skill_to_skills_string(profile.skills, body.skill)
    db.commit()
 
    entries = db.query(ResumeEntry).filter(ResumeEntry.user_id == user_id).all()
    entry_dicts = [{"raw_description": e.raw_description} for e in entries]
    return build_skills_section({"skills": profile.skills}, entry_dicts)
 
