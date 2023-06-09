"""Support for Enphase Envoy sensors."""
from __future__ import annotations

import datetime
import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import localtime, strftime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import BATTERY_ENERGY_CHARGED_SENSOR  # BATTERY_SENSORS,
from .const import (
    BATTERY_ENERGY_DISCHARGED_SENSOR,
    COORDINATOR,
    DOMAIN,
    INVERTERS_KEY,
    NAME,
    SENSORS,
)
from .entity import BatteryEntity, EnvoyEntity, InverterEntity

_LOGGER = logging.getLogger(__name__)


@dataclass
class InverterRequiredKeysMixin:
    """Mixin for required keys."""

    value_fn: Callable[[tuple[float, str]], datetime.datetime | float | None]


@dataclass
class InverterSensorEntityDescription(
    SensorEntityDescription, InverterRequiredKeysMixin
):
    """Describes an Envoy inverter sensor entity."""


def _inverter_last_report_time(
    watt_report_time: tuple[float, str]
) -> datetime.datetime | None:
    if (report_time := watt_report_time[1]) is None:
        return None
    if (last_reported_dt := dt_util.parse_datetime(report_time)) is None:
        return None
    if last_reported_dt.tzinfo is None:
        return last_reported_dt.replace(tzinfo=dt_util.UTC)
    return last_reported_dt


