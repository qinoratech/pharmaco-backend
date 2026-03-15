from pydantic import BaseModel, Field
from typing import Optional


class PharmacyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    contact_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    city_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_active: bool = True


class PharmacyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    contact_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    city_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_active: Optional[bool] = None


class PharmacyOut(BaseModel):
    id: str
    name: str
    contact_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    city_id: str
    city_name: Optional[str] = None
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_active: bool
    is_on_duty_today: bool = False

    class Config:
        populate_by_name = True
