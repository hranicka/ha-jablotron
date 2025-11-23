# Developer Documentation - Jablotron Web Integration

Technical guide for understanding and modifying the integration.

## Architecture Overview

```
Home Assistant
    ↓
__init__.py (Setup & Coordinator)
    ↓
config_flow.py (User Configuration)
    ↓
jablotron_client.py (API Communication)
    ↓
sensor.py + binary_sensor.py (Entities)
```

## File Structure & Responsibilities

### 1. `__init__.py` - Integration Setup & Data Coordinator

**Purpose**: Entry point for the integration, manages setup and data updates.

**Key Functions**:

- **`async_setup_entry(hass, entry)`**
  - Called when integration is loaded
  - Creates `JablotronClient` with credentials from `entry.data`
  - Sets up `DataUpdateCoordinator` for periodic updates
  - Registers platforms (sensor, binary_sensor)
  - **Edit here**: Change update logic, add new platforms

- **`async_unload_entry(hass, entry)`**
  - Called when integration is removed
  - Unloads all platforms
  - Cleans up stored data

**Data Flow**:
```python
entry.data → {username, password, service_id, sensor_names}
    ↓
JablotronClient(username, password, service_id, hass)
    ↓
DataUpdateCoordinator(update_method=client.get_status, interval=300s)
    ↓
coordinator.data → Shared across all entities
```

**Error Handling**:
- `UpdateFailed` exception → Coordinator marks entities as unavailable
- Re-login handled in `jablotron_client.py`

---

### 2. `config_flow.py` - User Interface Configuration

**Purpose**: Handles user input during setup and options configuration.

**Key Classes**:

#### `JablotronConfigFlow`
Manages initial setup flow.

**Step 1: `async_step_user(user_input)`**
- Shows credential form
- Validates by attempting login
- On success → proceeds to sensor naming
- **On login failure**: Shows error `invalid_auth` or `cannot_connect`
- **Edit here**: Add/remove credential fields

**Step 2: `async_step_sensors(user_input)`**
- Discovers sensors by fetching data from API
- Shows form with one field per sensor
- Stores custom names in `entry.data[CONF_SENSOR_NAMES]`
- **Edit here**: Customize sensor naming UI

**Error Codes**:
```python
"invalid_auth" → Wrong username/password
"cannot_connect" → Network error or API down
"already_configured" → Email already added
```

#### `JablotronOptionsFlowHandler`
Allows changing a scan interval after setup.

**`async_step_init(user_input)`**
- Shows scan interval option
- Updates `entry.options["scan_interval"]`
- **Edit here**: Add more configurable options

---

### 3. `jablotron_client.py` - API Communication & Session Management

**Purpose**: Handles all HTTP communication with Jablotron API.

**Key Class**: `JablotronClient`

**Initialization**:
```python
__init__(username, password, service_id, hass)
    → Stores credentials
    → Gets aiohttp session from Home Assistant
    → Initializes phpsessid = None
```

**Methods**:

#### `async login()`
**Flow**:
1. GET `https://www.jablonet.net` → Extract initial PHPSESSID from cookies
2. POST `/ajax/login.php` with credentials → Get authenticated PHPSESSID
3. Store updated PHPSESSID for future requests

**Returns**: `True` on success, `False` on failure

**When login fails**:
- Returns `False`
- Logs error message
- Config flow shows `invalid_auth` error to user

**Edit here**: Change login endpoint, add 2FA support

#### `async get_status()`
**Flow**:
1. Call `_fetch_status()`
2. If response `status == 300` (expired):
   - Call `login()` to re-authenticate
   - Retry `_fetch_status()`
3. Return sensor data

**Returns**: Dict with `teplomery`, `pgm`, etc.

**Edit here**: Add caching, change retry logic

#### `async _fetch_status()`
Internal method that:
1. Checks if PHPSESSID exists (if not, calls `login()`)
2. POST `/app/ja100/ajax/stav.php` with PHPSESSID cookie
3. Returns JSON response

**Edit here**: Change API endpoint, modify payload

**Helper Methods**:

- **`_get_headers(referer)`**: Builds request headers
- **`_get_cookies()`**: Builds cookie dict with PHPSESSID

**Session Expiration Detection**:
```python
if data.get("status") == 300:
    # Session expired, re-login needed
```

---

