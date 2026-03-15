from pydantic import BaseModel, Field
from typing import Optional


class CityCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    department: Optional[str] = None
    country_code: str = Field(..., min_length=2, max_length=3, description="Code ISO pays, ex: BJ")
    country_name: str = Field(..., min_length=2, max_length=100, description="Ex: Bénin")


class CityUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    department: Optional[str] = None
    country_code: Optional[str] = Field(None, min_length=2, max_length=3)
    country_name: Optional[str] = None


class CityOut(BaseModel):
    id: str
    name: str
    department: Optional[str] = None
    country_code: str
    country_name: str

    class Config:
        populate_by_name = True
