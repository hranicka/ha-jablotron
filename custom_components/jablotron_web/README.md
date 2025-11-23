# Jablotron Web Integration

Custom Home Assistant integration for Jablotron JA-100 with automatic session management.

## Features

- Automatic PHPSESSID session handling
- Auto re-login on session expiration
- Customizable temperature sensor names
- All sensors are auto-discovered
- UI-based configuration
- Supports multiple devices via `service_id` (e.g., car, house, etc.)

## Installation

1. Copy to Home Assistant:
   ```bash
   cp -r custom_components/jablotron_web /config/custom_components/
   ```

2. Restart Home Assistant

3. Add Integration:
   - Settings → Devices & Services → Add Integration
   - Search "Jablotron Web"
   - Enter credentials
   - **Optionally specify `service_id` to select which device (car, house, etc.) to use**
   - Name your temperature sensors
   - Done

## How It Works

### Session Management

```
1. Get Initial PHPSESSID
   GET https://www.jablonet.net
   → Extract PHPSESSID from Set-Cookie header

2. Login
   POST https://www.jablonet.net/ajax/login.php
   Headers: Cookie: PHPSESSID=xxx
   Body: login=email&heslo=password&aStatus=200&loginType=Login&service_id=your_service_id
   → Updates PHPSESSID from response

3. Fetch Data (every 300s)
   POST https://www.jablonet.net/app/ja100/ajax/stav.php
   Headers: Cookie: PHPSESSID=yyy
   Body: activeTab=heat&service_id=your_service_id
   → Returns sensor data for the selected device

4. Session Expiration Detection
   If response: {"status": 300, ...}
   → Go to step 2 (re-login automatically)
```

### Data Structure

**Temperature Sensors** (`teplomery`):
```json
"040": {"value": -8.5, "ts": 1763887586}
```
- API provides value and timestamp only
- Names are customizable during setup
- **Sensors are linked to the selected `service_id` device**

**Binary Sensors** (`pgm`):
```json
"6": {"stav": 1, "nazev": "Vypni ventilátor", ...}
```
- `stav == 0` → ON
- `stav == 1` → OFF
- **PGM sensors are specific to the chosen device (`service_id`)**

## Configuration

### During Setup
1. Credentials: email, password, **service ID (optional, selects which device to use: car, house, etc.)**
2. **Temperature sensor names**: Customize each sensor (e.g., "Venku", "Kotel")

### Options
- Update interval: Default 300 seconds (Settings → Configure)
- **Change `service_id` to switch between devices**

## Files

```
custom_components/jablotron_web/
├── __init__.py           - Integration setup, coordinator
├── config_flow.py        - UI configuration, sensor naming
├── jablotron_client.py   - API client, session management
├── sensor.py             - Temperature sensors
├── binary_sensor.py      - Binary sensors (PGM)
├── const.py              - Constants
├── manifest.json         - Integration metadata
└── strings.json          - UI translations
```

## Troubleshooting

Enable debug logging in `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.jablotron_web: debug
```

Check logs: Settings → System → Logs

## API Endpoints

- **Login**: `POST /ajax/login.php` (add `service_id` to a select device)
- **Status**: `POST /app/ja100/ajax/stav.php` (add `service_id` to select device)
- **Session check**: Response with `status: 300` means expired

## Entities Created

Based on your Jablotron system and selected device (`service_id`):
- Temperature sensors: `sensor.jablotron_<your_name>`
- Binary sensors (PGM): `binary_sensor.jablotron_<pgm_nazev>`

All sensors are auto-discovered from the API response for the chosen device.