INVERTER_SENSORS = (
    InverterSensorEntityDescription(
        key=INVERTERS_KEY,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
        value_fn=lambda watt_report_time: watt_report_time[0],
    ),
    InverterSensorEntityDescription(
        key="last_reported",
        name="Last Reported",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_inverter_last_report_time,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up envoy sensor platform."""
    data: dict = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: DataUpdateCoordinator = data[COORDINATOR]
    envoy_data: dict = coordinator.data
    envoy_name: str = data[NAME]
    envoy_serial_num = config_entry.unique_id
    assert envoy_serial_num is not None
    _LOGGER.debug("Envoy data: %s", envoy_data)

    entities = []
    for sensor_description in SENSORS:
        if sensor_description.key == "batteries":
            if envoy_data.get("batteries") is not None:
                for battery in envoy_data["batteries"]:
                    entity_name = f"{envoy_name} {sensor_description.name} {battery}"
                    serial_number = battery
                    entities.append(
                        EnvoyBatteryEntity(
                            sensor_description,
                            entity_name,
                            envoy_name,
                            config_entry.unique_id,
                            serial_number,
                            coordinator,
                        )
                    )

        elif sensor_description.key == "current_battery_capacity":
            if envoy_data.get("batteries") is not None:
                battery_capacity_entity = TotalBatteryCapacityEntity(
                    sensor_description,
                    f"{envoy_name} {sensor_description.name}",
                    envoy_name,
                    config_entry.unique_id,
                    None,
                    coordinator,
                )
                entities.append(battery_capacity_entity)

                entities.append(
                    BatteryEnergyChangeEntity(
                        BATTERY_ENERGY_CHARGED_SENSOR,
                        f"{envoy_name} {BATTERY_ENERGY_CHARGED_SENSOR.name}",
                        envoy_name,
                        config_entry.unique_id,
                        None,
                        coordinator,
                        battery_capacity_entity,
                        True,
                    )
                )

                entities.append(
                    BatteryEnergyChangeEntity(
                        BATTERY_ENERGY_DISCHARGED_SENSOR,
                        f"{envoy_name} {BATTERY_ENERGY_DISCHARGED_SENSOR.name}",
                        envoy_name,
                        config_entry.unique_id,
                        None,
                        coordinator,
                        battery_capacity_entity,
                        False,
                    )
                )

        elif sensor_description.key == "total_battery_percentage":
            if envoy_data.get("batteries") is not None:
                entities.append(
                    TotalBatteryPercentageEntity(
                        sensor_description,
                        f"{envoy_name} {sensor_description.name}",
                        envoy_name,
                        config_entry.unique_id,
                        None,
                        coordinator,
                    )
                )

        else:
            data = envoy_data.get(sensor_description.key)
            if isinstance(data, str) and "not available" in data:
                continue

            entities.append(
                EnvoySensorEntity(
                    coordinator, sensor_description, envoy_name, envoy_serial_num
                )
            )

    if production := envoy_data.get("inverters_production"):
        entities.extend(
            InverterSensorEntity(coordinator, description, inverter, envoy_serial_num)
            for description in INVERTER_SENSORS
            for inverter in production
        )

    async_add_entities(entities)


class EnvoySensorEntity(EnvoyEntity, SensorEntity):
    """Envoy sensor entity."""

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get(self.entity_description.key)


class InverterSensorEntity(InverterEntity, SensorEntity):
    """Inverter sensor entity."""

    entity_description: InverterSensorEntityDescription

    @property
    def native_value(self) -> datetime.datetime | float | None:
        """Return the state of the sensor."""
        watt_report_time: tuple[float, str] = self.coordinator.data[
            "inverters_production"
        ][self.serial_number]
        return self.entity_description.value_fn(watt_report_time)


class BatterySensorEntity(BatteryEntity, SensorEntity):
    """Battery sensor entity."""

    def __init__(
        self,
        description,
        name,
        device_name,
        device_serial_number,
        serial_number,
        coordinator,
    ):
        """Initialize."""
        super().__init__(coordinator, description, serial_number, device_serial_number)
        self.name = name
        self.device_name = device_name
        self.device_serial_number = device_serial_number
        self.serial_number = serial_number


class EnvoyBatteryEntity(BatterySensorEntity):
    """Envoy battery entity."""

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data.get("batteries") is not None:
            return self.coordinator.data["batteries"][self.serial_number]["percentFull"]

        return None

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if self.coordinator.data.get("batteries") is not None:
            battery = self.coordinator.data["batteries"][self.serial_number]
            last_reported = strftime(
                "%Y-%m-%d %H:%M:%S", localtime(battery["last_rpt_date"])
            )
            return {
                "last_reported": last_reported,
                "capacity": battery["encharge_capacity"],
            }

        return None


class TotalBatteryCapacityEntity(BatterySensorEntity):
    """Total battery capacity entity."""

    @property
    def native_value(self):
        """Return the state of the sensor."""
        batteries = self.coordinator.data.get("batteries")
        if batteries is not None:
            total = 0
            for battery in batteries:
                percentage = batteries.get(battery).get("percentFull")
                capacity = batteries.get(battery).get("encharge_capacity")
                total += round(capacity * (percentage / 100.0))

            return total

        return None


class TotalBatteryPercentageEntity(BatterySensorEntity):
    """Total battery percentage entity."""

    @property
    def native_value(self):
        """Return the state of the sensor."""
        batteries = self.coordinator.data.get("batteries")
        if batteries is not None:
            battery_sum = 0
            for battery in batteries:
                battery_sum += batteries.get(battery).get("percentFull", 0)

            return round(battery_sum / len(batteries), 2)

        return None


class BatteryEnergyChangeEntity(BatterySensorEntity):
    """Battery energy change entity."""

    def __init__(
        self,
        description,
        name,
        device_name,
        device_serial_number,
        serial_number,
        coordinator,
        total_battery_capacity_entity,
        positive: bool,
    ):
        super().__init__(
            description,
            name,
            device_name,
            device_serial_number,
            serial_number,
            coordinator,
        )

        self._sensor_source = total_battery_capacity_entity
        self._positive = positive
        self._state = 0
        self._attr_last_reset = datetime.datetime.now()

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        @callback
        def calc_change(event):
            """Handle the sensor state changes."""
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")

            if (
                old_state is None
                or old_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
                or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            ):
                self._state = 0

            else:
                old_state_value = int(old_state.state)
                new_state_value = int(new_state.state)

                if self._positive:
                    if new_state_value > old_state_value:
                        self._state = new_state_value - old_state_value
                    else:
                        self._state = 0

                else:
                    if old_state_value > new_state_value:
                        self._state = old_state_value - new_state_value
                    else:
                        self._state = 0

            self._attr_last_reset = datetime.datetime.now()
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._sensor_source.entity_id, calc_change
            )
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state
