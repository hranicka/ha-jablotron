# Jablotron Web Integration for Home Assistant

Custom Home Assistant integration for Jablotron JA-100 alarm systems with automatic session management via jablonet.net cloud API.

## Features

- **Automatic session management** with full cookie jar handling
- **Multistep authentication** (4-step browser-like login process)
- **Auto re-login** on session expiration without user intervention
- **Reauth flow** when credentials change
- **Customizable temperature sensor names** during setup
- **All sensors auto-discovered**:
  - Temperature sensors (`teplomery`)
  - Alarm sections (`sekce`) — armed/disarmed state
  - PGM outputs (`pgm`) — with smart device class detection
  - PIR motion sensors (`pir`)
- **PGM switching support** — Control switchable PGM outputs (on/off)
- **UI-based configuration** with option flow
- **Intelligent retry backoff** (configurable, default: 5 minutes)
- **Supports multiple devices** via `service_id`

## Installation

### Via HACS (Recommended)

1. Add a custom repository:
   - HACS → Integrations → ⋮ (top right) → Custom repositories
   - Repository: `https://github.com/hranicka/ha-jablotron`
   - Category: Integration
   - Click "Add"

2. Install integration:
   - HACS → Integrations → Search "Jablotron Web"
   - Click "Download"
   - Restart Home Assistant

3. Configure:
   - Settings → Devices & Services → Add Integration
   - Search "Jablotron Web"
   - Enter credentials (email, password)
   - Optionally specify `service_id` and PGM control code

### Manual Installation

```bash
cp -r custom_components/jablotron_web /config/custom_components/
# Restart Home Assistant
```

## Quick Start

- **[docs/configuration.md](../../docs/configuration.md)** — Full setup guide, config options, services reference
- **[docs/entities.md](../../docs/entities.md)** — What entities are created, how they work
- **[docs/static-sensors.md](../../docs/static-sensors.md)** — YAML-based REST sensor alternative (no automatic session)

## Configuration

### Setup Flow
1. **Email and password** for jablonet.net account
2. **Service ID** (optional): Select which device to monitor (house, car, etc.)
3. **PGM Control Code** (optional): 4-digit PIN for controlling outputs
   - Without code: PGMs are read-only binary sensors
   - With code + permission: Switchable PGMs become controllable switches
4. **Sensor names**: Customize each temperature sensor

### Options (After Setup)
Settings → Devices & Services → Jablotron Web → Configure:
- `Scan interval` — Update frequency (default: 300s)
- `Timeout` — Request timeout in seconds (default: 10s)
- `Retry delay` — Wait time after errors (default: 300s)
- Change credentials, service_id, or pgm_code at any time

## Services

### `jablotron_web.reload`
Reload all Jablotron Web integrations. Use after upgrades or configuration changes.
```yaml
service: jablotron_web.reload
```

### `jablotron_web.update`
Force immediate data refresh from the API.
```yaml
service: jablotron_web.update
```

## Troubleshooting

Enable debug logging:
```yaml
logger:
  logs:
    custom_components.jablotron_web: debug
```

Or use the HA UI: Settings → Devices & Services → Jablotron Web → ⋮ → Enable debug logging.

---

For detailed developer documentation, see [docs/](../../docs/).
