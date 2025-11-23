# Jablotron Integration for Home Assistant
Two approaches for integrating Jablotron JA-100 sensors into Home Assistant:
## 1. Custom Component (Recommended)
**Location**: `custom_components/jablotron_web/`
- Automatic session management
- Auto re-login on expiration
- Customizable sensor names
- Auto-discovered sensors
[See README](custom_components/jablotron_web/README.md)
## 2. REST Sensors (Static)
**Location**: `static_sensors/`
- Simple REST configuration
- Manual PHPSESSID management
- Static YAML configuration
[See README](static_sensors/README.md)
---
## Developer Documentation
For developers wanting to understand or modify the integration:
[See DEVELOPER.md](DEVELOPER.md) - Technical guide with code explanations, error handling, and modification instructions.
