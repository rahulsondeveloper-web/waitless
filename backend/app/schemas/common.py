from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.phone import normalize_phone

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class Page(ApiModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int


PhoneNumber = Annotated[str, Field(min_length=8, max_length=20), AfterValidator(normalize_phone)]
Password = Annotated[str, Field(min_length=8, max_length=128)]
