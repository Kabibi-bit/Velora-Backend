"""Best-effort REAL submission of a web-form job application via a headless
browser (Playwright/Chromium).
 
This is the honest version of "auto-apply to the job site". There is no universal
API to submit an arbitrary employer's application form, so the only real way to do
it is to drive a browser the way a person would. That is genuinely possible for
simple public forms - and genuinely NOT possible for a large share of real
postings (logins, CAPTCHAs, multi-step Workday-style flows, employer accounts).
This module is built to be honest about which case it hit, and - above all - to
NEVER submit a garbled or partial application under the user's name:
 
  Safety model (why this can't silently ruin an application):
    * It aborts (returns "needs_manual") the moment it detects a login/signup
      wall or a CAPTCHA - it does not try to bluff past them.
    * It fills only fields it can confidently map to the user's real data
      (name / email / phone / resume file / cover letter).
    * Before clicking Submit it re-checks EVERY required control on the form.
      If any required field is still empty (i.e. something it couldn't map),
      it aborts instead of submitting an incomplete/garbled application.
    * It only reports "submitted" when it can actually detect a confirmation
      after submitting. No confirmation -> it reports "needs_manual", never a
      fabricated success.
    * If Playwright or a browser binary isn't available in the runtime, it
      returns "unavailable" and the caller falls back to the manual hand-off -
      it never crashes the request.
 
Result status is one of:
    "submitted"    - the form was filled and a submission confirmation was seen.
    "needs_manual" - a real blocker (login/CAPTCHA), an unmappable required
                     field, or no detectable confirmation. Hand off to the user.
    "unavailable"  - no browser automation in this runtime.
    "error"        - an unexpected failure; caller falls back to the hand-off.
 
Deployment note: the deployed backend must have the `playwright` package AND its
Chromium binary installed (`playwright install chromium`). Without them this
returns "unavailable" and the app degrades to the manual hand-off - safe, just
not automatic.
"""
from __future__ import annotations
 
import logging
 
_log = logging.getLogger("velora")
 
# Text seen on a page that means "you must sign in / create an account first".
_LOGIN_MARKERS = ("sign in to apply", "log in to apply", "login to apply", "create an account to apply")
# Text/markup that means a CAPTCHA is present - we never try to defeat these.
_CAPTCHA_SELECTOR = "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha, .h-captcha, [data-sitekey]"
# Text that means the submission went through.
_CONFIRM_MARKERS = (
    "thank you for applying", "thanks for applying", "application received",
    "received your application", "application submitted", "successfully submitted",
    "we have received", "we've received", "we'll be in touch", "thank you for your application",
    "your application has been", "application complete",
)
_CONFIRM_URL_MARKERS = ("thank", "confirm", "success", "complete", "submitted", "received")
 
 
def _fill_first(page, selectors, value) -> bool:
    """Fill the first visible, editable control matching any selector. Returns
    True if something was filled. Never raises - a missing field just returns False."""
    if not value:
        return False
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible() and loc.is_editable():
                loc.fill(str(value), timeout=3000)
                return True
        except Exception:
            continue
    return False
 
 
def _required_controls_all_satisfied(page) -> bool:
    """True only if every REQUIRED form control has a value / a file. This is the
    core anti-garbage guard: if we couldn't map some required field, we must not
    submit. Fails safe to False (do not submit) on any uncertainty."""
    try:
        controls = page.locator(
            "input[required]:not([type=hidden]):not([type=submit]):not([type=button]), "
            "textarea[required], select[required], "
            "[aria-required='true']"
        )
        n = controls.count()
        for i in range(n):
            c = controls.nth(i)
            try:
                if not c.is_visible():
                    continue
                type_attr = (c.get_attribute("type") or "").lower()
                if type_attr in ("checkbox", "radio"):
                    # Required consent/eligibility box we didn't knowingly check -
                    # treat as unsatisfied so we don't auto-agree to something.
                    if not c.is_checked():
                        return False
                    continue
                if type_attr == "file":
                    # A required file with nothing attached => unsatisfied.
                    files_val = c.evaluate("el => el.files ? el.files.length : 0")
                    if not files_val:
                        return False
                    continue
                val = (c.input_value() if hasattr(c, "input_value") else c.evaluate("el => el.value")) or ""
                if not str(val).strip():
                    return False
            except Exception:
                return False  # can't verify -> don't risk a bad submit
        return True
    except Exception:
        return False
 
 
def _looks_confirmed(page) -> bool:
    try:
        url = (page.url or "").lower()
        if any(m in url for m in _CONFIRM_URL_MARKERS):
            return True
        body = (page.locator("body").inner_text(timeout=3000) or "").lower()
        return any(m in body for m in _CONFIRM_MARKERS)
    except Exception:
        return False
 
 
