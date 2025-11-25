# REST Sensors for Jablotron (Static Configuration)

Simple REST-based sensors using Home Assistant's built-in REST platform. Requires manual PHPSESSID management.

⚠️ **Note**: For automatic session management and all sensor types, use the custom component instead.

## Getting PHPSESSID

1. Log in to https://www.jablonet.net/
2. Open browser Developer Tools (F12)
3. Go to Application/Storage → Cookies
4. Copy the `PHPSESSID` value
5. Replace `xxx` in the configuration below
6. Add also `service_id=` parameter to match your service ID (car, house, ...)

**Note**: Session expires periodically - you'll need to manually update PHPSESSID when it does.

## Getting Data with curl

```bash
# Method 1: Test with cookies from browser
curl 'https://www.jablonet.net/app/ja100/ajax/stav.php' \
  -X POST \
  -H 'Cookie: lastMode-info@example.com=jablonet; PHPSESSID=your_session_id_here' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'activeTab=heat&service_id=YOUR_SERVICE_ID'

# Method 2: Full authentication flow (recommended for testing)
# Step 1: Get initial cookies
curl -c cookies.txt 'https://www.jablonet.net'

# Step 2: Login
curl -b cookies.txt -c cookies.txt 'https://www.jablonet.net/ajax/login.php' \
  -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'login=email@example.com&heslo=password&aStatus=200&loginType=Login'

# Step 3: Get lastMode cookie
curl -b cookies.txt -c cookies.txt 'https://www.jablonet.net/cloud'

# Step 4: Initialize JA100 app
curl -b cookies.txt -c cookies.txt 'https://www.jablonet.net/app/ja100?service=YOUR_SERVICE_ID'

# Step 5: Fetch data
curl -b cookies.txt 'https://www.jablonet.net/app/ja100/ajax/stav.php' \
  -X POST \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data 'activeTab=heat&service_id=YOUR_SERVICE_ID'
```

## Configuration

Add to `configuration.yaml`:

```yaml
rest:
  - resource: "https://www.jablonet.net/app/ja100/ajax/stav.php"
    method: POST
    headers:
      User-Agent: "Mozilla/5.0"
      Accept: "application/json"
      Content-Type: "application/x-www-form-urlencoded"
      Cookie: "PHPSESSID=xxx"  # Replace xxx with your session ID
    payload: "activeTab=heat&service_id=YOUR_SERVICE_ID"  # Add your service_id
    scan_interval: 300
    sensor:
      # Temperature sensors
      - name: "Jablotron Teploměr Obývák"
        value_template: "{{ value_json.teplomery['040'].value }}"
        unit_of_measurement: "°C"
        device_class: temperature
      - name: "Jablotron Teploměr Ložnice"
        value_template: "{{ value_json.teplomery['046'].value }}"
        unit_of_measurement: "°C"
        device_class: temperature
    binary_sensor:
      # PGM outputs (stav == 1 means ON)
      - name: "Jablotron Osvětlení"
        value_template: "{{ value_json.pgm['6'].stav == 1 }}"
        device_class: power
      
      # Alarm sections (stav == 1 means Armed)
      - name: "Jablotron Přízemí"
        value_template: "{{ value_json.sekce['1'].stav == 1 }}"
        device_class: safety
      
      # PIR motion sensors (active == 1 means Motion)
      - name: "Jablotron PIR Chodba"
        value_template: "{{ value_json.pir['2'].active == 1 }}"
        device_class: motion
```

## State Logic

**Temperature Sensors** (`teplomery`):
- Access via `value_json.teplomery['SENSOR_ID'].value`

**PGM Outputs** (`pgm`):
- `stav == 1` → ON (Active)
- `stav == 0` → OFF (Inactive)

**Alarm Sections** (`sekce`):
- `stav == 1` → ON (Armed)
- `stav == 0` → OFF (Disarmed)

**PIR Sensors** (`pir`):
- `active == 1` → ON (Motion detected)
- `active == 0` → OFF (No motion)

## Limitations

- Manual PHPSESSID management (needs updating when session expires)
- No automatic re-authentication
- Static configuration (sensors not auto-discovered)
- No reauth flow
- Response with `{"status": 300}` means session expired - update PHPSESSID manually

## Recommendation

For production use, consider the **custom component** instead:
- Automatic session management
- Auto re-login on expiration
- Reauth flow support
- Auto-discovery of all sensors
- UI-based configuration

[See custom component README](../custom_components/jablotron_web/README.md)

