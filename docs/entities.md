# Entities

All entities are created dynamically based on data from the API response at setup time. Platform setup functions read from `coordinator.data["sekce"]`, `coordinator.data["pgm"]`, `coordinator.data["teplomery"]`, and `coordinator.data["pir"]` to populate Home Assistant entity registry.

## Temperature Sensors (`sensor.py`)

**Platform**: `SENSOR`

Each temperature sensor in the API response creates one `SensorEntity`:

| Property | Value |
|----------|-------|
| Name | `Jablotron {custom_name}` (e.g., "Jablotron Venku") |
| Device class | `temperature` |
| State class | `MEASUREMENT` |
| Unit | °C (Celsius) |
| Unique ID | `{entry_id}_teplomer_{sensor_id}` |

**Value source**: `coordinator.data["teplomery"][sensor_id]["value"]` → float or `None` if missing.

**Attributes**:
- `sensor_id` — API sensor key (e.g., `"040"`)
- `state_name` — API identifier (e.g., `"HEAT_40"`)
- `timestamp` — Unix timestamp (if present in response)

**Custom naming**: During config flow, each discovered temperature sensor can be given a custom name. Stored in `entry.data["sensor_names"]`. Default format: "Teploměr {sensor_id}".

---

## Next Update Sensor (`sensor.py`)

**Platform**: `SENSOR`

A single entity showing when the next periodic update will occur:

| Property | Value |
|----------|-------|
| Name | `Jablotron Next Update` |
| Device class | `TIMESTAMP` |
| Unique ID | `{entry_id}_next_update` |
| Icon | `mdi:update` |

**Value source**: `coordinator.last_updated + coordinator.update_interval` — computed from the timestamp of the last successful update.

**Attributes**:
- `last_update` — ISO format of last successful update
- `next_update` — ISO format of scheduled next update
- `update_interval_seconds` / `update_interval_minutes` — polling interval
- `seconds_until_next_update` / `minutes_until_next_update` — countdown
- `last_update_success` — boolean (coordinator state)

