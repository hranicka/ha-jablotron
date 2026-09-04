# Architecture Overview

Home Assistant custom component for Jablotron JA-100 alarm systems, connecting via the [jablonet.net](https://www.jablonet.net) cloud API as an automated browser session.

## Core Components

### `__init__.py` — Integration Entry Point

Handles the Home Assistant config entry lifecycle: setup, reload, unload. Creates a `JablotronClient`, a `DataUpdateCoordinator`, and forwards to all platforms.

- **Platforms**: `SENSOR`, `BINARY_SENSOR`, `SWITCH`, `BUTTON`
- **Data flow**: Stores `{"coordinator", "client"}` under `hass.data[DOMAIN][entry_id]`; the last successful update timestamp lives on `coordinator.last_updated`
- **First refresh** runs synchronously before any entities are created, ensuring data is available at entity setup time

### `config_flow.py` — Configuration UI

Two handler classes:

1. **`JablotronConfigFlow`** — initial setup with 2 steps:
   - `user`: credentials + optional service_id and pgm_code
   - `sensors`: customize temperature sensor names (auto-discovered from API)
   - `reauth`: triggered automatically when auth fails; pre-fills existing values

2. **`JablotronOptionsFlowHandler`** — post-setup options:
   - Credentials (username, password, service_id, pgm_code) trigger a reload on change
   - Toggles only update options (`scan_interval`, `timeout`, `retry_delay`)

### `jablotron_client.py` — API Client

HTTP wrapper over jablonet.net with automatic session management:

- **4-step login**: homepage → login.php → /cloud → /app/ja100
- **Session recovery**: on session expiry, resets cookies and re-login immediately; if re-login fails, sets a configurable retry delay (default 5 min)
- **Two public methods**: `get_status()` for all sensor data, `control_pgm()` for PGM output control

### Platform Files

All platforms extend `CoordinatorEntity`, reading from the shared `DataUpdateCoordinator` data:

| File | Entities | Data Source |
|------|----------|-------------|
| `sensor.py` | Temperature sensors, Next Update timestamp | `teplomery` |
| `binary_sensor.py` | Alarm sections, PGM status, PIR motion | `sekce`, `pgm`, `pir` |
| `switch.py` | Controllable PGM outputs | `pgm` (requires pgm_code) |
| `button.py` | Force update button | N/A (triggers coordinator refresh) |

### `services.py` — Custom Services

Two services registered under the `jablotron_web` domain:

- **`reload`**: Reload all config entries (discovers new sensors after upgrades)
- **`update`**: Trigger immediate data refresh for all coordinators

Services are registered only on the first config entry and unregistered when the last one is removed.

## Data Flow

```
User adds integration (config_flow.py)
  → Validate credentials via jablotron_client.login()
  → Discover temperature sensors from jablotron_client.get_status()
  → Create config entry with sensor names

Home Assistant calls __init__.py::async_setup_entry()
  → JablotronClient(username, password, service_id, pgm_code)
  → DataUpdateCoordinator(update_method=client.get_status, interval=scan_interval)
  → coordinator.async_config_entry_first_refresh()  ← triggers login if needed
    → session has no cookies? → login() [4-step]
    → GET /app/ja100/ajax/stav.php → {teplomery, pgm, sekce, pir, permissions}
  → Forward to all 4 platforms
    → Platforms read coordinator.data to discover entities
  → Register custom services (first entry only)

Ongoing operation:
  Coordinator polls at scan_interval (default 300s)
  On JablotronSessionError → automatic session recovery
  On JablotronAuthError → ConfigEntryAuthFailed → reauth flow

User controls PGM switch:
  switch._async_control_pgm(turn_on=True)
    → Set optimistic state (freezes coordinator updates)
    → client.control_pgm(pgm_id, 1)  [retry_on_relogin=False for pulse PGMs]
    → coordinator.set_pgm_state() with response result
    → coordinator.async_request_refresh() → full sync
    → Clear optimistic state
```

## State Storage

Entities are keyed by `unique_id` under `hass.data["jablotron_web"][entry_id]`:

Pattern: `{entry_id}_{entity_type}_{id}`

- Temperature: `{entry_id}_teplomer_{sensor_id}`
- Sections: `{entry_id}_section_{section_id}`
- PGM (binary): `{entry_id}_pgm_{pgm_id}`
- PGM (switch): `{entry_id}_pgm_switch_{pgm_id}`
- PIR: `{entry_id}_pir_{pir_id}`
- Next update: `{entry_id}_next_update`

The coordinator stores full raw API response in `coordinator.data`. All entities read from this shared dict. After a PGM control command, the switch updates the cached state via `coordinator.set_pgm_state(pgm_id, stav, ts)` — the single sanctioned mutation path for coordinator data during normal operation (`JablotronDataCoordinator` in `__init__.py`).

## Version Info

- **Component version**: 0.0.35 (manifest.json)
- **HA minimum**: 2025.12.0 (hacs.json) — `ConfigFlowResult`, automatic `OptionsFlow.config_entry`, and explicit `DataUpdateCoordinator(config_entry=...)`
- **Integration type**: hub (aggregation, forwards to platforms)
- **IoT class**: cloud_polling
