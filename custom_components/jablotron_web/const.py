"""Constants for Jablotron Web integration."""

DOMAIN = "jablotron_web"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SERVICE_ID = "service_id"
CONF_SENSOR_NAMES = "sensor_names"
CONF_PGM_CODE = "pgm_code"
CONF_TIMEOUT = "timeout"
CONF_RETRY_DELAY = "retry_delay"

DEFAULT_SCAN_INTERVAL = 300
DEFAULT_TIMEOUT = 10  # 10 seconds
DEFAULT_RETRY_DELAY = 300  # 5 minutes (in seconds)

# Legacy constant for backward compatibility
RETRY_DELAY = DEFAULT_RETRY_DELAY

# API URLs
API_BASE_URL = "https://www.jablonet.net"
API_LOGIN_URL = f"{API_BASE_URL}/ajax/login.php"
API_STATUS_URL = f"{API_BASE_URL}/app/ja100/ajax/stav.php"
API_CONTROL_URL = f"{API_BASE_URL}/app/ja100/ajax/ovladani2.php"

# PGM reactions that support switching
PGM_SWITCHABLE_REACTIONS = ["pgorSwitchOnOff", "pgorPulse"]