### 4. `sensor.py` - Temperature Sensor Platform

**Purpose**: Creates temperature sensor entities.

**Key Function**: `async_setup_entry(hass, entry, async_add_entities)`

**Flow**:
1. Get coordinator from `hass.data[DOMAIN][entry.entry_id]`
2. Get custom sensor names from `entry.data[CONF_SENSOR_NAMES]`
3. Loop through `coordinator.data["teplomery"]`
4. Create `JablotronTemperatureSensor` for each sensor
5. Add entities to Home Assistant

**Class**: `JablotronTemperatureSensor(CoordinatorEntity, SensorEntity)`

**Key Properties**:

- **`native_value`**: Returns temperature from `coordinator.data["teplomery"][sensor_id]["value"]`
- **`extra_state_attributes`**: Returns sensor_id, state_name, timestamp

**When sensor data is missing**:
- Returns `None` → Entity shows as "Unknown"

**Edit here**: Add humidity sensors, change units, add more attributes

---

### 5. `binary_sensor.py` - Binary Sensor Platform (PGM)

**Purpose**: Creates binary sensor entities for PGM outputs.

**Key Function**: `async_setup_entry(hass, entry, async_add_entities)`

**Flow**:
1. Get coordinator data
2. Loop through `coordinator.data["pgm"]`
3. Create `JablotronPGMBinarySensor` for each PGM
4. Add entities

**Class**: `JablotronPGMBinarySensor(CoordinatorEntity, BinarySensorEntity)`

**Key Properties**:

- **`is_on`**: Returns `True` if `stav == 0`, `False` if `stav == 1`
- **`extra_state_attributes`**: Returns pgm_id, nazev, stav, reaction, timestamp, time

**State Logic**:
```python
stav == 0 → ON (PGM active)
stav == 1 → OFF (PGM inactive)
```

**Edit here**: Add alarm sensors, change device class, add controls

---

### 6. `const.py` - Constants & Configuration

**Purpose**: Centralized configuration constants.

**Constants**:

```python
DOMAIN = "jablotron_web"           # Integration domain
CONF_USERNAME = "username"          # Config key
CONF_PASSWORD = "password"          # Config key
CONF_SERVICE_ID = "service_id"      # Config key
CONF_SENSOR_NAMES = "sensor_names"  # Config key
DEFAULT_SCAN_INTERVAL = 300         # Default update interval (seconds)

API_BASE_URL = "https://www.jablonet.net"
API_LOGIN_URL = f"{API_BASE_URL}/ajax/login.php"
API_STATUS_URL = f"{API_BASE_URL}/app/ja100/ajax/stav.php"
```

**Edit here**: Add new constants, change defaults, add API endpoints

---

## Data Flow Diagram

```
User adds integration
    ↓
config_flow.async_step_user() → Validate credentials
    ↓
config_flow.async_step_sensors() → Name sensors
    ↓
__init__.async_setup_entry()
    ↓
Create JablotronClient
    ↓
Create DataUpdateCoordinator
    ↓
coordinator.async_config_entry_first_refresh()
    ↓
JablotronClient.get_status()
    ↓
    ├─ If no PHPSESSID → login()
    ├─ If status == 300 → login() + retry
    └─ Return data
    ↓
coordinator.data = {teplomery: {...}, pgm: {...}}
    ↓
    ├─ sensor.async_setup_entry() → Create temperature entities
    └─ binary_sensor.async_setup_entry() → Create PGM entities
    ↓
Entities read from coordinator.data
    ↓
Every 300s: coordinator triggers update → repeat get_status()
```

---

## Error Handling Scenarios

### Login Failure

**Where**: `jablotron_client.login()`

**Causes**:
- Wrong username/password
- Network error
- API down

**Result**:
- Returns `False`
- Logs error
- Config flow shows an error to the user

**To debug**:
- Check logs for HTTP status code
- Verify credentials at jablonet.net
- Check network connectivity

---

### Session Expiration

**Where**: `jablotron_client.get_status()`

**Detection**: API returns `{"status": 300, ...}`

**Handling**:
1. Detected in `get_status()`
2. Calls `login()` to get new PHPSESSID
3. Retries `_fetch_status()`
4. If re-login fails → raises exception → coordinator marks unavailable

**To debug**:
- Check logs for "Session expired, logging in again"
- Verify re-login succeeds

---

