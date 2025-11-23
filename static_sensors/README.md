# REST Sensors for Jablotron (Static Configuration)

Simple REST-based sensors using Home Assistant's built-in REST platform. Requires manual PHPSESSID management.

## Getting PHPSESSID

1. Log in to https://www.jablonet.net/
2. Open browser Developer Tools (F12)
3. Go to Application/Storage → Cookies
4. Copy the `PHPSESSID` value
5. Replace `xxx` in the configuration below
6. Add also `service_id=` parametr to match your service ID (car, house, ...)

## Getting Data with curl

```bash
# Get PHPSESSID from browser first, then:
curl 'https://www.jablonet.net/app/ja100/ajax/stav.php' \
  -X POST \
  -H 'Cookie: lastMode-info@example.com=jablonet; PHPSESSID=your_session_id_here' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-raw 'activeTab=heat'
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
    payload: "activeTab=heat"
    scan_interval: 300
    sensor:
      - name: "Jablotron Teploměr Venku"
        value_template: "{{ value_json.teplomery['040'].value }}"
        unit_of_measurement: "°C"
        device_class: temperature
      - name: "Jablotron Teploměr Kotel"
        value_template: "{{ value_json.teplomery['046'].value }}"
        unit_of_measurement: "°C"
        device_class: temperature
    binary_sensor:
      - name: "Jablotron Ventilátor"
        value_template: "{{ value_json.pgm['6'].stav == 0 }}"
        device_class: power
```

## Limitations

- **Manual PHPSESSID**: Must be updated when the session expires
- **No auto re-login**: Sensors become unavailable when session expires
- **Static configuration**: All sensors must be defined in YAML

For automatic session management, use the custom component instead.

