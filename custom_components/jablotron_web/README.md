# Jablotron Web Integration

Custom Home Assistant integration for Jablotron JA-100 with automatic session management.

## Features

- **Automatic session management** with full cookie jar handling
- **Multistep authentication** (4-step login process)
- **Auto re-login** on session expiration
- **Reauth flow** when credentials change
- **Customizable temperature sensor names** during setup
- **All sensors auto-discovered**:
  - Temperature sensors (`teplomery`)
  - Alarm sections (`sekce`) - armed/disarmed state
  - PGM outputs (`pgm`) - with smart device class detection
  - PIR motion sensors (`pir`)
- **UI-based configuration** with option flow
- **Intelligent retry backoff** (30 min on API errors)
- **Supports multiple devices** via `service_id` (e.g., car, house, etc.)

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
   - **Optionally specify `service_id`** to select which device to monitor
   - Name your temperature sensors
   - Done

### Manual Installation

1. Copy to Home Assistant:
   ```bash
   cp -r custom_components/jablotron_web /config/custom_components/
   ```

2. Restart Home Assistant

3. Configure (same as step 3 above)

## How It Works

### Session Management

The integration uses a sophisticated 4-step authentication process:

```
1. Visit Homepage
   GET https://www.jablonet.net
   → Get initial PHPSESSID cookie

2. Login with Credentials
   POST https://www.jablonet.net/ajax/login.php
   Body: login=email&heslo=password&aStatus=200&loginType=Login
   → Authenticate user

3. Visit Cloud Page
   GET https://www.jablonet.net/cloud
   → Get lastMode cookie

4. Initialize JA100 App
   GET https://www.jablonet.net/app/ja100?service={service_id}
   → Finalize session for device access

5. Fetch Data (every 300s)
   POST https://www.jablonet.net/app/ja100/ajax/stav.php
   Body: activeTab=heat&service_id={service_id}
   → Returns sensor data for the selected device

6. Session Expiration Detection
   If response: {"status": 300, ...}
   → Clear cookies and repeat steps 1-4 (automatic re-login)
```

### Data Structure

**Temperature Sensors** (`teplomery`):
```json
"040": {"value": -8.5, "ts": 1763887586, "stateName": "HEAT_40"}
```
- Customizable names during setup
- Auto-discovered from API

**Alarm Sections** (`sekce`):
```json
"1": {"stav": 0, "nazev": "Section 1", "stateName": "SEC_1", "active": 0, "time": ...}
```
- `stav == 1` → Armed (ON)
- `stav == 0` → Disarmed (OFF)
- Device class: SAFETY

**PGM Outputs** (`pgm`):
```json
"6": {"stav": 1, "nazev": "Ventilátor", "stateName": "PGM_7", "reaction": "", ...}
```
- `stav == 1` → Active (ON)
- `stav == 0` → Inactive (OFF)
- Smart device class detection based on name keywords

**PIR Motion Sensors** (`pir`):
```json
"2": {"active": 1, "nazev": "PIR Garage", "stateName": "PIR_2", "type": "motion", ...}
```
- `active == 1` → Motion detected (ON)
- `active == 0` → No motion (OFF)
- Device class: MOTION

## Configuration

### During Setup
1. **Credentials**: Email and password for jablonet.net
2. **Service ID** (optional): Select which device to monitor (e.g., house, a car)
3. **Temperature sensor names**: Customize each sensor (e.g., "Venku", "Kotel")

### Options (After Setup)
Access via Settings → Devices & Services → Jablotron Web → Configure:
- **Update interval**: Default 300 seconds (5 minutes)
- **Change credentials**: Update email, password, or service_id
- Changes trigger automatic reload and re-authentication

### Reauth Flow
If credentials expire or change:
- Integration automatically triggers reauth notification
- Update credentials through a UI prompt
- No need to remove and re-add integration

## Files

```
custom_components/jablotron_web/
├── __init__.py           - Integration setup, coordinator, reload logic
├── config_flow.py        - UI configuration, sensor naming, reauth
├── jablotron_client.py   - API client, 4-step auth, session management
├── sensor.py             - Temperature sensors
├── binary_sensor.py      - Alarm sections, PGM outputs, PIR sensors
├── const.py              - Constants and API URLs
├── manifest.json         - Integration metadata
└── strings.json          - UI translations
```

## Troubleshooting

### Enable Debug Logging

**Method 1: UI Button (Recommended)**

1. Go to Settings → Devices & Services → Integrations
2. Find "Jablotron Web" integration
3. Click the three-dot menu (⋮)
4. Click "Enable debug logging" (Povolit logování ladících informací)
5. Reproduce the issue
6. Click "Disable debug logging" to download the debug logs

Note: This works automatically - no code changes are needed. Home Assistant captures all DEBUG messages.

**Method 2: configuration.yaml**

For persistent debug logging, add to `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.jablotron_web: debug
```
Restart Home Assistant after making changes.

**View logs**: Settings → System → Logs

### Common Issues

**"Jablotron API is unavailable, next retry in X seconds"**
- API is temporarily down or unreachable
- Integration will automatically retry after 30 minutes
- Prevents hammering the API when the service is down

**Session keeps expiring**
- Check if credentials are correct
- Verify you can log in at jablonet.net manually
- Check if service_id is correct for your device

**Sensors show "Unknown" or "Unavailable"**
- Check coordinator data in debug logs
- Verify sensors exist in your Jablotron system
- Ensure the correct service_id is configured

**Frontend errors: "entity-picker.no_match" or "device-picker.no_match" (Czech language)**
- These are **NOT** from this integration
- They are Home Assistant core frontend bugs in Czech translations
- Safe to ignore - they don't affect functionality
- Appears in logs as: `[frontend.js.modern...] Failed to format translation...`
- Can be resolved by switching HA language to English temporarily

## API Endpoints

- **Homepage**: `GET /` (initial cookies)
- **Cloud page**: `GET /cloud` (lastMode cookie)
- **JA100 app**: `GET /app/ja100?service={id}` (session init)
- **Login**: `POST /ajax/login.php`
- **Status**: `POST /app/ja100/ajax/stav.php` (with service_id)
- **Session check**: Response with `status: 300` means expired

## Entities Created

Based on your Jablotron system and selected device (`service_id`):

- **Temperature sensors**: `sensor.jablotron_<your_name>`
- **Alarm sections**: `binary_sensor.jablotron_<section_name>` (device class: safety)
- **PGM outputs**: `binary_sensor.jablotron_<pgm_name>` (device class: auto-detected)
- **PIR sensors**: `binary_sensor.jablotron_<pir_name>` (device class: motion)

All sensors are auto-discovered from the API response for the chosen device.

## Developer Documentation

For technical details, architecture, and modification instructions:

[See DEVELOPER.md](../../DEVELOPER.md)
