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

# MyJABLOTRON mobile API v2.2 (api.jablonet.net). The web endpoints on
# www.jablonet.net reject non-browser clients since the 2026 web rework
# (TLS fingerprinting + reCAPTCHA on the SSO login), so the integration
# speaks the same API as the official mobile app instead.
API_V22_BASE_URL = "https://api.jablonet.net/api/2.2/"
API_USER_AUTHORIZE_URL = f"{API_V22_BASE_URL}userAuthorize.json"
API_ACCESS_TOKEN_URL = f"{API_V22_BASE_URL}accessTokenGet.json"
API_LOGOUT_URL = f"{API_V22_BASE_URL}logout.json"
API_SERVICE_LIST_URL = f"{API_V22_BASE_URL}serviceListGet.json"
API_DATA_UPDATE_URL = f"{API_V22_BASE_URL}dataUpdate.json"
API_CONTROL_SEGMENT_URL = f"{API_V22_BASE_URL}controlSegment.json"
# Live thermometer values: dataUpdate's thermometer segments only carry a
# stale cache ("unknown"); the per-alarm thermoDevicesGet endpoint returns
# real per-device readings (joined via THM-{segment_db_id}).
API_THERMO_DEVICES_URL = f"{API_V22_BASE_URL}JA100/thermoDevicesGet.json"

# Headers imitating the official MyJABLOTRON mobile client
API_USER_AGENT = "net.jablonet/8.6.1.3887"
API_VENDOR_ID = "JABLOTRON:Jablotron"
API_CLIENT_VERSION = "MYJ-PUB-IOS-8.6.1.3887"
API_ACCEPT_LANGUAGE = "en"

# `system` form value sent with data/control calls (any stable string works)
API_SYSTEM_NAME = "HomeAssistant"

# Service type of classic JA-100 panels (JA-100F/OASIS use different endpoints)
SERVICE_TYPE_JA100 = "ja100"

# API error codes (payload `errors[].code`)
ERROR_INVALID_CREDENTIALS = "USER.LOGIN.INVALID-CREDENTIALS"
ERROR_SESSION_EXPIRED = "USER.SESSION.EXPIRED"

# Segment ID prefixes in dataUpdate.json responses
SEGMENT_PREFIX_SECTION = "STATE_"
SEGMENT_PREFIX_PGM = "PGM_"
SEGMENT_PREFIX_THERMOMETER = "THERMOMETER_"
SEGMENT_PREFIX_THERMOSTAT = "THERMOSTAT_"

# PGM reactions that support switching
PGM_REACTION_SWITCH = "pgorSwitchOnOff"
PGM_REACTION_PULSE = "pgorPulse"
PGM_SWITCHABLE_REACTIONS = [PGM_REACTION_SWITCH, PGM_REACTION_PULSE]

# PGM states (stav field)
PGM_STATE_ON = 1
PGM_STATE_OFF = 0
