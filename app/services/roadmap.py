"""Generates a real career roadmap from a user's profile using Claude,
and explains how a specific listing fits into that roadmap. Each
milestone includes success criteria, a timeframe, and a literal first
action to take today -- this is what turns it from generic career
advice into an actual plan someone can start on immediately.
"""
import json
 
 
def generate_roadmap(anthropic_client, profile: dict, skill_gaps: list[str] | None = None) -> list[dict]:
    """Produces 4-6 ordered milestones from where the person is now to
    their stated goal. Returns a list of dicts with 'title',
    'description', 'success_criteria', 'estimated_timeframe',
    'first_action', and 'stage' (1, 2, 3...) keys.
    """
    gap_line = (
        f"Skills that show up often in listings that match their goal, but aren't in their stated skills yet: {', '.join(skill_gaps)}.\n"
        if skill_gaps else ""
    )
    prompt = (
        f"A person's long-term career goal: \"{profile['northstar']}\"\n"
        f"What 'made it' looks like to them, concretely: \"{profile.get('final_idea', '')}\"\n"
        f"Their timeframe: {profile.get('timeframe', 'unspecified')}\n"
        f"Current stage: {profile.get('stage', 'unspecified')}\n"
        f"Current skills: \"{profile.get('skills', '')}\"\n"
        f"What matters most to them: {', '.join(profile.get('priorities', []))}\n"
        f"{gap_line}\n"
        "Generate 4-6 ordered milestones forming a REAL, actionable roadmap "
        "from where they are now to that goal.\n\n"
        "BANNED as too vague, do not use language like this anywhere: "
        "'build skills', 'gain experience', 'network more', 'improve your "
        "profile', 'stay consistent', 'work hard', or any milestone that "
        "doesn't name a specific artifact, action, or outcome. If a "
        "milestone could apply to literally any career goal, rewrite it "
        "until it could only apply to THIS person's specific goal.\n\n"
        "For each milestone, include exactly these five keys:\n"
        "- title: a concrete action naming a real artifact or outcome "
        "(e.g. 'Ship a SQL-based analytics project using a real public "
        "dataset', not 'Build skills')\n"
        "- description: 1-2 sentences on exactly what to do and why it "
        "matters for THIS person's specific goal - reference their actual "
        "stated goal or skills by name, don't write something generic "
        "that could apply to anyone\n"
        "- success_criteria: a specific, checkable outcome someone else "
        "could verify - not a feeling of readiness (e.g. 'you have a "
        "live link you'd send a stranger', not 'you feel confident')\n"
        "- estimated_timeframe: a realistic duration for this one step "
        "(e.g. '2-3 weeks', '1-2 months')\n"
        "- first_action: the literal, physical first thing to do TODAY "
        "to start this milestone - specific enough that someone could "
        "do it in the next hour, not 'start researching'\n"
        "- stage: the order number, starting at 1\n\n"
        "If skill gaps were listed above, at least one milestone must "
        "directly address closing one of them by name. Return ONLY valid "
        "JSON, an array of objects with exactly those six keys, nothing "
        "else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)
 
 
def explain_listing_against_roadmap(anthropic_client, listing: dict, roadmap: list[dict], profile: dict) -> str:
    """Given a listing and the user's roadmap, explains in plain language
    which milestone(s) this listing advances, and why -- the actual
    'compares to your roadmap' feature.
    """
    roadmap_text = "\n".join(
        f"{m['stage']}. {m['title']}: {m['description']} (done when: {m.get('success_criteria', 'n/a')})"
        for m in roadmap
    )
    prompt = (
        f"User's roadmap toward their goal (\"{profile['northstar']}\"):\n{roadmap_text}\n\n"
        f"A listing they're considering: \"{listing['title']}\" at {listing['org']} "
        f"({listing['type']}), tags: {', '.join(listing.get('tags', []))}.\n\n"
        "In 1-2 sentences, explain which roadmap stage this listing advances "
        "and why, or state plainly if it doesn't fit the roadmap well. Be "
        "direct and concrete, no filler."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
 
