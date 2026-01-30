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
sensor.py + binary_sensor.py + switch.py + button.py (Entities)
```

## File Structure & Responsibilities

### 1. `__init__.py` - Integration Setup & Data Coordinator

**Purpose**: Entry point for the integration, manages setup and data updates.

**Platforms**: `SENSOR`, `BINARY_SENSOR`, `SWITCH`, `BUTTON`

**Key Functions**:

- **`async_setup_entry(hass, entry)`**
  - Extracts credentials: `username`, `password`, `service_id`, `pgm_code`
  - Creates `JablotronClient(username, password, service_id, hass, pgm_code)`
  - Sets up `DataUpdateCoordinator`:
    - Update method: `client.gethe the t_status()`
    - Interval: from `entry.options["scan_interval"]` (default 300s)
  - Performs first refresh
  - Registers services on first entry (via `services.async_setup_services()`)
  - Forwards setup to all platforms
  - Adds update listener for options changes

- **`async_reload_entry(hass, entry)`**
  - Called when options change
  - Reloads the integration to apply new settings

- **`async_unload_entry(hass, entry)`**
  - Unloads all platforms
  - Closes client session via `client.async_close()`
  - Unregisters services if last entry
  - Cleans up `hass.data[DOMAIN]`

**Data Flow**:
```python
entry.data → {username, password, service_id, pgm_code, sensor_names}
    ↓
JablotronClient(username, password, service_id, hass, pgm_code)
    ↓
DataUpdateCoordinator(update_method=client.get_status, interval=300s)
    ↓
coordinator.data → Shared across all entities
    ↓
hass.data[DOMAIN][entry_id] → {"coordinator": coordinator, "client": client}
```

**Error Handling**:
- **Retry Delay Awareness**: Coordinator checks `client.get_next_retry_time()` before calling API
  - If delay active → Raises `UpdateFailed` with time remaining message
  - Avoids unnecessary client calls during retry period
- **Session Errors**: `JablotronAuthError` → Raises `ConfigEntryAuthFailed` → Triggers reauth flow
- **Other Errors**: Generic exceptions → Raises `UpdateFailed` → Entities unavailable, retries on next interval
- **Session Management**: Automatic reset and retry delay handled in `jablotron_client.py`

---

### 2. `config_flow.py` - User Interface Configuration

**Purpose**: Handles user input during setup and options configuration.

#### `JablotronConfigFlow`
Manages initial setup flow.

**Step 1: `async_step_user(user_input)`**
- Form fields: `username`, `password`, `service_id` (optional), `pgm_code` (optional)
- Validates credentials by attempting login
- On success → proceeds to sensor naming
- **Errors**: `invalid_auth`, `cannot_connect`, `already_configured`

**Step 2: `async_step_sensors(user_input)`**
- Fetches data from API to discover temperature sensors
- Shows form with one field per sensor for custom naming
- Stores names in `entry.data[CONF_SENSOR_NAMES]`
- Creates config entry

**Reauth Flow** (`async_step_reauth`):
- Triggered when `ConfigEntryAuthFailed` is raised
- Pre-fills existing username/service_id
- Tests new credentials
- Updates `entry.data` and reloads on success

#### `JablotronOptionsFlowHandler`
Allows changing settings after setup.

**`async_step_init(user_input)`**
- Options: `scan_interval`, `username`, `password`, `service_id`, `pgm_code`
- All credential fields are optional (only update if provided)
- If credentials change → updates `entry.data` and triggers reload
- If only scan_interval changes → updates `entry.options`

---

### 3. `jablotron_client.py` - API Communication & Session Management

**Purpose**: Handles all HTTP communication with Jablotron API.

**Class**: `JablotronClient`

**Initialization**:
```python
__init__(username, password, service_id, hass, pgm_code, timeout, retry_delay)
    → Stores credentials, PGM code, timeout, and retry_delay
    → Initializes session = None (created on demand)
    → Initializes _next_retry_time = None (for retry backoff)
    → retry_delay defaults to 300 seconds (5 minutes)
