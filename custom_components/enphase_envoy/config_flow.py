"""Config flow for Enphase Envoy integration."""
from __future__ import annotations

import contextlib
import logging
from typing import Any, Mapping

import httpx
import voluptuous as vol
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import AbortFlow, FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
)
from packaging.version import Version

from .const import CONF_SERIAL, CONF_USE_ENLIGHTEN, DOMAIN
from .envoy_reader import EnvoyReader

_LOGGER = logging.getLogger(__name__)


async def _options_suggested_values(handler: SchemaCommonFlowHandler) -> dict[str, Any]:
    parent_handler: SchemaOptionsFlowHandler = handler.parent_handler
    return parent_handler.config_entry.data | parent_handler.options


ENVOY = "Envoy"
AUTH_LOGIN = "Username/Password"
AUTH_TOKEN = "Token"
CONF_LOGIN_METHOD = "login_method"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_HOST, default="envoy.local"): str}
)
STEP_ENLIGHTEN_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_LOGIN_METHOD): vol.In((AUTH_LOGIN, AUTH_TOKEN))}
)
STEP_LOGIN_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)
STEP_TOKEN_DATA_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): str})

OPTIONS_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})
OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        OPTIONS_SCHEMA, suggested_values=_options_suggested_values
    )
}


async def create_envoy_reader(hass: HomeAssistant, data: dict[str, Any]) -> EnvoyReader:
    """Create envoy reader from dict."""
    envoy_reader = EnvoyReader(
        data[CONF_HOST],
        username=data.get(CONF_USERNAME),
        password=data.get(CONF_PASSWORD),
        inverters=False,
        async_client=get_async_client(hass, verify_ssl=False),
        use_enlighten=data.get(CONF_USE_ENLIGHTEN, False),
        https_flag="s" if data.get(CONF_USE_ENLIGHTEN, False) else "",
        token=data.get(CONF_TOKEN),
    )
    await envoy_reader.read_info_xml()
    return envoy_reader


async def validate_envoy(envoy_reader: EnvoyReader) -> None:
    """Validate the envoy allows us to connect."""
    try:
        await envoy_reader.getData()
    except httpx.HTTPStatusError as err:
        raise InvalidAuth from err
    except (RuntimeError, httpx.HTTPError) as err:
        raise CannotConnect from err


class EnphaseEnvoyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Enphase Envoy."""

    VERSION = 1

    envoy_reader: EnvoyReader | None
    ip_address: str | None = None
    serial: str | None = None
    username: str | None = None
    _reauth_entry = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> SchemaOptionsFlowHandler:
        """Get the options flow for this handler."""

        def async_options_flow_finished(
            hass: HomeAssistant, user_input: Mapping[str, Any]
        ):
            hass.config_entries.async_update_entry(
                config_entry,
                data=config_entry.data | user_input,
            )

        return SchemaOptionsFlowHandler(
            config_entry, OPTIONS_FLOW, async_options_flow_finished
        )

    @callback
    def _async_generate_schema(self):
        """Generate schema."""
        schema = {}

        if self.ip_address:
            schema[vol.Required(CONF_HOST, default=self.ip_address)] = vol.In(
                [self.ip_address]
            )
        else:
            schema[vol.Required(CONF_HOST)] = str

        schema[vol.Optional(CONF_USERNAME, default=self.username or "envoy")] = str
        schema[vol.Optional(CONF_PASSWORD, default="")] = str
        schema[vol.Optional(CONF_USE_ENLIGHTEN)] = bool
        return vol.Schema(schema)

    @callback
    def _async_current_hosts(self):
        """Return a set of hosts."""
        return {
            entry.data[CONF_HOST]
            for entry in self._async_current_entries(include_ignore=False)
            if CONF_HOST in entry.data
        }

    async def async_step_zeroconf(
        self, discovery_info: zeroconf.ZeroconfServiceInfo
    ) -> FlowResult:
        """Handle a flow initialized by zeroconf discovery."""
        serial = discovery_info.properties["serialnum"]
        await self.async_set_unique_id(serial)
        self.ip_address = discovery_info.host
        self._abort_if_unique_id_configured({CONF_HOST: self.ip_address})
        for entry in self._async_current_entries(include_ignore=False):
            if (
                entry.unique_id is None
                and CONF_HOST in entry.data
                and entry.data[CONF_HOST] == self.ip_address
            ):
                title = f"{ENVOY} {serial}" if entry.title == ENVOY else ENVOY
                self.hass.config_entries.async_update_entry(
                    entry, title=title, unique_id=serial
                )
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(entry.entry_id)
                )
                return self.async_abort(reason="already_configured")

        return await self.async_step_user()

    async def async_step_reauth(self, user_input: dict[str, Any] | None) -> FlowResult:
        """Handle configuration by re-auth."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_user()

    def _async_envoy_name(self) -> str:
        """Return the name of the envoy."""
        if self.unique_id:
            return f"{ENVOY} {self.unique_id}"
        return ENVOY

    async def _async_set_unique_id_from_envoy(self) -> bool:
        """Set the unique id by fetching it from the envoy."""
        serial = None
        with contextlib.suppress(httpx.HTTPError):
            serial = await self.envoy_reader.get_full_serial_number()
        if serial:
            await self.async_set_unique_id(serial)
            return True
        return False

    async def _async_create_entry(
        self, step_id: str, data_schema: vol.Schema
    ) -> FlowResult:
        """Finish config flow and create a config entry."""
        errors = {}

        try:
            await validate_envoy(self.envoy_reader)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.exception(ex)
            errors["base"] = "unknown"

        if errors:
            return self.async_show_form(
                step_id=step_id, data_schema=data_schema, errors=errors
            )

        data = {CONF_HOST: self.envoy_reader.host}
        data[CONF_NAME] = self._async_envoy_name()
        data[CONF_TOKEN] = self.envoy_reader.get_token()

        if self._reauth_entry:
            self.hass.config_entries.async_update_entry(
                self._reauth_entry,
                data=data,
            )
            return self.async_abort(reason="reauth_successful")

        if not self.unique_id and await self._async_set_unique_id_from_envoy():
            data[CONF_NAME] = self._async_envoy_name()

        if self.unique_id:
            self._abort_if_unique_id_configured({CONF_HOST: data[CONF_HOST]})

        return self.async_create_entry(title=data[CONF_NAME], data=data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            if (
                not self._reauth_entry
                and user_input[CONF_HOST] in self._async_current_hosts()
            ):
                return self.async_abort(reason="already_configured")
            try:
                self.envoy_reader = await create_envoy_reader(self.hass, user_input)
                await self.async_set_unique_id(self.envoy_reader.serial_number)
                self._abort_if_unique_id_configured({CONF_HOST: user_input[CONF_HOST]})
                if Version(self.envoy_reader.software[1:]).major >= 7:
                    return await self.async_step_enlighten()
                await validate_envoy(self.envoy_reader)
            except AbortFlow:
                raise
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                data = user_input.copy()
                data[CONF_NAME] = self._async_envoy_name()
                data[CONF_TOKEN] = self.envoy_reader.get_token()

                if self._reauth_entry:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry,
                        data=data,
                    )
                    return self.async_abort(reason="reauth_successful")

                if not self.unique_id and await self._async_set_unique_id_from_envoy():
                    data[CONF_NAME] = self._async_envoy_name()

                if self.unique_id:
                    self._abort_if_unique_id_configured({CONF_HOST: data[CONF_HOST]})

                return self.async_create_entry(title=data[CONF_NAME], data=data)

        if self.unique_id:
            self.context["title_placeholders"] = {
                CONF_SERIAL: self.unique_id,
                CONF_HOST: self.ip_address,
            }
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_enlighten(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the enlighten step."""
        errors = {}

        if user_input is not None:
            self.envoy_reader.https_flag = "s"
            self.envoy_reader.use_enlighten = True
            if user_input[CONF_LOGIN_METHOD] == AUTH_TOKEN:
                return await self.async_step_token()
            return await self.async_step_login()

        return self.async_show_form(
            step_id="enlighten", data_schema=STEP_ENLIGHTEN_DATA_SCHEMA, errors=errors
        )

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the enlighten step."""
        errors = {}

        if user_input is not None:
            self.envoy_reader.username = user_input[CONF_USERNAME]
            self.envoy_reader.password = user_input[CONF_PASSWORD]
            return await self._async_create_entry(
                step_id="login", data_schema=STEP_LOGIN_DATA_SCHEMA
            )

        return self.async_show_form(
            step_id="login", data_schema=STEP_LOGIN_DATA_SCHEMA, errors=errors
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the enlighten step."""
        errors = {}

        if user_input is not None:
            self.envoy_reader.set_token(user_input[CONF_TOKEN])
            return await self._async_create_entry(
                step_id="token", data_schema=STEP_TOKEN_DATA_SCHEMA
            )

        return self.async_show_form(
            step_id="token", data_schema=STEP_TOKEN_DATA_SCHEMA, errors=errors
        )

    # async def async_step_user(
    #     self, user_input: dict[str, Any] | None = None
    # ) -> FlowResult:
    #     """Handle the initial step."""
    #     errors = {}

    #     if user_input is not None:
    #         if (
    #             not self._reauth_entry
    #             and user_input[CONF_HOST] in self._async_current_hosts()
    #         ):
    #             return self.async_abort(reason="already_configured")
    #         try:
    #             envoy_reader = await create_envoy_reader(self.hass, user_input)
    #             await validate_envoy(envoy_reader)
    #         except CannotConnect:
    #             errors["base"] = "cannot_connect"
    #         except InvalidAuth:
    #             errors["base"] = "invalid_auth"
    #         except Exception:  # pylint: disable=broad-except
    #             _LOGGER.exception("Unexpected exception")
    #             errors["base"] = "unknown"
    #         else:
    #             data = user_input.copy()
    #             data[CONF_NAME] = self._async_envoy_name()
    #             data[CONF_TOKEN] = envoy_reader._token

    #             if self._reauth_entry:
    #                 self.hass.config_entries.async_update_entry(
    #                     self._reauth_entry,
    #                     data=data,
    #                 )
    #                 return self.async_abort(reason="reauth_successful")

    #             if not self.unique_id and await self._async_set_unique_id_from_envoy(
    #                 envoy_reader
    #             ):
    #                 data[CONF_NAME] = self._async_envoy_name()

    #             if self.unique_id:
    #                 self._abort_if_unique_id_configured({CONF_HOST: data[CONF_HOST]})

    #             return self.async_create_entry(title=data[CONF_NAME], data=data)

    #     if self.unique_id:
    #         self.context["title_placeholders"] = {
    #             CONF_SERIAL: self.unique_id,
    #             CONF_HOST: self.ip_address,
    #         }
    #     return self.async_show_form(
    #         step_id="user",
    #         data_schema=self._async_generate_schema(),
    #         errors=errors,
    #     )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
