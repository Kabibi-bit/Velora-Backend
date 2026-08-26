"""Real, live web research grounded in the candidate's actual
situation - not a generic score, not invented knowledge. Two things
no mainstream job board does:
 
1. research_company() - gives Claude real web search to find and cite
   current, public information about a SPECIFIC company before the
   person applies. Same honest pattern as the athletics program
   research: report only what's actually found, say plainly when
   nothing specific turns up.
 
2. generate_interview_prep() - once someone has a real interview, this
   stitches together the company research, the actual role, and the
   person's own roadmap into a genuine prep brief - not generic
   "tell me about yourself" advice.
"""
 
 
def research_company(anthropic_client, company_name: str, role_title: str) -> dict:
    prompt = (
        f"Search for real, current, publicly available information about \"{company_name}\" that would "
        f"help someone preparing to apply for or interview for a \"{role_title}\" role there - what the "
        "company says about itself, recent news, their stated values or mission, size and stage, and "
        "anything publicly discussed about their interview process or culture.\n\n"
        "Report ONLY what you actually find through search - do not fill in gaps with generic assumptions "
        "about companies of this type in general, and do not invent specific claims this company doesn't "
        "support. If you can't find anything specific and current, say that plainly rather than guessing.\n\n"
        "Paraphrase what you find in your own words rather than quoting sources at length. Structure your "
        "answer as: what you found, and then 2-3 concrete implications for how this candidate should "
        "position themselves for this specific company and role."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    findings = "".join(b.text for b in resp.content if b.type == "text").strip()
 
    sources = []
    for block in resp.content:
        if getattr(block, "type", None) == "web_search_tool_result":
            for item in getattr(block, "content", []) or []:
                url = getattr(item, "url", None)
                title = getattr(item, "title", None)
                if url:
                    sources.append({"url": url, "title": title or url})
 
    return {"company_name": company_name, "findings": findings, "sources": sources}
 
 
def generate_interview_prep(anthropic_client, company_name: str, role_title: str, company_research: str | None, profile: dict, roadmap_summary: str | None) -> dict:
    research_line = (
        f"Real research on this company: \"{company_research}\"\n\n"
        if company_research else
        "No company research has been done yet for this one - work from the role and candidate's "
        "background only, and don't invent specifics about the company.\n\n"
    )
    prompt = (
        f"A candidate has a real interview for \"{role_title}\" at \"{company_name}\".\n\n"
        f"{research_line}"
        f"Their stated goal: \"{profile.get('northstar','')}\". Skills: \"{profile.get('skills','')}\". "
        f"Their roadmap strategy: \"{roadmap_summary or 'no roadmap yet'}\".\n\n"
        "Generate a real, specific interview prep brief - grounded in what's actually known about this "
        "role and candidate, not generic interview advice.\n\n"
        "Return a JSON object with exactly these four keys:\n"
        "- likely_questions: an array of 3-4 specific questions this candidate should genuinely expect "
        "for this role, each with a 1-sentence note on what a strong answer would actually demonstrate\n"
        "- talking_points: an array of 3-4 specific things from THIS candidate's real background "
        "(reference their actual stated skills/goal) that are worth emphasizing for this specific role\n"
        "- questions_to_ask: an array of 2-3 real, specific questions this candidate should ask the "
        "interviewer - not generic ('what's the culture like'), grounded in the actual role or company "
        "research if available\n"
        "- roadmap_connection: 1-2 sentences on how this specific interview connects to the candidate's "
        "actual roadmap - what it would mean for their plan if it goes well\n\n"
        "Return ONLY valid JSON, nothing else, no markdown fences, no commentary."
    )
    resp = anthropic_client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)
 
