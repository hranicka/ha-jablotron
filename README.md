# Jablotron Web Integration for Home Assistant

Full-featured Home Assistant integration for Jablotron JA-100 alarm systems via the [jablonet.net](https://www.jablonet.net) cloud API.

## Features

- Automatic session management with 4-step browser-like authentication
- Auto re-login on session expiration (no user intervention needed)
- Reauth flow support when credentials change
- Temperature sensors with customizable names
- Alarm sections as binary sensors (armed/disarmed state)
- PGM outputs — read-only binary sensors or controllable switches
- PIR motion sensors
- PGM switching (requires a 4-digit control PIN code)
- Multi-device / multi-service support via `service_id`
- Configurable polling interval, request timeout, and retry backoff
- Countdown timer tracking next data update
- Manual force-update button entity
- Optional YAML-based REST sensor alternative

## Installation

### Via HACS (Recommended)

1. Add custom repository: **HACS → Integrations → ⋮ → Custom repositories** → `https://github.com/hranicka/ha-jablotron` (Integration)
2. Install from HACS integration browser → restart Home Assistant
3. Configure: **Settings → Devices & Services → Add Integration → Jablotron Web**

### Manual Installation

```bash
mkdir -p /config/custom_components/
cp -r custom_components/jablotron_web /config/custom_components/
# Restart Home Assistant
```

## Getting Started

- **[docs/configuration.md](docs/configuration.md)** — Full setup guide, config options, multi-service setup, services reference
- **[docs/entities.md](docs/entities.md)** — What entities are created and how they behave
- **[docs/static-sensors.md](docs/static-sensors.md)** — Alternative YAML-based REST sensor setup

## Documentation

- **[docs/architecture.md](docs/architecture.md)** — System architecture, data flow, component structure
- **[docs/api-reference.md](docs/api-reference.md)** — Jablotron API reference (auth flow, status, control endpoints)
- **[docs/session-management.md](docs/session-management.md)** — Authentication, session recovery, retry backoff logic
- **[docs/configuration.md](docs/configuration.md)** — Setup, options, services, multi-device
- **[docs/entities.md](docs/entities.md)** — Entity types, value sources, custom naming
- **[docs/static-sensors.md](docs/static-sensors.md)** — YAML-based REST sensor alternative

## Testing & Debugging

A standalone test script replicating the API login flow:

```bash
python test_jablonet.py <username> <password> [service_id]
```

Enable debug logging in Home Assistant:

```yaml
logger:
  logs:
    custom_components.jablotron_web: debug
```

## License

MIT License — see [LICENSE](LICENSE) for details.

**Disclaimer**: Educational use only, no warranty. Use at your own risk.
