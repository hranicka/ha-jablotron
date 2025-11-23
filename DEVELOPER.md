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
  - Unloads all platforms using `async_unload_platforms`
  - Calls `client.async_close()` to close aiohttp session
  - Cleans up stored data from `hass.data[DOMAIN]`

- **`async_reload_entry(hass, entry)`**
  - Called when options are changed
  - Triggers reload of the integration
  - Used by update listener for scan interval changes

**Data Flow**:
```python
entry.data → {username, password, service_id, sensor_names}
    ↓
JablotronClient(username, password, service_id, hass)
    ↓
DataUpdateCoordinator(update_method=client.get_status, interval=300s)
    ↓
coordinator.data → Shared across all entities
    ↓
hass.data[DOMAIN][entry_id] → {"coordinator": coordinator, "client": client}
```

**Error Handling**:
- `UpdateFailed` exception → Coordinator marks entities as unavailable
- `ConfigEntryAuthFailed` exception → Triggers reauth flow
- Re-login and retry logic handled in `jablotron_client.py`
- Client session cleanup on unload via `async_close()`

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

**Credential Update Flow**:
1. User enters a new username / password / service_id (optional fields)
2. If any credential changed → update `entry.data`
3. Reload integration to create a new client with new credentials
4. Return success

**Reauth Flow** (`async_step_reauth`):
- Triggered when `ConfigEntryAuthFailed` is raised
- Shows credential form pre-filled with existing username/service_id
- Tests new credentials
- Updates entry data and reloads on success
- Shows error if credentials are still invalid

---

### 3. `jablotron_client.py` - API Communication & Session Management

**Purpose**: Handles all HTTP communication with Jablotron API.

**Key Class**: `JablotronClient`

**Initialization**:
```python
__init__(username, password, service_id, hass)
    → Stores credentials
    → Stores hass reference
    → Initializes session = None (created on demand)
    → Initializes _next_retry_time = None (for retry backoff)
```

**Session Management**:
- `async _ensure_session()`: Creates ClientSession with CookieJar if needed
- `async async_close()`: Closes aiohttp session (called on unload)

**Methods**:

#### `async login()`
**Flow** (Multi-step authentication):
1. Clear all cookies from session
2. GET `https://www.jablonet.net` → Get initial PHPSESSID cookie
3. POST `/ajax/login.php` with credentials → Authenticate
4. GET `/cloud` → Get `lastMode` cookie
5. GET `/app/ja100?service={service_id}` → Finalize session for JA100 app

**Returns**: Nothing (raises exception on failure)

**Raises**:
- `JablotronAuthError` on any step failure
- Includes detailed logging at each step

**When login fails**:
- Raises `JablotronAuthError` with a descriptive message
- Config flow catches error and shows `invalid_auth` to user
- Coordinator catches error and triggers reauth flow

**Edit here**: Change login endpoint, add 2FA support

#### `async get_status()`
**Flow**:
1. Check retry backoff timer (30 min cooldown if API was down)
2. Call `_api_request_handler(_fetch_status)`
3. Handler manages session expiry and retries

**Returns**: Dict with `teplomery`, `pgm`, `sekce`, `pir`, etc.

**Raises**:
- `JablotronAuthError` - triggers reauth flow in Home Assistant
- Generic `Exception` - marks entities unavailable, retries later

**Edit here**: Change retry timeout, add caching

#### `async _fetch_status()`
Internal method that:
1. Ensures session exists
2. POST `/app/ja100/ajax/stav.php` with cookies from session
3. Payload: `activeTab=heat&service_id={service_id}`
4. Returns parsed JSON response

**Edit here**: Change API endpoint, modify payload

#### `async _api_request_handler(fetch_func)`
Generic handler for all API requests:
1. Check if in retry backoff period (30 min cooldown)
2. Ensure session exists
3. If no cookies, call `login()` first
4. Call `fetch_func()` to get data
5. If `status == 300` (session expired):
   - Clear cookies and call `login()` again
   - Retry `fetch_func()`
6. If still `status == 300` after retry → raise `JablotronAuthError`
7. On success: Clear retry timer and return data
8. On error: Set 30-minute retry backoff

**Helper Methods**:

