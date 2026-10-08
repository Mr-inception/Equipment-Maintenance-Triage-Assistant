from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SensorIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    value: Optional[float] = None
    unit: Optional[str] = Field(default=None, max_length=16)
    source: Optional[str] = Field(default=None, max_length=64)
    recorded_at: Optional[datetime] = None


class OperatingEventIn(BaseModel):
    time: Optional[str] = Field(default=None, max_length=40)
    event: str = Field(min_length=1, max_length=500)


class ReportIn(BaseModel):
    equipment_type: str = Field(min_length=2, max_length=64)
    identifier: str = Field(min_length=1, max_length=64)
    issue_description: str = Field(min_length=5, max_length=4000)
    operating_events: list[OperatingEventIn] = Field(default_factory=list, max_length=50)
    sensor_readings: list[SensorIn] = Field(default_factory=list, max_length=50)
