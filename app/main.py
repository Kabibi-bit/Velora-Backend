import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
 
from app.routes import profile, listings, chat, users, roadmap, outcomes, applications, manual_listings, saved_listings, notifications, career_discovery, outreach, auth, social, athletics, market_research, resume
from app.services.scheduler import start_scheduler
 
load_dotenv()
 
app = FastAPI(title="Scanline API")
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
 
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(profile.router)
app.include_router(listings.router)
app.include_router(chat.router)
app.include_router(roadmap.router)
app.include_router(outcomes.router)
app.include_router(applications.router)
app.include_router(manual_listings.router)
app.include_router(saved_listings.router)
app.include_router(notifications.router)
app.include_router(career_discovery.router)
app.include_router(outreach.router)
app.include_router(social.router)
app.include_router(athletics.router)
app.include_router(market_research.router)
app.include_router(resume.router)
 
# system.py is a small, purely diagnostic router (the
# /system/embeddings-status health check) - genuinely optional,
# unlike every router above. This import is deliberately isolated
# and guarded: without this try/except, a missing or broken
# system.py (a new file, easy to miss when applying a batch of
# changes - exactly what happened once already, taking the entire
# backend down for a single diagnostic endpoint) would crash this
# whole shared import statement, since it previously sat in the same
# line as every essential router. A purely diagnostic endpoint
# should never be able to take the rest of the app down with it.
try:
    from app.routes import system
    app.include_router(system.router)
except Exception as e:
    print(f"system router (embeddings-status diagnostic endpoint) failed to load, continuing without it: {e}")
 
 
# TEMPORARY DEBUG HANDLER: shows the real error directly in the API
# response instead of only in Render's logs, so it's easy to read.
# Remove this once things are working -- it can leak internal details.
@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
        },
    )
 
 
@app.on_event("startup")
def on_startup():
    start_scheduler()
 
 
@app.get("/health")
def health():
    return {"status": "ok"}
 
