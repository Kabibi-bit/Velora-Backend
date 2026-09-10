"""Genuine longitudinal career-strategy reasoning - understanding
someone's real, current position and how their actual actions
compound toward a result, rather than scoring one listing at a time
in isolation. Every other AI-calling function in this codebase
reasons about a single listing, a single application, or a single
outcome. Nothing synthesizes across a person's real, accumulated
history to answer the actual question a career platform should be
able to answer: given everything this person has genuinely done so
far, what's the single highest-leverage next move, and why does it
compound rather than just add one more independent task to a list?
 
The real, new risk this introduces that per-listing reasoning doesn't
have: inventing a plausible-sounding connection between two real but
actually-unrelated data points. A model asked to find compounding
connections has a genuine incentive to find one even where none
exists - two applications to unrelated fields can be narrated into a
"strategic thread" that isn't real. The prompt is explicit that a
genuinely disconnected set of actions should be reported as exactly
that, not stitched into a false narrative.
"""
 
 
def _format_applications_for_prompt(applications: list[dict]) -> str:
    if not applications:
        return "No applications sent yet."
    lines = []
    for a in applications:
        status = a.get("status") or "pending_review"
        outcome = f", real outcome: {a['outcome_status']}" if a.get("outcome_status") else ""
        lines.append(f"- \"{a.get('listing_title', 'Unknown role')}\" at {a.get('listing_org', 'unknown org')} "
                     f"(sent {a.get('created_at', 'unknown date')}, status: {status}{outcome})")
    return "\n".join(lines)
 
 
def _format_roadmap_for_prompt(milestones: list[dict]) -> str:
    if not milestones:
        return "No roadmap has been generated yet."
    lines = []
    for m in milestones:
        lines.append(f"- Stage {m.get('target_stage')}: \"{m.get('title', '')}\" - status: {m.get('status', 'planned')}")
    return "\n".join(lines)
 
 
