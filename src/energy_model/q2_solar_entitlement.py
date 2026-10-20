"""Contemporaneous 2013 solar support duration, separate from asset life.

Only the unambiguous annual cohort boundary (commissioned from 2014) is used.
Earlier assets require approval-date evidence; their existing assumptions are
reported unchanged. This does not reconstruct distributed/central sales.
"""
from dataclasses import replace


def apply_solar_duration(policy):
    """Configure before any new awards; keep meters, cash and payables intact."""
    changes = []
    programme = policy.new_support
    if programme is not None:
        if programme.awards or programme.reserved:
            raise ValueError("Solar duration must be configured before commitment awards")
        for key, offer in list(programme.offers.items()):
            if offer.technology != "solar" or offer.decision_year < 2014:
                continue
            current = replace(offer, eligible_years=min(offer.eligible_years, 20),
                              lifetime_hours=min(offer.lifetime_hours, 20 * 8760))
            if current != offer:
                programme.offers[key] = current
                changes.append(dict(kind="new_project_offer", year=offer.decision_year,
                    old_eligible_years=offer.eligible_years, eligible_years=current.eligible_years,
                    old_lifetime_hours=offer.lifetime_hours, lifetime_hours=current.lifetime_hours))
    for position in policy.positions:
        old = position["terms"]
        if old.actor != "solar" or old.commissioned_year < 2014:
            continue
        current = replace(old, eligible_years=min(old.eligible_years, 20),
                          lifetime_hours=min(old.lifetime_hours, 20 * 8760))
        if current != old:
            position["terms"] = current
            changes.append(dict(kind="inherited_project", project=old.project,
                old_eligible_years=old.eligible_years, eligible_years=current.eligible_years,
                old_lifetime_hours=old.lifetime_hours, lifetime_hours=current.lifetime_hours,
                preserved_prior_lifetime_mwh=position["prior_lifetime_mwh"]))
    return changes
