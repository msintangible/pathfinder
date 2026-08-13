"""
Evidence-based keyword classification — the "why is this keyword matched or
missing" record behind schemas/resume.py::KeywordEvidence. Wired into
keyword_matcher.match_keywords, which is the sole caller: every job keyword
is classified here first, and match_keywords' matched/missing split is
derived from classify_keyword's status (anything but "unsupported" counts
as matched).

Safety model, same as inferable_keywords.py's existing precedent: every
alias/category/activity relationship below is a hand-reviewed, closed list,
never inferred or generated at runtime. Two rules keep this from becoming
the kind of over-eager guessing that would let "AWS" satisfy "Terraform":

1. CATEGORY_MAP only ever holds genuine IS-A relationships (a member is
   definitionally an instance of the category — "Azure SQL" IS-A relational
   database) — never correlational ones ("Python" and "Pandas" are often
   used together, but knowing one doesn't entail the other, so that pairing
   is deliberately absent). Infrastructure-as-code tools (Terraform,
   CloudFormation, Pulumi, Ansible) are deliberately excluded from every
   category here, including "cloud platforms" — provisioning a cloud
   platform and using an IaC tool to manage it are genuinely different
   skills, so having AWS/Azure must never credit Terraform.
2. Container orchestration (Kubernetes, Docker Swarm, ECS) is deliberately
   NOT a category with "containerization" (Docker) as a satisfying member —
   running containers and orchestrating them at scale are different skills.
"""

from schemas.resume import KeywordEvidence
from services.keyword_matcher import (
    _NESTED_SKILL_SECTIONS,
    _STOPWORDS,
    _flatten_candidate_profile_text,
    _word_present,
    PROFILE_SKILL_FIELDS,
)

# Genuinely equivalent spellings of the SAME underlying technology — not
# different technologies in the same category (that's CATEGORY_MAP below).
# Each group is pre-lowercased; keep additions narrow and reviewed, same bar
# as everything else here.
TECH_ALIASES: list[list[str]] = [
    ["asp.net", "asp.net core", "asp.net mvc"],
    ["javascript", "js"],
    ["typescript", "ts"],
    ["postgresql", "postgres"],
    ["kubernetes", "k8s"],
    ["amazon web services", "aws"],
    ["microsoft azure", "azure"],
    ["google cloud platform", "google cloud", "gcp"],
    ["node.js", "nodejs", "node"],
    ["react.js", "reactjs", "react"],
    ["c#", "c sharp", "csharp"],
    [
        "continuous integration/continuous deployment", "ci/cd", "cicd",
        "continuous integration and continuous deployment",
    ],
]

_ALIAS_GROUP_BY_TERM: dict[str, list[str]] = {
    term: group for group in TECH_ALIASES for term in group
}

# Each entry is (synonym keys, concrete member technologies). Multiple keys
# per entry exist for the same reason TECH_ALIASES groups multiple spellings
# together: a job posting phrases the same real-world category many ways
# ("RDBMS" vs "relational database management systems" are literally the
# same thing spelled two ways), and a keyword classifying as "unsupported"
# purely because the posting used a different-but-equivalent phrasing than
# our one curated key is a false negative, not a safety win. Adding a key
# here must still satisfy the module docstring's IS-A rule — it only ever
# widens which *phrasings* reach an already-approved category, never adds a
# new category or member.
_CATEGORY_GROUPS: list[tuple[list[str], list[str]]] = [
    (
        [
            "relational databases", "relational database", "sql databases", "sql database",
            "relational database systems", "relational database management systems", "rdbms", "sql",
        ],
        ["Azure SQL", "SQL Server", "MySQL", "PostgreSQL", "Oracle", "SQLite", "MariaDB", "Amazon RDS"],
    ),
    (
        ["nosql databases", "nosql", "nosql database", "non-relational databases"],
        ["MongoDB", "DynamoDB", "Firebase", "Redis", "Cassandra", "Cosmos DB"],
    ),
    (
        # Bare "Databases" (no relational/nosql qualifier) — satisfied by any
        # concrete database technology, relational or not.
        ["databases", "database", "database technologies", "database management", "database systems"],
        [
            "Azure SQL", "SQL Server", "MySQL", "PostgreSQL", "Oracle", "SQLite", "MariaDB", "Amazon RDS",
            "MongoDB", "DynamoDB", "Firebase", "Redis", "Cassandra", "Cosmos DB",
        ],
    ),
    (
        ["cloud platforms", "cloud computing", "cloud services", "cloud technologies"],
        ["AWS", "Azure", "Google Cloud", "GCP"],
    ),
    (
        ["containerization", "container technologies", "containers"],
        ["Docker", "Podman"],
    ),
    (
        ["version control", "version control systems", "source control"],
        ["Git", "GitHub", "GitLab", "Bitbucket", "SVN"],
    ),
    (
        ["frontend frameworks", "front-end frameworks", "ui frameworks"],
        ["React", "Angular", "Vue", "Vue.js", "Svelte"],
    ),
    (
        ["javascript frameworks", "js frameworks"],
        ["React", "Angular", "Vue", "Vue.js", "Svelte", "Next.js"],
    ),
    (
        ["unit testing", "unit tests"],
        ["Jest", "PyTest", "JUnit", "xUnit", "NUnit", "Mocha"],
    ),
]