def analyze_strategic_position(
    anthropic_client,
    profile: dict,
    roadmap_milestones: list[dict],
    applications: list[dict],
    saved_listings: list[dict],
) -> dict:
    """The real, new synthesis this app has never had: not "does this
    ONE listing fit", but "given everything this person has actually
    done, where do they genuinely stand, and what's the highest-
    leverage next move". Grounds the analysis in real, concrete data
    (real applications sent, real outcomes received, real roadmap
    progress) rather than generic career-stage advice.
    """
    applications_text = _format_applications_for_prompt(applications)
    roadmap_text = _format_roadmap_for_prompt(roadmap_milestones)
    saved_text = ", ".join(f"\"{s.get('title', '')}\" at {s.get('org', '')}" for s in saved_listings[:10]) or "None saved yet."
 
    prompt = f"""A candidate's real, stated goal: "{profile.get('northstar', 'not specified')}". What "made it" looks like to them: "{profile.get('final_idea', 'not specified')}". Their stated skills: "{profile.get('skills', 'not specified')}". What matters most to them: {', '.join(profile.get('priorities') or []) or 'not specified'}.
 
Their real roadmap (their own stated plan):
{roadmap_text}
 
Their real applications actually sent, with real outcomes where known:
{applications_text}
 
Listings they've saved but not yet acted on: {saved_text}
 
You are synthesizing this person's REAL, accumulated history - not scoring one listing in isolation. Answer three things, grounded ONLY in what's actually here:
 
1. An honest, specific read on where they genuinely stand right now - their real momentum (or lack of it), based on the actual pattern of applications/outcomes/roadmap progress above, not a generic assessment of "early career" or similar. If the real data shows stalled momentum or no clear direction, say that plainly rather than finding false encouragement. Also explicitly check whether their real, actual applications align with their stated goal above - if their real behavior points somewhere genuinely different from what they said they want (e.g. their stated goal is one field but every real application sent is in a different one), name that honestly. This kind of real, checkable mismatch is one of the most valuable things this analysis can surface, so don't let a focus on "momentum" alone cause you to miss it.
 
2. Whether their real actions so far genuinely compound - do any of their actual applications, roadmap progress, or saved listings build on each other in a real, specific way (e.g. an application to a smaller company in the same real domain as their stated goal genuinely builds real, checkable experience toward a saved listing at a bigger one)? This must be a REAL, SPECIFIC connection between things that actually appear above - if their actions are genuinely disconnected from each other with no real compounding relationship, say that honestly rather than inventing a narrative thread that isn't there. Do not stitch together two unrelated actions into a false "strategy" - a genuine absence of connection is a real, useful finding, not a failure to find one.
 
3. Given all of the above, ONE specific, highest-leverage next move - not a generic "apply to more listings" but a specific action that genuinely compounds given their real, particular situation, and a concrete reason why THIS one, not something else.
 
Return a JSON object with exactly these four keys:
- current_position: 2-3 honest, specific sentences per point 1 above
- compounding_connections: an array of 0-3 strings, each describing one real, specific compounding relationship you found (empty array if genuinely none exist - do not force one)
- has_genuine_compounding: true only if compounding_connections is non-empty and each entry describes a real, specific, checkable relationship - false if their actions are genuinely disconnected
- next_move: an object with "action" (one specific, concrete thing to do) and "why_this_compounds" (1-2 sentences on why this specific move, given their real situation, builds on what already exists rather than starting a new, disconnected thread)
 
Return ONLY valid JSON, nothing else, no markdown fences, no commentary."""
 
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    except Exception as e:
        raise ValueError(f"Could not generate a strategic position analysis just now: {e}")
 
    import json
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Strategic position response was not valid JSON: {e}")
 
    # Real shape validation, consistent with every other AI-JSON
    # function in this codebase - a malformed response must be
    # rejected explicitly here, not silently passed through to
    # whatever renders it.
    if not isinstance(parsed.get("current_position"), str) or not parsed["current_position"].strip():
        raise ValueError(f"Strategic position response is missing a real current_position: {parsed}")
    if not isinstance(parsed.get("compounding_connections"), list):
        raise ValueError(f"Strategic position response's compounding_connections is not a real list: {parsed}")
    if not all(isinstance(c, str) and c.strip() for c in parsed["compounding_connections"]):
        raise ValueError(f"Strategic position response has an empty or non-string compounding connection: {parsed}")
    if not isinstance(parsed.get("has_genuine_compounding"), bool):
        raise ValueError(f"Strategic position response's has_genuine_compounding is not a real boolean: {parsed}")
    next_move = parsed.get("next_move")
    if not isinstance(next_move, dict) or not isinstance(next_move.get("action"), str) or not next_move["action"].strip() \
       or not isinstance(next_move.get("why_this_compounds"), str) or not next_move["why_this_compounds"].strip():
        raise ValueError(f"Strategic position response has an incomplete next_move: {parsed}")
 
    # Honest consistency check between has_genuine_compounding and the
    # actual, real content of compounding_connections - a genuinely
    # plausible failure mode where the model states "true" while the
    # array is empty, which would otherwise silently render a
    # confident "yes, compounding" verdict with nothing behind it.
    if parsed["has_genuine_compounding"] and not parsed["compounding_connections"]:
        parsed["has_genuine_compounding"] = False
 
    return parsed
 """Genuine longitudinal career-strategy reasoning - understanding
someone's real, current position and how their actual actions
compound toward a result, rather than scoring one listing at a time
in isolation. Every other AI-calling function in this codebase
reasons about a single listing, a single application, or a single
outcome. Nothing synthesizes across a person's real, accumulated
history to answer the actual question a career platform should be
able to answer: given everything this person has genuinely done so
far, what's the single highest-leverage next move, and why does it
compound rather than just add one more independent task to a list?
 
The real, new risk this introduces that per-listing reasoning doesn't
have: inventing a plausible-sounding connection between two real but
actually-unrelated data points. A model asked to find compounding
connections has a genuine incentive to find one even where none
exists - two applications to unrelated fields can be narrated into a
"strategic thread" that isn't real. The prompt is explicit that a
genuinely disconnected set of actions should be reported as exactly
that, not stitched into a false narrative.
"""
 
 
def _format_applications_for_prompt(applications: list[dict]) -> str:
    if not applications:
        return "No applications sent yet."
    lines = []
    for a in applications:
        status = a.get("status") or "pending_review"
        outcome = f", real outcome: {a['outcome_status']}" if a.get("outcome_status") else ""
        lines.append(f"- \"{a.get('listing_title', 'Unknown role')}\" at {a.get('listing_org', 'unknown org')} "
                     f"(sent {a.get('created_at', 'unknown date')}, status: {status}{outcome})")
    return "\n".join(lines)
 
 
def _format_roadmap_for_prompt(milestones: list[dict]) -> str:
    if not milestones:
        return "No roadmap has been generated yet."
    lines = []
    for m in milestones:
        lines.append(f"- Stage {m.get('target_stage')}: \"{m.get('title', '')}\" - status: {m.get('status', 'planned')}")
    return "\n".join(lines)
 
 
