"""The seeded demo brief.

Chosen because it forces genuinely external research. Lagos filming permits,
Nigerian drone regulation, February harmattan conditions, night-shoot security
and local equipment depth are not answerable from model memory - which is the
whole point of the Parallel integration.

This is demo *input*, not demo output. Every result it produces is retrieved
live at run time.
"""

from __future__ import annotations

from .schemas import ProductionBrief

DEMO_BRIEF = ProductionBrief(
    title="Shadow District",
    project_type="Independent feature film",
    genre="Crime thriller",
    country="Nigeria",
    city="Lagos",
    budget_amount=85_000,
    budget_currency="USD",
    shooting_days=12,
    shooting_period="February 2027",
    locations=[
        "Rooftop overlooking Lagos Island at dusk",
        "Police station exterior",
        "Nightclub interior",
        "Urban street scenes, Yaba and Surulere",
    ],
    requirements=[
        "Night filming across multiple locations",
        "Small crew of 12-15 people",
        "Drone establishing shots over the city",
        "Practical locations only, no studio build",
        "Local fixer and security detail",
    ],
    target_audience="18-34 domestic Nigerian audience plus international festival circuit",
    constraints=(
        "No studio build. Single equipment rental vendor assumed. Limited contingency "
        "budget. Director is travelling in from abroad and needs to know visa and "
        "equipment import implications."
    ),
    free_text=(
        "We are a two-person production company shooting our first feature in Lagos. "
        "We need to know whether 12 days is realistic for this location list, what "
        "permits we actually need for street and rooftop filming, whether drone shots "
        "over the city are permitted, and what the weather will do to us in February. "
        "We have no local production office and no legal team."
    ),
)