```

**Architecture**: Clean design with thin HTTP wrapper and uniform error handling.

**HTTP Layer (Thin Wrapper)**:

#### `async _http_request(method, url, headers, data)`
Low-level HTTP wrapper for all requests.
- **Returns**: `(status_code, response_text)` tuple
- **Accepts**: Only HTTP 200 as success
- **Raises**: `JablotronSessionError` on any unexpected result (non-200, network errors)

#### `async _http_json(method, url, headers, data, expected_status=200)`
HTTP wrapper for JSON responses.
- **Returns**: Parsed JSON dict
- **Validates**: JSON structure and `status` field in response
- **Raises**: `JablotronSessionError` on invalid JSON or `status != expected_status`

**Session Management**:

#### `async login()`
4-step authentication process:
1. `_visit_homepage()` → GET `https://www.jablonet.net` → Initial PHPSESSID cookie
2. `_login_post()` → POST `/ajax/login.php` → Authenticate credentials
3. `_get_cloud_page()` → GET `/cloud` → Get lastMode cookie
4. `_get_ja100_app()` → GET `/app/ja100?service={service_id}` → Initialize JA100 session

**Raises**: `JablotronAuthError` on any failure (wraps `JablotronSessionError`)

#### `async _reset_session()`
Complete session reset (called on every error):
1. Clears all cookies from cookie jar
2. Closes aiohttp session
3. Sets session to `None`

**Public API Methods**:

#### `def get_next_retry_time()`
Returns timestamp when next retry is allowed.
- **Returns**: `Optional[float]` - Unix timestamp (seconds since epoch) or `None` if no delay active
- **Usage**: Coordinator checks this before calling API methods to avoid unnecessary calls during retry delay

#### `async get_status()`
Fetches the current state of all system components.
- Calls `_with_session_handling(_fetch_status)`
- Returns dict with `teplomery`, `pgm`, `sekce`, `pir`, `permissions`, etc.
- **Raises**: `JablotronAuthError` on session errors

#### `async control_pgm(pgm_id, status)`
Controls a PGM output (turn on/off).
- **Args**: `pgm_id` (e.g., "6"), `status` (0=off, 1=on)
- **Returns**: Response dict with `{"result": 0/1, "authorization": 200, ...}`
- Calls `_with_session_handling(_control_pgm_internal)`
- **Raises**: `JablotronAuthError` on session errors

**Error Handling**:

#### `async _with_session_handling(api_func)`
Wrapper for all API calls with automatic error recovery:
1. **Ensure session**: If no session/cookies → reset + login
2. **Execute API call**: Call `api_func()` (e.g., `_fetch_status()`)
3. **On success**: Clear retry timer, return data
4. **On `JablotronSessionError`**: 
   - Call `_reset_session()` (complete cleanup)
   - **Immediately attempt re-login** (no delay)
   - If re-login succeeds → retry API call, return data
   - If re-login fails → set retry delay (configurable, default: 5 minutes), raise `JablotronAuthError`

**Note**: Retry delay is only set when re-login fails, not when the initial API call fails. This allows fast recovery from common session expiry scenarios.

**Error Flow**:
```
Coordinator checks get_next_retry_time()
  → If delay active: Raise UpdateFailed ("retrying in X minutes")
  → If no delay: Call client.get_status()
    ↓
API Call → JablotronSessionError (non-200 HTTP, invalid JSON, status != 200)
  → _with_session_handling catches it
  → _reset_session() - complete cleanup
  → Immediately attempt re-login (no delay!)
    ↓
    ├── Re-login SUCCESS
    │     → Retry API call
    │     → Return data (recovery time: ~2-5 seconds)
    │
    └── Re-login FAILS
          → Set _next_retry_time = now + self.retry_delay (default: 5 minutes)
          → Raise JablotronAuthError
          → Coordinator raises UpdateFailed
          → Entities show "Unavailable"
          → Next coordinator attempt (5 min): Delay check → UpdateFailed
          → After 30 minutes: Delay expired → Fresh login → Resume
```

**Session Expiry Detection**:
- API returns `{"status": 300, ...}` when session expires
- `_http_json()` detects this and raises `JablotronSessionError`
- Triggers complete reset + retry flow above

**Cookie Management**:
- Cookie jar maintains `PHPSESSID` and `lastMode`
- Automatically sent with each request
- Cleared on every error via `_reset_session()`

---

### 3a. Jablotron API Reference

