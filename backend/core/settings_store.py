"""
Reading and writing the settings an administrator can change from the UI.

Resolution order for every value: **database, then environment, then a
hardcoded default.** That means `.env` keeps working as the deployment
default, and anything changed in the Settings page overrides it without a
restart or a redeploy.

Every setting is declared once, in SETTINGS_SPEC below, with its type, its
environment-variable name and a sentence explaining what it does. The API
renders that spec directly, so adding a knob here makes it appear in the UI
with no frontend change at all.
"""
from __future__ import annotations

import os

# key -> spec
SETTINGS_SPEC = {
    "organisation_name": {
        "label": "Organisation name",
        "type": "text",
        "env": "ORGANISATION_NAME",
        "default": "GST Circular-Trade Fraud Detection",
        "help": "Shown at the top of every case report a supervisor receives.",
        "group": "Reports",
    },
    "report_supervisor_emails": {
        "label": "Supervisor email addresses",
        "type": "text",
        "env": "REPORT_SUPERVISOR_EMAILS",
        "default": "",
        "help": (
            "Comma-separated. Copied on every case report alongside the officer "
            "who issued it. Anyone in the Supervisors group with an email on "
            "their account is added automatically as well."
        ),
        "group": "Reports",
    },
    "risk_threshold": {
        "label": "High-risk threshold",
        "type": "number",
        "env": "RISK_THRESHOLD",
        "default": "70",
        "help": (
            "Score at or above which an alert counts as high risk. A policy "
            "choice: lower it to catch more and investigate more, raise it to "
            "spend less officer time. Every detection run and every ledger "
            "block records the value in force when it ran."
        ),
        "group": "Detection",
        "min": 1,
        "max": 99,
    },
    "mill_min_score": {
        "label": "Invoice-mill alert threshold",
        "type": "number",
        "env": "MILL_MIN_SCORE",
        "default": "45",
        "help": (
            "Minimum score before a suspected fake invoice mill is raised as an "
            "alert. Mills are scored by explicit rules, not the ML model."
        ),
        "group": "Detection",
        "min": 1,
        "max": 99,
    },
    "max_ring_size": {
        "label": "Longest ring to search for",
        "type": "number",
        "env": "MAX_RING_SIZE",
        "default": "6",
        "help": (
            "Real ITC rings are short - the point is to return the credit "
            "quickly. Raising this finds longer rings but makes cycle "
            "enumeration dramatically more expensive."
        ),
        "group": "Detection",
        "min": 2,
        "max": 10,
    },
}


def _raw(key: str) -> str:
    """DB value if one exists, else the environment, else the default."""
    spec = SETTINGS_SPEC.get(key)
    if spec is None:
        raise KeyError(f"Unknown setting: {key}")

    # Imported here rather than at module scope: settings_store is imported by
    # code that runs during app loading, before the model registry is ready.
    from .models import AppSetting

    try:
        row = AppSetting.objects.filter(key=key).first()
    except Exception:
        # No table yet (first migrate) - fall through to env/default.
        row = None

    if row is not None and row.value != "":
        return row.value
    return os.getenv(spec["env"], spec["default"])


def get_setting(key: str) -> str:
    return _raw(key)


def get_float(key: str) -> float:
    try:
        return float(_raw(key))
    except (TypeError, ValueError):
        return float(SETTINGS_SPEC[key]["default"])


def get_int(key: str) -> int:
    try:
        return int(float(_raw(key)))
    except (TypeError, ValueError):
        return int(float(SETTINGS_SPEC[key]["default"]))


def get_email_list(key: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in str(_raw(key) or "").replace(";", ",").split(","):
        email = part.strip()
        if email and email.lower() not in seen:
            seen.add(email.lower())
            out.append(email)
    return out


def set_setting(key: str, value, user=None) -> str:
    """Store an override. An empty value falls back to env/default again."""
    if key not in SETTINGS_SPEC:
        raise KeyError(f"Unknown setting: {key}")

    from .models import AppSetting

    text = "" if value is None else str(value).strip()
    AppSetting.objects.update_or_create(
        key=key,
        defaults={
            "value": text,
            "updated_by": user if (user is not None and user.is_authenticated) else None,
        },
    )
    return text


def describe_all() -> list[dict]:
    """Every setting with its current value and where that value came from."""
    from .models import AppSetting

    try:
        overrides = dict(AppSetting.objects.values_list("key", "value"))
    except Exception:
        overrides = {}

    out = []
    for key, spec in SETTINGS_SPEC.items():
        overridden = bool(overrides.get(key))
        out.append(
            {
                "key": key,
                "label": spec["label"],
                "type": spec["type"],
                "help": spec["help"],
                "group": spec["group"],
                "value": _raw(key),
                "default": spec["default"],
                "env_var": spec["env"],
                "source": "database" if overridden else (
                    "environment" if os.getenv(spec["env"]) is not None else "default"
                ),
                **({"min": spec["min"], "max": spec["max"]} if "min" in spec else {}),
            }
        )
    return out
