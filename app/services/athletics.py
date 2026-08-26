"""Recruiting content guidance for student-athletes: how to structure
a highlight reel, and which drills/metrics are commonly evaluated for
their specific sport, level, and career direction.
 
generate_recruiting_content_plan() gives grounded GENERAL guidance -
it deliberately never claims to know what a specific named coach or
program wants, since without a real information source that would be
fabrication.
 
research_target_program() is different: it gives Claude the real,
first-party Anthropic web search tool, so it can actually search for
and cite real, current, public information about a SPECIFIC named
program - their recruiting page, coaching staff statements, recent
recruiting classes, roster needs. This is genuinely real search, not
invented knowledge - and it's explicitly instructed to say plainly
when search turns up nothing specific, rather than filling the gap
with a guess.
"""
 
 
def generate_recruiting_content_plan(anthropic_client, sport: str, level: str, career_direction: str, achievements: str) -> dict:
    direction_label = {
        "play-college": "playing at the college level",
        "go-pro": "going pro",
        "coach": "coaching",
        "sports-management": "a sports management career",
    }.get(career_direction, career_direction)
 
    prompt = (
        f"A student-athlete: sport \"{sport}\", current level {level}, career direction: {direction_label}. "
        f"Their stated achievements: \"{achievements}\".\n\n"
        "Give them real, specific guidance on how to structure recruiting content and what to practice - "
        "grounded in genuinely common recruiting patterns for their sport and level, not generic motivational "
        "advice. Do NOT claim to know what any specific named coach, program, or scout individually wants - "
        "frame everything as what is COMMONLY evaluated by recruiters/scouts at this level, since that's "
        "real, honest knowledge, not a claim about a specific person's preferences.\n\n"
        "Return a JSON object with exactly these four keys:\n"
        "- reel_structure: an array of 4-6 short strings, each describing one segment of a highlight reel in "
        "order (e.g. 'Open with your fastest recorded time or most explosive play - recruiters often stop "
        "watching in the first 10 seconds if it doesn't grab attention'). Be specific to this sport and "
        "position/role, not generic ('show your best plays').\n"
        "- commonly_evaluated: an array of 4-6 objects, each with 'skill_or_metric' (a specific thing "
        "commonly evaluated for this sport/level, e.g. '40-yard dash time', 'first-step quickness on "
        "defense') and 'why' (1 sentence on why recruiters at this level commonly weight it)\n"
        "- drills_to_practice: an array of 3-5 specific, real drills or practice routines relevant to "
        "closing the gap between their current level and their target level - name real, standard drills "
        "for this sport, not vague advice\n"
        "- content_checklist: an array of 3-4 concrete, practical dos for filming/presenting content (e.g. "
        "camera angle, what footage to prioritize keeping, length) - specific to this sport\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)
 
 
def research_target_program(anthropic_client, sport: str, level: str, program_name: str) -> dict:
    """Uses Claude's real web search tool to find and cite current,
    public information about a specific named program - what they
    say they're looking for, recent recruiting classes, coaching
    staff, roster needs. Returns what was actually found, and says so
    plainly if search doesn't surface anything specific - this does
    not fill gaps with invented detail.
    """
    prompt = (
        f"Search for real, current, publicly available information about the {sport} program at "
        f"\"{program_name}\" that would help a {level}-level recruit understand what this specific "
        "program looks for - their official recruiting/roster page, public statements from coaching "
        "staff about what they value, their recent recruiting classes, team needs by position, or "
        "similar. \n\n"
        "Report ONLY what you actually find through search - do not fill in gaps with generic assumptions "
        "about the sport in general, and do not invent specific claims about this program that search "
        "doesn't support. If you can't find anything specific and current about this program, say that "
        "plainly rather than guessing.\n\n"
        "Paraphrase what you find in your own words rather than quoting sources at length. Structure your "
        "answer as: what you found (with a brief note on where it came from), and then, only if genuinely "
        "supported by what you found, 2-3 concrete implications for how this recruit should tailor their "
        "content or approach to this specific program."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    findings = "".join(b.text for b in resp.content if b.type == "text").strip()
 
    # Surface which real sources were actually consulted, so the
    # person can verify this themselves rather than taking Claude's
    # synthesis on faith alone.
    sources = []
    for block in resp.content:
        if getattr(block, "type", None) == "web_search_tool_result":
            for item in getattr(block, "content", []) or []:
                url = getattr(item, "url", None)
                title = getattr(item, "title", None)
                if url:
                    sources.append({"url": url, "title": title or url})
 
    return {"program_name": program_name, "findings": findings, "sources": sources}
 
 
def draft_coach_outreach(anthropic_client, sport: str, level: str, career_direction: str, achievements: str, target_description: str) -> dict:
    """Drafts both an email and a cold-call script for reaching a
    coach or staff member. Same honest boundary as the candidate-side
    connection strategy: never invents a specific named person, only
    describes the TYPE of contact and gives real, usable scripts.
    """
    direction_label = {
        "play-college": "playing at the college level",
        "go-pro": "going pro",
        "coach": "coaching",
        "sports-management": "a sports management career",
    }.get(career_direction, career_direction)
 
    prompt = (
        f"A student-athlete: sport \"{sport}\", level {level}, career direction: {direction_label}. "
        f"Achievements: \"{achievements}\". They want to reach out about: \"{target_description}\".\n\n"
        "Help them make direct contact. Never invent a specific real named person - describe the TYPE of "
        "contact to look for, not a fabricated name.\n\n"
        "Return a JSON object with exactly these five keys:\n"
        "- who_to_contact: the specific type of person worth reaching out to (e.g. 'the assistant coach "
        "responsible for recruiting at their position/event', or 'the program's recruiting coordinator')\n"
        "- how_to_find: 1-2 concrete sentences on how to actually find that person - a real search approach, "
        "not 'network more'\n"
        "- email_subject: a short, specific email subject line\n"
        "- email_body: a genuine, specific 100-140 word email referencing their actual sport, achievements, "
        "and goal - no generic filler, no placeholder brackets\n"
        "- cold_call_script: a real, specific phone call opening and structure (2-3 sentences of what to "
        "actually say when the person picks up, plus 1-2 follow-up talking points) - written for someone "
        "who has never cold-called before, concrete and usable, not generic 'be confident' advice\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)
 
 
def generate_clip_edit_plan(anthropic_client, sport: str, level: str, career_direction: str, clips_description: str) -> dict:
    """Honest scope note: this does not edit or process any real video
    file - there is no video hosting or editing infrastructure
    connected anywhere in this stack. What this gives is a real,
    specific EDIT PLAN grounded in the athlete's own description of
    their actual raw footage - which clips to use, in what order,
    how to trim them, and what to caption - for them to execute in
    whatever video editor they already use.
    """
    direction_label = {
        "play-college": "playing at the college level",
        "go-pro": "going pro",
        "coach": "coaching",
        "sports-management": "a sports management career",
    }.get(career_direction, career_direction)
 
    prompt = (
        f"A student-athlete: sport \"{sport}\", level {level}, career direction: {direction_label}.\n\n"
        f"They described their available raw footage/clips as:\n\"{clips_description}\"\n\n"
        "Give them a real, specific edit plan for turning this into a strong highlight reel - based ONLY "
        "on the clips they actually described, not invented footage. If what they described is too thin "
        "to make a strong reel, say so honestly rather than pretending it's enough.\n\n"
        "Return a JSON object with exactly these three keys:\n"
        "- edit_sequence: an array of objects, each with 'clip' (which described clip/moment this refers "
        "to, by their own description) and 'instruction' (specific guidance: where to trim it, how long "
        "to hold it, what to lead into next, and why it goes in this position)\n"
        "- captions: an array of 2-4 short on-screen text suggestions tied to specific clips (e.g. a stat, "
        "a title card idea) - concrete, not generic\n"
        "- honest_assessment: 1-2 sentences on whether what they described is actually enough for a strong "
        "reel, and if not, what specific kind of footage they're missing\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)
 
