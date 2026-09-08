# Jablotron API Reference (MyJABLOTRON mobile API v2.2)

The integration talks to the same API as the official MyJABLOTRON mobile app.
The old web endpoints on `www.jablonet.net` are closed to non-browser clients
since the 2026 web rework (TLS fingerprinting at nginx plus reCAPTCHA v2 on
the `jip.jablotron.cloud` SSO login) and cannot be used programmatically.

Unlike the old web API, this API returns proper HTTP status codes (401 for
auth/session problems) with machine-readable error codes in the body.

## Base URL

```
https://api.jablonet.net/api/2.2/
```

## Authentication Flow (2 requests)

### Step 1: Authorize

```
POST https://api.jablonet.net/api/2.2/userAuthorize.json
Content-Type: application/json

{"login": "<email>", "password": "<password>"}
```

**Response (success)**: HTTP 200 with `{"http-code": 200, ...}` and a
`PHPSESSID` session cookie.

**Response (failure)**: HTTP 401 with:

```json
{"errors": [{"code": "USER.LOGIN.INVALID-CREDENTIALS", "message": "Invalid login information"}], "http-code": 401}
```

### Step 2 (implicit): Session cookie

The `PHPSESSID` cookie alone authenticates all subsequent data/control calls.
The client keeps it in an `aiohttp.CookieJar` for the lifetime of the session.

> `accessTokenGet.json` (returns a Bearer token) exists for the GraphQL event
> history API on `graph.jablotron.cloud` and is **not** used by this
> integration.

### Required headers (all requests)

Imitating the mobile client is mandatory — the API validates vendor headers:

```
User-Agent: net.jablonet/8.6.1.3887
x-vendor-id: JABLOTRON:Jablotron
x-client-version: MYJ-PUB-IOS-8.6.1.3887
Accept: application/json
Accept-Language: en
```

### Logout

```
POST https://api.jablonet.net/api/2.2/logout.json
Content-Type: application/x-www-form-urlencoded

system=HomeAssistant
```

Response body is ignored. Called best-effort on integration unload.

## Service List

```
POST https://api.jablonet.net/api/2.2/serviceListGet.json
Content-Type: application/json

{"list-type": "EXTENDED", "visibility": "VISIBLE"}
```

**Response**:

```json
{
  "http-code": 200,
  "data": {
    "services": [
      {"service-id": 123456, "name": "Home", "status": "ENABLED",
       "service-type": "JA100", "warning": "", "warning-time": ""}
    ]
  }
}
```

`service-type` is `JA100`, `JA100F` or `OASIS` (matched case-insensitively).
Only `JA100` is supported. If no `service_id` is configured, the integration
picks the first enabled `JA100` service automatically.

## State Retrieval

```
POST https://api.jablonet.net/api/2.2/dataUpdate.json
Content-Type: application/x-www-form-urlencoded

data=[{"filter_data":[{"data_type":"section"},{"data_type":"pgm"},{"data_type":"thermometer"},{"data_type":"thermostat"}],"service_type":"ja100","service_id":123456,"data_group":"serviceData"}]&system=HomeAssistant
```

(`data` is URL-encoded JSON; `system` is an arbitrary stable string.)

**Successful response** (abbreviated):

```json
{
  "status": true,
  "data": {
    "service_data": [
      {
        "service_id": "123456",
        "data": [
          {"data_type": "section", "data": {"segments": [
            {"segment_id": "STATE_1", "segment_state": "unset", "segment_name": "Vše"}
          ]}},
          {"data_type": "pgm", "data": {"segments": [
            {"segment_id": "PGM_7", "segment_state": "unset", "segment_name": "Osvětlení"}
          ]}},
          {"data_type": "thermometer", "data": {"segments": [
            {"segment_id": "THERMOMETER_40", "segment_state": "set", "segment_name": "Venku",
             "segment_informations": [{"value": 1.3, "type": "temperature"}]}
          ]}}
        ]
      }
    ]
  }
}
```

**Value semantics**:

- `segment_state`: `set` / `unset` / `partialSet` for sections, `set` /
  `unset` for PGMs. Anything other than `unset` maps to legacy `stav: 1`.
- `segment_informations[].value`: temperature in °C (first entry is used).

**Adapter**: the response is translated by `v22_adapter.py` into the legacy
`stav.php`-shaped dict (`sekce`, `pgm`, `teplomery`, `pir`, `permissions`,
`timeStamp`) that the platforms consume. See "ID Mapping" below.

### Session expired

