"""Every edition of the brief, one function each.

The pipeline in daily_brief.py is edition-agnostic: research passes, relevance
gate, recency guard, cross-edition de-duplication, link verification, cost
tracking. What differs between editions is *editorial* — who is reading, what
counts as relevant, what to search for, and the running order of sections.

Each edition below states only its differences. Anything it does not override
keeps the property-brief default, so adding a third edition means writing one
function, not forking the pipeline.

    python editions.py property      # the daily
    python editions.py franchise     # the weekly
    python editions.py all           # both, in sequence
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

import daily_brief as pipeline  # noqa: E402
import franchise_content as fr  # noqa: E402


def run_property() -> None:
    """The Asset Brief — daily Australian commercial property intelligence.

    Uses the pipeline's built-in defaults for audience, rubric, clusters and
    sections, so there is nothing to override here beyond the config file.
    """
    pipeline.main(os.path.join(ROOT, "config.yml"))


def run_franchise() -> None:
    """The Franchise Brief — weekly, for landlords, investors and operators.

    Every override below is an editorial decision, not a technical one:
    a different readership, a rubric that treats store counts and senior
    appointments as headline signals, four research clusters aimed at the
    franchise beat, and a section order built around deals, networks,
    franchisee health and the landlord angle.
    """
    pipeline.main(
        os.path.join(ROOT, "config_franchise.yml"),
        audience=fr.AUDIENCE,
        relevance_rubric=fr.RELEVANCE_RUBRIC,
        research_clusters=fr.RESEARCH_CLUSTERS,
        section_plan=fr.SECTION_PLAN,
        coverage=fr.COVERAGE,
        intel_categories=fr.INTEL_CATEGORIES,
        brief_desc=fr.BRIEF_DESC,
        priority_sources=fr.PRIORITY_SOURCES,
        geography=fr.GEOGRAPHY,
        deal_threshold=fr.DEAL_THRESHOLD,
    )


EDITIONS = {"property": run_property, "franchise": run_franchise}


def main(argv: list[str]) -> int:
    which = (argv[1] if len(argv) > 1 else "property").lower()
    names = list(EDITIONS) if which == "all" else [which]
    if any(n not in EDITIONS for n in names):
        print(f"usage: python editions.py [{'|'.join(EDITIONS)}|all]",
              file=sys.stderr)
        return 2
    failures = 0
    for name in names:
        print(f"\n===== {name.upper()} EDITION =====", flush=True)
        try:
            EDITIONS[name]()
        except Exception as e:
            # One edition failing must not stop the other from going out.
            failures += 1
            print(f"FAILED ({name}): {e}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
