from __future__ import annotations

from math import pi

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NavigationSiteConfig(BaseModel):
    """Explicit user/test site used for navigation-geometry evidence.

    Values are scenario inputs, not operational defaults. Earth shape is supplied
    by the scenario force-model contract rather than repeated here.
    """

    model_config = ConfigDict(frozen=True)

    site_id: str = Field(min_length=1)
    latitude_rad: float = Field(ge=-pi / 2.0, le=pi / 2.0)
    longitude_rad: float = Field(ge=-pi, le=pi)
    height_m: float
    elevation_mask_rad: float = Field(ge=-pi / 2.0, lt=pi / 2.0)


class DopMetrics(BaseModel):
    """DOP result with explicit unavailable semantics."""

    model_config = ConfigDict(frozen=True)

    available: bool
    visible_satellite_ids: tuple[str, ...] = ()
    gdop: float | None = None
    pdop: float | None = None
    hdop: float | None = None
    vdop: float | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> DopMetrics:
        values = (self.gdop, self.pdop, self.hdop, self.vdop)
        if self.available:
            if len(self.visible_satellite_ids) < 4:
                raise ValueError("available DOP requires at least four visible satellites")
            if any(value is None or value <= 0.0 for value in values):
                raise ValueError("available DOP requires positive finite GDOP/PDOP/HDOP/VDOP")
            if self.reason is not None:
                raise ValueError("available DOP must not carry an unavailable reason")
        else:
            if any(value is not None for value in values):
                raise ValueError("unavailable DOP must not fabricate numeric values")
            if not self.reason:
                raise ValueError("unavailable DOP requires an explicit reason")
        return self
