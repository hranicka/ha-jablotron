"""Adapter: MyJABLOTRON API v2.2 payloads → legacy stav.php-shaped dicts.

The platforms (sensor/binary_sensor/switch) and the coordinator consume the
flat dict shape of the old www.jablonet.net `stav.php` endpoint. This module
translates the v2.2 `dataUpdate.json` response into that shape so the
platform layer needs no changes.

Legacy key numbering must be preserved because entity unique_ids derive from
it (e.g. `pgm["6"]` has stateName `PGM_7`, `teplomery["040"]` matches
`THERMOMETER_40` — confirmed against a live account, 2026-09).

Facts confirmed against a live account (2026-09-08 probes):
- Every segment carries `segment_is_controllable`; the account carries
  `service_permissions.controls_pgs` / `service_readonly`. Together these
  replace the old server-side `permissions` map for PGM gating.
- PIR motion data does not exist in v2.2 (probed data_types pir/peripheral/
  device/camera/window — all empty) → `pir` stays empty.
- PGM `reaction` (bistable vs pulse) is not reported → defaults to
  `pgorSwitchOnOff`; only the rare retry-after-relogin pulse guard is lost.
- dataUpdate's thermometer values are a STALE cache (the string "unknown"
  for online peripheries); live readings come from thermoDevicesGet.json
  (data.states[] with object-device-id, temperature, last-temperature-time)
  and are joined by `THM-{segment_db_id}` → segment_db_id.
"""
import time
from datetime import datetime
from typing import Any

from .const import (
    PGM_REACTION_SWITCH,
    PGM_STATE_OFF,
    PGM_STATE_ON,
    SEGMENT_PREFIX_PGM,
    SEGMENT_PREFIX_SECTION,
    SEGMENT_PREFIX_THERMOMETER,
    SEGMENT_PREFIX_THERMOSTAT,
)


def _segment_number(segment_id: str, prefix: str) -> int | None:
    """Extract the numeric suffix of a segment id (e.g. PGM_7 → 7)."""
    try:
        return int(segment_id[len(prefix):])
    except ValueError:
        return None


def _legacy_key(segment_id: str, prefix: str) -> str:
    """Map a segment id to its legacy stav.php dict key.

    Legacy keys are the stateName number minus one (PGM_7 → "6"); fall back
    to the raw segment id if the suffix is not a positive number.
    """
    number = _segment_number(segment_id, prefix)
    if number is not None and number >= 1:
        return str(number - 1)
    return segment_id


def _segment_stav(segment_state: Any) -> int:
    """Map segment_state to legacy stav 0/1 (anything but "unset" is on)."""
    return PGM_STATE_OFF if segment_state == "unset" else PGM_STATE_ON


def _first_temperature(segment: dict[str, Any]) -> tuple[float | None, int | None]:
    """First numeric value from segment_informations, plus its timestamp.

    The API reports the string "unknown" (or other non-numeric placeholders)
    when a thermometer periphery is offline — such entries are skipped, so
    the sensor resolves to unavailable rather than a bogus value.
    """
    for info in segment.get("segment_informations") or []:
        if not isinstance(info, dict):
            continue
        raw = info.get("value")
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        info_time = segment.get("segment_informations_time")
        ts = info_time if isinstance(info_time, int) else None
        return value, ts
    return None, None


def _adapt_section(result: dict[str, Any], segment: dict[str, Any], segment_id: str) -> None:
    """STATE_n → result["sekce"][str(n-1)]."""
    result["sekce"][_legacy_key(segment_id, SEGMENT_PREFIX_SECTION)] = {
        "stav": _segment_stav(segment.get("segment_state")),
        "nazev": str(segment.get("segment_name") or ""),
        "stateName": segment_id,
        "active": 1,
    }


def _adapt_pgm(
    result: dict[str, Any],
    segment: dict[str, Any],
    segment_id: str,
    has_pgm_code: bool,
    controls_allowed: bool,
) -> None:
    """PGM_n → result["pgm"][str(n-1)] (+ permission from the real flags).

    A PGM is exposed as controllable (legacy `permissions`) only when the
    account may control PGs at all, the segment itself is controllable, and
    the user configured a PGM code — mirroring the old triple condition.
    """
    result["pgm"][_legacy_key(segment_id, SEGMENT_PREFIX_PGM)] = {
        "stav": _segment_stav(segment.get("segment_state")),
        "nazev": str(segment.get("segment_name") or ""),
        "stateName": segment_id,
        "reaction": PGM_REACTION_SWITCH,
    }
    if (
        has_pgm_code
        and controls_allowed
        and segment.get("segment_is_controllable") is True
    ):
        result["permissions"][segment_id] = 1


