import traceback
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
 
from app.routes import profile, listings, chat, users, roadmap, outcomes, applications, manual_listings, tutors, businesses, saved_listings, notifications
from app.services.scheduler import start_scheduler
 
load_dotenv()
 
app = FastAPI(title="Scanline API")
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
 
app.include_router(users.router)
app.include_router(profile.router)
app.include_router(listings.router)
app.include_router(chat.router)
app.include_router(roadmap.router)
app.include_router(outcomes.router)
app.include_router(applications.router)
app.include_router(manual_listings.router)
app.include_router(tutors.router)
app.include_router(businesses.router)
app.include_router(saved_listings.router)
app.include_router(notifications.router)
 
 
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
 
