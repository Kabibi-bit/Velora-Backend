"""Recruiting content guidance for student-athletes: how to structure
a highlight reel, and which drills/metrics are commonly evaluated for
their specific sport, level, and career direction.
 
Honest boundary: this never claims to know what a specific NAMED coach
or program individually wants - there's no data source with that, and
claiming otherwise would be fabricating knowledge that doesn't exist.
What it gives is real, grounded general guidance - the kind an
experienced recruiting coordinator would give about what's commonly
evaluated at a given level, not mind-reading a specific person.
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
 
