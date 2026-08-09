"""
Evidence-based keyword classification — the "why is this keyword matched or
missing" record behind schemas/resume.py::KeywordEvidence.

Deliberately not wired into keyword_matcher.match_keywords yet — this module
is developed and tested standalone first (see the phased ATS-redesign plan);
match_keywords keeps its existing exact-only behavior until a later phase
rewires it to use classify_keyword.

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

# category (lowercase) -> concrete member technologies (original casing, as
# they'd appear in a profile) that genuinely satisfy it. See module
# docstring for the IS-A rule that keeps this list safe.
CATEGORY_MAP: dict[str, list[str]] = {
    "relational databases": [
        "Azure SQL", "SQL Server", "MySQL", "PostgreSQL", "Oracle", "SQLite", "MariaDB", "Amazon RDS",
    ],
    "relational database": [
        "Azure SQL", "SQL Server", "MySQL", "PostgreSQL", "Oracle", "SQLite", "MariaDB", "Amazon RDS",
    ],
    "sql databases": ["Azure SQL", "SQL Server", "MySQL", "PostgreSQL", "Oracle", "SQLite", "MariaDB"],
    "rdbms": ["Azure SQL", "SQL Server", "MySQL", "PostgreSQL", "Oracle", "SQLite", "MariaDB"],
    # Bare "SQL" is commonly shorthand for "a SQL/relational database" in job
    # postings — same member list as relational databases above.
    "sql": ["Azure SQL", "SQL Server", "MySQL", "PostgreSQL", "Oracle", "SQLite", "MariaDB", "Amazon RDS"],
    "nosql databases": ["MongoDB", "DynamoDB", "Firebase", "Redis", "Cassandra", "Cosmos DB"],
    "nosql": ["MongoDB", "DynamoDB", "Firebase", "Redis", "Cassandra", "Cosmos DB"],
    "cloud platforms": ["AWS", "Azure", "Google Cloud", "GCP"],
    "cloud computing": ["AWS", "Azure", "Google Cloud", "GCP"],
    "containerization": ["Docker", "Podman"],
    "version control": ["Git", "GitHub", "GitLab", "Bitbucket", "SVN"],
    "version control systems": ["Git", "GitHub", "GitLab", "Bitbucket", "SVN"],
    "frontend frameworks": ["React", "Angular", "Vue", "Vue.js", "Svelte"],
    "javascript frameworks": ["React", "Angular", "Vue", "Vue.js", "Svelte", "Next.js"],
    "unit testing": ["Jest", "PyTest", "JUnit", "xUnit", "NUnit", "Mocha"],
}

# Curated 1-2 word activity/practice phrases — deliberately NOT run through
# the generic 3+-significant-word text-overlap check below (too short to be
# safe there, per keyword_matcher._keyword_appears_in's own reasoning), but
# common enough in job postings to be worth a specific, reviewed trigger
# list, the same pattern inferable_keywords.py already uses. Every trigger
# is checked against the candidate's own real bullet/description text, not
# just skill tags — this is about demonstrated practice, not a tool name.
ACTIVITY_PHRASES: dict[str, list[str]] = {
    "api development": [
        "rest api", "restful api", "api endpoint", "built api", "built rest",
        "developed api", "designed api", "fastapi", "asp.net", "express", "flask", "graphql", "web api",
    ],
    "software design": [
        "architecture", "system design", "design pattern", "designed a", "software architecture", "clean architecture",
    ],
    "software engineering principles": [
        "clean architecture", "solid principles", "design pattern", "best practices",
        "software architecture", "code review", "unit test",
    ],
    "software engineering": [
        "clean architecture", "solid principles", "design pattern", "best practices",
        "software architecture", "code review", "unit test",
    ],
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
        return KeywordEvidence(keyword=keyword, status="unsupported", confidence=0.0, evidence=[])

    profile_terms = _profile_skill_terms(profile)

    # Tier 1 — exact
    if normalized in profile_terms:
        return KeywordEvidence(
            keyword=keyword, status="exact", confidence=_CONFIDENCE["exact"],
            evidence=[profile_terms[normalized]],
        )

    # Tier 2 — alias
    alias_group = _ALIAS_GROUP_BY_TERM.get(normalized)
    if alias_group:
        found = [profile_terms[term] for term in alias_group if term in profile_terms]
        if found:
            return KeywordEvidence(
                keyword=keyword, status="alias", confidence=_CONFIDENCE["alias"], evidence=found,
            )

    # Tier 3 — semantic/category
    members = CATEGORY_MAP.get(normalized)
    if members:
        found = [profile_terms[m.lower()] for m in members if m.lower() in profile_terms]
        if found:
            return KeywordEvidence(
                keyword=keyword, status="semantic", confidence=_CONFIDENCE["semantic"], evidence=found,
            )

    # Tier 4 — experience (curated activity phrase, or generic 3+-word text overlap)
    profile_text = _flatten_candidate_profile_text(profile).lower()

    triggers = ACTIVITY_PHRASES.get(normalized)
    if triggers:
        found_triggers = [t for t in triggers if t in profile_text]
        if found_triggers:
            return KeywordEvidence(
                keyword=keyword, status="experience",
                confidence=_CONFIDENCE["experience_curated"], evidence=found_triggers,
            )
    else:
        words = [word for word in normalized.split() if word not in _STOPWORDS]
        if len(words) >= 3:
            haystack_tokens = profile_text.split()
            present = [word for word in words if _word_present(word, haystack_tokens)]
            if len(present) >= len(words) - 1:
                return KeywordEvidence(
                    keyword=keyword, status="experience",
                    confidence=_CONFIDENCE["experience_generic"], evidence=present,
                )

    return KeywordEvidence(keyword=keyword, status="unsupported", confidence=0.0, evidence=[])


def classify_keywords(keywords: list[str], profile: dict) -> list[KeywordEvidence]:
    return [classify_keyword(keyword, profile) for keyword in keywords]
