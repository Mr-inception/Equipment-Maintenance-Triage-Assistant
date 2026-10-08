from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class WorkOrderEdit(BaseModel):
    edited_by: str = Field(min_length=1, max_length=64)
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, min_length=3, max_length=8000)
    priority: Optional[Literal["low", "medium", "high", "critical"]] = None

    @model_validator(mode="after")
    def _need_change(self):
        if self.title is None and self.description is None and self.priority is None:
            raise ValueError("Provide at least one of title, description or priority to change.")
        return self


class ApproveIn(BaseModel):
    decided_by: str = Field(min_length=1, max_length=64)


class RejectIn(BaseModel):
    decided_by: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=3, max_length=2000)


class FindingIn(BaseModel):
    kind: Literal["observation", "confirmed_finding"]
    text: str = Field(min_length=3, max_length=2000)
    recorded_by: str = Field(min_length=1, max_length=64)
    evidence_note: Optional[str] = Field(default=None, max_length=1000)


class ConfirmIn(BaseModel):
    confirmed_by: str = Field(min_length=1, max_length=64)
    notes: Optional[str] = Field(default=None, max_length=1000)
