# Velora backend — security & load review

A concrete pass over the real codebase, not a generic checklist. Every
finding below was verified against actual code, with the file noted.
Items are ordered by priority (severity × likelihood). "Fixed this
pass" means done and tested; the rest are honest, open recommendations.

---

## Fixed this pass

### ✅ Auth on every route (done over prior turns)
Every endpoint now verifies the caller's token matches the user being
acted on, except two *intentionally* public endpoints, both documented
inline:
- `engagement.accept_suggestion` — the no-login email accept link (single-use token).
- `users.create_user` — legacy password-less demo endpoint; real signup is the authenticated `/auth/signup`.
Verified with real-JWT tests: cross-user → 403; forged/expired/garbage → 401.

### ✅ CORS locked (`app/main.py`)
Wildcard `allow_origins=["*"]` replaced with an env-configurable
allowlist (`VELORA_ALLOWED_ORIGINS`), defaulting to localhost dev
origins, never a wildcard. `allow_credentials=False` (the app uses
bearer tokens, not cookies).

### ✅ Traceback leak fixed (`app/main.py`)
The debug handler that returned exception type + message + full stack
trace to clients now logs the traceback server-side and returns only a
generic message + correlation id. `HTTPException` is re-raised so auth
status codes reach clients unchanged.

### ✅ Email recipient guard (`app/services/email_send.py`)
Centralized recipient-format validation on the single send path,
covering all 5 send endpoints at once. Blocks blank/malformed
addresses, CRLF header-injection, and comma/semicolon multi-address
"blasts". Verified with 11 test cases. (Does not change legitimate
single-recipient behavior.)

### ✅ Input-size caps on AI-bound fields (chat, assistance, market_research, engagement)
Added Pydantic `Field(max_length=...)` to every user-supplied string
that flows into an Anthropic prompt (message 8k, need_description 4k,
company/role 200, post_content 8k, etc.) and capped `chat.history`
length. Closes the "POST a multi-MB string → huge token bill" vector.
(This was open item #2 below — now done.)

### ✅ Scan loop: hoisted the per-user listings query (`app/services/scheduler.py`)
`run_scan_for_all_users` re-ran `db.query(Listing).all()` inside the
per-user loop for every auto-apply user. Now loaded once per cycle and
reused — removes N redundant full-table loads. (The larger task-queue
change in #5 remains open.)

---

## Open — high priority (do before real public launch)

### 1. No rate limiting anywhere — HIGH
**Verified:** zero rate-limiting code in the whole backend.
**Risk:** every AI endpoint (chat, assistance, market-research,
career-discovery explain, resume/cover-letter generation, outreach
drafting, roadmap generation) is now auth-gated but still callable in
an unlimited loop by any logged-in user. One account can run up an
unbounded Anthropic/Voyage bill or hammer Resend. This is the single
biggest remaining cost/abuse exposure.
**Fix (infra decision):** add `slowapi` (or a reverse-proxy / Render
rate limit) with per-user limits, tightest on the AI + email endpoints
(e.g. a few AI calls/minute/user, a small number of sends/hour/user).
**Effort:** ~half a day; needs a dependency + a small amount of config,
which is why it's flagged rather than silently added here.

### 2. Unbounded request-body sizes on AI endpoints — ✅ DONE this pass
**Was:** no length caps on AI-bound inputs.
**Fixed:** added `Field(max_length=...)` to the user-supplied string
fields on `ChatIn`, `AssistanceSearchIn`, `CompanyResearchIn`,
`InterviewPrepIn`, and engagement `DraftIn`, plus a cap on
`chat.history`. Verified syntax + auth still intact on all four files.

### 3. Arbitrary outreach recipient — MEDIUM (partially mitigated)
**Verified:** `outreach.edit_outreach` lets a user set any
`to_address`; `address_verified` exists but is **never set True
anywhere**, so it can't be enforced without breaking all sending.
**Mitigated this pass:** the recipient-format guard now blocks
malformed/injection/blast addresses.
**Residual risk:** a user can still send *one* well-formed email to an
arbitrary address via your Resend domain. Rate limiting (#1) is the
real mitigation. Longer term, consider a per-user daily send cap and/or
domain-reputation monitoring.

---

## Open — medium priority

### 4. JWT lifetime is 14 days — MEDIUM
**Verified:** `JWT_EXPIRY_HOURS = 24 * 14` in `app/services/auth.py`.
**Risk:** a leaked token stays valid for two weeks; there's no
server-side revocation.
**Fix:** shorten to something like 24–72h, and/or add a refresh-token
flow. Shortening is a one-line change but a UX trade-off (more frequent
re-login), so it's a product decision rather than an automatic fix.

### 5. Background scan doesn't scale — MEDIUM (load)
**Verified:** `run_scan_for_all_users` (`app/services/scheduler.py`)
loops over every current-profile user sequentially in one background
thread, and re-runs `db.query(Listing).all()` *inside* the per-user
loop (line ~439) — so all listings are re-loaded N times per cycle.
**Risk:** fine for dozens of users; degrades badly at thousands. The
per-user full-listings query is the worst part.
**Fix:** hoist the listings query out of the loop (load once per
cycle), and for real scale move to a task queue (e.g. a worker per
user-batch) instead of one in-process thread. The hoist is a genuine
quick win; the queue is a larger architectural change.

---

## Open — low priority / hygiene

### 6. `datetime.utcnow()` deprecation — LOW
**Verified:** 20 call sites. Deprecated in Python 3.12+; still works but
will eventually warn/break.
**Fix:** mechanical replace with `datetime.now(datetime.UTC)`. Safe to
batch, but touches many files, so worth doing as its own focused pass.

### 7. Confirm `JWT_SECRET_KEY` is set in production — LOW (but critical if missed)
`decode_access_token` returns `None` (reject-all) if the secret is
unset, so a missing secret fails safe (no auth bypass) — but the whole
app's auth silently breaks. Documented in the new `.env.example`;
verify it's set in Render before launch.

---

## Summary

The launch-blocking security items — auth on every route, CORS,
traceback leak — are **closed and tested**, and this pass additionally
closed the email-recipient vector, the unbounded-input vector (#2), and
the redundant per-user listings query. The most important *remaining*
item is now **rate limiting (#1)** — it needs a small infra decision (a
dependency or a proxy-level limit), which is why it's flagged for you
rather than silently added. Everything below #1 is real but not
launch-blocking: a shorter JWT lifetime (#4, a UX trade-off), the
scan task-queue for real scale (#5), and the `datetime.utcnow()`
cleanup (#6).
