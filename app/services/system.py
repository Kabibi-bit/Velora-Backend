"""System-wide status checks, not tied to a specific user - a
separate file since these don't fit any existing user-scoped router.
"""
from fastapi import APIRouter
 
router = APIRouter(prefix="/system", tags=["system"])
 
 
@router.get("/embeddings-status")
def embeddings_status():
    """Whether real semantic matching (see app/services/embeddings.py)
    is actually working right now - previously invisible without
    reading raw server logs. Makes a single real, throwaway call to
    Voyage if a key is configured, so this distinguishes "no key set"
    from "key set but the call is failing" - those need different
    fixes (add a key vs. check the key's validity or Voyage's status)
    and looked identical from the outside before this endpoint
    existed.
    """
    from app.services.embeddings import check_embeddings_status
 
    return check_embeddings_status()
 