def analyze_strategic_position(
    anthropic_client,
    profile: dict,
    roadmap_milestones: list[dict],
    applications: list[dict],
    saved_listings: list[dict],
) -> dict:
    """The real, new synthesis this app has never had: not "does this
    ONE listing fit", but "given everything this person has actually
    done, where do they genuinely stand, and what's the highest-
    leverage next move". Grounds the analysis in real, concrete data
    (real applications sent, real outcomes received, real roadmap
    progress) rather than generic career-stage advice.
    """
    applications_text = _format_applications_for_prompt(applications)
    roadmap_text = _format_roadmap_for_prompt(roadmap_milestones)
    saved_text = ", ".join(f"\"{s.get('title', '')}\" at {s.get('org', '')}" for s in saved_listings[:10]) or "None saved yet."
 
    prompt = f"""A candidate's real, stated goal: "{profile.get('northstar', 'not specified')}". What "made it" looks like to them: "{profile.get('final_idea', 'not specified')}". Their stated skills: "{profile.get('skills', 'not specified')}". What matters most to them: {', '.join(profile.get('priorities') or []) or 'not specified'}.
 
Their real roadmap (their own stated plan):
{roadmap_text}
 
Their real applications actually sent, with real outcomes where known:
{applications_text}
 
Listings they've saved but not yet acted on: {saved_text}
 
You are synthesizing this person's REAL, accumulated history - not scoring one listing in isolation. Answer three things, grounded ONLY in what's actually here:
 
1. An honest, specific read on where they genuinely stand right now - their real momentum (or lack of it), based on the actual pattern of applications/outcomes/roadmap progress above, not a generic assessment of "early career" or similar. If the real data shows stalled momentum or no clear direction, say that plainly rather than finding false encouragement.
 
2. Whether their real actions so far genuinely compound - do any of their actual applications, roadmap progress, or saved listings build on each other in a real, specific way (e.g. an application to a smaller company in the same real domain as their stated goal genuinely builds real, checkable experience toward a saved listing at a bigger one)? This must be a REAL, SPECIFIC connection between things that actually appear above - if their actions are genuinely disconnected from each other with no real compounding relationship, say that honestly rather than inventing a narrative thread that isn't there. Do not stitch together two unrelated actions into a false "strategy" - a genuine absence of connection is a real, useful finding, not a failure to find one.
 
3. Given all of the above, ONE specific, highest-leverage next move - not a generic "apply to more listings" but a specific action that genuinely compounds given their real, particular situation, and a concrete reason why THIS one, not something else.
 
Return a JSON object with exactly these four keys:
- current_position: 2-3 honest, specific sentences per point 1 above
- compounding_connections: an array of 0-3 strings, each describing one real, specific compounding relationship you found (empty array if genuinely none exist - do not force one)
- has_genuine_compounding: true only if compounding_connections is non-empty and each entry describes a real, specific, checkable relationship - false if their actions are genuinely disconnected
- next_move: an object with "action" (one specific, concrete thing to do) and "why_this_compounds" (1-2 sentences on why this specific move, given their real situation, builds on what already exists rather than starting a new, disconnected thread)
 
Return ONLY valid JSON, nothing else, no markdown fences, no commentary."""
 
    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    except Exception as e:
        raise ValueError(f"Could not generate a strategic position analysis just now: {e}")
 
    import json
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Strategic position response was not valid JSON: {e}")
 
    # Real shape validation, consistent with every other AI-JSON
    # function in this codebase - a malformed response must be
    # rejected explicitly here, not silently passed through to
    # whatever renders it.
    if not isinstance(parsed.get("current_position"), str) or not parsed["current_position"].strip():
        raise ValueError(f"Strategic position response is missing a real current_position: {parsed}")
    if not isinstance(parsed.get("compounding_connections"), list):
        raise ValueError(f"Strategic position response's compounding_connections is not a real list: {parsed}")
    if not all(isinstance(c, str) and c.strip() for c in parsed["compounding_connections"]):
        raise ValueError(f"Strategic position response has an empty or non-string compounding connection: {parsed}")
    if not isinstance(parsed.get("has_genuine_compounding"), bool):
        raise ValueError(f"Strategic position response's has_genuine_compounding is not a real boolean: {parsed}")
    next_move = parsed.get("next_move")
    if not isinstance(next_move, dict) or not isinstance(next_move.get("action"), str) or not next_move["action"].strip() \
       or not isinstance(next_move.get("why_this_compounds"), str) or not next_move["why_this_compounds"].strip():
        raise ValueError(f"Strategic position response has an incomplete next_move: {parsed}")
 
    # Honest consistency check between has_genuine_compounding and the
    # actual, real content of compounding_connections - a genuinely
    # plausible failure mode where the model states "true" while the
    # array is empty, which would otherwise silently render a
    # confident "yes, compounding" verdict with nothing behind it.
    if parsed["has_genuine_compounding"] and not parsed["compounding_connections"]:
        parsed["has_genuine_compounding"] = False
 
    return parsed
 
