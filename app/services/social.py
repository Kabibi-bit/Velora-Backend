"""Waypoint: a private progress journal, not a social feed.
 
This used to include connection suggestions and a cross-user feed
ranked by goal relevance. That was cut deliberately: a feed and a
connection system only have real value once there are enough real
users for either to mean something, and a connection feature between
real people carries a genuine moderation/safety workload (spam, fake
profiles, harassment, abuse reports) that isn't worth taking on for a
feature with no real users behind it yet. What's left is the one part
that has real value on day one with a single user: journaling real
progress against real roadmap stages, with an honest AI reflection on
each entry.
"""
 
 
def reflect_on_journal_entry(anthropic_client, profile: dict, roadmap_summary: str, entry_body: str, roadmap_stage_title: str | None) -> str:
    """A real, specific reflection on the user's own journal entry,
    grounded in their actual goal and roadmap - not generic
    encouragement.
    """
    stage_line = f"They tagged this entry to their roadmap stage: \"{roadmap_stage_title}\".\n" if roadmap_stage_title else ""
    prompt = (
        f"A person's goal: \"{profile.get('northstar','')}\". Their roadmap strategy: \"{roadmap_summary or 'no roadmap yet'}\".\n"
        f"{stage_line}\n"
        f"A journal entry they just wrote about their progress:\n\"{entry_body}\"\n\n"
        "In 2-3 sentences, give an honest, specific reflection - does this genuinely represent progress "
        "toward their stated goal, is there a real risk or blind spot worth naming, or a concrete next "
        "step implied by what they wrote? Reference their actual goal or roadmap stage by name. Avoid "
        "generic encouragement like 'great job' or 'keep it up' - be specific or say nothing complimentary at all."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
 