**Important**: All API endpoints return HTTP 200 OK status even on errors. Error conditions are indicated in the JSON response body (e.g., `{"status": 300}` for expired session).

#### Authentication Flow

The Jablotron API uses cookie-based session authentication. Full login requires 4 steps:

**Step 1: Get Initial Session Cookie**
```bash
GET https://www.jablonet.net
```
- **Purpose**: Obtain initial `PHPSESSID` cookie
- **Response**: HTML page with Set-Cookie header
- **Cookies Set**: `PHPSESSID`

**Step 2: Authenticate**
```bash
POST https://www.jablonet.net/ajax/login.php
Content-Type: application/x-www-form-urlencoded

login=email@example.com&heslo=password&aStatus=200&loginType=Login
```
- **Purpose**: Authenticate user credentials
- **Required Headers**:
  - `User-Agent`: Any modern browser UA
  - `Content-Type`: `application/x-www-form-urlencoded`
  - `X-Requested-With`: `XMLHttpRequest`
  - `Origin`: `https://www.jablonet.net`
  - `Referer`: `https://www.jablonet.net/`
- **Cookies Required**: `PHPSESSID` (from Step 1)
- **Response**: JSON (usually empty on success) + updated `PHPSESSID` cookie
- **Cookies Set**: `PHPSESSID` (authenticated)

**Step 3: Get lastMode Cookie**
```bash
GET https://www.jablonet.net/cloud
```
- **Purpose**: Obtain `lastMode` cookie for app access
- **Cookies Required**: Authenticated `PHPSESSID`
- **Response**: HTML redirect page
- **Cookies Set**: `lastMode`

**Step 4: Initialize JA100 App Session**
```bash
GET https://www.jablonet.net/app/ja100?service={service_id}
```
- **Purpose**: Finalize session for JA100 app API access
- **Cookies Required**: `PHPSESSID`, `lastMode`
- **Response**: HTML application page
- **Note**: `service_id` is optional but recommended for multiservice accounts

**Session Lifetime**:
- Sessions expire after inactivity (typically 30-60 minutes)
- Expired sessions return `{"status": 300, "url": "..."}` in API responses
- Must repeat the full login flow to obtain a new session

---

#### State Retrieval API (stav.php)

**Endpoint**: `POST https://www.jablonet.net/app/ja100/ajax/stav.php`

**Purpose**: Retrieve the current state of all system components (sections, PGMs, sensors, PIRs, alarms, troubles)

**Required Headers**:
```
User-Agent: Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0
Accept: application/json, text/javascript, */*; q=0.01
Accept-Language: en-US,en;q=0.5
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
Origin: https://www.jablonet.net
Referer: https://www.jablonet.net/app/ja100?service={service_id}
Cookie: PHPSESSID=...; lastMode=...
```

**Request Body**:
```
activeTab=heat
```
- **activeTab**: Tab context (use `heat` for full data)

**Successful Response** (`HTTP 200 OK`):
```json
{
  "status": 200,
  "termostaty": [],
  "elektromery": [],
  "sekce": {
    "4": {
      "stav": 0,
      "nazev": "Garáž",
      "stateName": "STATE_5",
      "time": "30.10.2025 - 08:54",
      "active": 1
    },
    "0": {
      "stav": 0,
      "nazev": "Vše",
      "stateName": "STATE_1",
      "time": "16.11.2025 - 14:34",
      "active": 1
    }
  },
  "pgm": {
    "6": {
      "stav": 0,
      "nazev": "Osvětlení",
      "stateName": "PGM_7",
      "ts": 1764068252,
      "reaction": "pgorSwitchOnOff",
      "time": "today - 11:57",
      "active": 1
    },
    "15": {
      "stav": 0,
      "nazev": "Vrata",
      "stateName": "PGM_16",
      "ts": 1763300203,
      "reaction": "pgorPulse",
      "time": "16.11.2025 - 14:36",
      "active": 1
    }
  },
  "moduly": [],
  "alarms": [],
  "troubles": [
    {
      "type": "TROUBLE",
      "message": "Periphery battery low - Periphery Teplota venku",
      "date": "22.11.2025 04:32"
    }
  ],
  "tampers": [],
  "service": 0,
  "sdc": [],
  "common": [],
  "teplomery": {
    "040": {
      "stateName": "HEAT_40",
      "value": 1.3,
      "ts": 1764069354
    },
    "046": {
      "stateName": "HEAT_46",
      "value": 40.8,
      "ts": 1764069379
    }
  },
  "pir": {
    "5": {
      "stateName": "PPIR_6790289",
      "nazev": "PIR Chodba",
      "active": 0,
      "last_pic": -1,
      "type": "JA-160PC"
    },
    "6": {
      "stateName": "PPIR_6790397",
      "nazev": "PIR Vstup",
      "active": 1,
      "last_pic": -1,
      "type": "JA-120PC"
    }
  },
  "tz": "Europe/Prague",
  "prava": 0,
  "permissions": {
    "PGM_1": 0,
    "PGM_7": 1,
    "STATE_1": 1,
    "STATE_2": 0
  },
  "timeStamp": 1764069529,
  "vypis": []
}
```

