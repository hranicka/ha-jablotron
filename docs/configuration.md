# Configuration

## Setup (Config Flow)

The config flow runs when a user adds the `Jablotron Web` integration through Home Assistant UI:

1. **Settings → Devices & Services → Add Integration → Jablotron Web**

### Step 1 — Credentials

| Field | Required | Description |
|-------|----------|-------------|
| Email (username) | Yes | Jablotron account email address |
| Password | Yes | Jablotron account password (stored encrypted by Home Assistant) |
| Service ID | No | Specific service identifier for multi-service accounts (house, car, etc.) |
| PGM Control Code | No | 4-digit PIN for controlling PGM outputs. If omitted, PGM switchable outputs appear as read-only binary sensors |

On submit: credentials are tested by calling `client.login()`. If valid, `get_status()` is called to discover available temperature sensors.

### Step 2 — Sensor Naming (conditional)

If the API returns temperature sensors, this step appears:

| Field | Default | Description |
|-------|---------|-------------|
| Custom name per sensor | "Teploměr {sensor_id}" | Override for each discovered temperature sensor |

The custom names are stored in `entry.data["sensor_names"]` and reused at every entity creation. Users can also rename sensors later through the Home Assistant UI.

### Reauth Flow

Triggered automatically by Home Assistant when `ConfigEntryAuthFailed` is raised (usually after `JablotronAuthError` during a coordinator update):

1. Config flow starts with `_reauth_entry` set
2. Pre-fills existing username, service_id, pgm_code
3. User enters new credentials and submits
4. Credentials validated → `entry.data` updated → entry reloaded

## Options Flow (Post-Setup)

Accessed from device configuration page → three dots → Options:

| Field | Default Range | Description |
|-------|---------------|-------------|
| Username | — | Leave blank to keep current username |
| Password | — | Leave blank to keep current password |
| Service ID | — | Change for multi-service accounts |
| PGM Control Code | — | Add/change PIN code; removing it converts switches to binary sensors on reload |
| Update interval (seconds) | `300` (positive int) | Seconds between coordinator polls; lower = more frequent API calls |
| Request timeout (seconds) | `10` (positive int) | Per HTTP request timeout; raise if API is slow |
| Retry delay (seconds) | `300` (positive int) | Backoff period when re-login fails after session error |

Credential fields trigger a full reload (new client instance). Toggle-only fields (`scan_interval`, `timeout`, `retry_delay`) update entry options and reload via the update listener.

## Storage Locations

### Config Entry Data

Stored in Home Assistant's `.storage/core.config_entries`:

```json
{
  "data": {
    "username": "user@example.com",
    "password": "encrypted_value",
    "service_id": "12345",
    "sensor_names": {"040": "Venku", "046": "Kotel"},
    "pgm_code": "1234"
  },
  "options": {
    "scan_interval": 300,
    "timeout": 10,
    "retry_delay": 300
  }
}
```

### In-Memory State

During runtime, `hass.data["jablotron_web"][entry_id]` holds:

```python
{
    "coordinator": DataUpdateCoordinator,
    "client": JablotronClient,
    "last_update_time": float | None  # Unix timestamp of latest successful update
}
```

## Multi-Device / Multi-Service Setup

Each Home Assistant config entry connects to **one** Jablotron service (house, car, etc.). To monitor multiple services:

1. Add the Jablotron Web integration once per service
2. Each time enter the same credentials but a different `service_id`
3. Home Assistant creates separate entries with separate coordinators and entity sets
4. The integration supports unlimited entries (unlike standard HA integrations that use unique_id for deduplication)

Note: Unlike typical HA integrations, this integration does **not** enforce `async_set_unique_id()` for deduplication — multiple entries with the same credentials but different service_ids are allowed and expected.

## Install via HACS

The project is a HACS custom repository:

1. **HACS → Integrations → Three dots → Custom repositories**
2. URL: `https://github.com/hranicka/ha-jablotron`, Category: Integration
3. **HACS → Integrations → Search "Jablotron Web" → Download**
4. Restart Home Assistant
5. Settings → Devices & Services → Add Integration → Jablotron Web

Metadata in `hacs.json`:

```json
{
  "name": "Jablotron Web",
  "render_readme": true,
  "filename": "jablotron_web.zip",
  "homeassistant": "2024.1.0",
  "content_in_root": false
}
```

## Manual Installation

```bash
cp -r custom_components/jablotron_web /config/custom_components/
# Restart Home Assistant
```

## Services

Two services are available after setup:

### `jablotron_web.reload`

Reloads all Jablotron Web config entries. Use after upgrading the component or changing configuration (e.g., adding pgm_code). Discovers new sensors from API.

```yaml
service: jablotron_web.reload
```

### `jablotron_web.update`

Forces an immediate data update for all coordinators, bypassing the normal scan interval:

```yaml
service: jablotron_web.update
```

Also accessible per-entry via the Force Update button entity.
