
"""SQLAlchemy models mirroring db/schema.sql.
Run schema.sql directly against Postgres for the pgvector setup;
these models are for querying/inserting from the app layer.
"""
import uuid
from datetime import datetime
 
from sqlalchemy import (
    Column, String, Text, ForeignKey, DateTime, Numeric, Integer,
    ARRAY, Boolean, Date
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector
 
Base = declarative_base()
 
 
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=True)  # nullable for backward-compat with any users created before auth existed
    role = Column(String, nullable=False, default="candidate")  # candidate / tutor / athlete
    created_at = Column(DateTime, default=datetime.utcnow)
 
    profiles = relationship("Profile", back_populates="user")
 
 
class Profile(Base):
    __tablename__ = "profiles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    northstar = Column(Text, nullable=False)
    final_idea = Column(Text)
    timeframe = Column(String)
    stage = Column(String)
    priorities = Column(ARRAY(String))
    skills = Column(Text)
    dealbreakers = Column(Text)
    location_pref = Column(String)
    target_types = Column(ARRAY(String))
    is_current = Column(Boolean, default=True)
    auto_apply_enabled = Column(Boolean, nullable=False, default=False)
    auto_apply_threshold = Column(Integer, nullable=False, default=80)
    created_at = Column(DateTime, default=datetime.utcnow)
 
    user = relationship("User", back_populates="profiles")
 
 
class Listing(Base):
    __tablename__ = "listings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    org = Column(String, nullable=False)
    type = Column(String, nullable=False)
    location = Column(String)
    description = Column(Text)
    tags = Column(ARRAY(String))
    deadline = Column(Date)
    apply_url = Column(String, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    embedding = Column(Vector(512), nullable=True)  # None until embedded - see app/services/embeddings.py
 
 
class MatchScore(Base):
    __tablename__ = "match_scores"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"))
    profile_id = Column(UUID(as_uuid=True), ForeignKey("profiles.id"))
    score_pct = Column(Numeric(5, 2), nullable=False)
    goal_match_tags = Column(ARRAY(String))
    skill_match_tags = Column(ARRAY(String))
    rationale = Column(Text)
    scan_cycle = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class Outcome(Base):
    __tablename__ = "outcomes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"))
    status = Column(String, nullable=False)  # applied/interview/rejected/ghosted/offer
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class RoadmapMilestone(Base):
    __tablename__ = "roadmap_milestones"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String, nullable=False)
    description = Column(Text)
    success_criteria = Column(Text)
    estimated_timeframe = Column(String)
    first_action = Column(Text)
    resource = Column(Text)
    risk = Column(Text)
    if_it_works = Column(Text)
    if_it_stalls = Column(Text)
    target_stage = Column(Integer, nullable=False)
    status = Column(String, default="planned")
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class RoadmapSummary(Base):
    __tablename__ = "roadmap_summaries"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    summary = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class ChatMemory(Base):
    __tablename__ = "chat_memory"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class Application(Base):
    __tablename__ = "applications"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"))
    draft_content = Column(Text)
    confidence_pct = Column(Numeric(5, 2))
    status = Column(String, default="pending_review")
    sendable_at = Column(DateTime)
    sent_at = Column(DateTime)
    auto_generated = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    factors_snapshot = Column(JSONB, nullable=True)  # the score_listing() factor breakdown at creation time - without this, there's no way to later learn which TYPES of signal actually predicted success for this user
    counterfactual_confidence_pct = Column(Numeric(5, 2), nullable=True)  # what the score WOULD have been without personalized factor weighting - without this, there's no way to check whether personalization is actually helping this user or just moving the number around
    draft_flagged_terms = Column(JSONB, nullable=True)  # numbers or specific timing claims (e.g. "summer") that appear in draft_content but nowhere in the real source material - see draft_application()'s fabrication check
 
 
class Tutor(Base):
    __tablename__ = "tutors"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    bio = Column(Text)
    expertise_tags = Column(ARRAY(String))
    certifications = Column(ARRAY(String))
    hourly_rate = Column(Numeric(8, 2))
    application_status = Column(String, nullable=False, default="pending")
    application_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class TutorRequest(Base):
    __tablename__ = "tutor_requests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    tutor_id = Column(UUID(as_uuid=True), ForeignKey("tutors.id", ondelete="CASCADE"))
    skill_gap = Column(Text, nullable=False)
    message = Column(Text)
    status = Column(String, nullable=False, default="requested")
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class SavedListing(Base):
    __tablename__ = "saved_listings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"))
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class Notification(Base):
    __tablename__ = "notifications"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    detail = Column(Text)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class CareerDiscoveryResult(Base):
    __tablename__ = "career_discovery_results"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    answers = Column(JSONB, nullable=False)
    directions = Column(JSONB, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class OutreachEmail(Base):
    __tablename__ = "outreach_emails"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    listing_id = Column(UUID(as_uuid=True), ForeignKey("listings.id", ondelete="CASCADE"))
    to_address = Column(String, nullable=False)
    address_verified = Column(Boolean, nullable=False, default=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="drafted")  # drafted / sent / failed
    auto_generated = Column(Boolean, nullable=False, default=False)
    leadership_grounded = Column(Boolean, nullable=False, default=False)  # True only if real, current leadership statements were found and referenced
    leadership_research_sources = Column(JSONB, nullable=True)  # [{url, title}] - the real sources behind a leadership_grounded draft, for the recipient's own verification
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class SocialPost(Base):
    """A private progress journal entry - generalized to work across
    all 3 roles, not just candidates. tag_value/tag_label are generic
    on purpose: for candidates and athletes they hold a real roadmap
    stage number and title; for tutors they hold a teaching phase
    (prep/session/followup/curriculum). Never a fake roadmap forced
    onto a role that doesn't have one - each role's frontend supplies
    whatever tagging is actually real for it.
    """
    __tablename__ = "social_posts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    body = Column(Text, nullable=False)
    video_url = Column(String)
    tag_value = Column(String)
    tag_label = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)
 
 
