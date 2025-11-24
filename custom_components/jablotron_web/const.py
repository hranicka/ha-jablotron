"""Constants for Jablotron Web integration."""

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
PGM_SWITCHABLE_REACTIONS = ["pgorSwitchOnOff"]
