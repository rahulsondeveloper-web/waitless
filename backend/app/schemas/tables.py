import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel

TableStatus = Literal["available", "reserved", "occupied", "cleaning"]
ManualStatus = Literal["available", "reserved", "cleaning"]  # "occupied" only via seating


class SectionIn(ApiModel):
    branch_id: uuid.UUID
    name: str = Field(min_length=1, max_length=60)


class SectionPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    sort_order: int | None = Field(default=None, ge=0, le=999)


class SectionOut(ApiModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    sort_order: int


class TableIn(ApiModel):
    branch_id: uuid.UUID
    section_id: uuid.UUID | None = None
    label: str = Field(min_length=1, max_length=20)
    capacity: int = Field(ge=1, le=50)


class TablePatch(ApiModel):
    section_id: uuid.UUID | None = None
    label: str | None = Field(default=None, min_length=1, max_length=20)
    capacity: int | None = Field(default=None, ge=1, le=50)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


class TableOut(ApiModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    section_id: uuid.UUID | None
    label: str
    capacity: int
    status: TableStatus
    is_active: bool
    sort_order: int


class TableStatusIn(ApiModel):
    status: ManualStatus


class BoardSession(ApiModel):
    id: uuid.UUID
    public_code: str
    party_size: int
    guest_name: str | None
    opened_at: datetime
    source: str


class BoardTable(TableOut):
    section_name: str | None
    session: BoardSession | None


class BoardOut(ApiModel):
    branch_id: uuid.UUID
    tables: list[BoardTable]
    sections: list[SectionOut]
    counts: dict[str, int]  # by status
    server_time: datetime


class SeatIn(ApiModel):
    table_id: uuid.UUID
    party_size: int = Field(ge=1, le=100)
    guest_name: str | None = Field(default=None, max_length=80)


class TransferIn(ApiModel):
    table_id: uuid.UUID


class SessionOut(ApiModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    public_code: str
    status: str
    party_size: int
    guest_name: str | None
    table_ids: list[uuid.UUID]
    opened_at: datetime
    closed_at: datetime | None


class SeatedOut(ApiModel):
    session: SessionOut
    pin: str = Field(description="Shown once. Give it to the guests with the code; it is stored hashed.")


class DashboardOut(ApiModel):
    branch_id: uuid.UUID | None
    tables_total: int
    tables_by_status: dict[str, int]
    open_sessions: int
    guests_seated: int
    branches_active: int
    staff_active: int
    dishes_live: int
    # Filled by later phases (PRD §15). null = module not live yet.
    todays_revenue: str | None = None
    orders_today: int | None = None
    active_orders: int | None = None
    active_reservations: int | None = None
    queue_length: int | None = None
    average_wait_minutes: int | None = None
    average_serving_minutes: int | None = None
    delayed_orders: int | None = None
    discounts_today: str | None = None
    low_inventory_alerts: int | None = None
