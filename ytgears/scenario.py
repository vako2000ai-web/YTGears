"""Backwards-compatible JSON scenario adapter; all money is parsed as Decimal."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

from .core import Donation, MechanismRound, RoundParameters, RoundPhase, SpeedPolicy, finite

POLICY_FIELDS = {
    "viewerSlope": "viewer_slope", "viewerTransitionSeconds": "viewer_transition_seconds",
    "viewerTimeoutSeconds": "viewer_timeout_seconds", "maximumMultiplier": "maximum_multiplier",
    "donationRule": "donation_rule", "donationDurationSeconds": "donation_duration_seconds",
}


def _fields(data, allowed, label):
    if not isinstance(data, dict): raise ValueError(f"{label}: a JSON object is required")
    unknown = data.keys() - set(allowed)
    if unknown: raise ValueError(f"{label}: unknown fields {', '.join(sorted(unknown))}")


def load_scenario(path):
    def invalid(value): raise ValueError(f"Invalid JSON number: {value}")
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_float=Decimal, parse_constant=invalid)
    _fields(data, ("roundId", "gearCount", "targetSeconds", "stepSeconds", "policy", "events"), "Scenario")
    return data


def run_scenario(data):
    _fields(data, ("roundId", "gearCount", "targetSeconds", "stepSeconds", "policy", "events"), "Scenario")
    policy = data.get("policy", {})
    _fields(policy, POLICY_FIELDS, "policy")
    round_ = MechanismRound(data.get("roundId", "simulation"),
                            RoundParameters(data.get("gearCount", 8), data.get("targetSeconds", 1800)),
                            SpeedPolicy(**{POLICY_FIELDS[k]: v for k, v in policy.items()}))
    step = finite(data.get("stepSeconds", 1), "stepSeconds", .01)
    if round_.transmission.parameters.target_seconds / step > 10_000_000:
        raise ValueError("Too many steps; increase stepSeconds")
    events = data.get("events", [])
    if not isinstance(events, list): raise ValueError("events: an array is required")
    validated = []
    for event in events:
        _fields(event, ("atSeconds", "type", "viewers", "roundId", "provider", "id", "amountUsd", "currency", "confirmed"), "Event")
        at = finite(event.get("atSeconds", 0), "atSeconds")
        if event.get("type") == "donation":
            payload = Donation(event.get("roundId", round_.round_id), event.get("provider", "simulator"),
                               event.get("id", ""), event.get("amountUsd", 0), event.get("currency", "USD"), event.get("confirmed", True))
        elif event.get("type") == "viewers":
            from .core import integer
            payload = event.get("viewers")
            if payload is not None: integer(payload, "viewers")
        else: raise ValueError("type: expected viewers or donation")
        validated.append((at, event["type"], payload))
    log = []
    for at, kind, payload in sorted(validated, key=lambda e: e[0]):
        while round_.phase == RoundPhase.RUNNING and round_.elapsed_seconds < at:
            round_.advance(min(step, at - round_.elapsed_seconds))
        if kind == "donation":
            status = round_.receive_donation(payload)
            log.append(f"{at:.6f}s donation {payload.provider}/{payload.event_id}: {status}")
        else:
            applied = round_.observe_viewers(payload)
            log.append(f"{at:.6f}s viewers={payload}: {'applied' if applied else 'round closed'}")
    while round_.phase == RoundPhase.RUNNING: round_.advance(step)
    round_.begin_destruction()
    round_.complete_destruction()
    result = asdict(round_.result)
    result["saved_seconds"] = round_.result.saved_seconds
    candidate = round_.transmission.approximate_teeth()
    tooth = asdict(candidate)
    tooth["wheel_count"] = candidate.wheel_count
    return {"mode": "SIMULATION — provisional policies, no YouTube or real payments",
            "configuration": data, "result": result, "tooth_candidate": tooth,
            "impact_count": round_.impact_count, "final_phase": round_.phase, "event_log": log}


def json_report(report):
    # Monetary values are lossless strings; timing values remain JSON numbers.
    return json.dumps(report, ensure_ascii=False, indent=2, default=lambda v: str(v) if isinstance(v, Decimal) else v, allow_nan=False)
