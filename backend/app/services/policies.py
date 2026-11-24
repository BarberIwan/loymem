"""Terms a business chooses from, instead of writing them itself.

Every sentence here is shown to customers as part of what they accept, and is
checked once by a lawyer (``docs/legal/voorwaarden-zinnen.md`` lists them; a
static test keeps that list and this file the same). A business picks one option
per subject; the chosen sentence is stored on the plan at that moment, so a
customer keeps the text they accepted even if this catalogue changes later.

Only options the platform actually carries out are offered: rolling unused
visits over is done by the daily round, and a missed visit is booked by staff
with "Bezoek afboeken".
"""

from __future__ import annotations

from app.models import PlanKind

# Unused visits in a renewing membership.
UNUSED_MEMBERSHIP = {
    "expire_period": "Bezoeken die je in een maand niet gebruikt, vervallen aan het eind "
    "van die maand.",
    "roll_one_period": "Bezoeken die je in een maand niet gebruikt, schuiven één maand door. "
    "Wat je ook die maand niet gebruikt, vervalt. Je oudste bezoeken gebruik je eerst.",
}

# Fixed: a bundle or a balance simply ends with its validity.
UNUSED_BUNDLE = (
    "Bezoeken die je niet gebruikt binnen de geldigheid, vervallen op de laatste dag. "
    "Je ziet op je kaart tot wanneer ze geldig zijn."
)
UNUSED_CREDIT = (
    "Tegoed dat je niet besteedt binnen de geldigheid, vervalt op de laatste dag. "
    "Je ziet op je kaart hoeveel je nog hebt en tot wanneer."
)

NO_SHOW = {
    "free": "Kom je niet, dan kost dat geen bezoek. Laat het ons wel even weten.",
    "no_show_counts": "Kom je niet en heb je niet afgemeld, dan telt dat als een gebruikt "
    "bezoek. Afmelden kan tot het begin van je afspraak.",
    "late_24h": "Afmelden kan kosteloos tot 24 uur voor je afspraak. Meld je later af of "
    "kom je niet, dan telt dat als een gebruikt bezoek.",
    "late_24h_first_free": "Afmelden kan kosteloos tot 24 uur voor je afspraak. Meld je later "
    "af of kom je niet, dan telt dat als een gebruikt bezoek. De eerste keer per jaar niet.",
}

# Fixed until the platform can pause a membership itself.
PAUSE = "Pauzeren kan niet. Opzeggen kan altijd, per het eind van de betaalde maand."

UNUSED_RULES = set(UNUSED_MEMBERSHIP)
NO_SHOW_RULES = set(NO_SHOW)


def texts(kind: PlanKind, unused_rule: str | None, no_show_rule: str | None) -> dict[str, str]:
    """The sentences a plan shows, for the rules chosen. Raises on an unknown rule."""
    if kind == PlanKind.CREDIT:
        return {"unused_policy": UNUSED_CREDIT, "no_show_policy": "", "pause_policy": ""}
    if no_show_rule not in NO_SHOW:
        raise ValueError("no_show_rule")
    if kind == PlanKind.MEMBERSHIP:
        if unused_rule not in UNUSED_MEMBERSHIP:
            raise ValueError("unused_rule")
        unused = UNUSED_MEMBERSHIP[unused_rule]
    else:
        unused = UNUSED_BUNDLE
    return {"unused_policy": unused, "no_show_policy": NO_SHOW[no_show_rule], "pause_policy": PAUSE}


def all_sentences() -> list[str]:
    return [*UNUSED_MEMBERSHIP.values(), UNUSED_BUNDLE, UNUSED_CREDIT, *NO_SHOW.values(), PAUSE]
