"""School knowledge base + admissions-advice tailoring.
 
The backend mirror of the frontend school KB (velora/state.js). Holds the
curated, source-verified profiles for the US T30 + top UK universities -
each with its real motto, what it values, tailored guidance, and a
"what accepted students actually did" pattern - plus the logic that
tailors advice to a student's specific target schools.
 
Honesty rules carried over from the frontend, deliberately:
- Data is curated and source-verified, NOT generated per-request, so
  there are no hallucinated mottos, acceptance rates, or admit patterns.
- UK schools use the real UK course-specific academic model, which is
  genuinely different from the US holistic model - never a US copy.
- Nothing here promises admission; guidance is school-general and honest.
- Schools NOT in this curated set get an explicit "general guidance"
  fallback rather than fabricated school-specific claims.
 
Keep this file in sync with velora/state.js SCHOOLS. If you change one,
change the other - a drift test in the test suite guards this.
"""
 
SCHOOLS = [
    {
        "name": "Harvard University",
        "aka": [
            "harvard"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~3.6%",
        "region": "Cambridge, MA",
        "dataDepth": "deep",
        "motto": "\"Veritas\" — Latin for \"truth.\" Harvard's mission is to educate citizens and citizen-leaders through a transformative liberal-arts education.",
        "values": [
            "intellectual vitality",
            "a genuine spike",
            "impact on others",
            "authentic voice"
        ],
        "guidance": "Harvard rejects the vast majority of valedictorians - grades and scores get you considered, not admitted. What separates admits is a genuine, deep \"spike\" (a demonstrated, exceptional strength in one area) plus evidence you affect the people around you. Its motto \"Veritas\" rewards intellectual honesty and real curiosity - reference the value through your own experience, never by name-dropping.",
        "acceptedPattern": "Public analyses of admitted students consistently show a clear spike, usually built from extracurriculars and honors rather than coursework - e.g. an admit who progressed over four years from environmental-club member to regional coordinator, showing rising responsibility and measurable impact. The recurring pattern: sustained depth in one or two things, framed around real, quantifiable change - not a long list of shallow memberships."
    },
    {
        "name": "Stanford University",
        "aka": [
            "stanford"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "Stanford, CA",
        "dataDepth": "deep",
        "motto": "\"Die Luft der Freiheit weht\" — German for \"the wind of freedom blows,\" chosen to enshrine fearless, unfettered inquiry (\"studies blossom and the minds move\").",
        "values": [
            "intellectual vitality",
            "initiative",
            "a distinctive angle",
            "building things"
        ],
        "guidance": "Stanford prizes intellectual curiosity for its own sake and students who build or start things - its \"intellectual vitality\" essay directly probes this. The motto reflects a culture of fearless inquiry, so a self-started project or genuine intellectual obsession reads far stronger than a prestigious-but-passive membership.",
        "acceptedPattern": "Admitted profiles tend to show a distinctive personal angle - the \"what makes you, you\" - and evidence of self-directed initiative (a founded project, a curiosity taken further than assigned). Depth and an authentic, specific essay voice recur far more than a broad resume."
    },
    {
        "name": "Massachusetts Institute of Technology (MIT)",
        "aka": [
            "mit",
            "massachusetts institute of technology"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "Cambridge, MA",
        "dataDepth": "deep",
        "motto": "\"Mens et Manus\" — Latin for \"Mind and Hand.\" MIT's founding ideal is education for practical application: learning by doing, theory joined to making.",
        "values": [
            "hands-on making",
            "STEM depth",
            "collaboration",
            "using knowledge for good"
        ],
        "guidance": "MIT wants makers, not just high scorers. Its motto \"Mens et Manus\" (Mind and Hand) means concrete evidence you build, tinker, and solve real problems is what tips an application. MIT genuinely values collaboration over competition (\"you cannot graduate from MIT by yourself\") - show teamwork and mutual support, not just individual wins.",
        "acceptedPattern": "By MIT's own admissions materials and analyses of admitted profiles, the Maker Portfolio is often the real tie-breaker: admitted students show \"the stuff they have built\" - a coded app on GitHub, a robotics project, a restored engine, a hackathon build, or olympiad/research work with genuine hands-on depth. Building something tangible beats winning a generic award."
    },
    {
        "name": "California Institute of Technology (Caltech)",
        "aka": [
            "caltech",
            "california institute of technology"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~3.8%",
        "region": "Pasadena, CA",
        "dataDepth": "deep",
        "motto": "\"The truth shall make you free\" (Veritas vos liberabit). Caltech is a tiny, intensely rigorous science-and-engineering institute (~2,200 students).",
        "values": [
            "capacity for rigor",
            "scholarly character",
            "deep STEM ability",
            "lifting up peers"
        ],
        "guidance": "Caltech is uniquely, unapologetically about raw scientific and mathematical ability at an extreme level. Its own admissions site names three qualities: capacity for Caltech rigor, scholarly character (integrity, resilience, generosity), and readiness to thrive in a brutally fast pace. Deep math/science preparation and genuine research or problem-solving matter more here than a well-rounded profile.",
        "acceptedPattern": "Admits show exceptional depth in advanced math and science - olympiads, serious research, self-driven technical work - and, per Caltech, \"elevate the people learning alongside them.\" It is one of the few top schools where pure STEM firepower and scholarly character outweigh breadth of activities."
    },
    {
        "name": "Princeton University",
        "aka": [
            "princeton"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "Princeton, NJ",
        "dataDepth": "deep",
        "motto": "\"Dei sub numine viget\" — \"Under God's power she flourishes,\" paired with the informal ethos \"in the nation's service and the service of humanity.\"",
        "values": [
            "scholarship",
            "service",
            "intellectual depth",
            "writing"
        ],
        "guidance": "Princeton has a strong undergraduate focus and service ethos. It weighs intellectual depth and strong writing heavily - the graded written paper it requests is read seriously. Sustained scholarship and genuine service commitments matter more than breadth.",
        "acceptedPattern": "Admitted students commonly pair real intellectual depth (research, a scholarly pursuit) with authentic, sustained service - and write exceptionally well. Because Princeton reads a graded academic paper, demonstrated writing quality is a recurring differentiator."
    },
    {
        "name": "Yale University",
        "aka": [
            "yale"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "New Haven, CT",
        "dataDepth": "deep",
        "motto": "\"Lux et Veritas\" — Latin for \"Light and Truth.\"",
        "values": [
            "intellectual engagement",
            "community impact",
            "distinctive voice",
            "the arts and humanities"
        ],
        "guidance": "Yale reads for how you engage ideas and community - it famously weighs \"what you'll bring to the residential college.\" A distinctive essay voice and genuine engagement (including arts and humanities, which Yale values strongly) stand out more than a purely stats-driven profile.",
        "acceptedPattern": "Admitted profiles often show a person who visibly contributes to a community and brings a distinctive voice - Yale wants to picture what you add to residential-college life. Engagement and character recur as much as raw achievement."
    },
    {
        "name": "University of Pennsylvania (UPenn)",
        "aka": [
            "upenn",
            "penn",
            "university of pennsylvania"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~6%",
        "region": "Philadelphia, PA",
        "dataDepth": "deep",
        "motto": "\"Leges sine moribus vanae\" — \"Laws without morals are in vain,\" reflecting Benjamin Franklin's founding emphasis on practical, ethical purpose.",
        "values": [
            "pre-professional focus",
            "a specific \"why Penn\"",
            "interdisciplinary drive",
            "purpose"
        ],
        "guidance": "Penn is the most pre-professional Ivy and admits with real attention to fit with its specific schools (Wharton, Engineering, Nursing, CAS) and cross-disciplinary programs. A concrete, specific \"why Penn / why this program\" and evidence you'll use your education purposefully read very well.",
        "acceptedPattern": "Admits typically show a focused direction that maps onto a specific Penn school or program, plus a clear, researched reason for Penn specifically - not a generic Ivy application. Demonstrated purpose and pre-professional initiative recur."
    },
    {
        "name": "Columbia University",
        "aka": [
            "columbia"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~4%",
        "region": "New York, NY",
        "dataDepth": "deep",
        "motto": "\"In lumine Tuo videbimus lumen\" — \"In Thy light shall we see light.\"",
        "values": [
            "intellectual breadth",
            "the Core Curriculum",
            "engagement with NYC",
            "ideas across disciplines"
        ],
        "guidance": "Columbia's famous Core Curriculum means it looks for genuine intellectual breadth and love of big ideas across disciplines, plus students who will engage with New York City. Its distinctive \"list\" supplements (books, media you enjoy) reward authentic intellectual curiosity, not a curated performance.",
        "acceptedPattern": "Admits show wide-ranging intellectual curiosity and specific, honest engagement with ideas (and the city) - the Core rewards thinkers comfortable across the humanities and sciences, not just single-track specialists."
    },
    {
        "name": "Brown University",
        "aka": [
            "brown"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5%",
        "region": "Providence, RI",
        "dataDepth": "deep",
        "motto": "\"In Deo Speramus\" — \"In God we hope.\" Brown is known for its Open Curriculum (no core requirements).",
        "values": [
            "intellectual self-direction",
            "curiosity",
            "fit with the Open Curriculum",
            "initiative"
        ],
        "guidance": "Brown's Open Curriculum means it specifically seeks self-directed students who thrive without a rigid structure. Show intellectual independence and a clear sense of what you'd do with that freedom - a student who needs to be told what to study is a poor fit, and Brown's essays test exactly this.",
        "acceptedPattern": "Admits demonstrate genuine intellectual self-direction - self-designed projects, unusual course combinations, pursuits driven by their own curiosity. A convincing account of why the Open Curriculum fits how you learn recurs strongly."
    },
    {
        "name": "Dartmouth College",
        "aka": [
            "dartmouth"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5.3%",
        "region": "Hanover, NH",
        "dataDepth": "deep",
        "motto": "\"Vox clamantis in deserto\" — \"A voice crying out in the wilderness.\" Dartmouth is the smallest, most undergraduate-focused Ivy.",
        "values": [
            "undergraduate focus",
            "community",
            "a bold, independent voice",
            "engagement with a tight-knit campus"
        ],
        "guidance": "Dartmouth prizes undergraduate teaching and a close community, so it reads for students who will actively contribute to a small, tight-knit campus. A bold, authentic voice and evidence you engage deeply with people and place fit its \"voice in the wilderness\" identity.",
        "acceptedPattern": "Admits often show genuine community contribution and a distinctive, independent voice - Dartmouth wants people who will show up for a small campus, not just excel in isolation."
    },
    {
        "name": "Duke University",
        "aka": [
            "duke"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~6%",
        "region": "Durham, NC",
        "dataDepth": "deep",
        "motto": "\"Eruditio et Religio\" — \"Knowledge and Faith.\"",
        "values": [
            "ambition with balance",
            "collaboration",
            "breadth and depth",
            "real-world application"
        ],
        "guidance": "Duke looks for high-achieving students who combine serious ambition with collaboration and range (it prizes both intellectual and, often, athletic/extracurricular energy). A specific \"why Duke\" and evidence of applying your interests in the real world read well.",
        "acceptedPattern": "Admits tend to pair strong academics with genuine collaborative leadership and applied impact - the recurring theme is ambition balanced with contribution to a team or community, not solo achievement alone."
    },
    {
        "name": "Johns Hopkins University",
        "aka": [
            "johns hopkins",
            "jhu",
            "hopkins"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~6%",
        "region": "Baltimore, MD",
        "dataDepth": "deep",
        "motto": "\"Veritas vos liberabit\" — \"The truth shall set you free.\" America's first research university.",
        "values": [
            "research",
            "collaboration",
            "hands-on inquiry",
            "depth in a field"
        ],
        "guidance": "Hopkins, the original US research university, explicitly values students who do real research and collaborate. It is especially strong in the sciences and medicine, and its essays reward concrete evidence of inquiry and teamwork over polished generalities.",
        "acceptedPattern": "Admits frequently show genuine research or hands-on inquiry (labs, independent projects) and collaborative work - Hopkins publicly emphasizes collaboration over competition, and that shows up in who gets in."
    },
    {
        "name": "Northwestern University",
        "aka": [
            "northwestern"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~7%",
        "region": "Evanston, IL",
        "dataDepth": "deep",
        "motto": "\"Quaecumque sunt vera\" — \"Whatsoever things are true.\"",
        "values": [
            "a specific \"why Northwestern\"",
            "interdisciplinary interests",
            "balance of academics and passions",
            "fit"
        ],
        "guidance": "Northwestern weighs demonstrated interest and fit heavily, and its \"Why Northwestern\" essay is genuinely important - it wants students who have researched its specific programs (journalism, engineering, theatre, its quarter system). Balanced, cross-disciplinary students who can name exactly why Northwestern do well.",
        "acceptedPattern": "Admits show a well-researched, specific fit with Northwestern's programs and culture, plus a balance of academic strength and real passions. Generic applications fare worse; specificity recurs among those admitted."
    },
    {
        "name": "University of Chicago",
        "aka": [
            "uchicago",
            "university of chicago",
            "u chicago"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5%",
        "region": "Chicago, IL",
        "dataDepth": "deep",
        "motto": "\"Crescat scientia; vita excolatur\" — \"Let knowledge grow from more to more; and so be human life enriched.\"",
        "values": [
            "intellectual playfulness",
            "rigor for its own sake",
            "original thinking",
            "loving ideas"
        ],
        "guidance": "UChicago is famous for its quirky, open-ended essay prompts that test genuine intellectual playfulness and original thinking - \"the life of the mind\" is its whole identity. It rewards students who love ideas for their own sake and can think unconventionally, not resume-optimizers.",
        "acceptedPattern": "Admits consistently show intellectual originality and a real delight in ideas - the standout essays take an unusual prompt somewhere genuinely creative and rigorous. Loving the thinking itself, visibly, is the recurring signal."
    },
    {
        "name": "Cornell University",
        "aka": [
            "cornell"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~7%",
        "region": "Ithaca, NY",
        "dataDepth": "deep",
        "motto": "\"I would found an institution where any person can find instruction in any study.\" — Ezra Cornell.",
        "values": [
            "fit with a specific college",
            "breadth of access",
            "applied and practical study",
            "a clear academic direction"
        ],
        "guidance": "Cornell admits by specific college (Engineering, Arts & Sciences, CALS, Hotel, ILR, etc.), each with its own priorities, so fit with your chosen college and a clear \"why this college/major\" is central. Its \"any person, any study\" ethos values applied, practical study alongside theory.",
        "acceptedPattern": "Admits show a clear academic direction that genuinely matches their chosen Cornell college, with evidence of engagement in that specific field - the per-college structure makes focused, well-matched applications recur among those admitted."
    },
    {
        "name": "Rice University",
        "aka": [
            "rice"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~8%",
        "region": "Houston, TX",
        "dataDepth": "deep",
        "motto": "\"Letters, Science, Art.\" Rice is small, collaborative, and known for its residential-college culture.",
        "values": [
            "collaboration",
            "fit with the residential-college culture",
            "depth in a field",
            "a distinctive perspective"
        ],
        "guidance": "Rice is small and collaborative, with a strong residential-college system and a famous supplemental question (\"what perspective would you add?\"). It reads for students who will add something distinctive to a tight community and go deep in their field.",
        "acceptedPattern": "Admits show real depth in an area plus a genuine, specific sense of what they'd contribute to Rice's collaborative community - the recurring theme is distinctive perspective and fit, not just stats."
    },
    {
        "name": "Vanderbilt University",
        "aka": [
            "vanderbilt",
            "vandy"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~5%",
        "region": "Nashville, TN",
        "dataDepth": "deep",
        "motto": "\"Crescere Aude\" — \"Dare to grow.\"",
        "values": [
            "leadership",
            "collaboration",
            "ambition with balance",
            "contribution to community"
        ],
        "guidance": "Vanderbilt (among the most selective now) looks for high-achieving students with real leadership and a collaborative, community-minded streak. Its \"dare to grow\" ethos rewards evidence of stretching yourself and lifting others, alongside strong academics.",
        "acceptedPattern": "Admits pair strong academics with demonstrated leadership and community contribution - growth, initiative, and helping others recur alongside raw achievement."
    },
    {
        "name": "University of Notre Dame",
        "aka": [
            "notre dame",
            "nd"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~9%",
        "region": "Notre Dame, IN",
        "dataDepth": "deep",
        "motto": "\"Vita, Dulcedo, Spes\" — \"Life, Sweetness, Hope.\" A Catholic university with a strong service and community identity.",
        "values": [
            "service",
            "character and values",
            "community",
            "a sense of purpose"
        ],
        "guidance": "Notre Dame has a distinctive Catholic mission and a strong service ethos, and it reads for character, values, and genuine community commitment alongside academics. Authentic service and a sense of purpose fit its identity - and its essays probe for exactly that.",
        "acceptedPattern": "Admits often show sustained, genuine service and a clear values-driven purpose, plus real community involvement - character and contribution recur strongly, consistent with its mission."
    },
    {
        "name": "Georgetown University",
        "aka": [
            "georgetown"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~12%",
        "region": "Washington, DC",
        "dataDepth": "deep",
        "motto": "\"Utraque Unum\" — \"Both into one.\" A Jesuit university strong in government, international affairs, and service.",
        "values": [
            "service (\"cura personalis\")",
            "engagement with the world",
            "intellectual seriousness",
            "purpose"
        ],
        "guidance": "Georgetown, Jesuit and DC-based, is strong in politics, international relations, and service, and its ethos \"cura personalis\" (care for the whole person) shapes what it seeks. It uses its own application (not the Common App) and values intellectual seriousness plus genuine engagement with the world.",
        "acceptedPattern": "Admits show real engagement with the world (service, politics, global issues) and intellectual seriousness - purpose and contribution recur, fitting its Jesuit, service-oriented mission."
    },
    {
        "name": "University of California, Berkeley",
        "aka": [
            "uc berkeley",
            "berkeley",
            "cal"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~11%",
        "region": "Berkeley, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A public research powerhouse.",
        "values": [
            "academic excellence",
            "overcoming challenges",
            "contribution to community",
            "the UC PIQs"
        ],
        "guidance": "Berkeley uses the UC application (no Common App essay) and its Personal Insight Questions carry real weight. It reads holistically with genuine attention to context and challenges overcome. For CS/engineering it is especially competitive - demonstrated rigor in your intended field matters.",
        "acceptedPattern": "Strong Personal Insight Question responses that show real contribution and growth in context recur among admits. Berkeley values demonstrated excellence within a student's own circumstances, not just absolute stats."
    },
    {
        "name": "University of California, Los Angeles (UCLA)",
        "aka": [
            "ucla",
            "uc los angeles"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~9%",
        "region": "Los Angeles, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" The most-applied-to university in the US.",
        "values": [
            "academic excellence",
            "the UC PIQs",
            "contribution and context",
            "breadth with depth"
        ],
        "guidance": "UCLA (UC application, PIQs matter) reads holistically with real attention to context and contribution. It is extremely competitive overall. Strong, specific Personal Insight Questions and demonstrated impact in your community stand out more than stats alone.",
        "acceptedPattern": "Like Berkeley, UCLA admits tend to show strong, specific Personal Insight Question responses and real community impact framed in the context of their own circumstances."
    },
    {
        "name": "University of Michigan",
        "aka": [
            "michigan",
            "umich",
            "university of michigan"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~18%",
        "region": "Ann Arbor, MI",
        "dataDepth": "deep",
        "motto": "\"Artes, Scientia, Veritas\" — \"Arts, Knowledge, Truth.\"",
        "values": [
            "academic rigor",
            "community contribution",
            "specific \"why Michigan\"",
            "leadership"
        ],
        "guidance": "Michigan values genuine \"why Michigan / why this community\" specificity and sustained contribution. It reads rigor in context. A thoughtful, specific supplemental essay and real depth in a couple of activities matter more than a generic strong-student profile.",
        "acceptedPattern": "A specific, well-researched \"why Michigan\" supplement and sustained depth in a few activities recur among admits far more than a generically strong record."
    },
    {
        "name": "University of North Carolina at Chapel Hill (UNC)",
        "aka": [
            "unc",
            "unc chapel hill",
            "north carolina"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~17%",
        "region": "Chapel Hill, NC",
        "dataDepth": "deep",
        "motto": "\"Lux Libertas\" — \"Light and Liberty.\" The oldest US public university.",
        "values": [
            "service and public good",
            "leadership",
            "contribution to community",
            "academic strength"
        ],
        "guidance": "UNC (much more selective for out-of-state applicants) has a strong public-service ethos and reads for leadership and community contribution alongside academics. Genuine service and a clear sense of contributing to the public good fit its identity.",
        "acceptedPattern": "Admits show academic strength plus real service and leadership - contribution to community recurs, consistent with UNC's public-good mission. Out-of-state admission is notably more competitive."
    },
    {
        "name": "Carnegie Mellon University",
        "aka": [
            "carnegie mellon",
            "cmu"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~11%",
        "region": "Pittsburgh, PA",
        "dataDepth": "deep",
        "motto": "\"My heart is in the work.\" — Andrew Carnegie.",
        "values": [
            "depth in the intended program",
            "a technical or artistic portfolio",
            "fit with the specific college",
            "rigor"
        ],
        "guidance": "CMU admits by specific college/program, so depth and fit with your exact intended field is central - a portfolio or concrete body of work (technical or artistic) is often what tips it. Its ethos \"my heart is in the work\" rewards visible dedication. Generalist profiles fare worse here than at more holistic schools; go deep in your lane.",
        "acceptedPattern": "Admits usually present a real body of work in their intended program - a portfolio, a technical project, an artistic reel - showing the dedication Carnegie's \"heart is in the work\" ethos points to."
    },
    {
        "name": "Emory University",
        "aka": [
            "emory"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~13%",
        "region": "Atlanta, GA",
        "dataDepth": "deep",
        "motto": "\"Cor prudentis possidebit scientiam\" — \"The wise heart seeks knowledge.\"",
        "values": [
            "intellectual curiosity",
            "service",
            "fit and demonstrated interest",
            "strength in the health sciences/humanities"
        ],
        "guidance": "Emory reads for genuine intellectual curiosity and demonstrated interest, and is especially strong for pre-med and the humanities. A specific \"why Emory\" and authentic engagement with your field read well; it values fit and character over pure prestige-chasing.",
        "acceptedPattern": "Admits show real curiosity and often service, with a specific reason for Emory - demonstrated interest and authentic fit recur alongside strong academics."
    },
    {
        "name": "University of Virginia (UVA)",
        "aka": [
            "uva",
            "university of virginia",
            "virginia"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~17%",
        "region": "Charlottesville, VA",
        "dataDepth": "deep",
        "motto": "Founded by Thomas Jefferson on ideals of self-governance and honor; known for its student-run Honor System.",
        "values": [
            "character and honor",
            "leadership",
            "community and self-governance",
            "academic strength"
        ],
        "guidance": "UVA (much more selective out-of-state) has a distinctive honor and student-self-governance culture, and reads for character, leadership, and community contribution. Its short, specific supplements reward authentic voice and a real sense of how you'd engage its community.",
        "acceptedPattern": "Admits pair academic strength with genuine leadership and character - contribution to community and a fit with UVA's honor culture recur, especially given how competitive out-of-state admission is."
    },
    {
        "name": "Washington University in St. Louis (WashU)",
        "aka": [
            "washu",
            "wustl",
            "washington university",
            "washington university in st louis"
        ],
        "country": "US",
        "tier": "reach",
        "accept": "~11%",
        "region": "St. Louis, MO",
        "dataDepth": "deep",
        "motto": "\"Per veritatem vis\" — \"Strength through truth.\"",
        "values": [
            "demonstrated interest",
            "academic depth",
            "collaboration",
            "fit"
        ],
        "guidance": "WashU weighs demonstrated interest meaningfully and is strong in the sciences, medicine, and business. A specific \"why WashU,\" genuine engagement, and real academic depth read well - it rewards students who clearly want WashU specifically.",
        "acceptedPattern": "Admits show strong academics plus clear, demonstrated interest and fit - a specific reason for WashU and authentic engagement recur among those admitted."
    },
    {
        "name": "University of Southern California (USC)",
        "aka": [
            "usc",
            "university of southern california",
            "southern cal"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~10%",
        "region": "Los Angeles, CA",
        "dataDepth": "deep",
        "motto": "\"Palmam qui meruit ferat\" — \"Let whoever earns the palm bear it.\"",
        "values": [
            "a distinctive talent or angle",
            "interdisciplinary drive",
            "fit with a specific school (film, business, engineering)",
            "initiative"
        ],
        "guidance": "USC is strong in film, business, engineering, and the arts, and admits with real attention to fit with its specific schools and to a distinctive talent or angle. A clear \"why this USC school\" and evidence of a genuine, developed passion read well.",
        "acceptedPattern": "Admits often show a distinctive, developed talent that maps onto a specific USC school, plus interdisciplinary energy - a clear angle and fit recur more than a generic strong profile."
    },
    {
        "name": "New York University (NYU)",
        "aka": [
            "nyu",
            "new york university"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~12%",
        "region": "New York, NY",
        "dataDepth": "deep",
        "motto": "\"Perstare et praestare\" — \"To persevere and to excel.\"",
        "values": [
            "genuine fit with NYU's global/urban identity",
            "demonstrated interest",
            "academic rigor"
        ],
        "guidance": "NYU reads for genuine fit with its urban, global identity and rewards demonstrated interest and a specific \"why NYU.\" It has no single \"type,\" but a clear reason you want NYU specifically (not just New York) and real depth in your field help a lot.",
        "acceptedPattern": "A convincing, specific \"why NYU\" (the programs, the global identity - not just the city) plus demonstrated interest recur among admits, alongside solid rigor in the intended field."
    },
    {
        "name": "Tufts University",
        "aka": [
            "tufts"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~10%",
        "region": "Medford, MA",
        "dataDepth": "deep",
        "motto": "\"Pax et Lux\" — \"Peace and Light.\" Known for its quirky, thoughtful supplemental essays.",
        "values": [
            "intellectual playfulness",
            "a distinctive voice",
            "fit and demonstrated interest",
            "global engagement"
        ],
        "guidance": "Tufts is known for creative, open-ended supplements that reward authentic voice and intellectual playfulness (its \"why Tufts\" and quirky prompts genuinely matter). It values students who are thoughtful, distinctive, and clearly want Tufts specifically.",
        "acceptedPattern": "Admits show a distinctive, genuine voice in the supplements and real fit with Tufts - the standout applications lean into the quirky prompts sincerely rather than playing it safe."
    },
    {
        "name": "Georgia Institute of Technology",
        "aka": [
            "georgia tech",
            "gatech",
            "georgia institute of technology"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~16%",
        "region": "Atlanta, GA",
        "dataDepth": "deep",
        "motto": "\"Progress and Service.\"",
        "values": [
            "STEM rigor",
            "hands-on projects",
            "fit with the major",
            "problem-solving"
        ],
        "guidance": "Georgia Tech is strongly major-focused - fit with your intended (especially STEM) program matters a lot, and admission can differ sharply by major. Demonstrated rigor and real projects in your field, plus a clear \"why this major,\" read very well. Slightly less essay-driven than the Ivies, more focused on academic fit.",
        "acceptedPattern": "Admits typically show clear rigor in the intended major plus concrete projects (a build, a competition, applied work) that prove genuine engagement with the field - and a specific, credible reason for that major."
    },
    {
        "name": "University of Oxford",
        "aka": [
            "oxford",
            "oxford university",
            "university of oxford"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~13% (course-dependent)",
        "region": "Oxford, England",
        "dataDepth": "deep",
        "motto": "\"Dominus illuminatio mea\" — \"The Lord is my light.\"",
        "values": [
            "deep subject knowledge",
            "academic potential",
            "ability to think under pressure",
            "fit for the tutorial system"
        ],
        "guidance": "UK admissions are fundamentally different from the US: Oxford cares almost entirely about ACADEMIC ability and potential in your one chosen subject - not well-roundedness or a broad activity list. Its own guidance: \"show how deeply you have engaged with your subject, above and beyond school.\" Most courses require an admissions test (e.g. TMUA, TARA) and an interview that probes how you think. Your UCAS personal statement should be overwhelmingly about your subject.",
        "acceptedPattern": "Successful applicants demonstrate subject obsession that goes far beyond the syllabus - wider reading, engaging with real problems in the field, and articulating ideas clearly. In interviews, admits think aloud and handle unfamiliar problems rather than reciting facts. Extracurriculars matter only if they connect to academic ability."
    },
    {
        "name": "University of Cambridge",
        "aka": [
            "cambridge",
            "cambridge university",
            "university of cambridge"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~16% (course-dependent)",
        "region": "Cambridge, England",
        "dataDepth": "deep",
        "motto": "\"Hinc lucem et pocula sacra\" — \"From here, light and sacred draughts\" (enlightenment and knowledge).",
        "values": [
            "exceptional subject ability",
            "academic depth",
            "supervision-system fit",
            "clear scientific/analytical thinking"
        ],
        "guidance": "Like Oxford, Cambridge is about pure academic ability in your chosen subject, assessed through your grades, a subject admissions test (e.g. TMUA, ESAT), your personal statement, and a rigorous interview. It also asks many applicants to complete extra questionnaires. Deep, demonstrated engagement with your subject - not breadth of activities - is what matters.",
        "acceptedPattern": "Admits show top-level performance in the relevant subjects plus genuine intellectual depth beyond the curriculum, and in interviews they reason through hard, unfamiliar problems calmly. The recurring signal is exceptional, demonstrated ability in the one subject - the UK system rewards specialists."
    },
    {
        "name": "Imperial College London",
        "aka": [
            "imperial",
            "imperial college",
            "imperial college london"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~14% (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "Imperial retired its Latin motto in 2020; today it centres science, engineering, medicine, and business for real-world benefit.",
        "values": [
            "STEM excellence",
            "course fit",
            "quantitative ability",
            "practical application of science"
        ],
        "guidance": "Imperial is a STEM-focused UK powerhouse - admission is course-specific and heavily academic, with most courses requiring an admissions test (e.g. TMUA, ESAT) and strong maths/science grades. Its new structured personal statement asks directly why the course and why you're ready. Show deep, genuine ability and interest in your specific subject.",
        "acceptedPattern": "Admits show strong quantitative ability and genuine subject engagement (projects, competitions, wider study) - Imperial is unapologetically academic and course-focused, so demonstrated STEM depth and test performance recur far more than breadth."
    },
    {
        "name": "London School of Economics (LSE)",
        "aka": [
            "lse",
            "london school of economics"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~9% (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "\"Rerum cognoscere causas\" — \"To understand the causes of things.\"",
        "values": [
            "analytical and quantitative ability",
            "deep interest in the social sciences",
            "academic writing",
            "course fit"
        ],
        "guidance": "LSE places arguably more weight on the personal statement than any other top UK university, because it does not interview - the statement is your only chance to show fit. Its guidance is explicit: it should be overwhelmingly academic, focused on your chosen social-science subject. Strong grades, often a maths test (TMUA), and demonstrated analytical engagement matter most.",
        "acceptedPattern": "Because LSE doesn't interview, admits stand out through an intensely academic personal statement - real engagement with economics/social science beyond the syllabus, wider reading, and clear analytical thinking. Top grades and (where required) strong test scores recur. Extracurriculars are near-irrelevant unless academically connected."
    },
    {
        "name": "University College London (UCL)",
        "aka": [
            "ucl",
            "university college london"
        ],
        "country": "UK",
        "tier": "reach",
        "accept": "~30% (course-dependent)",
        "region": "London, England",
        "dataDepth": "deep",
        "motto": "\"Cuncti adsint meritaeque expectent praemia palmae\" — \"Let all come who by merit deserve the most reward.\" Founded as a secular, inclusive alternative to Oxbridge.",
        "values": [
            "academic ability in the chosen course",
            "genuine subject interest",
            "breadth of London/UCL opportunity",
            "merit"
        ],
        "guidance": "UCL is a large, research-intensive UK university with course-specific admission. Founded to be open to all \"by merit,\" it reads for genuine academic ability and subject interest through your grades, personal statement, and (for some courses) an admissions test. As in all UK applications, focus the statement on your chosen subject, not a broad activity list.",
        "acceptedPattern": "Admits show solid-to-strong grades and clear, genuine engagement with their chosen subject in the personal statement. Requirements vary widely by course, but the recurring signal is academic fit and subject motivation, not well-roundedness."
    },
    {
        "name": "University of Edinburgh",
        "aka": [
            "edinburgh",
            "university of edinburgh"
        ],
        "country": "UK",
        "tier": "target",
        "accept": "course-dependent",
        "region": "Edinburgh, Scotland",
        "dataDepth": "deep",
        "motto": "\"Nec temere, nec timide\" — \"Neither rashly, nor timidly.\"",
        "values": [
            "academic ability in the chosen course",
            "genuine subject interest",
            "independent thinking",
            "course fit"
        ],
        "guidance": "Edinburgh is a large, ancient, research-intensive UK university with course-specific admission driven mainly by grades and the personal statement (it generally does not interview for most subjects). As with all UK applications, make the statement overwhelmingly about your chosen subject and your academic readiness for it.",
        "acceptedPattern": "Admits show the required grades and a focused, subject-driven personal statement demonstrating genuine interest and independent thinking. Competitiveness varies significantly by course; academic fit is the recurring signal."
    },
    {
        "name": "University of Texas at Austin",
        "aka": [
            "ut austin",
            "university of texas",
            "ut",
            "texas",
            "ut-austin"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~29% overall (far lower for top majors)",
        "region": "Austin, TX",
        "dataDepth": "deep",
        "motto": "\"Disciplina Praesidium Civitatis\" — \"A cultivated mind is the guardian genius of democracy.\" A major public flagship with elite CS, business, and engineering.",
        "values": [
            "fit with the specific major",
            "genuine depth in your field",
            "a real 'why this major'",
            "academic rigor"
        ],
        "guidance": "UT Austin admits BY MAJOR, and this is the single most important thing to understand: the ~29% overall rate is misleading because top programs (CS, McCombs business, engineering) are dramatically harder - CS's Turing honors reportedly denies 85% of valedictorians and competitive CS applicants rank top 1-3% with 1500+ SAT. Texas residents in the top ~6% get automatic admission to the university (not necessarily the major). Write the ApplyTexas Topic A personal statement plus a major-specific short answer that shows genuine curiosity about THAT field, not 'CS/business at any top school.'",
        "acceptedPattern": "Admitted students to competitive majors show deep, specific experience in that exact field (real projects, research, competitions) plus top-percentile academics - and essays that engage the actual discipline (specific CS subareas, faculty research, real problems), not generic ambition. Generic 'why this major' essays are immediately less competitive. For non-impacted majors, a solid record and clear direction suffice."
    },
    {
        "name": "University of California, San Diego (UCSD)",
        "aka": [
            "ucsd",
            "uc san diego"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~25%",
        "region": "La Jolla, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A top public research university (2nd in the world by some research measures) with a distinctive eight-college system.",
        "values": [
            "strong PIQs with specificity",
            "academic and research focus",
            "contribution and self-reflection",
            "fit with a college theme"
        ],
        "guidance": "UCSD uses the UC application - four of eight Personal Insight Questions (350 words each), the SAME essays across every UC campus, no separate supplement. Since admitted students' academics are uniformly strong, the PIQs are your real differentiator: they reward specificity, genuine self-reflection, and even honest vulnerability (what you found hard, how you improved) over polished bragging. UCSD is especially strong in STEM, and its eight-college system rewards showing where you'd fit.",
        "acceptedPattern": "Admits show strong GPAs plus PIQs with real specificity and reflection - a documented pattern is essays that reveal a genuine, sustained intellectual or community commitment (e.g. a student who led a marine-biology club, researched ocean acidification, and built underwater drones toward a clear goal). CS, engineering, and biology are the most competitive."
    },
    {
        "name": "University of California, Davis (UC Davis)",
        "aka": [
            "uc davis",
            "ucd",
            "davis"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~37%",
        "region": "Davis, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" World-leading in veterinary medicine, agriculture, and environmental science.",
        "values": [
            "strong PIQs",
            "academic focus",
            "community contribution",
            "fit with signature programs"
        ],
        "guidance": "UC Davis uses the UC application - four of eight Personal Insight Questions (350 words each), identical across all UC campuses. It's a well-rounded research university that's genuinely world-first in veterinary science, agriculture, and environmental studies. As with all UCs, the PIQs carry real weight and reward specificity and self-reflection; a clear academic direction (especially in its signature fields) helps.",
        "acceptedPattern": "Admits show solid academics and PIQs conveying genuine interest and contribution. Applicants with real depth in Davis's standout areas (vet/ag/environmental/sustainability) stand out; the recurring signal is specificity and growth in the PIQs, not just stats."
    },
    {
        "name": "University of California, Irvine (UC Irvine)",
        "aka": [
            "uc irvine",
            "uci",
            "irvine"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~25%",
        "region": "Irvine, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A fast-rising research university strong in CS, biology, and public health.",
        "values": [
            "strong PIQs",
            "academic focus in your field",
            "contribution",
            "self-reflection"
        ],
        "guidance": "UC Irvine uses the UC application - four of eight Personal Insight Questions (350 words each), identical across all UC campuses. It's rising fast and especially strong in computer science, biological sciences, and public health. The PIQs are the key differentiator among academically-strong applicants; write with specificity and genuine reflection, and show focus in your intended field (top majors are more competitive).",
        "acceptedPattern": "Admits show strong academics and focused, specific PIQs. Competitiveness varies sharply by major - CS and biology are among the hardest - and the recurring signal is demonstrated interest plus reflective, specific essays."
    },
    {
        "name": "University of California, Santa Barbara (UCSB)",
        "aka": [
            "ucsb",
            "uc santa barbara"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~38%",
        "region": "Santa Barbara, CA",
        "dataDepth": "deep",
        "motto": "\"Fiat Lux\" — \"Let there be light.\" A research university with standout physics, engineering, and materials science (and multiple Nobel laureates).",
        "values": [
            "strong PIQs",
            "intellectual curiosity",
            "empathy and contribution",
            "academic focus"
        ],
        "guidance": "UCSB uses the UC application - four of eight Personal Insight Questions (350 words each), identical across all UC campuses. It has genuinely elite physics, engineering, and materials-science programs. UCSB specifically values students who will positively contribute to campus and show empathy alongside achievement; write PIQs with specificity and real reflection, and show genuine intellectual interest.",
        "acceptedPattern": "Admits show solid academics and PIQs conveying real curiosity, contribution, and (UCSB emphasizes) empathy and character. Its top science/engineering programs are notably more competitive; specific, reflective essays recur."
    },
    {
        "name": "University of Wisconsin-Madison",
        "aka": [
            "wisconsin",
            "uw madison",
            "university of wisconsin",
            "uw-madison"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~43%",
        "region": "Madison, WI",
        "dataDepth": "deep",
        "motto": "\"Numen Lumen\" (\"God, our light\"), but its living ethos is the \"Wisconsin Idea\": that university knowledge should improve people's lives beyond the classroom.",
        "values": [
            "the Wisconsin Idea (real-world impact)",
            "academic rigor",
            "genuine involvement",
            "a clear direction"
        ],
        "guidance": "Wisconsin-Madison is a top public research university whose defining value is the \"Wisconsin Idea\" - knowledge applied for the public good, statewide and beyond. Its supplemental essay asks what you want to accomplish and how you'd contribute, so tie your interests to real-world impact. It reads for rigor plus genuine involvement; out-of-state and top majors (CS, business, engineering) are more competitive.",
        "acceptedPattern": "Admits show strong academics plus genuine involvement, and the strongest essays connect the applicant's interests to real-world contribution consistent with the Wisconsin Idea. A clear sense of how you'd use your education recurs."
    },
    {
        "name": "University of Illinois Urbana-Champaign (UIUC)",
        "aka": [
            "uiuc",
            "university of illinois",
            "illinois",
            "u of i"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~45% overall (far lower for engineering/CS)",
        "region": "Urbana-Champaign, IL",
        "dataDepth": "deep",
        "motto": "\"Learning and Labor.\" A public powerhouse with top-5-in-the-nation engineering and computer science.",
        "values": [
            "fit with the specific major",
            "genuine technical depth",
            "problem-solving",
            "a real 'why this major'"
        ],
        "guidance": "UIUC admits BY MAJOR, and its world-class engineering and CS programs (Grainger College) are dramatically more competitive than the ~45% overall rate - CS admits are near the very top of the applicant pool. Apply directly to the major you want and write essays showing genuine, specific technical interest and real projects. A clear 'why this major and why UIUC' matters; generic ambition doesn't compete for the top programs.",
        "acceptedPattern": "Admits to top engineering/CS programs show serious demonstrated technical depth - real projects, competitions, applied work - well beyond strong grades, plus essays engaging the specific field. For less-impacted majors, a solid record and clear direction suffice."
    },
    {
        "name": "University of Washington (UW)",
        "aka": [
            "uw",
            "university of washington",
            "udub"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~43% overall (far lower for CS)",
        "region": "Seattle, WA",
        "dataDepth": "deep",
        "motto": "\"Lux Sit\" — \"Let there be light.\" A major public research university with an elite CS program (the Allen School), plus top medicine and sciences.",
        "values": [
            "fit with the intended field",
            "real engagement and impact",
            "a clear direction",
            "genuine reflection"
        ],
        "guidance": "UW is a leading public research university where the Allen School of Computer Science is extremely competitive and effectively a separate, much harder admit than the ~43% overall rate. It reads holistically with two required essays (a personal statement and a short response) that reward genuine reflection and real engagement. Show demonstrated depth in your field; top majors (CS especially) require serious evidence.",
        "acceptedPattern": "Admits show strong academics and reflective essays showing real engagement or impact; CS/Allen School admits in particular show serious demonstrated technical depth. Fit with the intended field and authentic reflection recur."
    },
    {
        "name": "University of Florida (UF)",
        "aka": [
            "uf",
            "university of florida",
            "florida"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~24%",
        "region": "Gainesville, FL",
        "dataDepth": "deep",
        "motto": "\"Civium in moribus rei publicae salus\" — \"The welfare of the state depends on the character of its citizens.\" A top public flagship and an especially strong value.",
        "values": [
            "academic rigor",
            "genuine involvement and leadership",
            "a clear direction",
            "contribution"
        ],
        "guidance": "UF is a highly-ranked public flagship, strong across the board, that has become notably more selective. It reads for academic rigor plus genuine, sustained involvement and leadership. Its application rewards clear direction and real contribution to your community; the competitive Honors Program and top majors ask for more demonstrated depth.",
        "acceptedPattern": "Admits show strong academics with genuine involvement and leadership over time; the recurring signal is sustained commitment and contribution rather than a scattered activity list. Honors and top majors are more competitive."
    },
    {
        "name": "Michigan State University",
        "aka": [
            "michigan state",
            "msu",
            "mich state"
        ],
        "country": "US",
        "tier": "target",
        "accept": "~83%",
        "region": "East Lansing, MI",
        "dataDepth": "deep",
        "motto": "\"Advancing Knowledge. Transforming Lives.\" A large land-grant flagship, pioneer of the land-grant model, strong in education, supply chain, and the sciences.",
        "values": [
            "academic readiness",
            "a clear direction",
            "involvement",
            "fit with the major/program"
        ],
        "guidance": "Michigan State is a large, accessible land-grant flagship (the original land-grant model) with a much higher overall admit rate, though its Honors College and top programs (supply-chain management, education, some sciences) are meaningfully more competitive. A solid academic record, a clear direction, and genuine involvement read well; it's a strong target/safety with real program strengths.",
        "acceptedPattern": "Admits generally clear a solid GPA and course-rigor bar with a clear academic direction; Honors College and standout programs reward additional demonstrated depth and involvement."
    }
]
 
 
def _norm(s: str) -> str:
    return (s or "").strip().lower()
 
 
def _alias_matches(query_norm: str, alias: str) -> bool:
    """True if the alias genuinely matches the query. The query containing
    the alias only counts at a word boundary, so short aliases like 'cal'
    or 'nd' don't spuriously match inside unrelated words (e.g. 'cal' in
    'some local college'). The alias containing the query is fine (typing
    a prefix like 'harv')."""
    import re as _re
    if query_norm in alias:
        return True
    return bool(_re.search(r"\b" + _re.escape(alias) + r"\b", query_norm))
 
 
def search_schools(query: str) -> list[dict]:
    """Search the KB by name or alias - powers the survey autocomplete.
    Mirrors the frontend searchSchools() exactly."""
    q = _norm(query)
    if not q:
        return []
    out = []
    for s in SCHOOLS:
        name = s["name"].lower()
        aka = s.get("aka", [])
        if q in name or any(_alias_matches(q, a) for a in aka):
            out.append(s)
        if len(out) >= 6:
            break
    return out
 
 
def lookup_school(name: str):
    """Resolve a stored school name (or free text) to its KB entry, or None.
    Mirrors the frontend lookupSchool() exactly."""
    q = _norm(name)
    if not q:
        return None
    # exact / alias first, then substring, matching the frontend precedence
    for s in SCHOOLS:
        if s["name"].lower() == q or q in s.get("aka", []):
            return s
    for s in SCHOOLS:
        if q in s["name"].lower() or any(_alias_matches(q, a) for a in s.get("aka", [])):
            return s
    return None
 
 
def target_school_entries(target_schools: str) -> list[dict]:
    """Resolve a student's comma-separated target_schools string to the
    KB entries that are found. Unknown schools are simply omitted (the
    caller reports them honestly as 'general guidance')."""
    names = [n.strip() for n in (target_schools or "").split(",") if n.strip()]
    entries = []
    for n in names:
        e = lookup_school(n)
        if e and e not in entries:
            entries.append(e)
    return entries
 
 
def _anchor_school(entries: list[dict]):
    """The school that sets the bar - the most selective (reach) one,
    else the first. Advice anchors on this. Mirrors the frontend."""
    if not entries:
        return None
    for e in entries:
        if e.get("tier") == "reach":
            return e
    return entries[0]
 
 
def tailor_advice_for_opportunity(opp: dict, profile: dict) -> str:
    """The school-specific "why this fits" for one opportunity, tailored to
    the student's target schools. Honest and deterministic - never a
    fabricated per-officer claim. Mirrors the frontend deepExplain()."""
    major = profile.get("intended_major") or "your intended field"
    tags = opp.get("tags", []) or []
    matched = (opp.get("matched") or [])[:3]
    overlap = ", ".join(matched)
 
    if "competition" in tags:
        kind = "A strong result here is a concrete, verifiable achievement"
    elif "internship" in tags:
        kind = "Real hands-on experience like this shows genuine, tested interest"
    elif "leadership" in tags:
        kind = "Sustained leadership here demonstrates initiative over time"
    else:
        kind = "Consistent involvement here shows real, demonstrated commitment"
 
    overlap_line = (
        f"This overlaps directly with your stated focus on {overlap}. "
        if overlap else
        f"This is a broader activity - useful while you narrow your focus, but pair it with something more specific to {major}. "
    )
 
    entries = target_school_entries(profile.get("target_schools", ""))
    school_line = " Depth in one or two areas reads far stronger than a long list of shallow activities."
    anchor = _anchor_school(entries)
    if anchor:
        vals = anchor.get("values", [])
        value_match = None
        for v in vals:
            vl = v.lower()
            first = vl.split(" ")[0] if vl else ""
            if any(vl in t or (first and first in t) for t in tags) \
               or (("leadership" in vl) and ("leadership" in tags)) \
               or (("making" in vl) and ("competition" in tags)) \
               or (("building" in vl) and ("entrepreneurship" in tags)):
                value_match = v
                break
        two_values = " and ".join(vals[:2]) if vals else "genuine depth"
        if value_match:
            school_line = (
                f" For {anchor['name']} ({anchor['accept']} admit rate), what actually moves the "
                f"needle is {two_values} - and this opportunity speaks directly to that."
            )
        else:
            school_line = (
                f" For {anchor['name']} ({anchor['accept']} admit rate), what actually moves the "
                f"needle is {two_values}, so make sure this connects to a genuine, deep interest "
                f"rather than sitting on a list."
            )
 
    return (
        f"{overlap_line}{kind} in {major}.{school_line} "
        "Add it to your tracker to get it onto your schedule with its real deadline."
    )
 
 
def school_guidance_for_profile(profile: dict) -> dict:
    """The full school-tailored guidance payload for a student's dashboard:
    each matched target school's real profile + guidance, plus an honest
    note for any target schools not in the curated KB.
 
    Returns:
        {
          "schools": [ {name, country, tier, accept, region, motto,
                        values, guidance, acceptedPattern}, ... ],
          "uncurated": ["Some Local College", ...],   # honestly flagged
          "note": str | None
        }
    """
    target = profile.get("target_schools", "") or ""
    entries = target_school_entries(target)
    all_named = [n.strip() for n in target.split(",") if n.strip()]
    curated_names_lower = {e["name"].lower() for e in entries}
    # a named school is "uncurated" if it didn't resolve to a KB entry
    uncurated = []
    for n in all_named:
        e = lookup_school(n)
        if not e:
            uncurated.append(n)
 
    note = None
    if uncurated and not entries:
        note = (
            f"We don't have a detailed, source-verified profile for "
            f"{', '.join(uncurated)} yet, so guidance for those is general. "
            "The universal rule still holds: depth beats breadth - one genuine "
            "spike and a concrete achievement outweigh a long, shallow activity "
            "list at any selective school."
        )
    elif uncurated:
        note = (
            f"Detailed profiles shown below are source-verified. We don't have "
            f"one for {', '.join(uncurated)} yet - treat guidance for those as general."
        )
 
    return {
        "schools": entries,
        "uncurated": uncurated,
        "note": note,
    }
 
