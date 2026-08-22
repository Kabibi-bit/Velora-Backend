"""Generates a career roadmap from a user's profile using Claude,
and explains how a specific listing fits into that roadmap.
This is what makes recommendations tie back to the long-term goal,
not just today's keyword match.
"""
import json
 
 
def generate_roadmap(anthropic_client, profile: dict) -> list[dict]:
    """Produces 3-5 ordered milestones from stated goal to timeframe.
    Returns a list of dicts: [{"title": ..., "description": ..., "stage": 1}, ...]
    """
    prompt = (
        f"A person's long-term career goal: \"{profile['northstar']}\"\n"
        f"What 'made it' looks like to them: \"{profile.get('final_idea', '')}\"\n"
        f"Their timeframe: {profile.get('timeframe', 'unspecified')}\n"
        f"Current stage: {profile.get('stage', 'unspecified')}\n"
        f"Current skills: \"{profile.get('skills', '')}\"\n\n"
        "Generate 3-5 ordered milestones forming a realistic roadmap from "
        "where they are now to that goal. Return ONLY valid JSON, an array "
        "of objects with 'title', 'description', and 'stage' (1, 2, 3...) "
        "keys, nothing else, no markdown fences."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
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
    roadmap_text = "\n".join(f"{m['stage']}. {m['title']}: {m['description']}" for m in roadmap)
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
 
