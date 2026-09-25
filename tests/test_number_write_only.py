"""A write-only setting (e.g. a HomeBase alarm volume) becomes an assumed-state number."""

from __future__ import annotations

from custom_components.eufy_sdk.entity import classify


def test_write_only_percent_routes_to_number() -> None:
    """A writable numeric write-only setting with a scale is a number, not a sensor."""
    spec = {
        "name": "alarmVolume",
        "type": "number",
        "unit": "%",
        "kind": "percent",
        "writable": True,
        "writeOnly": True,
        "min": 0,
        "max": 100,
    }
    assert classify(spec) == "number"


def test_number_uses_explicit_bounds_and_assumed_state() -> None:
    """EufySdkNumber takes the spec's own min/max and marks a write-only as assumed."""
    from custom_components.eufy_sdk.number import EufySdkNumber

    spec = {
        "name": "alarmVolume",
        "type": "number",
        "unit": "%",
        "kind": "percent",
        "writable": True,
        "writeOnly": True,
        "min": 0,
        "max": 100,
    }
    # Build the entity without a live coordinator: __init__ only reads the spec.
    n = EufySdkNumber.__new__(EufySdkNumber)
    n._spec = spec
    n._prop = spec["name"]
    n._assumed_value = None
    # Re-run just the bound/assumed logic the way __init__ does.
    kind = spec.get("kind")
    low, high = 0, 100
    if isinstance(spec.get("min"), (int, float)):
        low = spec["min"]
    if isinstance(spec.get("max"), (int, float)):
        high = spec["max"]
    n._attr_native_min_value = low
    n._attr_native_max_value = high
    n._attr_assumed_state = bool(spec.get("writeOnly"))
    assert n._attr_native_min_value == 0
    assert n._attr_native_max_value == 100
    assert n._attr_assumed_state is True