**Availability**: Only available once at least one successful update has occurred (the coordinator's `last_updated` timestamp is set).

---

## Alarm Section Binary Sensors (`binary_sensor.py`)

**Platform**: `BINARY_SENSOR`

Each section in the API response creates one `BinarySensorEntity`:

| Property | Value |
|----------|-------|
| Name | `Jablotron {section_nazev}` (e.g., "Jablotron Garáž") |
| Device class | `SAFETY` |
| Unique ID | `{entry_id}_section_{section_id}` |

**Value source**: `coordinator.data["sekce"][section_id]["stav"]` — `0` = OFF (disarmed), `1` = ON (armed).

**Attributes**:
- `section_id` — API section key (e.g., `"4"`)
- `nazev` — Section name in Czech
- `stav` — Raw state value (`0` or `1`)
- `state_name` — API identifier (e.g., `"STATE_5"`)
- `active` — Whether section is active/available
- `time` — Human-readable last state change timestamp

---

## PGM Binary Sensors (`binary_sensor.py`)

**Platform**: `BINARY_SENSOR`

Each PGM output in the API response creates a binary sensor, **unless** all three conditions are met: (1) a `pgm_code` is configured, (2) the PGM reaction type is switchable (`pgorSwitchOnOff` or `pgorPulse`), and (3) the user has control permission. In that case, a switch entity is created instead (see below).

> **v2.2 API note**: the mobile API reports real controllability — a PGM
> becomes a switch when the segment is flagged `segment_is_controllable`
> (plus account-level `controls_pgs`/not read-only) **and** a `pgm_code` is
> configured; non-controllable PGMs (indication outputs, door states) stay
> binary sensors. The PGM `reaction` type is not reported: everything is
> treated as bistable, so the pulse non-retry guard cannot be auto-applied
> to one-directional outputs (e.g. gate PGs).

| Property | Value |
|----------|-------|
| Name | `Jablotron {pgm_nazev}` (e.g., "Jablotron Osvětlení") |
| Unique ID | `{entry_id}_pgm_{pgm_id}` |

**Device class auto-detection** based on name keywords:

| Keywords in name | Device class |
|------------------|-------------|
| "dveře", "dore", "door" | `DOOR` |
| "vrata", "gate", "garáž", "garage" | `GARAGE_DOOR` |
| "okno", "window" | `WINDOW` |
| "pohyb", "pir", "motion" | `MOTION` |
| "zvon", "doorbell", "bell" | `SOUND` |
| (any other) | `POWER` |

**Value source**: `coordinator.data["pgm"][pgm_id]["stav"]` — `0` = OFF, `1` = ON.

**Attributes**:
- `pgm_id` — API PGM key (e.g., `"6"`)
- `nazev` — PGM name in Czech
- `stav` — Raw state value
- `state_name` — API identifier (e.g., `"PGM_7"`)
- `reaction` — Reaction type string
- `timestamp` / `time` — State change timing info

---

## PIR Motion Sensors (`binary_sensor.py`)

**Platform**: `BINARY_SENSOR`

> **Currently unavailable**: the v2.2 mobile API has no known data type that returns PIR motion data (the old web `stav.php` provided it). No PIR entities are created; this section documents the historical behavior and becomes active again if a data source is found. The `test_jablonet.py` probe checks for extended data types.

Each PIR sensor in the API response creates one binary sensor:

| Property | Value |
|----------|-------|
| Name | `Jablotron {pir_nazev}` (e.g., "Jablotron PIR Chodba") |
| Device class | `MOTION` |
| Unique ID | `{entry_id}_pir_{pir_id}` |

**Value source**: `coordinator.data["pir"][pir_id]["active"]` — `1` = ON (motion detected), `0` = OFF.

**Attributes**:
- `pir_id` — API PIR key (e.g., `"5"`)
- `nazev` — Sensor name in Czech
- `state_name` — API identifier (e.g., `"PPIR_6790289"`)
- `active` — Raw active state
- `type` — Device model (e.g., "JA-120PC")
- `last_picture` — Camera picture ID if available (`-1` means no camera, only shown when != -1)

---

## PGM Switches (`switch.py`)

**Platform**: `SWITCH`

Created **only** when: (1) a `pgm_code` is configured in the entry data, and (2) the PGM has a switchable reaction type (`pgorSwitchOnOff` or `pgorPulse`), and (3) the user has control permission (`permissions[stateName] == 1`).

All three conditions must be met. If any fails, the PGM appears as a binary sensor instead.

| Property | Value |
|----------|-------|
| Name | `Jablotron {pgm_nazev}` |
| Unique ID | `{entry_id}_pgm_switch_{pgm_id}` |

**Value source**: `coordinator.data["pgm"][pgm_id]["stav"]` (or optimistic state during control operation).

**Optimistic state management**: During a control operation, `_optimistic_state` temporarily freezes the switch to prevent coordinator updates from overwriting the UI:
1. Set `_optimistic_state = target_value` before API call
2. Clear it after successful API response processing OR on error (reverting to previous state)
3. Override `_handle_coordinator_update()` to skip coordinator writes while optimistic

**Control flow**:
1. `async_turn_on()` or `async_turn_off()` calls `_async_control_pgm(turn_on=True/False)`
2. Sets optimistic state, calls `client.control_pgm(pgm_id, command)` with status 0 or 1 (`retry_on_relogin=False` for pulse PGMs, so a session recovery never fires the command twice)
3. On success: reads `response["result"]`, updates the cached state via `coordinator.set_pgm_state()`
4. Clears optimistic state and triggers `coordinator.async_request_refresh()` to reconcile with the cloud
5. On failure: reverts to previous optimistic state

**Attributes**: Same as PGM binary sensors (`pgm_id`, `nazev`, `stav`, `state_name`, `reaction`, timing info).

---

## Force Update Button (`button.py`)

**Platform**: `BUTTON`

A single entity per config entry for manual trigger of data refresh:

| Property | Value |
|----------|-------|
| Name | `Jablotron Force Update` |
| Unique ID | `{entry_id}_force_update` |
| Icon | `mdi:sync` |

**Availability**: Always `True` — users can press even when coordinator has pending errors.

**Behavior**: Calls `coordinator.async_request_refresh()` which triggers the full API fetch → session handling → data push to entities.

---

## Entity Creation Summary

When a config entry is set up, all entities from all four platforms are created and added to Home Assistant in one batch. The number of entities depends entirely on the API response:

- 1 temperature sensor per entry in `teplomery` (often 0–5)
- + 1 next-update timestamp sensor
- 1 binary sensor per entry in `sekce` (typically 6–8 sections)
- N binary sensors or switches per entry in `pgm` (total PGMs minus switchable ones with code), typically 0–10
- M binary sensors per entry in `pir` (currently always 0 — see the PIR section above)

Entity count is determined at API call time during the first coordinator refresh (which runs before any platform setup).
