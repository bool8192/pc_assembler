from pydantic import ValidationError, BaseModel, field_validator, confloat, conint
from typing import Literal

class GPU(BaseModel):
    normalized_name: str
    price_rub: float = confloat(ge=1000, lt=1000000)
    tdp: float = confloat(ge=10, le=800)
    length_mm: float = confloat(ge=120.0, le=400.0)
    power_connectors: int = conint(ge=6, le=24)
    source_url: str
    explanation_ru: str

    @field_validator('source_url')
    def check_wildberries_domain(cls, v):
        if '.wildberries.ru' not in v:
            raise ValueError("incorrect source_url")
        return v


class CPU_MB(BaseModel):
    cpu_name: str
    motherboard_name: str
    test: str
    result: float = confloat(ge=10.0, lt=100000)
    cpu_and_mb_price: float = confloat(ge=10000, lt=1000000)
    tdp: float = confloat(ge=20, le=600)
    form_factor: Literal['ATX','mATX', 'mini-ITX', 'E-ATX']
    ram_type: Literal['DDR4','DDR5','CAMM2']
    num_ram_slots: int= conint(ge=2, le=4)
    cpu_power_pins: int = conint(ge=4, le=16)
    required_cpu_power_pins: int = conint(ge=4, le=16)
    motherboard_url: str
    cpu_url: str

    @field_validator('motherboard_url', 'cpu_url')
    def check_wildberries_domain(cls, v):
        if '.wildberries.ru' not in v:
            raise ValueError("incorrect source_url")
        return v