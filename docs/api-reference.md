# Jablotron API Reference

All jablonet.net endpoints return HTTP 200 OK even when errors occur — error conditions are encoded in the JSON response body via a `status` field or specific error fields.

## Base URL

```
https://www.jablonet.net
```

## Authentication Flow (4-Step)

The API uses cookie-based session authentication mimicking browser behavior. Four requests must complete in order:

### Step 1: Get Initial Session Cookie

```
GET https://www.jablonet.net
```

**Purpose**: Obtain initial `PHPSESSID` cookie.

**Headers**: `User-Agent`, `Accept` (text/html) — standard browser headers.

**Response**: HTML page, Set-Cookie header with `PHPSESSID`.

---

### Step 2: POST Credentials

```
POST https://www.jablonet.net/ajax/login.php
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
Origin: https://www.jablonet.net
Referer: https://www.jablonet.net/

login=<email>&heslo=<password>&aStatus=200&loginType=Login
```

**Purpose**: Authenticate user.

**Cookies required**: `PHPSESSID` from Step 1.

**Response**: 
- HTTP 200 on success; error message in JSON body via `errorMessage` field
- Set-Cookie with authenticated `PHPSESSID`

**Error**: `{"errorMessage": "..."}` — wrong credentials.

---

### Step 3: Get lastMode Cookie

```
GET https://www.jablonet.net/cloud
Referer: https://www.jablonet.net/
```

**Purpose**: Obtain `lastMode` cookie for app access.

**Cookies required**: Authenticated `PHPSESSID`.

**Response**: HTML redirect page, Set-Cookie with `lastMode`.

---

### Step 4: Initialize JA100 App Session

```
GET https://www.jablonet.net/app/ja100?service=<service_id>
Referer: https://www.jablonet.net/cloud
```

**Purpose**: Finalize session for JA100 app API access.

**Cookies required**: `PHPSESSID`, `lastMode`.

**Response**: HTML application page. The `service` query parameter is optional but recommended when multiple services (house, car, etc.) are linked to the account.

---

### Cookie Management

The integration uses a dedicated `aiohttp.CookieJar()` per client instance:
- Cookies persist across requests within the same session
- Cookies are cleared entirely on every error via `_reset_session()`
- The aiohttp session is recreated automatically on first use (`self.session is None`) and after errors

### Session Lifetime

Sessions expire after inactivity (typically 30–60 minutes). Expired sessions return `{"status": 300, "url": "..."}` on API calls.

## State Retrieval API

**Endpoint**: `POST https://www.jablonet.net/app/ja100/ajax/stav.php`

**Purpose**: Get the full current state of all system components (sections, PGMs, temperature sensors, PIR sensors, permissions, alarms, troubles).

### Request Headers

```
User-Agent: Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0
Accept: application/json, text/javascript, */*; q=0.01
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
Origin: https://www.jablonet.net
Referer: https://www.jablonet.net/app/ja100?service=<service_id>
Cookie: PHPSESSID=<...>; lastMode=<...>
```

### Request Body

```
activeTab=heat
```

The `activeTab` parameter specifies the web app tab context. Use `heat` for full data including temperature sensors and PGMs. Optional `service_id` query param can be appended: `activeTab=heat&service_id=<id>`.

### Successful Response (HTTP 200, status field = 200)

```json
{
  "status": 200,
  "sekce": {
    "0": { "stav": 0, "nazev": "Vše", "stateName": "STATE_1", "time": "30.11.2025 - 14:34", "active": 1 },
    "4": { "stav": 1, "nazev": "Garáž", "stateName": "STATE_5", "time": "30.10.2025 - 08:54", "active": 1 }
  },
  "pgm": {
    "6": { "stav": 0, "nazev": "Osvětlení", "stateName": "PGM_7", "ts": 1764068252, "reaction": "pgorSwitchOnOff", "time": "today - 11:57", "active": 1 },
    "15": { "stav": 0, "nazev": "Vrata", "stateName": "PGM_16", "ts": 1763300203, "reaction": "pgorPulse", "time": "16.11.2025 - 14:36", "active": 1 }
  },
  "teplomery": {
    "040": { "stateName": "HEAT_40", "value": 1.3, "ts": 1764069354 },
    "046": { "stateName": "HEAT_46", "value": 40.8, "ts": 1764069379 }
  },
  "pir": {
    "5": { "stateName": "PPIR_6790289", "nazev": "PIR Chodba", "active": 0, "last_pic": -1, "type": "JA-160PC" },
    "6": { "stateName": "PPIR_6790397", "nazev": "PIR Vstup", "active": 1, "last_pic": -1, "type": "JA-120PC" }
  },
  "permissions": {
    "PGM_7": 1,
    "STATE_1": 1
  },
  "troubles": [
    { "type": "TROUBLE", "message": "Periphery battery low - Periphery Teplota venku", "date": "22.11.2025 04:32" }
  ],
  "alarms": [],
  "tampers": [],
  "service": 0,
  "tz": "Europe/Prague",
  "prava": 0,
  "timeStamp": 1764069529
}
```