def submit_application_via_browser(
    apply_url: str,
    candidate: dict,
    resume_path: str | None = None,
    cover_letter: str | None = None,
    timeout_ms: int = 25000,
) -> dict:
    """Attempt a real submission at apply_url. See module docstring for the
    status contract and the safety model. candidate keys used (all optional):
    full_name, first_name, last_name, email, phone."""
    if not apply_url or not str(apply_url).startswith(("http://", "https://")):
        return {"status": "needs_manual", "reason": "no real application URL to open"}
 
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"status": "unavailable", "reason": "browser automation is not available in this environment"}
 
    candidate = candidate or {}
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                return {"status": "unavailable", "reason": f"could not launch a browser: {e}"}
            try:
                page = browser.new_page()
                page.set_default_timeout(8000)
                page.goto(apply_url, timeout=timeout_ms, wait_until="domcontentloaded")
 
                # 1) Never try to bluff past a CAPTCHA or a login wall.
                try:
                    if page.locator(_CAPTCHA_SELECTOR).count() > 0:
                        return {"status": "needs_manual", "reason": "the posting is protected by a CAPTCHA"}
                except Exception:
                    pass
                try:
                    body_lower = (page.locator("body").inner_text(timeout=4000) or "").lower()
                except Exception:
                    body_lower = ""
                if any(m in body_lower for m in _LOGIN_MARKERS) or page.locator("input[type=password]").count() > 0:
                    return {"status": "needs_manual", "reason": "the posting requires signing in or creating an account first"}
 
                # 2) Fill only what we can confidently map to real user data.
                _fill_first(page, ["input[type=email]", "input[name*=email i]", "input[id*=email i]", "input[placeholder*=email i]", "input[aria-label*=email i]"], candidate.get("email"))
                full_name = candidate.get("full_name") or " ".join(x for x in [candidate.get("first_name"), candidate.get("last_name")] if x).strip()
                filled_full = _fill_first(page, [
                    "input[name*='full_name' i]", "input[name*='full-name' i]", "input[name*='full name' i]", "input[name*=fullname i]",
                    "input[id*='full_name' i]", "input[id*=fullname i]",
                    "input[placeholder*='full name' i]", "input[aria-label*='full name' i]",
                    "input[autocomplete='name']",
                    "input[name='name' i]", "input[id='name' i]", "input[name*='your_name' i]", "input[name*=applicant i]",
                ], full_name)
                if not filled_full:
                    _fill_first(page, ["input[name*=first i]", "input[id*=first i]", "input[placeholder*='first name' i]", "input[aria-label*='first name' i]"], candidate.get("first_name"))
                    _fill_first(page, ["input[name*=last i]", "input[id*=last i]", "input[placeholder*='last name' i]", "input[aria-label*='last name' i]"], candidate.get("last_name"))
                _fill_first(page, ["input[type=tel]", "input[name*=phone i]", "input[id*=phone i]", "input[placeholder*=phone i]", "input[aria-label*=phone i]"], candidate.get("phone"))
                if cover_letter:
                    _fill_first(page, ["textarea[name*=cover i]", "textarea[id*=cover i]", "textarea[name*=message i]", "textarea[name*=letter i]", "textarea[placeholder*='cover letter' i]", "textarea[aria-label*='cover letter' i]", "textarea"], cover_letter)
 
                # 3) Resume upload (many forms require it).
                if resume_path:
                    try:
                        file_input = page.locator("input[type=file]").first
                        if file_input.count() > 0:
                            file_input.set_input_files(resume_path, timeout=5000)
                    except Exception:
                        pass  # if it fails and the file is required, the guard below aborts
 
                # 4) ANTI-GARBAGE GUARD: only proceed if every required control is
                #    satisfied. If we couldn't map a required field, hand off.
                if not _required_controls_all_satisfied(page):
                    return {"status": "needs_manual", "reason": "the form has required fields this couldn't fill safely"}
 
                # 5) Submit.
                submit = None
                for sel in ["button[type=submit]", "input[type=submit]",
                            "button:has-text('Submit application')", "button:has-text('Submit')",
                            "button:has-text('Apply')", "button:has-text('Send application')",
                            "button:has-text('Send')"]:
                    try:
                        loc = page.locator(sel).first
                        if loc.count() > 0 and loc.is_visible():
                            submit = loc
                            break
                    except Exception:
                        continue
                if submit is None:
                    return {"status": "needs_manual", "reason": "couldn't find a submit button on the form"}
                try:
                    submit.click(timeout=6000)
                except Exception as e:
                    return {"status": "needs_manual", "reason": f"couldn't click submit: {e}"}
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass
 
                # 6) Only claim success on a real, detectable confirmation.
                if _looks_confirmed(page):
                    return {"status": "submitted", "reason": "submission confirmed by the posting"}
                return {"status": "needs_manual", "reason": "submitted the form but couldn't confirm it went through - verify at the posting"}
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as e:
        _log.warning("Browser auto-submit failed for %s - %s", apply_url, e)
        return {"status": "error", "reason": str(e)}
 
