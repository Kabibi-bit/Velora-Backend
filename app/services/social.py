"""The mechanism that's supposed to make this genuinely different from
LinkedIn, not just a smaller copy of it: nothing here is ranked by
likes, impressions, or a generic engagement algorithm. Posts and
suggested connections are ranked by how relevant they actually are to
the viewer's stated goal and current roadmap - and that reasoning is
shown to the viewer, not hidden behind a black-box feed.
 
Two layers, same pattern used everywhere else in this app:
1. A free, instant heuristic (tag/keyword overlap) used to RANK every
   post and every suggested connection - this runs on every feed load
   with no AI cost.
2. An on-demand, real Claude call for a genuine written explanation of
   why a specific post or person matters to the viewer - only fired
   when the viewer actually asks, not automatically for everything in
   the feed (same cost-conscious pattern as the rest of the app).
"""
import re
 
 
def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z\-]{2,}", (text or "").lower())
 
 
def compute_post_relevance_heuristic(viewer_profile: dict, post_body: str, author_profile: dict) -> dict:
    """Free, instant ranking signal for the feed. Returns a score and
    a short list of matched terms, used both for sort order and for
    a visible 'why this is showing you' tag on every post.
    """
    viewer_tokens = set(tokenize(viewer_profile.get("northstar", "")) + tokenize(viewer_profile.get("skills", "")))
    post_tokens = set(tokenize(post_body))
    author_tokens = set(tokenize(author_profile.get("northstar", "")))
 
    matched_topic = viewer_tokens & post_tokens
    matched_goal = viewer_tokens & author_tokens
 
    score = len(matched_topic) * 3 + len(matched_goal) * 2
    return {
        "score": score,
        "matched_topic_terms": sorted(matched_topic)[:4],
        "same_goal_direction": len(matched_goal) > 0,
    }
 
 
def compute_connection_relevance_heuristic(viewer_profile: dict, target_profile: dict) -> dict:
    """Free, instant ranking signal for suggested connections."""
    viewer_tokens = set(tokenize(viewer_profile.get("northstar", "")) + tokenize(viewer_profile.get("skills", "")))
    target_tokens = set(tokenize(target_profile.get("northstar", "")) + tokenize(target_profile.get("skills", "")))
    overlap = viewer_tokens & target_tokens
    score = len(overlap) * 2
    stage_diff = None
    if viewer_profile.get("stage") and target_profile.get("stage"):
        stage_diff = "similar_stage" if viewer_profile["stage"] == target_profile["stage"] else "different_stage"
    return {"score": score, "matched_terms": sorted(overlap)[:5], "stage_relation": stage_diff}
 
 
def explain_post_relevance_deep(anthropic_client, viewer_profile: dict, viewer_roadmap_summary: str, post_body: str, author_profile: dict) -> str:
    """On-demand, real AI explanation of why a specific post matters to
    THIS viewer's specific roadmap - the actual differentiator vs a
    generic 'people also liked' feed.
    """
    prompt = (
        f"A person's goal: \"{viewer_profile.get('northstar','')}\". Their roadmap strategy: \"{viewer_roadmap_summary or 'no roadmap yet'}\".\n\n"
        f"A post from someone else on the platform, whose stated goal is \"{author_profile.get('northstar','')}\":\n\"{post_body}\"\n\n"
        "In 2-3 sentences, explain honestly whether and why this post is actually relevant to the "
        "viewer's specific goal and roadmap - reference their real roadmap stage or goal by name. "
        "If it's not genuinely relevant, say so plainly rather than forcing a connection."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
 
 
def explain_connection_relevance_deep(anthropic_client, viewer_profile: dict, target_profile: dict) -> str:
    """On-demand, real AI explanation of why connecting with a specific
    person could genuinely help the viewer's roadmap - not a generic
    'grow your network' nudge.
    """
    prompt = (
        f"Person A's goal: \"{viewer_profile.get('northstar','')}\". Skills: \"{viewer_profile.get('skills','')}\". Stage: {viewer_profile.get('stage','unspecified')}.\n"
        f"Person B's goal: \"{target_profile.get('northstar','')}\". Skills: \"{target_profile.get('skills','')}\". Stage: {target_profile.get('stage','unspecified')}.\n\n"
        "In 2-3 sentences, give Person A an honest, specific reason (or lack of one) to connect with "
        "Person B - reference their actual stated goals and skills. If the overlap is weak, say so "
        "rather than manufacturing a reason."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
 