**Error Response - Session Expired** (`HTTP 200 OK`):
```json
{
  "status": 300,
  "url": "https://www.jablonet.net/app/ja100?service="
}
```
- **status**: `300` indicates session expired
- **Action**: Must re-authenticate (repeat login flow)

**Response Fields Reference**:

- **status**: `200` = success, `300` = session expired
- **sekce**: Alarm sections (armed/disarmed state)
  - `stav`: `0` = disarmed, `1` = armed
  - `nazev`: Section name
  - `stateName`: API identifier (e.g., `STATE_1`)
  - `time`: Last state change timestamp (human-readable)
  - `active`: `1` = section is active/available

- **pgm**: PGM (Programmable Outputs)
  - `stav`: `0` = off/inactive, `1` = on/active
  - `nazev`: PGM name
  - `stateName`: API identifier (e.g., `PGM_7`)
  - `ts`: Unix timestamp of last state change
  - `reaction`: Output type
    - `pgorSwitchOnOff`: Bistable switch (on/off control)
    - `pgorPulse`: Momentary pulse (auto-resets)
    - `pgorCopy`: Mirrors another device state
  - `time`: Human-readable last change time
  - `active`: `1` = PGM is active/available

- **teplomery**: Temperature sensors
  - `value`: Temperature in °C
  - `ts`: Unix timestamp of last reading
  - `stateName`: API identifier (e.g., `HEAT_40`)

- **pir**: PIR motion sensors
  - `nazev`: Sensor name
  - `active`: `0` = no motion, `1` = motion detected
  - `last_pic`: Picture ID (-1 if no camera)
  - `type`: Device model (e.g., `JA-120PC`)
  - `stateName`: API identifier (e.g., `PPIR_6790289`)

- **permissions**: User control permissions
  - Key: `stateName` (e.g., `PGM_7`, `STATE_1`)
  - Value: `0` = no permission, `1` = can control
  - Used to determine if switch entities should be created

- **troubles**: Active system troubles/warnings
- **alarms**: Recent alarms
- **tampers**: Tamper events
- **timeStamp**: Server timestamp (Unix)
- **tz**: Timezone

---

#### Control API (ovladani2.php)

**Endpoint**: `POST https://www.jablonet.net/app/ja100/ajax/ovladani2.php`

**Purpose**: Control PGM outputs (turn on/off, trigger pulse)

**Required Headers**:
```
User-Agent: Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0
Accept: application/json, text/javascript, */*; q=0.01
Accept-Language: en-US,en;q=0.5
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
Origin: https://www.jablonet.net
Referer: https://www.jablonet.net/app/ja100?service={service_id}
Cookie: PHPSESSID=...; lastMode=...
```

**Request Body** (Turn OFF example):
```
section=PGM_7&status=0&code=1234&uid=PGM_7_prehled
```

**Request Body** (Turn ON example):
```
section=PGM_7&status=1&code=1234&uid=PGM_7_prehled
```

**Parameters**:
- **section**: PGM stateName (e.g., `PGM_7` for PGM ID `6`)
  - Format: `PGM_{id+1}` (PGM ID 6 → PGM_7)
- **status**: Target state
  - `0` = turn off / deactivate
  - `1` = turn on / activate
