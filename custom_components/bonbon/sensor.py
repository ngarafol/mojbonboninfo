"""Sensors: one device per phone number, four entities plus package quotas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_BONBON,
    ATTR_BONBON_ENTRY_ID,
    ATTR_BONBON_NUMBER,
    CONF_EXCLUDED_NUMBERS,
    DOMAIN,
    MANUFACTURER,
    PORTAL_URL,
)
from .coordinator import BonbonCoordinator
from .models import Package, PhoneNumber

type BonbonConfigEntry = ConfigEntry[BonbonCoordinator]

_USAGE_KINDS: tuple[str, ...] = ("data", "minutes", "sms")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BonbonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the entities for every visible number."""
    coordinator = entry.runtime_data
    excluded = set(entry.options.get(CONF_EXCLUDED_NUMBERS, []))
    entities: list[SensorEntity] = []
    for number in coordinator.data.numbers:
        if number.msisdn in excluded:
            continue
        entities.extend(
            (
                BonbonNumberSensor(coordinator, entry, number),
                BonbonBalanceSensor(coordinator, entry, number),
                BonbonValiditySensor(coordinator, entry, number),
                BonbonPackagesSensor(coordinator, entry, number),
            )
        )
        for key in _USAGE_KINDS:
            if _aggregate(number.packages, key)[0] is not None:
                entities.append(BonbonUsageSensor(coordinator, entry, number, key))
    async_add_entities(entities)


class BonbonEntity(CoordinatorEntity[BonbonCoordinator], SensorEntity):
    """Common device wiring for all entities of one number."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: BonbonCoordinator,
        entry: ConfigEntry,
        number: PhoneNumber,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self._slug = number.slug
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{number.slug}")},
            name=number.label or f"bonbon {number.msisdn}",
            manufacturer=MANUFACTURER,
            model="bonbon broj",
            serial_number=number.msisdn,
            configuration_url=PORTAL_URL,
        )

    @property
    def number(self) -> PhoneNumber:
        """Return the current state of this entity's number."""
        for number in self.coordinator.data.numbers:
            if number.slug == self._slug:
                return number
        raise KeyError(self._slug)

    @property
    def available(self) -> bool:
        """Return False when the number vanished from the account."""
        return super().available and any(
            number.slug == self._slug for number in self.coordinator.data.numbers
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the number for card grouping and automations."""
        return {
            ATTR_BONBON_NUMBER: self.number.msisdn,
            ATTR_BONBON_ENTRY_ID: self._entry_id,
        }


class BonbonNumberSensor(BonbonEntity):
    """The phone number itself, with the whole card payload attached."""

    _attr_translation_key = "number"
    _attr_icon = "mdi:sim"

    def __init__(self, coordinator, entry, number) -> None:
        super().__init__(coordinator, entry, number)
        self._attr_unique_id = f"{entry.entry_id}_{number.slug}_number"

    @property
    def native_value(self) -> str:
        """Return the msisdn."""
        return self.number.msisdn

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Everything the Lovelace card needs, in one place."""
        return {
            **super().extra_state_attributes,
            ATTR_BONBON: self.number.as_dict(),
        }


class BonbonBalanceSensor(BonbonEntity):
    """Account balance."""

    _attr_translation_key = "balance"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator, entry, number) -> None:
        super().__init__(coordinator, entry, number)
        self._attr_unique_id = f"{entry.entry_id}_{number.slug}_balance"

    @property
    def native_value(self) -> Decimal | None:
        """Return the balance."""
        balance = self.number.balance
        return Decimal(str(balance)) if balance is not None else None

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the account currency."""
        return self.number.currency

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose spending and the portal's own explanation when data is missing."""
        return {
            **super().extra_state_attributes,
            "spending": self.number.spending,
            "portal_message": self.number.portal_message,
        }


class BonbonValiditySensor(BonbonEntity):
    """Date the balance/package stays valid."""

    _attr_translation_key = "validity"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator, entry, number) -> None:
        super().__init__(coordinator, entry, number)
        self._attr_unique_id = f"{entry.entry_id}_{number.slug}_validity"

    @property
    def native_value(self) -> date | None:
        """Return the validity date."""
        return self.number.valid_until

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Add the day countdown used by the card."""
        valid_until = self.number.valid_until
        return {
            **super().extra_state_attributes,
            "days_left": (valid_until - date.today()).days if valid_until else None,
        }


class BonbonPackagesSensor(BonbonEntity):
    """Number of active packages, full list as attribute."""

    _attr_translation_key = "packages"
    _attr_icon = "mdi:package-variant-closed"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, number) -> None:
        super().__init__(coordinator, entry, number)
        self._attr_unique_id = f"{entry.entry_id}_{number.slug}_packages"

    @property
    def native_value(self) -> int:
        """Return the active package count."""
        return len(self.number.packages)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the packages with quotas and expiry."""
        return {
            **super().extra_state_attributes,
            "packages": [package.as_dict() for package in self.number.packages],
        }


class BonbonUsageSensor(BonbonEntity):
    """Remaining data, minutes or SMS, summed over matching packages."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, number, kind: str) -> None:
        self._kind = kind
        super().__init__(coordinator, entry, number)
        self._attr_translation_key = kind
        self._attr_unique_id = f"{entry.entry_id}_{number.slug}_{kind}"
        if kind == "data":
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
            self._attr_native_unit_of_measurement = UnitOfInformation.GIGABYTES
        elif kind == "minutes":
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.MINUTES
        else:
            self._attr_native_unit_of_measurement = "SMS"

    @property
    def native_value(self) -> float | None:
        """Return what is left."""
        return _aggregate(self.number.packages, self._kind)[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return used/total and the source packages."""
        _remaining, total, packages = _aggregate(self.number.packages, self._kind)
        used = None
        if total is not None and self.native_value is not None:
            used = round(total - self.native_value, 3)
        return {
            **super().extra_state_attributes,
            "used": used,
            "total": total,
            "packages": [package.name for package in packages],
        }


def _aggregate(
    packages: list[Package], kind: str
) -> tuple[float | None, float | None, list[Package]]:
    """Sum remaining/total for one unit family, normalising MB to GB."""
    remaining: float | None = None
    total: float | None = None
    contributing: list[Package] = []
    for package in packages:
        unit = (package.unit or "").upper()
        factor: float | None
        if kind == "data" and unit == "GB":
            factor = 1.0
        elif kind == "data" and unit == "MB":
            factor = 1 / 1024
        elif kind == "minutes" and unit in ("MIN", "MINUTE", "MINUTES"):
            factor = 1.0
        elif kind == "sms" and unit == "SMS":
            factor = 1.0
        else:
            continue
        contributing.append(package)
        if package.remaining is not None:
            remaining = (remaining or 0.0) + package.remaining * factor
        if package.total is not None:
            total = (total or 0.0) + package.total * factor
    if contributing:
        remaining = round(remaining, 3) if remaining is not None else None
        total = round(total, 3) if total is not None else None
    return remaining, total, contributing
