"""Config flow for Jablotron Web integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_SERVICE_ID, CONF_SENSOR_NAMES, DEFAULT_SCAN_INTERVAL
from .jablotron_client import JablotronClient

_LOGGER = logging.getLogger(__name__)


class JablotronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Jablotron Web."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._discovered_sensors = {}
        self._user_input = {}

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            client = JablotronClient(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input.get(CONF_SERVICE_ID, ""),
                self.hass,
            )
            try:
                if not await client.login():
                    errors["base"] = "invalid_auth"
                else:
                    # Get initial data to discover sensors
                    try:
                        data = await client.get_status()
                        if data and "teplomery" in data:
                            self._discovered_sensors = {
                                sensor_id: f"Teploměr {sensor_id}"
                                for sensor_id in data["teplomery"].keys()
                            }
                    except Exception as e:
                        _LOGGER.warning(f"Could not fetch sensors: {e}")
                        self._discovered_sensors = {}

                    self._user_input = user_input

                    # If sensors were discovered, go to a naming step
                    if self._discovered_sensors:
                        return await self.async_step_sensors()

                    if self.context.get("source") == config_entries.SOURCE_REAUTH:
                        existing_entry = self.hass.config_entries.async_get_entry(
                            self.context["entry_id"]
                        )
                        self.hass.config_entries.async_update_entry(
                            existing_entry, data=user_input
                        )
                        await self.hass.config_entries.async_reload(existing_entry.entry_id)
                        return self.async_abort(reason="reauth_successful")

                    # Otherwise, create entry without custom names
                    await self.async_set_unique_id(user_input[CONF_USERNAME])
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"Jablotron ({user_input[CONF_USERNAME]})",
                        data=user_input,
                    )
            except Exception:
                _LOGGER.exception("Unexpected exception during login")
                errors["base"] = "cannot_connect"
            finally:
                # Ensure the client session is always closed
                await client.async_close()

        if errors:
            # If there were errors, show the form again
            data_schema = vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_SERVICE_ID, default=user_input.get(CONF_SERVICE_ID, "")): str,
                }
            )
            return self.async_show_form(
                step_id="user", data_schema=data_schema, errors=errors
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SERVICE_ID, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_sensors(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle sensor naming step."""
        if user_input is not None:
            # Combine credentials with sensor names
            data = {**self._user_input}
            data[CONF_SENSOR_NAMES] = {
                sensor_id: user_input.get(f"sensor_{sensor_id}", default_name)
                for sensor_id, default_name in self._discovered_sensors.items()
            }

            await self.async_set_unique_id(self._user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Jablotron ({self._user_input[CONF_USERNAME]})",
                data=data,
            )

        # Build schema for sensor names
        schema_dict = {}
        for sensor_id, default_name in sorted(self._discovered_sensors.items()):
            schema_dict[vol.Optional(f"sensor_{sensor_id}", default=default_name)] = str

        return self.async_show_form(
            step_id="sensors",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "sensor_count": str(len(self._discovered_sensors))
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the option flow for this handler."""
        return JablotronOptionsFlowHandler(config_entry)


class JablotronOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Jablotron Web."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize option flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "scan_interval",
                        default=self.config_entry.options.get(
                            "scan_interval", DEFAULT_SCAN_INTERVAL
                        ),
                    ): cv.positive_int,
                }
            ),
        )

