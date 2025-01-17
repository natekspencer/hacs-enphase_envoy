"""Diagnostics support for Enphase Envoy."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_UNIQUE_ID, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import COORDINATOR, DOMAIN

CONF_TITLE = "title"

TO_REDACT = {
    CONF_NAME,
    CONF_PASSWORD,
    # Config entry title and unique ID may contain sensitive data
    CONF_TITLE,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "data": coordinator.data,
        },
        TO_REDACT,
    )
