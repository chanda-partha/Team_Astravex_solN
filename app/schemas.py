from __future__ import annotations

import math
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

DIRECTIVE_TYPES = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]

HourInt = Annotated[int, Field(ge=0, le=23)]


class BatterySpec(BaseModel):
    capacity_kwh: float = Field(gt=0)
    initial_energy_kwh: float = Field(ge=0)
    minimum_energy_kwh: float = Field(ge=0)
    max_charge_kwh_per_hour: float = Field(ge=0)
    max_discharge_kwh_per_hour: float = Field(ge=0)

    @model_validator(mode="after")
    def check_finite_and_bounds(self) -> "BatterySpec":
        for field_name in (
            "capacity_kwh",
            "initial_energy_kwh",
            "minimum_energy_kwh",
            "max_charge_kwh_per_hour",
            "max_discharge_kwh_per_hour",
        ):
            val = getattr(self, field_name)
            if not math.isfinite(val):
                raise ValueError(f"{field_name} must be a finite number")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        if (
            self.initial_energy_kwh < self.minimum_energy_kwh
            or self.initial_energy_kwh > self.capacity_kwh
        ):
            raise ValueError(
                "initial_energy_kwh must be between minimum_energy_kwh and capacity_kwh"
            )
        return self


class HourInput(BaseModel):
    hour: HourInt
    demand_kwh: float = Field(ge=0)
    solar_kwh: float = Field(ge=0)
    tariff_bdt_per_kwh: float = Field(ge=0)

    @model_validator(mode="after")
    def check_finite(self) -> "HourInput":
        for field_name in ("demand_kwh", "solar_kwh", "tariff_bdt_per_kwh"):
            val = getattr(self, field_name)
            if not math.isfinite(val):
                raise ValueError(f"{field_name} must be a finite number")
        return self


class OptimizeRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourInput] = Field(min_length=24, max_length=24)
    battery: BatterySpec

    @model_validator(mode="after")
    def validate_request(self) -> "OptimizeRequest":
        if not self.scenario_id.strip():
            raise ValueError("scenario_id cannot be blank")
        for i, note in enumerate(self.operator_notes):
            if not isinstance(note, str) or not note.strip():
                raise ValueError(f"operator_notes[{i}] must be a non-empty string")
        hour_values = [h.hour for h in self.hours]
        if hour_values != list(range(24)):
            raise ValueError("hours must contain exactly one entry for each hour 0..23 in order")
        return self


class SolarReduction(BaseModel):
    hours: list[HourInt] = Field(min_length=1)
    factor: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_finite(self) -> "SolarReduction":
        if not math.isfinite(self.factor):
            raise ValueError("factor must be finite")
        return self


class MinimumBatteryReserve(BaseModel):
    hours: list[HourInt] = Field(min_length=1)
    minimum_energy_kwh: float = Field(ge=0)

    @model_validator(mode="after")
    def check_finite(self) -> "MinimumBatteryReserve":
        if not math.isfinite(self.minimum_energy_kwh):
            raise ValueError("minimum_energy_kwh must be finite")
        return self


class HoursOnly(BaseModel):
    hours: list[HourInt] = Field(min_length=1)


class MaxGridWindow(BaseModel):
    hours: list[HourInt] = Field(min_length=1)
    max_grid_kwh: float = Field(ge=0)

    @model_validator(mode="after")
    def check_finite(self) -> "MaxGridWindow":
        if not math.isfinite(self.max_grid_kwh):
            raise ValueError("max_grid_kwh must be finite")
        return self


class DirectiveInterpretation(BaseModel):
    note_index: int = Field(ge=0)
    applies: bool
    directive_type: DIRECTIVE_TYPES
    structured_adjustment: Optional[
        Union[SolarReduction, MinimumBatteryReserve, HoursOnly, MaxGridWindow]
    ] = None
    explanation: str = ""

    @model_validator(mode="after")
    def check_semantics(self) -> "DirectiveInterpretation":
        if self.directive_type == "no_op":
            if self.applies:
                raise ValueError("no_op must have applies=false")
            if self.structured_adjustment is not None:
                raise ValueError("no_op must have structured_adjustment=null")
        else:
            if not self.applies:
                raise ValueError(f"{self.directive_type} must have applies=true")
            if self.structured_adjustment is None:
                raise ValueError(f"{self.directive_type} requires structured_adjustment")
        return self


class HourlyPlanEntry(BaseModel):
    hour: HourInt
    grid_kwh: float = Field(ge=0)
    solar_used_kwh: float = Field(ge=0)
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float = Field(ge=0)
    battery_energy_after_kwh: float = Field(ge=0)

    @model_validator(mode="after")
    def check_idle_kwh(self) -> "HourlyPlanEntry":
        if self.battery_action == "idle" and self.battery_kwh != 0:
            raise ValueError("battery_kwh must be 0 when battery_action is idle")
        return self


class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation]
    hourly_plan: list[HourlyPlanEntry] = Field(min_length=24, max_length=24)
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