class AthleteEvent(Base):
    """A tracked deadline or trial opportunity for a student-athlete -
    a tryout, camp, combine, or application deadline, optionally tied
    to a specific roadmap stage.
    """
    __tablename__ = "athlete_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String, nullable=False)
    org = Column(String)
    event_type = Column(String, nullable=False)  # tryout / camp / combine / application_deadline / other
    event_date = Column(Date)
    roadmap_stage = Column(Integer)
    roadmap_stage_title = Column(String)
    status = Column(String, nullable=False, default="upcoming")  # upcoming / attended / passed / missed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class AthleteOutreach(Base):
    """A draft/edit/send email + cold-call script for reaching a coach
    or staff member. Separate from OutreachEmail since it isn't tied
    to a real listing row - grounded in a free-text description of
    who to reach instead.
    """
    __tablename__ = "athlete_outreach"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    target_description = Column(Text, nullable=False)
    to_address = Column(String, nullable=False)
    address_verified = Column(Boolean, nullable=False, default=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    cold_call_script = Column(Text)
    roadmap_stage = Column(Integer)
    roadmap_stage_title = Column(String)
    status = Column(String, nullable=False, default="drafted")  # drafted / sent / failed
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class AthleteRoadmapMilestone(Base):
    """Real backend roadmap for athletes - mirrors RoadmapMilestone,
    plus if_it_works/if_it_stalls branching which the candidate
    backend roadmap doesn't even have yet (only the frontend does).
    """
    __tablename__ = "athlete_roadmap_milestones"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String, nullable=False)
    description = Column(Text)
    success_criteria = Column(Text)
    estimated_timeframe = Column(String)
    first_action = Column(Text)
    resource = Column(Text)
    risk = Column(Text)
    if_it_works = Column(Text)
    if_it_stalls = Column(Text)
    target_stage = Column(Integer, nullable=False)
    status = Column(String, default="planned")
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class AthleteRoadmapSummary(Base):
    __tablename__ = "athlete_roadmap_summaries"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    summary = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class ResumeEntry(Base):
    """A single real, user-provided fact about their experience -
    a job, an education entry, or a project. entry_type + title +
    org + dates are all things the user states directly; raw_description
    is their own plain-language account of what they did. The AI-
    polish step (see app/services/resume_builder.py) is only ever
    allowed to strengthen the PHRASING of raw_description into
    resume-style language - never to add a fact, metric, or
    achievement the user didn't put here themselves. This table is
    the real source of truth a resume gets built from; nothing about
    a person's work history is ever generated from scratch.
    """
    __tablename__ = "resume_entries"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    entry_type = Column(String, nullable=False)  # work / education / project
    title = Column(String, nullable=False)  # job title, degree, or project name
    org = Column(String)  # employer, school, or None for a personal project
    start_date = Column(String)  # free text ("Jun 2024") - real dates people give are rarely full ISO dates
    end_date = Column(String)  # free text, or "Present"
    raw_description = Column(Text, nullable=False)  # the user's own plain-language account - never AI-generated
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
 
 
class ResumeDocument(Base):
    """The most recently generated resume for a user - polished
    bullet points and a summary line, always traceable back to the
    real ResumeEntry rows it was built from (entries_snapshot keeps
    the exact raw_description text used, so a later edit to an entry
    doesn't silently make an old generated resume look like it was
    based on something the user never actually said).
    """
    __tablename__ = "resume_documents"
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    summary_line = Column(Text)
    polished_entries = Column(JSONB, nullable=False)  # [{entry_id, title, org, dates, bullets: [str]}]
    entries_snapshot = Column(JSONB, nullable=False)  # raw_description text as it existed at generation time
    generated_at = Column(DateTime, default=datetime.utcnow)
 
 
class ApiQuotaTracker(Base):
    """Tracks real daily call volume against a specific external
    API's documented rate limit - built after actually checking
    Adzuna's real, current free-tier terms (roughly 1,000 calls a
    month, about 33 a day) rather than assuming the ingestion
    pipeline's call volume was safely within some unverified "should
    be fine" range. One row per (api_name, date); see
    app/services/ingestion.py's check_and_reserve_quota for how this
    gets used to gracefully skip rather than blindly exceed a real,
    external limit.
    """
    __tablename__ = "api_quota_tracker"
    api_name = Column(String, primary_key=True)
    date = Column(String, primary_key=True)  # YYYY-MM-DD, not a DateTime - this is a daily bucket key, not a timestamp
    call_count = Column(Integer, default=0)
 
 
class CompanyLeadershipResearch(Base):
    """A real cache, not just a nice-to-have: without this, a
    candidate viewing a company's leadership research and then
    deciding to draft an outreach email would trigger the same real,
    billed web-search call twice for the same company - and every
    other candidate applying to the same company would each trigger
    their own redundant search too. Keyed by a normalized company
    name (lowercased, stripped) so "Acme Inc" and "acme inc " hit the
    same cached row. See app/services/market_research.py's
    get_or_research_company_leadership for how this gets checked
    before ever making a real search call.
    """
    __tablename__ = "company_leadership_research"
    company_name_normalized = Column(String, primary_key=True)
    company_name_display = Column(String, nullable=False)  # the real, as-typed name, for display
    leaders = Column(JSONB, nullable=False)
    priorities_summary = Column(Text, nullable=False)
    sources = Column(JSONB, nullable=False)
    researched_at = Column(DateTime, default=datetime.utcnow)
 
