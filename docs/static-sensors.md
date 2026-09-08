# Static REST Sensors (Alternative)

> **⚠️ DEPRECATED — non-functional since the 2026 Jablotron web rework.**
> The `www.jablonet.net` web endpoints reject non-browser requests (TLS
> fingerprinting) and the scripted login now hits a reCAPTCHA-protected SSO,
> so neither the curl cookie recipe nor the REST sensor can work anymore.
> Use the custom component, which talks to the MyJABLOTRON mobile API
> (`api.jablonet.net`) — see [api-reference.md](api-reference.md).

A simple YAML-based alternative that uses Home Assistant's built-in REST sensor platform. **No automatic session management** — the user must manually manage the `PHPSESSID` cookie in configuration.

## When to Use

- Simple setups where manual cookie refresh is acceptable
- No HA custom component installation available
- Quick testing of API connectivity

## Limitations

- Manual `PHPSESSID` management (session expires, must update config)
- No auto re-authentication
- Static YAML — sensors not auto-discovered from API
- No PGM control (switch entities)
- No reauth flow, no options flow
- Cannot handle `status: 300` session expiry automatically

## Getting PHPSESSID

1. Log in to https://www.jablonet.net/ with a browser
2. Open Developer Tools (F12 → Application/Storage → Cookies)
3. Copy the `PHPSESSID` value
4. Replace `xxx` in the configuration below
5. Session expires periodically — you must manually update it

## Full API Flow via curl (for obtaining fresh cookies)

```bash
# Step 1: Get initial cookies
curl -c cookies.txt 'https://www.jablonet.net'

# Step 2: Login
curl -b cookies.txt -c cookies.txt \
  'https://www.jablonet.net/ajax/login.php' \
  -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'login=email@example.com&heslo=password&aStatus=200&loginType=Login'

# Step 3: Get lastMode cookie
curl -b cookies.txt -c cookies.zip \
  'https://www.jablonet.net/cloud'

# Step 4: Initialize JA100 app
curl -b cookies.txt -c cookies.zip \
  'https://www.jablonet.net/app/ja100?service=YOUR_SERVICE_ID'

# Step 5: Fetch status
curl -b cookies.txt \
  'https://www.jablonet.net/app/ja100/ajax/stav.php' \
  -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'activeTab=heat&service_id=YOUR_SERVICE_ID'
```

## Configuration

Add to `configuration.yaml` (or include via packages):

```yaml
rest:
  - resource: "https://www.jablonet.net/app/ja100/ajax/stav.php"
    method: POST
    headers:
      User-Agent: "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0"
      Accept: "application/json"
      Content-Type: "application/x-www-form-urlencoded"
      Cookie: "lastMode-info@example.com=jablonet; PHPSESSID=xxx"  # Replace with your session
    payload: "activeTab=heat&service_id=YOUR_SERVICE_ID"
    scan_interval: 300
    sensor:
      - name: "Jablotron Teploměr Obývák"
        unique_id: jablotron_teplomer_040
        value_template: "{{ value_json.teplomery['040'].value }}"
        unit_of_measurement: "°C"
        device_class: temperature
        state_class: measurement
      - name: "Jablotron Teploměr Kotel"
        unique_id: jablotron_teplomer_046
        value_template: "{{ value_json.teplomery['046'].value }}"
        unit_of_measurement: "°C"
        device_class: temperature
        state_class: measurement
    binary_sensor:
      - name: "Jablotron Osvětlení"
        unique_id: jablotron_pgm_6
        value_template: "{{ value_json.pgm['6'].stav == 1 }}"
        device_class: power
      - name: "Jabloton Přízemí Alarm"
        unique_id: jablotron_section_1
        value_template: "{{ value_json.sekce['1'].stav == 1 }}"
        device_class: safety
      - name: "Jabloton PIR Chodba"
        unique_id: jablotron_pir_2
        value_template: "{{ value_json.pir['2'].active == 1 }}"
        device_class: motion
```

## Dashboard Example

A simple dashboard template is in `static_sensors/dashboard_simple.yaml`. It creates an entities panel showing temperature sensors with badges.

## Value Logic (same as custom component)

| Entity type | Field | ON condition | OFF condition |
|-------------|-------|-------------|---------------|
| Temperature | `teplomery[<id>].value` | numeric °C | N/A (always numeric) |
| PGM status | `pgm[<id>].stav` | `1` | `0` |
| Section armed | `sekce[<id>].stav` | `1` (armed) | `0` (disarmed) |
| PIR motion | `pir[<id>].active` | `1` (motion) | `0` (no motion) |

## Recommendation

For production use, consider the **custom component** instead:
- Automatic session management
- Auto re-login on expiration
- Reauth flow support
- Auto-discovery of all sensors
- UI-based configuration

See [docs/configuration.md](../docs/configuration.md) for installation instructions.
