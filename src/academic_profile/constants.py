from __future__ import annotations

DATA_CATEGORIES = (
    "education",
    "research",
    "publications",
    "projects",
    "awards",
    "competitions",
    "coursework",
    "skills",
    "presentations",
    "english",
    "activities",
    "links",
)

PROFILE_NAMES = (
    "phd",
    "ra",
    "summer_research",
    "domestic",
    "internship",
)

PUBLICATION_STATUSES = {
    "published",
    "accepted",
    "under_review",
    "submitted",
    "preprint",
    "manuscript",
}

GENERAL_STATUSES = {"planned", "active", "completed", "archived"}
RECORD_STATES = {"draft", "ready"}
RESEARCH_STATUSES = {
    "planned",
    "active",
    "idea",
    "literature",
    "method",
    "experiment",
    "writing",
    "submitted",
    "completed",
    "archived",
}

REFERENCE_FIELDS = {
    "research": {"paper_id": "publications", "presentation_id": "presentations"},
    "publications": {"research_id": "research"},
    "presentations": {"research_id": "research"},
    "competitions": {"project_id": "projects"},
}

REFERENCE_LIST_FIELDS = {
    "research": {
        "paper_ids": "publications",
        "presentation_ids": "presentations",
        "skill_ids": "skills",
    },
    "projects": {"competition_ids": "competitions", "skill_ids": "skills"},
    "coursework": {"skill_ids": "skills"},
}
