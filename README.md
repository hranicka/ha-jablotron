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

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### Educational Purpose Disclaimer

⚠️ **Important Notice**:
- This software is created for **non-profit and self-educational purposes only**
- The author provides this software "as is" **without any warranty or guarantee**
- The author assumes **no responsibility** for any damages, losses, or issues that may arise from the use of this software
- You use this software **entirely at your own risk**
- The author is not liable for any direct, indirect, incidental, special, exemplary, or consequential damages arising from the use of this software

---

## Developer Documentation

For developers wanting to understand or modify the integration:

[See DEVELOPER.md](DEVELOPER.md) - Technical guide with code explanations, error handling, and modification instructions.