### Missing Sensor Data

**Where**: `sensor.py` / `binary_sensor.py`

**Causes**:
- Sensor removed from system
- API response changed
- Network error

**Result**:
- Entity shows as "Unknown"
- No error raised

**To debug**:
- Check `coordinator.data` in logs
- Verify sensor exists in API response

---

### Update Errors

**Where**: `__init__.py` DataUpdateCoordinator

**Causes**:
- Network timeout
- API error
- Invalid response

**Result**:
- `UpdateFailed` exception raised
- All entities marked as "Unavailable"
- Coordinator retries on next interval

**To debug**:
- Check logs for `UpdateFailed` message
- Enable debug logging

---

## Common Modifications

### Add New Sensor Type

1. Check API response for a new data field
2. Create a new platform file (e.g., `switch.py`)
3. Add a platform to `PLATFORMS` in `__init__.py`
4. Create entity class extending the appropriate base
5. Parse data from `coordinator.data`

### Change Update Interval

**Method 1**: Default
- Edit `DEFAULT_SCAN_INTERVAL` in `const.py`

**Method 2**: User configurable
- Already available in options flow
- User can change in UI

### Add New Configuration Field

1. Add constant to `const.py`
2. Add field to `async_step_user()` in `config_flow.py`
3. Access value from `entry.data[CONF_YOUR_FIELD]`

### Change API Endpoint

1. Update URL in `const.py`
2. Modify request in `jablotron_client.py`
3. Test with curl first

---

## Debugging Tips

### Enable Debug Logging

```yaml
logger:
  logs:
    custom_components.jablotron_web: debug
```

### Key Log Messages

- "Attempting to log in" → Login started
- "Login successful, got new PHPSESSID" → Login OK
- "Session expired, logging in again" → Auto re-login
- "Status data received" → Data fetch OK
- "Error communicating with API" → Update failed

### Check Coordinator Data

Add temporary logging in `__init__.py`:
```python
_LOGGER.debug(f"Coordinator data: {coordinator.data}")
```

### Test API Manually

```bash
# Test login
curl -v 'https://www.jablonet.net/ajax/login.php' \
  -X POST \
  --data 'login=email&heslo=password&aStatus=200&loginType=Login'

# Test status (use PHPSESSID from login)
curl 'https://www.jablonet.net/app/ja100/ajax/stav.php' \
  -X POST \
  -H 'Cookie: PHPSESSID=xxx' \
  --data 'activeTab=heat'
```

---

## Integration with Home Assistant

### Config Entry Storage

Data stored in `.storage/core.config_entries`:
```json
{
  "data": {
    "username": "email@example.com",
    "password": "encrypted_password",
    "service_id": "12345",
    "sensor_names": {
      "040": "Venku",
      "046": "Kotel"
    }
  },
  "options": {
    "scan_interval": 300
  }
}
```

### Entity Registry

Entities registered with unique_id:
- `{entry_id}_teplomer_{sensor_id}`
- `{entry_id}_pgm_{pgm_id}`

Allows renaming in UI without losing history.

### State Storage

Entity states are stored in a recorder database.
Accessible via a history panel and `history.get_last_state()`.

---

## API Response Structure

### Login Response
```json
// Success - returns new PHPSESSID in Set-Cookie header
```

### Status Response (Normal)
```json
{
  "status": 200,
  "teplomery": {
    "040": {"value": -8.5, "ts": 1763887586, "stateName": "HEAT_40"}
  },
  "pgm": {
    "6": {"stav": 1, "nazev": "Ventilátor", "stateName": "PGM_7", ...}
  }
}
```

### Status Response (Expired Session)
```json
{
  "status": 300,
  "url": "https://www.jablonet.net/app/ja100?service="
}
```

---

## Testing Changes

1. **Copy to Home Assistant**: `cp -r custom_components/jablotron_web /config/custom_components/`
2. **Restart Home Assistant**
3. **Check logs**: Settings → System → Logs
4. **Test setup**: Add integration via UI
5. **Verify entities**: Developer Tools → States

---

## Useful Resources

- Home Assistant Integration Development: https://developers.home-assistant.io/
- aiohttp Documentation: https://docs.aiohttp.org/
- Config Flow: https://developers.home-assistant.io/docs/config_entries_config_flow_handler
- Entity: https://developers.home-assistant.io/docs/core/entity

