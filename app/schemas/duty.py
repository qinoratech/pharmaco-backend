from pydantic import BaseModel
from datetime import date
from typing import Optional


class DutyCreate(BaseModel):
    pharmacy_id: str
    date: date
    validated: bool = False


class DutyUpdate(BaseModel):
    date: Optional[date] = None
    validated: Optional[bool] = None


class DutyOut(BaseModel):
    id: str
    pharmacy_id: str
    pharmacy_name: Optional[str] = None
    city_name: Optional[str] = None
    country_name: Optional[str] = None
    country_code: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    date: date
    validated: bool

    class Config:
        populate_by_name = True