- **`_get_headers(referer)`**: Builds request headers with User-Agent, referer, etc.
- **`async _visit_homepage()`**: Gets initial cookies from homepage
- **`async _ensure_session()`**: Creates aiohttp ClientSession if needed
- **`async async_close()`**: Closes aiohttp session

**Session Expiration Detection**:
```python
if data.get("status") == 300:
    # Session expired, re-login needed
```

**Retry Backoff**:
- On API error (not auth): Sets `_next_retry_time = now + 1800` (30 minutes)
- Prevents hammering API when service is down
- Logged message shows time until next retry

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

### 5. `binary_sensor.py` - Binary Sensor Platform (Sections, PGM, PIR)

**Purpose**: Creates binary sensor entities for alarm sections, PGM outputs, and PIR motion sensors.

**Key Function**: `async_setup_entry(hass, entry, async_add_entities)`

**Flow**:
1. Get coordinator data
2. Loop through `coordinator.data["sekce"]` → Create `JablotronSectionBinarySensor`
3. Loop through `coordinator.data["pgm"]` → Create `JablotronPGMBinarySensor`
4. Loop through `coordinator.data["pir"]` → Create `JablotronPIRBinarySensor`
5. Add all entities

#### Class: `JablotronSectionBinarySensor`
Represents an alarm section (armed/disarmed state).

**Device Class**: `SAFETY`

**Key Properties**:
- **`is_on`**: Returns `True` if `stav == 1` (armed), `False` if `stav == 0` (disarmed)
- **`extra_state_attributes`**: Returns section_id, nazev, stav, state_name, active, time
- **`unique_id`**: `{entry_id}_section_{section_id}`

**State Logic**:
```python
stav == 1 → ON (Armed)
stav == 0 → OFF (Disarmed)
```

#### Class: `JablotronPGMBinarySensor`
Represents PGM output with smart device class detection.

**Device Class**: Auto-detected based on name keywords:
- Door keywords → `DOOR`
- Gate/garage keywords → `GARAGE_DOOR`
- Window keywords → `WINDOW`
- Motion/PIR keywords → `MOTION`
- Doorbell keywords → `SOUND`
- Default → `POWER`

**Key Properties**:
- **`is_on`**: Returns `True` if `stav == 1`, `False` if `stav == 0`
- **`extra_state_attributes`**: Returns pgm_id, nazev, stav, state_name, reaction, timestamp, time
- **`unique_id`**: `{entry_id}_pgm_{pgm_id}`

**State Logic**:
```python
stav == 1 → ON (PGM active)
stav == 0 → OFF (PGM inactive)
```

#### Class: `JablotronPIRBinarySensor`
Represents PIR motion sensor.

**Device Class**: `MOTION`

**Key Properties**:
- **`is_on`**: Returns `True` if `active == 1`, `False` otherwise
- **`extra_state_attributes`**: Returns pir_id, nazev, state_name, active, type, last_picture
- **`unique_id`**: `{entry_id}_pir_{pir_id}`

**State Logic**:
```python
active == 1 → ON (Motion detected)
active == 0 → OFF (No motion)
```

**Edit here**: Add controls for arming/disarming, customize device classes

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
# Step 1: Get initial cookies
curl -c cookies.txt 'https://www.jablonet.net'

# Step 2: Login
curl -b cookies.txt -c cookies.txt -v 'https://www.jablonet.net/ajax/login.php' \
  -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'login=email&heslo=password&aStatus=200&loginType=Login'

# Step 3: Get lastMode cookie
curl -b cookies.txt -c cookies.txt 'https://www.jablonet.net/cloud'

# Step 4: Visit JA100 app
curl -b cookies.txt -c cookies.txt 'https://www.jablonet.net/app/ja100?service=YOUR_SERVICE_ID'

# Step 5: Test status fetch
curl -b cookies.txt 'https://www.jablonet.net/app/ja100/ajax/stav.php' \
  -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'activeTab=heat&service_id=YOUR_SERVICE_ID'
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
- `{entry_id}_teplomer_{sensor_id}` - Temperature sensors
- `{entry_id}_pgm_{pgm_id}` - PGM outputs
- `{entry_id}_section_{section_id}` - Alarm sections
- `{entry_id}_pir_{pir_id}` - PIR motion sensors

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