**Response fields**:

| Field | Description |
|-------|-------------|
| `status` | `200` = success, `300` = session expired |
| `sekce` | Alarm sections — keys are section IDs |
| `pgm` | Programmable outputs — keys are PGM IDs (offset by 1 from stateName) |
| `teplomery` | Temperature sensors — keys are sensor IDs |
| `pir` | PIR motion sensors — keys are PIR IDs |
| `permissions` | User control permissions — key=stateName, value=`0`=no access, `1`=can control |
| `troubles` | Active system troubles/warnings |
| `alarms` | Recent alarm events |
| `tampers` | Tamper events |
| `timeStamp` | Server timestamp (Unix epoch) |
| `tz` | Server timezone identifier |

**Value semantics**:

- `stav`: `0` = off/disarmed, `1` = on/armed
- `active`: `1` = entity is available in the system
- `active` in PIR: `0` = no motion, `1` = motion detected
- `value` in temperature: numeric °C (float)

### Error Response — Session Expired

```json
{ "status": 300, "url": "https://www.jablonet.net/app/ja100?service=" }
```

Detected by `_http_json()` which raises `JablotronSessionError`. Triggers automatic re-login.

## Control API (PGM Output)

**Endpoint**: `POST https://www.jablonet.net/app/ja100/ajax/ovladani2.php`

**Purpose**: Control PGM outputs (turn on/off). Requires a valid session and user's PGM control code.

### Request Headers

Same as stav.php, plus:

```
Cookie: PHPSESSID=<...>; lastMode=<...>
```

### Request Body

```
section=PGM_7&status=1&code=1234&uid=PGM_7_prehled
```

**Parameters**:

| Parameter | Description |
|-----------|-------------|
| `section` | PGM stateName, format: `PGM_{id+1}` (e.g., API key `"6"` → `"PGM_7"`) |
| `status` | `0` = off/deactivate, `1` = on/activate |
| `code` | User's 4-digit PGM control PIN code |
| `uid` | UI identifier, format: `{section}_prehled` |

### Successful Response

```json
{
  "ts": 1764068250,
  "id": "PGM_7",
  "authorization": 200,
  "result": 1,
  "responseCode": 200
}
```

| Field | Description |
|-------|-------------|
| `ts` | Unix timestamp of state change |
| `id` | PGM stateName that was controlled |
| `authorization` | `200` = authorized, `403` = wrong code/no permission |
| `result` | New active state (`0` or `1`) — the authoritative source |
| `responseCode` | `200` = success, other = control failed |

### Error Responses

- **Unauthorized**: `{"authorization": 403, "responseCode": 403}` — wrong PGM code or no permission
- **Session expired**: `{"status": 300, "url": "..."}` — same as state API

## PGM Reaction Types

| Type | Behavior | Controllable | Entity type |
|------|----------|-------------|-------------|
| `pgorSwitchOnOff` | Bistable switch — state persists | Yes | Switch (if code + permission) or binary sensor |
| `pgorPulse` | Momentary pulse — auto-resets to off after short duration | Yes | Switch (if code + permission) or binary sensor |
| `pgorCopy` | Mirrors another device state (read-only) | No | Binary sensor only |

The integration imports `PGM_SWITCHABLE_REACTIONS = ["pgorSwitchOnOff", "pgorPulse"]` from `const.py`.

## PGM ID Mapping

API response keys are 0-based and differ from the stateName:

```
stav.php key "6" → stateName "PGM_7"      (id + 1)
stav.php key "15" → stateName "PGM_16"    (id + 1)
```

Control API uses stateName format: `section=PGM_{int(pgm_id) + 1}`.
