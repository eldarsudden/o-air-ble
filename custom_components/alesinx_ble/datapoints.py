"""O-Air datapoints from its tuya-local device profile.

This schema describes commands, not proof that firmware reports a value.
No units are invented for the manufacturer's undocumented corrections.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Datapoint:
    id: int
    key: str
    kind: int
    minimum: int | None = None
    maximum: int | None = None
    unit: str | None = None
    device_class: str | None = None
    enabled: bool = True
    options: tuple = ()


ACTIONS = ("OPEN", "CLOSE", "MICRO", "VENTILATE")
WINDOW_STATES = ("OPEN", "CLOSE", "VENTILATE", "MICRO") + (
    "EXT_OPEN",
    "OPENING",
    "VENT_OPENING",
    "MICRO_OPENING",
    "CLOSING",
)
EVENTS = (
    "TEMPHI",
    "TEMPLO",
    "TEMPBACK",
    "AIRQBAD",
    "AIRQBACK",
    "TIMEREVT",
    "EXTOPEN",
    "BATTLOW",
    "WINDHI",
    "CLOSEFAIL",
    "CUROVLOAD",
    "REBOOT",
    "OPENFAIL",
)

NUMBERS = (
    Datapoint(129, "opening_limit", 2, 0, 100, "%"),
    Datapoint(106, "maximum_temperature", 2, 0, 60, "°C", "temperature"),
    Datapoint(107, "minimum_temperature", 2, 0, 60, "°C", "temperature"),
    Datapoint(108, "tvoc_threshold", 2, 1, 9999, "ppb"),
    Datapoint(112, "opening_interval", 2, 0, 1440, "min", "duration"),
    Datapoint(113, "opening_duration", 2, 1, 1440, "min", "duration"),
    Datapoint(114, "belt_retraction_limit", 2, 100, 1000, enabled=False),
    Datapoint(115, "current_overload_threshold", 2, 100, 700, enabled=False),
    Datapoint(135, "humidity_calibration", 2, 0, 99, enabled=False),
    Datapoint(136, "heater_time_correction", 2, 0, 99, enabled=False),
)
SWITCHES = (
    Datapoint(109, "scenario", 1),
    Datapoint(111, "timer", 1),
    Datapoint(116, "sound", 1),
    Datapoint(134, "tvoc_display", 1),
)
SCENARIO_ACTION = Datapoint(110, "scenario_action", 4, options=ACTIONS)
CHILD_LOCK = Datapoint(133, "child_lock", 1)
CONTROL = Datapoint(
    101, "control", 4, options=("OPEN", "VENTILATE", "MICRO", "CLOSE", "CALIBRATE")
)
WRITABLE = {
    dp.id: dp for dp in (*NUMBERS, *SWITCHES, SCENARIO_ACTION, CHILD_LOCK, CONTROL)
}
READINGS = (
    Datapoint(101, "last_control", 4, options=CONTROL.options),
    Datapoint(132, "opening_position", 2, 0, 100, "%"),
    Datapoint(119, "window_action", 4, options=WINDOW_STATES),
    Datapoint(117, "open_time_remaining", 2, 0, 1440, "min", "duration"),
    Datapoint(118, "time_until_next_opening", 2, 0, 1440, "min", "duration"),
    Datapoint(120, "tvoc", 2, 0, 9999, "ppb", "volatile_organic_compounds_parts"),
    Datapoint(121, "temperature", 2, -45, 85, "°C", "temperature"),
    Datapoint(122, "humidity", 2, 0, 100, "%", "humidity"),
    Datapoint(123, "battery", 2, 0, 100, "%", "battery"),
    Datapoint(127, "atmospheric_pressure", 2, 220, 830, "mmHg", "atmospheric_pressure"),
    Datapoint(128, "wifi_signal", 2, 0, 100, "%"),
    Datapoint(130, "wind_level", 2, 0, 100),
    Datapoint(131, "last_event", 4, options=EVENTS),
)
ALL_IDS = tuple(sorted(set(WRITABLE) | {dp.id for dp in READINGS}))


def validate_value(dp, value):
    if dp.kind == 1:
        valid = isinstance(value, bool)
    elif dp.kind == 2:
        valid = isinstance(value, int) and not isinstance(value, bool)
        valid = valid and (dp.minimum is None or value >= dp.minimum)
        valid = valid and (dp.maximum is None or value <= dp.maximum)
    else:
        valid = isinstance(value, str) and (not dp.options or value in dp.options)
    if not valid:
        raise ValueError("Invalid O-Air datapoint value")
    return value


def reported_value(datapoints, dp):
    report = datapoints.get(dp.id, {})
    if report.get("type") != dp.kind:
        return None
    try:
        value = report.get("value")
        if dp.kind == 4:
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value < len(dp.options)
            ):
                return None
            return dp.options[value]
        return validate_value(dp, value)
    except ValueError:
        return None