# category (lowercase) -> concrete member technologies (original casing, as
# they'd appear in a profile) that genuinely satisfy it. See module
# docstring for the IS-A rule that keeps this list safe.
CATEGORY_MAP: dict[str, list[str]] = {
    key: members for keys, members in _CATEGORY_GROUPS for key in keys
}

# Curated activity/practice phrases — deliberately NOT run through the
# generic 3+-significant-word text-overlap check below (too short/variable
# to be safe there, per keyword_matcher._keyword_appears_in's own
# reasoning), but common enough in job postings to be worth a specific,
# reviewed trigger list, the same pattern inferable_keywords.py already
# uses. Every trigger is checked against the candidate's own real
# bullet/description text, not just skill tags — this is about demonstrated
# practice, not a tool name.
#
# As with _CATEGORY_GROUPS above, each entry lists every reviewed phrasing
# of the SAME underlying activity a job posting might use ("API design" and
# "building APIs" both mean "has developed APIs") — widening recognized
# phrasing, not the underlying claim being made.
_ACTIVITY_GROUPS: list[tuple[list[str], list[str]]] = [
    (
        [
            "api development", "building apis", "developing apis", "designing apis",
            "api design", "rest api development", "restful api development", "web api development",
        ],
        [
            "rest api", "restful api", "api endpoint", "built api", "built rest",
            "developed api", "designed api", "fastapi", "asp.net", "express", "flask", "graphql", "web api",
        ],
    ),
    (
        ["software design", "system design", "software architecture design"],
        ["architecture", "system design", "design pattern", "designed a", "software architecture", "clean architecture"],
    ),
    (
        ["software engineering principles", "software engineering", "software engineering best practices"],
        [
            "clean architecture", "solid principles", "design pattern", "best practices",
            "software architecture", "code review", "unit test",
        ],
    ),
    # Short (1-2 word) soft-skill/process concepts below never reach the generic
    # 3+-word overlap check (see classify_keyword's Tier 4 else-branch), so
    # without a curated entry here they'd always classify unsupported no
    # matter how much real evidence exists — the exact gap reported for
    # "Collaboration" against a profile bullet reading "collaborating via Git
    # for version control and code reviews".
    (
        ["collaboration", "team collaboration", "collaborative"],
        ["team", "collaborat", "pair programming", "code review", "cross-functional"],
    ),
    (
        # Widened per explicit user spec: client work, requirements gathering,
        # team/code reviews, and hackathons all count as real communication
        # evidence, not just the literal word "communicat(e/ion)".
        ["communication", "communication skills", "verbal communication", "written communication"],
        [
            "communicat", "presented", "presentation", "stakeholder", "client",
            "requirements gathering", "code review", "hackathon", "cross-functional",
        ],
    ),
    (
        ["implementation", "feature implementation", "implementing features"],
        ["implement", "built", "developed", "engineered", "designed and built"],
    ),
    (
        ["delivery", "project delivery", "software delivery"],
        ["delivered", "deployed", "shipped", "launched", "released", "production"],
    ),
    (
        ["ci/cd", "continuous integration", "continuous deployment", "continuous integration/continuous deployment", "cicd"],
        [
            "ci/cd", "continuous integration", "continuous deployment", "pipeline",
            "github actions", "jenkins", "circleci", "gitlab ci",
        ],
    ),
    (
        ["research and development", "r&d", "research", "technical research"],
        ["research", "investigat", "prototype", "proof of concept", "explored", "evaluated"],
    ),
]

