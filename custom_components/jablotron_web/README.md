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
- **PGM switching support** - Control switchable PGM outputs (on/off)
- **UI-based configuration** with option flow
- **Intelligent retry backoff** (30 min on API errors)
- **Supports multiple devices** via `service_id` (e.g., car, house, etc.)
- **Reload service** - Easily refresh sensors and switches after updates

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

## How It Works

### Authentication (4-Step Process)

```
1. GET https://www.jablonet.net
   → Get PHPSESSID cookie

2. POST /ajax/login.php
   Body: login=email&heslo=password&aStatus=200&loginType=Login
   → Authenticate user

3. GET /cloud
   → Get lastMode cookie

4. GET /app/ja100?service={service_id}
   → Initialize device session
```

### Data Polling (Every 5 minutes)

```
POST /app/ja100/ajax/stav.php
Body: activeTab=heat
→ Returns: {teplomery, pgm, sekce, pir, permissions, ...}

If response.status == 300:
  → Session expired, repeat authentication
```

### PGM Control (When switching)

```
POST /app/ja100/ajax/ovladani2.php
Body: section=PGM_7&status=1&code={pgm_code}&uid=PGM_7_prehled
→ Returns: {"result": 1, "authorization": 200, "responseCode": 200}

Integration behavior:
1. Freeze switch state (prevent coordinator overwrites)
2. Send control command
3. Process response.result → Update coordinator immediately
4. Request full data refresh
5. Unfreeze switch state
```

### API Data Structure

**Temperature Sensors** (`teplomery`):
```json
"040": {"value": -8.5, "ts": 1763887586, "stateName": "HEAT_40"}
```

**Alarm Sections** (`sekce`):
```json
"1": {"stav": 0, "nazev": "Přízemí", "stateName": "STATE_2", "time": "..."}
```
- `stav`: 0=disarmed, 1=armed

**PGM Outputs** (`pgm`):
```json
"6": {"stav": 1, "nazev": "Osvětlení", "stateName": "PGM_7", "reaction": "pgorSwitchOnOff", "ts": 123}
```
- `stav`: 0=off, 1=on
- `reaction`: Type (`pgorSwitchOnOff`, `pgorPulse`, `pgorCopy`)

**PIR Sensors** (`pir`):
```json
"2": {"active": 1, "nazev": "PIR Chodba", "stateName": "PPIR_123", "type": "JA-120PC"}
```
- `active`: 0=no motion, 1=motion detected

### Entity Types Created

**Temperature Sensors** (always created):
- One sensor entity per `teplomery` entry
- Customizable names during setup
- Unit: °C

**Binary Sensors** (always created):
- **Alarm sections**: All `sekce` entries (device_class: SAFETY)
- **PIR motion**: All `pir` entries (device_class: MOTION)
- **PGM outputs**: Created when:
  - No `pgm_code` configured → All PGMs as binary sensors
  - `pgm_code` configured → Only non-switchable PGMs (e.g., `pgorCopy`)

**Switches** (requires `pgm_code`):
- **Switchable PGMs**: Created when:
  - `pgm_code` is configured
  - PGM reaction is `pgorSwitchOnOff` or `pgorPulse`
  - User has permission for that PGM
- **Replaces** binary sensor for that PGM (not created as both)
- Allows on/off control with immediate state feedback

**Important**: A PGM is either a binary sensor OR a switch, never both.

## Configuration

### Setup Flow
1. **Credentials**: Email and password for jablonet.net
2. **Service ID** (optional): Specify which device to monitor (for multi-device accounts)
3. **PGM Control Code** (optional): PIN for PGM switching
   - Without code: PGMs are binary sensors only (read-only)
   - With code: Switchable PGMs become switches (controllable)
   - Can be added later via Options → triggers reload
4. **Sensor Names**: Customize each temperature sensor

### Options (After Setup)
Settings → Devices & Services → Jablotron Web → Configure:
- **Scan interval**: Update frequency (default: 300s)
- **Credentials**: Change username, password, service_id, or pgm_code
- Changes trigger automatic reload

### Reauth Flow
- Triggered automatically on authentication errors
- Update credentials via UI prompt
- No need to remove/re-add integration

## Files

```
custom_components/jablotron_web/
├── __init__.py           - Integration setup, coordinator, reload logic
├── config_flow.py        - UI configuration, sensor naming, reauth
├── jablotron_client.py   - API client, 4-step auth, session management
├── sensor.py             - Temperature sensors
├── binary_sensor.py      - Alarm sections, PGM outputs, PIR sensors
├── switch.py             - Switchable PGM outputs (on/off control)
├── const.py              - Constants and API URLs
├── manifest.json         - Integration metadata
└── strings.json          - UI translations
```

## Services

### `jablotron_web.reload`

Reloads all Jablotron Web integrations to discover new/updated entities.

**When to use:**
- After adding PGM control code (to create switch entities)
- After updating to a new version
- After changing Jablotron system configuration
- To force discovery of new sensors/PGMs

**Example:**
```yaml
service: jablotron_web.reload
```

**Note:** Entity configurations and states are preserved.

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
- API is temporarily down, unreachable, or responded too slowly (timeout)
- Integration will automatically retry after 15 minutes
- Prevents hammering the API when the service is down
- You can adjust timeout in integration options if needed

**Session keeps expiring**
- Check if credentials are correct
- Verify you can log in at jablonet.net manually
- Check if service_id is correct for your device

**Sensors show "Unknown" or "Unavailable"**
- Check coordinator data in debug logs
- Verify sensors exist in your Jablotron system
- Ensure the correct service_id is configured

**New switches do not appear after an update**
- Add PGM control code in integration options
- Use the reload service: `jablotron_web.reload`
- Or manually reload: Settings → Devices & Services → Jablotron Web → ⋮ → Reload
- Check that PGMs have `reaction: "pgorSwitchOnOff"` (see debug logs)
- Verify you have permission to control the PGM
- **If old binary sensor exists**: Delete the old `binary_sensor.jablotron_*` entity for that PGM, then reload

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
