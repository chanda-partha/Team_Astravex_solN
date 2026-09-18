from __future__ import annotations

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


class HourInput(BaseModel):
    hour: HourInt
    demand_kwh: float = Field(ge=0)
    solar_kwh: float = Field(ge=0)
    tariff_bdt_per_kwh: float = Field(ge=0)


class OptimizeRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourInput] = Field(min_length=24, max_length=24)
    battery: BatterySpec

    @model_validator(mode="after")
    def check_hours_complete(self) -> "OptimizeRequest":
        hour_values = [h.hour for h in self.hours]
        if hour_values != list(range(24)):
            raise ValueError("hours must contain exactly one entry for each hour 0..23 in order")
        return self


class SolarReduction(BaseModel):
    hours: list[HourInt] = Field(min_length=1)
    factor: float = Field(ge=0, le=1)


class MinimumBatteryReserve(BaseModel):
    hours: list[HourInt] = Field(min_length=1)
    minimum_energy_kwh: float = Field(ge=0)


class HoursOnly(BaseModel):
    hours: list[HourInt] = Field(min_length=1)


class MaxGridWindow(BaseModel):
    hours: list[HourInt] = Field(min_length=1)
    max_grid_kwh: float = Field(ge=0)


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


class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation]
    hourly_plan: list[HourlyPlanEntry] = Field(min_length=24, max_length=24)
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