HTTP 401 with `{"errors": [{"code": "USER.SESSION.EXPIRED", ...}], "http-code": 401}` —
triggers the automatic re-login + retry flow.

### Known gaps vs. the old web API

| Old (`stav.php`) | v2.2 (`dataUpdate.json`) | Consequence |
|------------------|--------------------------|-------------|
| `pir` (PIR motion sensors) | no data_type returns it (probed pir/peripheral/device/camera/window — all empty) | PIR binary sensors are absent; no workaround known |
| `reaction` per PGM (`pgorSwitchOnOff`/`pgorPulse`) | not reported | all PGMs default to bistable behavior |
| `permissions` per stateName | replaced by real flags: per-segment `segment_is_controllable` + account-level `service_permissions.controls_pgs` / `service_readonly` | a PGM becomes a switch when it is flagged controllable and a PGM code is configured |
| thermometer values | stale `"unknown"` cache in dataUpdate; live values via `thermoDevicesGet.json` (see above) | solved — sensors carry live values + `last-temperature-time` as `ts` |
| per-item `ts`/`time` timestamps | thermometers: `last-temperature-time`; sections/PGMs: none | PGM/section timestamp attributes absent |

## Thermo Devices (live temperature source)

`dataUpdate.json`'s thermometer segments only carry a **stale cache** (the
string `"unknown"` for online peripheries). Live readings come from the
per-alarm endpoint family instead:

```
POST https://api.jablonet.net/api/2.2/JA100/thermoDevicesGet.json
Content-Type: application/json

{"connect-device": false, "list-type": "FULL", "service-id": 70537, "service-states": true}
```

(`connect-device: false` is sufficient — fresh readings are returned either
way; the sibling endpoints `JA100/sectionsGet.json` and
`JA100/programmableGatesGet.json` follow the same pattern.)

**Response** (abbreviated):

```json
{
  "data": {
    "service-states": {"events": [{"type": "TROUBLE", "message": "...", "date": "..."}]},
    "states": [
      {"object-device-id": "THM-6790417", "temperature": 28,
       "last-temperature-time": "2026-09-08T15:51:03+02:00"}
    ]
  }
}
```

**Join key**: the numeric suffix of `object-device-id` equals the
dataUpdate thermometer segment's `segment_db_id` (`THM-6790417` ↔
`THERMOMETER_40` "Teplota venku"). A faulty periphery keeps reporting its
last reading with an old `last-temperature-time` — the value is shown, the
timestamp attribute reveals its staleness.

The client fetches this alongside every `dataUpdate.json` poll; on failure
it degrades gracefully to the cached dataUpdate values (sensors without a
cached value are not created).

## Control API (PGM Output)

```
POST https://api.jablonet.net/api/2.2/controlSegment.json
Content-Type: application/x-www-form-urlencoded

service=ja100&serviceId=123456&segmentId=PGM_7&segmentKey=pgm_7&expected_status=set&control_time=0&control_code=1234&system=HomeAssistant
```

| Parameter | Description |
|-----------|-------------|
| `service` | `ja100` |
| `serviceId` | numeric service id |
| `segmentId` | `PGM_{id+1}` (same stateName as the old web API) |
| `segmentKey` | lowercased segmentId, e.g. `pgm_7` |
| `expected_status` | `set` = on, `unset` = off |
| `control_time` | always `0` |
| `control_code` | user's PGM control PIN code |
| `system` | same stable string as in dataUpdate |

**Successful response**: HTTP 200 with `{"status": true}`.

**Failure**: HTTP 200 with `{"status": false, "error_message": "..."}` (e.g.
wrong code), or HTTP 401 when the session died. The client reports success as
`{"result": <0|1>, "ts": <unix>}` (legacy `ovladani2.php` shape); the
authoritative new state arrives with the next poll.

## PGM ID Mapping

Same numbering as the old web API — entity keys are the segment number minus
one:

```
dataUpdate segment "PGM_7"  → legacy key "6"
dataUpdate segment "PGM_16" → legacy key "15"
dataUpdate segment "STATE_1" → legacy key "0"
```

Temperature sensors keep the legacy zero-padded numbering
(`THERMOMETER_40` → `"040"`, matching the old `HEAT_40`); thermostats get
`"t"`-prefixed keys (`THERMOSTAT_1` → `"t001"`) so the two device families
cannot collide.

## Test Script

`test_jablonet.py` probes this API with real credentials (login, service list,
raw `dataUpdate.json` dump, extended data_type probes, and the adapted
legacy-shape summary). It never triggers control calls:

```bash
python test_jablonet.py <username> <password> [service_id]
```