- **code**: User's PGM control code (4-digit PIN)
- **uid**: UI identifier, format: `{section}_prehled`

**Successful Response** (`HTTP 200 OK`):
```json
{
  "ts": 1764068250,
  "id": "PGM_7",
  "authorization": 200,
  "result": 0,
  "responseCode": 200
}
```

**Response Fields**:
- **ts**: Unix timestamp of the state change
- **id**: PGM stateName that was controlled
- **authorization**: `200` = authorized, other = permission denied
- **result**: New state after command
  - `0` = PGM is now off
  - `1` = PGM is now on
- **responseCode**: `200` = success, other = error

**Error Response - Unauthorized** (`HTTP 200 OK`):
```json
{
  "ts": 1764068250,
  "id": "PGM_7",
  "authorization": 403,
  "result": 0,
  "responseCode": 403
}
```
- **authorization**: `403` = wrong PGM code or no permission
- **responseCode**: `403` = authorization failed

**Error Response - Session Expired** (`HTTP 200 OK`):
```json
{
  "status": 300,
  "url": "https://www.jablonet.net/app/ja100?service="
}
```
- Same as stav.php - must re-authenticate

**Important Notes**:
- The `result` field in the response contains the **actual new state** from the server
- Always use this value to update the local state (don't assume command succeeded)
- For `pgorPulse` type PGMs, state may return to 0 automatically after pulse
- For `pgorSwitchOnOff` type PGMs, state persists until changed
- Invalid PGM code returns authorization error, not session error

---

#### PGM ID Mapping

**Important**: PGM IDs in the API are offset by 1:
- **In `stav.php` response**: PGM with key `"6"` has `stateName: "PGM_7"`
- **In `ovladani2.php` request**: Must use `section=PGM_7` to control PGM ID 6
- **Formula**: `stateName = "PGM_" + (pgm_id + 1)`

**Example**:
```python
pgm_id = "6"  # From stav.php response key
state_name = f"PGM_{int(pgm_id) + 1}"  # "PGM_7"
# Use "PGM_7" in control requests
```

---

#### PGM Reaction Types

Different PGM types behave differently when controlled:

**`pgorSwitchOnOff`** (Bistable Switch):
- Can be turned ON (status=1) and OFF (status=0)
- State persists until changed
- Example: Fan, heating valve, lights
- **Create switch entities** for this type

**`pgorPulse`** (Momentary):
- Activates briefly, then auto-resets to OFF
- Sending status=1 triggers pulse, returns to 0
- Example: Doorbell, gate trigger, lock pulse
- **Create switch entities** if the user wants manual control
- State always returns to 0 after pulse duration

**`pgorCopy`** (Mirror/Sensor):
- Mirrors the state of another device (door sensor, etc.)
- Cannot be controlled via API
- Read-only state
- Example: Door/window contact, gate position
- **Create binary sensors** only (read-only)

**Switchable Reactions** (can be controlled):
- `pgorSwitchOnOff`
- `pgorPulse`

**Non-Switchable Reactions** (read-only):
- `pgorCopy`
- Others (if any)

---

#### API Error Handling Best Practices

1. **Always check HTTP status is 200** (but errors still in JSON body)
2. **Check response JSON structure**:
   - If `status: 300` → Session expired, re-login
   - If `authorization: 403` → Wrong PGM code or no permission
   - If `responseCode: 200` → Success
3. **Use response `result` field** for actual state (don't assume)
4. **Handle network errors** with retry backoff
5. **Rate limiting**: Avoid hammering API (configurable retry backoff, default: 5 minutes)

---

#### Example: Complete Control Flow

```python
# 1. Get current state
response = POST stav.php
if response["status"] == 300:
    # Session expired - re-login
    login()
    response = POST stav.php

# 2. Check permission
pgm_id = "6"
state_name = f"PGM_{int(pgm_id) + 1}"  # "PGM_7"
has_permission = response["permissions"].get(state_name) == 1
if not has_permission:
    raise Exception("No permission to control this PGM")

# 3. Control PGM
control_response = POST ovladani2.php
    section=PGM_7
    status=1
    code=1234
    uid=PGM_7_prehled

# 4. Process response
if control_response.get("status") == 300:
    # Session expired during control
    login()
    # Retry control
    
if control_response.get("authorization") != 200:
    raise Exception("Authorization failed - wrong PGM code")
    
if control_response.get("responseCode") != 200:
    raise Exception("Control failed")

# 5. Update the local state with an actual result
new_state = control_response["result"]  # 0 or 1
# Update coordinator data immediately with this authoritative state
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

### 6. `switch.py` - Switch Platform (PGM Control)

**Purpose**: Creates switch entities for controllable PGM outputs (bistable and pulse types).

**Key Function**: `async_setup_entry(hass, entry, async_add_entities)`

**Flow**:
1. Check if PGM control code is configured
2. Get coordinator data and permissions
3. Loop through `coordinator.data["pgm"]`
4. For each PGM with a switchable reaction type and permission:
   - Create `JablotronPGMSwitch`
5. Add switch entities to Home Assistant

**Class**: `JablotronPGMSwitch(CoordinatorEntity, SwitchEntity)`

**Key Methods**:

- **`_async_control_pgm(turn_on: bool)`**: Shared logic for on/off control
  - Sets optimistic state (freezes coordinator updates during operation)
  - Calls `client.control_pgm(pgm_id, command)`
  - Processes response and updates coordinator data immediately
  - Requests full refresh for other entities
  - Handles errors with state reversion

- **`async_turn_on()`**: Calls `_async_control_pgm(turn_on=True)`
- **`async_turn_off()`**: Calls `_async_control_pgm(turn_on=False)`

**State Management**:
- Uses optimistic state during control operation
- Freezes entity to prevent coordinator overwrites
- Processes control response for immediate state update
- Triggers full refresh after control completes

**Key Properties**:
- **`is_on`**: Returns optimistic state during operation, otherwise from coordinator data
- **`_handle_coordinator_update()`**: Blocks updates while optimistic state is set

**Edit here**: Add support for the section arming/disarming

---

### 7. `const.py` - Constants & Configuration

**Purpose**: Centralized configuration constants.

**Constants**:

```python
DOMAIN = "jablotron_web"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SERVICE_ID = "service_id"
CONF_SENSOR_NAMES = "sensor_names"
CONF_PGM_CODE = "pgm_code"
DEFAULT_SCAN_INTERVAL = 300

# API URLs
API_BASE_URL = "https://www.jablonet.net"
API_LOGIN_URL = f"{API_BASE_URL}/ajax/login.php"
API_STATUS_URL = f"{API_BASE_URL}/app/ja100/ajax/stav.php"
API_CONTROL_URL = f"{API_BASE_URL}/app/ja100/ajax/ovladani2.php"

# PGM reactions that support switching
PGM_SWITCHABLE_REACTIONS = ["pgorSwitchOnOff", "pgorPulse"]
```

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
Create JablotronClient(username, password, service_id, hass, pgm_code, timeout=10)
    ↓
Create DataUpdateCoordinator
    ↓
coordinator.async_config_entry_first_refresh()
    ↓
JablotronClient.get_status() (with 10-second timeout)
    ↓
    ├─ If no PHPSESSID → login()
    ├─ If status == 300 → login() + retry
    ├─ If timeout → Raise error → retry delay (default: 5 min)
    └─ Return data
    ↓
coordinator.data = {teplomery: {...}, pgm: {...}, sekce: {...}, pir: {...}, permissions: {...}}
    ↓
    ├─ sensor.async_setup_entry() → Create temperature sensors
    ├─ binary_sensor.async_setup_entry() → Create section, PGM, PIR binary sensors
    └─ switch.async_setup_entry() → Create PGM switches (if pgm_code configured)
    ↓
Entities read from coordinator.data
    ↓
Every 300s: coordinator triggers update → repeat get_status()
    ↓
User switches PGM:
    ├─ switch._async_control_pgm() → Freeze state
    ├─ client.control_pgm(pgm_id, status) → Send command (with 10-second timeout)
    ├─ Process response → Update coordinator.data immediately
    ├─ coordinator.async_request_refresh() → Full sync
    └─ Unfreeze state
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
- Sensor removed from a system
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
4. Create an entity class extending the appropriate base
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
    "6": {"stav": 1, "nazev": "Osvětlení", "stateName": "PGM_7", ...}
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

