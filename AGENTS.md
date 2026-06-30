# AGENTS — Navigation Guide

This file helps LLM agents navigate the Jablotron Web integration codebase efficiently. Read these files before making changes or answering questions.

## Documentation Quick Map

| Task | Read first | Then if needed |
|------|-----------|----------------|
| **How does this component work?** | [docs/architecture.md](docs/architecture.md) | — |
| **What does the API look like?** | [docs/api-reference.md](docs/api-reference.md) | `test_jablonet.py` for a runnable example |
| **What entities are created?** | [docs/entities.md](docs/entities.md) | Read the specific platform file (`sensor.py`, `binary_sensor.py`, `switch.py`) |
| **How does session/login work?** | [docs/session-management.md](docs/session-management.md) | `jablotron_client.py` for implementation details |
| **What config options exist?** | [docs/configuration.md](docs/configuration.md) | `config_flow.py` and `const.py` |
| **Alternative YAML approach** | [docs/static-sensors.md](docs/static-sensors.md) | `static_sensors/jablotron_sensors.yaml` |

## Core Files (in rough dependency order)

1. **[custom_components/jablotron_web/const.py](custom_components/jablotron_web/const.py)** — All constants, API URLs, defaults. The foundational reference.
2. **[custom_components/jablotron_web/manifest.json](custom_components/jablotron_web/manifest.json)** — HA integration metadata (version, domain, capabilities).
3. **[custom_components/jablotron_web/jablotron_client.py](custom_components/jablotron_web/jablotron_client.py)** — The single HTTP client. All API calls flow through here. Read this to understand authentication and session recovery.
4. **[custom_components/jablotron_web/__init__.py](custom_components/jablotron_web/__init__.py)** — Integration entry point. Sets up coordinator, manages lifecycle, dispatches to platforms.
5. **[custom_components/jablotron_web/config_flow.py](custom_components/jablotron_web/config_flow.py)** — UI config flow (setup, options, reauth).
6. **Platform files**: `sensor.py`, `binary_sensor.py`, `switch.py`, `button.py` — Entity definitions. All extend `CoordinatorEntity` and read from the shared coordinator data dict.

## Key Concepts at a Glance

- **Domain**: `jablotron_web` (from `const.py` and `manifest.json`)
- **Entry point**: `async_setup_entry()` in `__init__.py`
- **Central pattern**: One `DataUpdateCoordinator` per config entry fetches all data via `client.get_status()`. All entities read from `coordinator.data`.
- **Auth flow**: 4-step browser-like login (homepage → login.php → /cloud → /app/ja100) storing PHPSESSID and lastMode cookies.
- **Session handling**: On session expiry, automatic re-login + retry API call. If re-login also fails, configurable delay (default 5 min).
- **Entity creation**: Dynamic at setup time based on API response data. No static entity list.
- **PGM switches vs binary sensors**: Switchable PGMs (`pgorSwitchOnOff`, `pgorPulse`) with a configured `pgm_code` and user permission become switches. Everything becomes binary sensors.

## Where to Find Things

| Need | File(s) |
|------|---------|
| Change defaults (interval, timeout, retry delay) | `const.py` |
| Add new config field | `const.py` → `config_flow.py` |
| Change API URL or add endpoint | `const.py` + `jablotron_client.py` |
| New entity type | Create platform file + add to `PLATFORMS` in `__init__.py` |
| PGM control logic | `switch.py::_async_control_pgm()` and `jablotron_client.py::_control_pgm_internal()` |
| Entity naming / locale strings | `translations/en.json`, `translations/cs.json` |
| Service definitions (HA UI) | `services.yaml` |

## Testing Changes

1. Test API connectivity: `python test_jablonet.py <email> <password> [service_id]`
2. Install to HA: Copy `custom_components/` into `/config/custom_components/`, restart HA
3. Enable debug logging:
   ```yaml
   logger:
     logs:
       custom_components.jablotron_web: debug
   ```
4. Check entities in Developer Tools → States

