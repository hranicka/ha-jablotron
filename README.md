# Jablotron Web Integration for Home Assistant

Full-featured Home Assistant integration for Jablotron JA-100 alarm systems.

## Features

- ✅ Automatic session management with 4-step authentication
- ✅ Auto re-login on session expiration
- ✅ Reauth flow support
- ✅ Temperature sensors with customizable names
- ✅ Alarm sections (armed/disarmed state)
- ✅ PGM outputs (binary sensors or switches)
- ✅ PIR motion sensors
- ✅ PGM switching (requires control code)
- ✅ Multi-device support via `service_id`
- ✅ Intelligent retry backoff (configurable, default: 5 minutes)
- ✅ Configurable timeout (default: 10 seconds)
- ✅ Countdown timer to next update
- ✅ Manual update trigger button
- ✅ UI configuration with option flow

## Installation

### Via HACS (Recommended)

1. Add custom repository:
   - HACS → Integrations → ⋮ → Custom repositories
   - URL: `https://github.com/hranicka/ha-jablotron`
   - Category: Integration

2. Install:
   - HACS → Integrations → Search "Jablotron Web"
   - Click "Download" → Restart Home Assistant

3. Configure:
   - Settings → Devices & Services → Add Integration
   - Search "Jablotron Web"
   - Enter credentials

**[Full Documentation](custom_components/jablotron_web/README.md)**

### Manual Installation

```bash
cp -r custom_components/jablotron_web /config/custom_components/
# Restart Home Assistant
```

## Alternative: Static REST Sensors

Simple YAML-based configuration without automatic session management.

**[See static_sensors/README.md](static_sensors/README.md)**

---

## Documentation

- **[User Guide](custom_components/jablotron_web/README.md)** - Setup, configuration, features
- **[Developer Guide](DEVELOPER.md)** - Code structure, API reference, development

---

## License

MIT License - See [LICENSE](LICENSE) file for details.

**Disclaimer**: This software is provided for educational purposes only, without any warranty. Use at your own risk. The author assumes no responsibility for any damages or issues arising from its use.