ACTIVITY_PHRASES: dict[str, list[str]] = {
    key: triggers for keys, triggers in _ACTIVITY_GROUPS for key in keys
}

# Per-tier confidence — fixed constants, not a per-instance guess, so the
# same keyword+profile always classifies identically.
_CONFIDENCE = {
    "exact": 1.0,
    "alias": 0.9,
    "semantic": 0.85,
    "experience_curated": 0.75,
    "experience_generic": 0.6,
    "unsupported": 0.0,
}


def _profile_skill_terms(profile: dict) -> dict[str, str]:
    """lowercase term -> original casing, from every flat + nested skill/tech field."""
    terms: dict[str, str] = {}
    for field in PROFILE_SKILL_FIELDS:
        for term in profile.get(field) or []:
            if term:
                terms.setdefault(term.strip().lower(), term.strip())
    for section, fields in _NESTED_SKILL_SECTIONS.items():
        for entry in profile.get(section) or []:
            for field in fields:
                for term in entry.get(field) or []:
                    if term:
                        terms.setdefault(term.strip().lower(), term.strip())
    return terms


def classify_keyword(keyword: str, profile: dict) -> KeywordEvidence:
    """Classify one job keyword's support level against a candidate profile. See KeywordEvidence's docstring for the tier definitions."""
    normalized = keyword.strip().lower()
    if not normalized:
        return KeywordEvidence(keyword=keyword, status="unsupported", evidence_type="none", confidence=0.0, evidence=[])

    profile_terms = _profile_skill_terms(profile)

    # Tier 1 — exact
    if normalized in profile_terms:
        return KeywordEvidence(
            keyword=keyword, status="supported", evidence_type="exact", confidence=_CONFIDENCE["exact"],
            evidence=[profile_terms[normalized]],
        )

    # Tier 2 — alias
    alias_group = _ALIAS_GROUP_BY_TERM.get(normalized)
    if alias_group:
        found = [profile_terms[term] for term in alias_group if term in profile_terms]
        if found:
            return KeywordEvidence(
                keyword=keyword, status="supported", evidence_type="alias",
                confidence=_CONFIDENCE["alias"], evidence=found,
            )

    # Tier 3 — semantic/category
    members = CATEGORY_MAP.get(normalized)
    if members:
        found = [profile_terms[m.lower()] for m in members if m.lower() in profile_terms]
        if found:
            return KeywordEvidence(
                keyword=keyword, status="supported", evidence_type="semantic",
                confidence=_CONFIDENCE["semantic"], evidence=found,
            )

    # Tier 4 — experience (curated activity phrase, or generic 3+-word text overlap)
    profile_text = _flatten_candidate_profile_text(profile).lower()

    triggers = ACTIVITY_PHRASES.get(normalized)
    if triggers:
        found_triggers = [t for t in triggers if t in profile_text]
        if found_triggers:
            return KeywordEvidence(
                keyword=keyword, status="supported", evidence_type="experience",
                confidence=_CONFIDENCE["experience_curated"], evidence=found_triggers,
            )
    else:
        words = [word for word in normalized.split() if word not in _STOPWORDS]
        if len(words) >= 3:
            haystack_tokens = profile_text.split()
            present = [word for word in words if _word_present(word, haystack_tokens)]
            if len(present) >= len(words) - 1:
                return KeywordEvidence(
                    keyword=keyword, status="supported", evidence_type="experience",
                    confidence=_CONFIDENCE["experience_generic"], evidence=present,
                )

    return KeywordEvidence(keyword=keyword, status="unsupported", evidence_type="none", confidence=0.0, evidence=[])


def classify_keywords(keywords: list[str], profile: dict) -> list[KeywordEvidence]:
    return [classify_keyword(keyword, profile) for keyword in keywords]
