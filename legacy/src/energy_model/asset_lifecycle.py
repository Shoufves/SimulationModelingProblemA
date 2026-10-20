"""Evidence-limited asset event states, separate from dispatch and retirement."""
from collections import Counter
from copy import deepcopy
from datetime import date
from math import isfinite

KNOWLEDGE_RULE = "document_generated_date_replay_convention_not_verified_publication"


def iso(value):
    if not isinstance(value, str):
        raise ValueError("Expected ISO date")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Expected canonical ISO date")
    return parsed


def validate_case(data):
    if data.get("scope") != "documented_permit_case" or data.get("knowledge_rule") != KNOWLEDGE_RULE:
        raise ValueError("Unspecified asset scope or information convention")
    units = data["units"]
    by_id = {unit["unit_id"]: unit for unit in units}
    if not units or len(by_id) != len(units):
        raise ValueError("Empty or duplicate unit identities")
    for unit in units:
        if not all(isinstance(unit.get(key), str) and unit[key].strip()
                   for key in ("unit_id", "plant", "unit", "attachment_record_id")):
            raise ValueError("Missing unit identity")
        capacity = unit["capacity_mw"]
        if capacity is not None and (type(capacity) not in (int, float)
                                    or not isfinite(capacity) or capacity <= 0):
            raise ValueError("Invalid capacity")
        if unit["commercial_online_date"] is not None:
            iso(unit["commercial_online_date"])
    event_ids, event_dates = set(), set()
    for event in data["permit_events"]:
        if not event.get("event_id") or event["event_id"] in event_ids:
            raise ValueError("Duplicate or empty event identity")
        event_ids.add(event["event_id"])
        if event["unit_id"] not in by_id or event["source_id"] not in data["source_ids"]:
            raise ValueError("Unknown unit or event source")
        document, known, end = (iso(event[key]) for key in
                                ("document_date", "known_from", "valid_until"))
        if document > known or end < document:
            raise ValueError("Inconsistent event chronology")
        key = (event["unit_id"], known)
        if key in event_dates:
            raise ValueError("Ambiguous same-date event order")
        event_dates.add(key)
        if event["kind"] not in {"permit_record", "permit_extension"}:
            raise ValueError("Unsupported event kind")
    bindings = data["attachment_bindings"]
    if len({b["record_id"] for b in bindings}) != len(bindings):
        raise ValueError("Duplicate attachment binding")
    assigned = []
    for binding in bindings:
        if not binding.get("expected_name") or not binding["unit_ids"]:
            raise ValueError("Incomplete attachment binding")
        for unit_id in binding["unit_ids"]:
            if unit_id not in by_id or by_id[unit_id]["attachment_record_id"] != binding["record_id"]:
                raise ValueError("Attachment-to-unit identity mismatch")
            assigned.append(unit_id)
    if Counter(assigned) != Counter(by_id.keys()):
        raise ValueError("Each unit must bind to exactly one attachment record")
    fact_units = set()
    indicators = {row["indicator"]: row for row in data["observations"]}
    for fact in data["lifecycle_facts"]:
        unit_id = fact["unit_id"]
        if unit_id not in by_id or unit_id in fact_units:
            raise ValueError("Unknown or duplicate lifecycle unit")
        fact_units.add(unit_id)
        if fact["source_id"] not in data["source_ids"]:
            raise ValueError("Unknown lifecycle source")
        first, reference = iso(fact["first_grid_date"]), iso(fact["design_reference_end"])
        iso(fact["known_from"])
        indicator = indicators[fact["design_life_indicator"]]
        life = indicator["value"]
        if (indicator["unit"] != "year" or indicator["source_id"] != fact["source_id"]
                or type(life) is not int or life <= 0 or reference <= first
                or reference.year - first.year != life):
            raise ValueError("Inconsistent design-life fact")
    return by_id


def bind_attachments(data, attachment_data):
    """Retain original plant-level rows; do not assign their unknown units to reactors."""
    validate_case(data)
    records = attachment_data["records"]
    by_id = {r["record_id"]: r for r in records}
    if len(by_id) != len(records):
        raise ValueError("Duplicate processed attachment identity")
    result = []
    for binding in data["attachment_bindings"]:
        record = by_id.get(binding["record_id"])
        if (record is None or record["name"] != binding["expected_name"]
                or record["source_file"] != "附件4.xlsx" or record["technology"] != "nuclear"):
            raise ValueError("Attachment record identity changed")
        result.append({
            "record_id": record["record_id"], "original_name": record["original_name"],
            "source_file": record["source_file"], "sheet": record["sheet"], "row": record["row"],
            "original_capacity": record["original_capacity"], "original_unit": record["original_unit"],
            "unit_ids": list(binding["unit_ids"]),
            "capacity_conversion": None, "national_weight": None,
        })
    return result


def snapshot(data, as_of, *, evidence_cutoff, disabled_event_ids=()):
    """Only already visible documents affect a state; expiry alone never retires a unit."""
    validate_case(data)
    target = iso(as_of)
    cutoff = min(target, iso(evidence_cutoff))
    disabled = set(disabled_event_ids)
    if disabled - {event["event_id"] for event in data["permit_events"]}:
        raise ValueError("Unknown disabled event")
    visible = [event for event in data["permit_events"]
               if event["event_id"] not in disabled and iso(event["known_from"]) <= cutoff]
    facts = {f["unit_id"]: f for f in data["lifecycle_facts"] if iso(f["known_from"]) <= cutoff}
    rows = []
    for unit in data["units"]:
        events = [e for e in visible if e["unit_id"] == unit["unit_id"]]
        latest = max(events, key=lambda e: e["known_from"]) if events else None
        status = ("no_visible_permit_record" if latest is None else
                  "covered_by_recorded_end_date" if target <= iso(latest["valid_until"]) else
                  "recorded_end_passed_needs_review")
        fact = facts.get(unit["unit_id"])
        rows.append({
            "unit_id": unit["unit_id"], "plant": unit["plant"], "unit": unit["unit"],
            "attachment_record_id": unit["attachment_record_id"],
            "permit_status": status, "latest_visible_event": deepcopy(latest),
            "visible_lifecycle_fact": deepcopy(fact),
            "design_reference_reached": None if fact is None else target >= iso(fact["design_reference_end"]),
            "capacity_mw": unit["capacity_mw"], "actual_operating_status": None,
            "actual_retired": None, "dispatch_available_capacity_mw": None,
        })
    return {
        "as_of": as_of, "information_cutoff": cutoff.isoformat(),
        "interpretation": "document_replay" if target <= iso(evidence_cutoff) else
                          "existing_document_end_dates_only_not_a_retirement_forecast",
        "units": rows, "permit_counts": dict(Counter(r["permit_status"] for r in rows)),
        "actual_operating_capacity_mw": None, "actual_retired_capacity_mw": None,
        "national_expansion_weight": None,
    }
