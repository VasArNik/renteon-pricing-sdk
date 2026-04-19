from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from annotated_types import Ge
from pydantic import BaseModel, model_validator, Field, AfterValidator
from typing import Annotated



def _validate_sipp(val:str)->str:
    ''' this is specifically just for the message that explains why sipps have to be 4 character long'''
    # same thing can be achieved with SippCode = Annotated[str, Field(min_length=4, max_length=4)]. 
    #but it raises a pydantic validation error not a custom error explaining what acriss is
    if len(val) !=4:
        raise ValueError(f"SIPP code must be exactly 4 characters as per the Acriss Code standard\nVisit https://www.acriss.org/car-codes/")
    return val.upper()  

SippCode = Annotated[str,  AfterValidator(_validate_sipp)]  

# All acriss codes are allways 4 letters long. no exceptions as far as I know. str too long



class GetPricesRequest(BaseModel):
    """Validated request body for ExPricelist/GetPrices.

    The API requires both DateFrom and DateTo , neither is optional.
    DateTo must not be earlier than DateFrom.

    CarCategorySipps and OfficeIds default to empty lists (= no filter = all).

    
            """

    PricelistId:      int
    DateFrom:         datetime
    DateTo:           datetime
    CarCategorySipps: List[SippCode] = []
    OfficeIds:        List[int] = []

    @model_validator(mode="after")
    def date_range_valid(self) -> "GetPricesRequest":
        if self.DateTo < self.DateFrom:
            raise ValueError(
                f"DateTo ({self.DateTo}) cannot be earlier than DateFrom ({self.DateFrom})"
            )
        return self

class DurationPrice(BaseModel):
    """A single pricing cell: a rental duration (LOR) range and its price.

    Example: DurationFrom=1, DurationTo=3, Amount=120.00
             means "1 to 3 days costs 120.00 per day"
    """

    DurationFrom: Annotated[int, Ge(1)]
    DurationTo:   Optional[Annotated[int, Ge(1)]] = None
    Amount:       Annotated[float, Field(ge=0, description="Price cannot be negative")]


    @model_validator(mode="after")
    def duration_to_not_before_from(self) -> DurationPrice:
        if self.DurationTo is not None and self.DurationTo < self.DurationFrom:
            raise ValueError(
                f"DurationTo ({self.DurationTo}) cannot be less than DurationFrom ({self.DurationFrom})"
            )
        return self


class PriceRow(BaseModel):
    """A single row in a Renteon pricelist.

    Represents one SIPP category (optionally scoped to an office else 'Common Prices')
    for a specific date range, with a list of duration-based per-day prices.
    """

    CarCategorySipp:    SippCode
    OfficeId:           Optional[int]   = None
    DateFrom:           datetime
    DateTo:             datetime
    DiscountPercentage: Optional[float] = None
    Durations:          List[DurationPrice]

    @model_validator(mode="after")
    def date_to_not_before_date_from(self) -> PriceRow:
        if self.DateTo < self.DateFrom:
            raise ValueError(
                f"DateTo ({self.DateTo}) cannot be earlier than DateFrom ({self.DateFrom})"
            )
        return self
