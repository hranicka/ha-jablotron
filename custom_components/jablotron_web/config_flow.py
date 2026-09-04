"""Config flow for Jablotron Web integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, CONF_SERVICE_ID, CONF_SENSOR_NAMES, CONF_PGM_CODE, DEFAULT_SCAN_INTERVAL, CONF_TIMEOUT, DEFAULT_TIMEOUT, CONF_RETRY_DELAY, DEFAULT_RETRY_DELAY
from .jablotron_client import JablotronClient, JablotronAuthError

_LOGGER = logging.getLogger(__name__)


class JablotronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Jablotron Web."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._discovered_sensors = {}
        self._user_input = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            if self.context.get("entry_id"):
                # This is a reauth flow
                reauth_entry = self.hass.config_entries.async_get_entry(
                    self.context["entry_id"]
                )
                try:
                    await self._test_credentials(user_input)
                    new_data = reauth_entry.data.copy()
                    new_data.update(user_input)
                    self.hass.config_entries.async_update_entry(
                        reauth_entry, data=new_data
                    )
                    # The update listener on the entry performs the reload
                    return self.async_abort(reason="reauth_successful")
                except JablotronAuthError:
                    errors["base"] = "invalid_auth"
                except Exception:
                    _LOGGER.exception("Unexpected exception during reauth")
                    errors["base"] = "cannot_connect"
            else:
                # This is a new config flow
                try:
                    status = await self._test_credentials(user_input)

                    await self.async_set_unique_id(user_input[CONF_USERNAME])
                    self._abort_if_unique_id_configured()

                    # Get initial data to discover sensors
                    try:
                        data = await self._discover_sensors(user_input, status=status)
                        if data and "teplomery" in data:
                            self._discovered_sensors = {
                                sensor_id: f"Teploměr {sensor_id}"
                                for sensor_id in data["teplomery"].keys()
                            }
                    except Exception as e:
                        # Temperature names are cosmetic - create the entry anyway,
                        # sensors get generic names and can be renamed in HA
                        _LOGGER.error("Sensor discovery failed: %s", e)
                        self._discovered_sensors = {}

                    self._user_input = user_input

                    # If sensors were discovered, go to a naming step
                    if self._discovered_sensors:
                        return await self.async_step_sensors()

                    # Otherwise, create entry without custom names
                    return self.async_create_entry(
                        title=f"Jablotron ({user_input[CONF_USERNAME]})",
                        data=user_input,
                    )
                except JablotronAuthError:
                    errors["base"] = "invalid_auth"
                except Exception:
                    _LOGGER.exception("Unexpected exception during login")
                    errors["base"] = "cannot_connect"

        # Determine default values for the form
        default_username = ""
        default_service_id = ""
        default_pgm_code = ""
        if self.context.get("entry_id"):
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            default_username = entry.data.get(CONF_USERNAME, "")
            default_service_id = entry.data.get(CONF_SERVICE_ID, "")
            default_pgm_code = entry.data.get(CONF_PGM_CODE, "")
        elif user_input:
            default_username = user_input.get(CONF_USERNAME, "")
            default_service_id = user_input.get(CONF_SERVICE_ID, "")
            default_pgm_code = user_input.get(CONF_PGM_CODE, "")

        schema_fields = {
            vol.Required(CONF_USERNAME, default=default_username): str,
            vol.Required(CONF_PASSWORD): str,
        }
        if not self.context.get("entry_id"):
            schema_fields[vol.Optional(CONF_SERVICE_ID, default=default_service_id)] = str
            schema_fields[vol.Optional(CONF_PGM_CODE, default=default_pgm_code)] = str

        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def _test_credentials(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Test credentials against Jablotron API. Returns status dict."""
        client = JablotronClient(
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            user_input.get(CONF_SERVICE_ID, ""),
            self.hass,
        )
        try:
            await client.login()
            return await client.get_status()
        finally:
            await client.async_close()

    async def _discover_sensors(
        self, user_input: dict[str, Any], *, status: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Discover sensors using Jablotron API."""
        if status is not None:
            return status
        client = JablotronClient(
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            user_input.get(CONF_SERVICE_ID, ""),
            self.hass,
        )
        try:
            await client.login()
            return await client.get_status()
        finally:
            await client.async_close()

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle sensor naming step."""
        if user_input is not None:
            # Combine credentials with sensor names
            data = {**self._user_input}
            data[CONF_SENSOR_NAMES] = {
                sensor_id: user_input.get(f"sensor_{sensor_id}", default_name)
                for sensor_id, default_name in self._discovered_sensors.items()
            }

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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Perform re-authentication with Jablotron.

        HA passes the entry's data as ``entry_data``; the entry itself is
        identified via self.context["entry_id"] (set up by the auth flow).
        """
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> JablotronOptionsFlowHandler:
        """Get the option flow for this handler."""
        return JablotronOptionsFlowHandler()


class JablotronOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Jablotron Web.

    The config entry is provided by the base class (`OptionsFlow.config_entry`)
    since HA 2024.11; it must not be stored manually.
    """

    def _options_schema(self) -> vol.Schema:
        """Build the options form schema."""
        return vol.Schema(
            {
                vol.Optional(
                    CONF_USERNAME,
                    default=self.config_entry.data.get(CONF_USERNAME, ""),
                ): str,
                vol.Optional(
                    CONF_PASSWORD,
                    default="",
                ): str,
                vol.Optional(
                    CONF_SERVICE_ID,
                    default=self.config_entry.data.get(CONF_SERVICE_ID, ""),
                ): str,
                vol.Optional(
                    CONF_PGM_CODE,
                    default=self.config_entry.data.get(CONF_PGM_CODE, ""),
                ): str,
                vol.Optional(
                    "scan_interval",
                    default=self.config_entry.options.get(
                        "scan_interval", DEFAULT_SCAN_INTERVAL
                    ),
                ): cv.positive_int,
                vol.Optional(
                    CONF_TIMEOUT,
                    default=self.config_entry.options.get(
                        CONF_TIMEOUT, DEFAULT_TIMEOUT
                    ),
                ): cv.positive_int,
                vol.Optional(
                    CONF_RETRY_DELAY,
                    default=self.config_entry.options.get(
                        CONF_RETRY_DELAY, DEFAULT_RETRY_DELAY
                    ),
                ): cv.positive_int,
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            errors = {}
            password_to_use = user_input.get(CONF_PASSWORD, "").strip()

            # Build new data dict with updated credentials
            new_data = self.config_entry.data.copy()
            credentials_changed = False

            if user_input.get(CONF_USERNAME) and user_input[CONF_USERNAME] != self.config_entry.data.get(CONF_USERNAME):
                new_data[CONF_USERNAME] = user_input[CONF_USERNAME]
                credentials_changed = True

            if password_to_use:
                new_data[CONF_PASSWORD] = password_to_use
                credentials_changed = True
            elif user_input.get(CONF_PASSWORD, "") != self.config_entry.data.get(CONF_PASSWORD, ""):
                _LOGGER.debug(
                    "Password field submitted empty while existing password differs; "
                    "keeping existing password"
                )

            if CONF_SERVICE_ID in user_input and user_input[CONF_SERVICE_ID] != self.config_entry.data.get(CONF_SERVICE_ID):
                new_data[CONF_SERVICE_ID] = user_input[CONF_SERVICE_ID]
                credentials_changed = True

            if CONF_PGM_CODE in user_input and user_input[CONF_PGM_CODE] != self.config_entry.data.get(CONF_PGM_CODE):
                new_data[CONF_PGM_CODE] = user_input[CONF_PGM_CODE]
                credentials_changed = True

            # Validate new credentials before applying
            if credentials_changed:
                client = JablotronClient(
                    new_data[CONF_USERNAME],
                    new_data[CONF_PASSWORD],
                    new_data.get(CONF_SERVICE_ID, ""),
                    self.hass,
                )
                try:
                    await client.get_status()
                except JablotronAuthError:
                    _LOGGER.error("New credentials invalid")
                    errors["base"] = "invalid_auth_new"
                except Exception:
                    _LOGGER.exception("Unexpected error validating new credentials")
                    errors["base"] = "cannot_connect"
                finally:
                    await client.async_close()

            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._options_schema(),
                    errors=errors,
                )

            # Update config entry data if credentials changed; the entry's
            # update listener performs the reload, so no explicit reload here
            if credentials_changed:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )

            # Save options (scan_interval, timeout, and retry_delay)
            # If only options changed, the update listener will handle the reload
            return self.async_create_entry(
                title="",
                data={
                    "scan_interval": user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                    "timeout": user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                    "retry_delay": user_input.get(CONF_RETRY_DELAY, DEFAULT_RETRY_DELAY),
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self._options_schema(),
        )