def _parse_iso_timestamp(value: Any) -> int | None:
    """Parse an ISO timestamp like 2026-09-08T15:51:03+02:00 to unix seconds."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp())
    except ValueError:
        return None


def thermo_state_map(thermo_payload: dict[str, Any] | None) -> dict[int, tuple[float, int | None]]:
    """Index thermoDevicesGet states by their numeric device id.

    Live readings arrive as data.states[] entries
    {"object-device-id": "THM-6790417", "temperature": 28,
     "last-temperature-time": "..."} — the numeric suffix equals the
    dataUpdate thermometer segment's `segment_db_id`.
    """
    states = ((thermo_payload or {}).get("data") or {}).get("states") or []
    result: dict[int, tuple[float, int | None]] = {}
    for state in states:
        if not isinstance(state, dict):
            continue
        device_id = str(state.get("object-device-id") or "")
        suffix = device_id[4:] if device_id.startswith("THM-") else ""
        temperature = state.get("temperature")
        if not suffix.isdigit() or not isinstance(temperature, (int, float)):
            continue
        result[int(suffix)] = (
            float(temperature),
            _parse_iso_timestamp(state.get("last-temperature-time")),
        )
    return result


def _adapt_thermometer(
    result: dict[str, Any],
    segment: dict[str, Any],
    segment_id: str,
    prefix: str,
    live_states: dict[int, tuple[float, int | None]] | None = None,
) -> None:
    """THERMOMETER_n / THERMOSTAT_n → result["teplomery"].

    Thermometers keep the legacy zero-padded key (HEAT_40 ↔ "040" numbering)
    so existing entity unique_ids survive. Thermostats get a "t"-prefixed
    key — THERMOMETER_1 and THERMOSTAT_1 must not collide on "001".

    Values come from the live thermoDevicesGet reading when available
    (joined via segment_db_id — dataUpdate's own value is a stale cache that
    reads "unknown" for online peripheries); the cached value is only a
    fallback when no live reading exists.
    """
    live: tuple[float, int | None] | None = None
    db_id = segment.get("segment_db_id")
    if live_states is not None:
        try:
            live = live_states.get(int(db_id))
        except (TypeError, ValueError):
            live = None
    if live is not None:
        value, ts = live
    else:
        value, ts = _first_temperature(segment)
        if value is None:
            return
    number = _segment_number(segment_id, prefix)
    if number is None:
        key = segment_id
    elif prefix == SEGMENT_PREFIX_THERMOSTAT:
        key = f"t{number:03d}"
    else:
        key = f"{number:03d}"
    item: dict[str, Any] = {
        "value": value,
        "stateName": segment_id,
    }
    if ts is not None:
        item["ts"] = ts
    result["teplomery"][key] = item


def _adapt_pir(result: dict[str, Any], segment: dict[str, Any], segment_id: str) -> None:
    """PIR segments → result["pir"] (defensive; no confirmed v2.2 source yet)."""
    result["pir"][segment_id] = {
        "active": _segment_stav(segment.get("segment_state")),
        "nazev": str(segment.get("segment_name") or ""),
        "stateName": segment_id,
    }


def _controls_allowed(entry: dict[str, Any]) -> bool:
    """Whether the account may control PG outputs at all.

    Combines `service_information.service_readonly` (must be false) with
    `service_permissions.controls_pgs` (must be true). Missing fields
    default to allowed — a degraded payload should not silently strip
    switches.
    """
    info = entry.get("service_information") or {}
    if info.get("service_readonly") is True:
        return False
    permissions = info.get("service_permissions") or {}
    if permissions.get("controls_pgs") is False:
        return False
    return True


def _pick_service_entry(payload: dict[str, Any], service_id: str) -> dict[str, Any] | None:
    """Find the service_data entry for service_id (fall back to the first)."""
    service_data = ((payload.get("data") or {}).get("service_data")) or []
    for entry in service_data:
        if str(entry.get("service_id")) == str(service_id):
            return entry
    return service_data[0] if service_data else None


def adapt_data_update(
    payload: dict[str, Any],
    *,
    service_id: str,
    has_pgm_code: bool = False,
    thermo_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a dataUpdate.json response into the legacy stav.php shape.

    `thermo_payload` is an optional thermoDevicesGet.json response providing
    live thermometer readings; without it (or without a matching reading)
    the stale cached values from dataUpdate are used, and "unknown" ones
    yield no sensor at all.

    Always returns all four item dicts (possibly empty) plus `permissions`
    and `timeStamp`, so consumers can rely on the keys being present.
    """
    result: dict[str, Any] = {
        "status": 200,
        "sekce": {},
        "pgm": {},
        "teplomery": {},
        "pir": {},
        "permissions": {},
        "timeStamp": int(time.time()),
    }

    entry = _pick_service_entry(payload, service_id)
    if entry is None:
        return result

    controls_allowed = _controls_allowed(entry)
    live_thermo = thermo_state_map(thermo_payload)
    for block in entry.get("data") or []:
        data_type = block.get("data_type")
        segments = (block.get("data") or {}).get("segments") or []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            segment_id = str(segment.get("segment_id") or "")
            if not segment_id:
                continue
            if data_type == "section" and segment_id.startswith(SEGMENT_PREFIX_SECTION):
                _adapt_section(result, segment, segment_id)
            elif data_type == "pgm" and segment_id.startswith(SEGMENT_PREFIX_PGM):
                _adapt_pgm(result, segment, segment_id, has_pgm_code, controls_allowed)
            elif data_type == "thermometer" and segment_id.startswith(SEGMENT_PREFIX_THERMOMETER):
                _adapt_thermometer(result, segment, segment_id, SEGMENT_PREFIX_THERMOMETER, live_thermo)
            elif data_type == "thermostat" and segment_id.startswith(SEGMENT_PREFIX_THERMOSTAT):
                _adapt_thermometer(result, segment, segment_id, SEGMENT_PREFIX_THERMOSTAT, live_thermo)
            elif data_type == "pir":
                _adapt_pir(result, segment, segment_id)

    return result


def adapt_control_response(requested_status: int) -> dict[str, Any]:
    """Build the legacy ovladani2.php-shaped control result.

    switch.py consumes `{"result": 0|1, "ts": unix_ts}`; v2.2 controlSegment
    only reports success/failure, so the requested state is echoed back and
    the authoritative value arrives with the next poll.
    """
    return {
        "result": int(requested_status),
        "ts": int(time.time()),
    }
