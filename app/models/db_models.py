""SQLAlchemy models mirroring db/schema.sql.
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
 
Base = declarative_base()
 
 
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=True)  # nullable for backward-compat with any users created before auth existed
    role = Column(String, nullable=False, default="candidate")  # candidate / business / tutor / athlete
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
    open_to_offers = Column(Boolean, nullable=False, default=False)
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
 
 
class Business(Base):
    __tablename__ = "businesses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String, nullable=False)
    contact_email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class CandidateAccessPurchase(Base):
    __tablename__ = "candidate_access_purchases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"))
    access_tier = Column(String, nullable=False)
    price_paid = Column(Numeric(10, 2))
    payment_status = Column(String, nullable=False, default="pending")
    starts_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class BusinessHire(Base):
    __tablename__ = "business_hires"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"))
    status = Column(String, nullable=False)  # contacted / interviewing / hired / passed
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
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
class SocialPost(Base):
    """A personal progress journal entry, optionally tagged to a
    roadmap stage. This used to be part of a cross-user social feed
    with connections and comments - cut down deliberately, since a
    feed needs real other users to have any value, and a connection
    feature carries a real moderation/safety workload that isnt
    worth taking on before theres anyone real to connect with.
    """
    __tablename__ = "social_posts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    body = Column(Text, nullable=False)
    video_url = Column(String)
    roadmap_stage = Column(Integer)
    roadmap_stage_title = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
 
 
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
 
