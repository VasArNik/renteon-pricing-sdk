from __future__ import annotations

import warnings
from typing import List, Optional
from datetime import datetime, timedelta
import pandas as pd

from .models import PriceRow, DurationPrice
from .bi_directional_dictionary import BiDirectionalDictionary

class PriceList:
    """An in-memory pricelist .  A collection of PriceRows objects fetched from Renteon itself
       or by external pricing systems output*. Can also be constructed from or an excel export.
     
    This class owns all operations that read or transform pricing data.


    *not implemented for public repo, depends heavily on which pricing data pipeline is used. 
    No point in including the constructor for a private pricing data pipeline or api that is not public.
.
    """

    def __init__(self, rows: List[PriceRow]) -> None:
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)
    
    def __iter__(self):
        return iter(self.rows)
    

    def __getitem__(self, get_this) -> "PriceRow | PriceList | list":
        if isinstance(get_this, int):
            return self.rows[get_this]

        if isinstance(get_this, str):
            return self.sipp(get_this).rows

        if isinstance(get_this, slice):
            start, stop = get_this.start, get_this.stop
            if not (start is None or isinstance(start, datetime)) or not (stop is None or isinstance(stop, datetime)):
                raise TypeError(
                    f"PriceList slice bounds must be datetime or None, got: "
                    f"start={type(start).__name__}, stop={type(stop).__name__}"
                )
            if get_this.step is not None:
                raise TypeError("PriceList slicing does not support a step value")
            return self.by_date_range(start, stop)

    def __repr__(self) -> str:
        sipps = sorted({row.CarCategorySipp for row in self.rows})
        return f"PriceList({len(self.rows)} rows, SIPPs={sipps})"
    

    #Dunder methods for operators
    def __add__(self, other: int | float| PriceList) -> "PriceList":
        if isinstance(other, (int, float)):
            return self._map_amounts(lambda a: round(a + other, 2))
        if isinstance(other, PriceList):
            return self.merge_add(other)
        return NotImplemented    
        
    
    def __sub__(self, other: int | float) -> "PriceList":
        if not isinstance(other, (int, float)):
            return NotImplemented
        
        return self._map_amounts(lambda a: round(a - other, 2))
    
    def __mul__(self, other: int | float) -> "PriceList":
        if not isinstance(other, (int, float)):
            return NotImplemented
        return self._map_amounts(lambda a: round(a * other, 2))
    

    def __truediv__(self, other: int | float) -> "PriceList":
        if not isinstance(other, (int, float)):
            return NotImplemented
        if other == 0:
            raise ValueError("Cannot divide prices by zero")
        return self._map_amounts(lambda a: round(a / other, 2))

    def __radd__(self, other: int | float) -> "PriceList":
        return self.__add__(other)

    def __rmul__(self, other: int | float) -> "PriceList":
        return self.__mul__(other)

    # class methods for construction

    @classmethod
    def from_getpricelist_api_response(cls, data: list[dict]) -> "PriceList":
        """Parse a raw JSON response list from the GetPrices endpoint into a PriceList."""
        return cls(rows=[PriceRow.model_validate(item) for item in data])
    


    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> "PriceList":
        """Create a PriceList from a DataFrame produced by method .to_dataframe().

        This way this class can be converted to and from a pandas DataFrame allowing for powerful data manipulation

        Expects the default band-mode output of .to_dataframe(unpack_durations=False)
        where duration columns are named like "1-1", "2-3"``, "4-6" , "7-".

        Required columns: SIPP, DateFrom, DateTo .
        Optional columns: OfficeId, Discount.

        Args:
            df: A DataFrame previously returned by method .to_dataframe().

        Raises:
            ValueError: If required columns are missing, no duration band columns
                        are found, or a row fails  PriceRow pydantic validation.
        """
        df = df.copy()

        required = {"SIPP", "DateFrom", "DateTo"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"DataFrame is missing required columns: {missing}. \nFound: {list(df.columns)}"
            )

        _meta = {"SIPP", "OfficeId", "DateFrom", "DateTo", "Discount"}
        duration_cols = []
        for c in df.columns:
            if c in _meta:
                continue
            parsed = cls._parse_duration_column(c)
            if parsed is not None:
                duration_cols.append((c, parsed))
        if not duration_cols:
            raise ValueError(
                f"No duration band columns found. Expected columns like '1-1', '2-3', '8-'. \nFound: {list(df.columns)}"
            )
        duration_cols.sort(key=lambda x: x[1][0])

        rows: list[PriceRow] = []
        for i, record in enumerate(df.to_dict(orient="records")):
            record = {k: None if isinstance(v, float) and v != v else v for k, v in record.items()}

            durations = [
                DurationPrice(DurationFrom=lo, DurationTo=hi, Amount=record[col])
                for col, (lo, hi) in duration_cols
                if record[col] is not None
            ]

            row_data = {
                "CarCategorySipp":    record["SIPP"],
                "OfficeId":           record.get("OfficeId"),
                "DateFrom":           record["DateFrom"],
                "DateTo":             record["DateTo"],
                "Durations":          durations,
                "DiscountPercentage": record.get("Discount"),
            }

            try:
                rows.append(PriceRow.model_validate(row_data))
            except Exception as e:
                raise ValueError(f"Row {i} failed validation: {e}\nRow data: {row_data}") from e

        return cls(rows)

    @classmethod
    def from_excel(cls, path: str, office_map: dict[str, int] |BiDirectionalDictionary| None = None) -> "PriceList":
        """Create a PriceList from the Excel exported by Renteon's 'Export Pricelist'.

        The pricelist data is expected in the second sheet.

        Args:
            path:       Path to the Excel file.
            office_map: Optional {OfficeCode: OfficeId} mapping to resolve the
                        'Office' column to integer OfficeIds.
                        get it from client.offices_map which returns a BiDirectionalDictionary object.
                        which means OfficeCodes can be accessed with their OfficeIds and vice versa
                            
                        If omitted, all rows will have OfficeId=None with a warning.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file cannot be read, a required sheet or column
                        is missing, no duration columns are found, or a row
                        fails PriceRow validation.
        """
        try:
            sheets = pd.read_excel(path, sheet_name=[1])
        except FileNotFoundError:
            raise FileNotFoundError(f"Excel file not found: {path}")
        except Exception as e:
            raise ValueError(f"Could not read Excel file '{path}': {e}") from e

        if 1 not in sheets:
            raise ValueError(f"'{path}' does not have a second sheet (index 1).")
        sheet = sheets[1]

        sheet = sheet.rename(columns={"ServiceName": "CarCategorySipp"})

        if "Office" in sheet.columns:
            if office_map is None:
                warnings.warn(
                    "Excel contains an 'Office' column (office codes) but no office_map was provided. "
                    "All rows will have OfficeId=None. "
                    "Pass office_map=client.offices_map.",
                    UserWarning,
                    stacklevel=2,
                )
                sheet = sheet.drop(columns=["Office"])
            else:
                sheet["OfficeId"] = sheet["Office"].map(office_map.get)
                sheet = sheet.drop(columns=["Office"])

        required = {"CarCategorySipp", "DateFrom", "DateTo"}
        missing = required - set(sheet.columns)
        if missing:
            raise ValueError(
                f"Excel sheet is missing expected columns: {missing}. "
                f"Found: {list(sheet.columns)}"
            )

        duration_cols = [c for c in sheet.columns if cls._parse_duration_column(c) is not None]
        if not duration_cols:
            raise ValueError(
                f"No duration columns found. Expected columns like '1-1', '2-3', '8-'. "
                f"Found: {list(sheet.columns)}"
            )

        rows: list[PriceRow] = []
        for i, record in enumerate(sheet.to_dict(orient="records")):
            # pandas stores missing values as float NaN in numeric columns; normalise to None
            record = {k: None if isinstance(v, float) and v != v else v for k, v in record.items()}

            durations = []
            row: dict = {}
            for col, val in record.items():
                parsed = cls._parse_duration_column(col)
                if parsed is not None:
                    dur_from, dur_to = parsed
                    durations.append({"DurationFrom": dur_from, "DurationTo": dur_to, "Amount": val})
                else:
                    row[col] = val
            row["Durations"] = durations

            try:
                rows.append(PriceRow.model_validate(row))
            except Exception as e:
                raise ValueError(f"Row {i} failed validation: {e}\nRow data: {row}") from e

        return cls(rows)

    #filtering / querying
    def sipp(self, *sipps: str) -> "PriceList":
        """Return a new PriceList containing only the given SIPP codes."""
        codes = {s.upper() for s in sipps}
        return PriceList([r for r in self.rows if r.CarCategorySipp in codes])

    def by_office(self, office_id: Optional[int]) -> "PriceList":
        """Return a new PriceList for a specific office (None = common prices)."""
        return PriceList([r for r in self.rows if r.OfficeId == office_id])
    

    def by_date_range(self, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None, crop:bool=False) -> "PriceList":
        """Return rows whose date window overlaps the given range.
        None on either bound means open-ended (no lower or upper limit).

        If crop=True, each returned row is cropped to fit within [date_from, date_to].
        """
        overlapping = [
            r for r in self.rows
            if (date_to is None or r.DateFrom < date_to)
            and (date_from is None or r.DateTo >= date_from)
        ]
        if not crop:
            return PriceList(overlapping)
        return PriceList([
            r.model_copy(update={
                "DateFrom": max(r.DateFrom, date_from) if date_from is not None else r.DateFrom,
                "DateTo":   min(r.DateTo,   date_to)   if date_to   is not None else r.DateTo,
            })
            for r in overlapping
        ])


    def by_duration(self, duration_from: int = 1, duration_to: Optional[int] = None) -> "PriceList":
        """Return a new PriceList keeping only duration bands that overlap [duration_from, duration_to].
        None on duration_to means open-ended (no upper limit).
        """
        result_rows = []
        for r in self.rows:
            matching = [
                cell for cell in r.Durations
                if (duration_to is None or cell.DurationFrom <= duration_to)
                and (cell.DurationTo is None or cell.DurationTo >= duration_from)
            ]
            if matching:
                result_rows.append(r.model_copy(update={"Durations": matching}))
        return PriceList(result_rows)


    #quick maffs

    def merge_add(self, other: "PriceList") -> "PriceList":
        """
        Add two PriceLists together, returning a new PriceList.
        This is a very specific opperation that in my opinion matches the uses of pricelists as used for pricing in renteon
        Rows are matched by SIPP code and OfficeId. Rows that belong to other with no match in self are dropped entirely from the result. Self's full date range is 
        preserved and split into  upto three segments per matching 'other' rows based on date ranges
        pre-overlap  (self only): dates before other starts, original amounts.

        overlap      (self + other): merged amounts, self's duration structure.
        
        post-overlap (self only): dates after other ends, original amounts.

        Duration band structure always comes from self; the first overlapping
        band from other is used for the amount addition.

        Example usecases: 
        Add a car-rental pricelist and an extras pricelist to have the extra included in the price.
    
        """
        INF = float("inf")
        result_rows: list[PriceRow] = []

        for row in self.rows:
            # gathrt ALL others rows that match SIPP+OfficeId and overlap this row's date range, sorted by DateFrom (datetime)
            matching_others = sorted(
                [
                    r for r in other.rows
                    if r.CarCategorySipp == row.CarCategorySipp
                    and r.OfficeId == row.OfficeId
                    and r.DateFrom <= row.DateTo
                    and r.DateTo   >= row.DateFrom
                ],
                key=lambda r: r.DateFrom,
            )

            # If no is found for the above keep self row unchanged
            if not matching_others:
                result_rows.append(row)
                continue

            # For this specific matching row keep the DateFrom
            cursor = row.DateFrom

            for other_row in matching_others:
                # Gap before this other_row starts (self only, original amounts)
                if cursor < other_row.DateFrom:
                    result_rows.append(row.model_copy(update={
                        "DateFrom": cursor,
                        "DateTo":   other_row.DateFrom - timedelta(seconds=1),
                    }))

                # Overlap section. sum durations. Durations sections always come from self
                overlap_from = max(cursor,       other_row.DateFrom)
                overlap_to   = min(row.DateTo,   other_row.DateTo)

                merged_durations: list[DurationPrice] = []
                for cell in row.Durations:
                    cell_end = cell.DurationTo if cell.DurationTo is not None else INF
                    match = next(
                        (
                            o for o in other_row.Durations
                            if cell.DurationFrom <= (o.DurationTo if o.DurationTo is not None else INF)
                            and o.DurationFrom <= cell_end
                        ),
                        None,
                    )
                    merged_durations.append(DurationPrice(
                        DurationFrom=cell.DurationFrom,
                        DurationTo=cell.DurationTo,
                        Amount=round(cell.Amount + (match.Amount if match else 0.0), 2),
                    ))

                result_rows.append(row.model_copy(update={
                    "DateFrom":  overlap_from,
                    "DateTo":    overlap_to,
                    "Durations": merged_durations,
                }))

                cursor = other_row.DateTo + timedelta(seconds=1)
                if cursor > row.DateTo:
                    break

            # the rest of the rows after the last other_row ends (self only self's amounts)
            if cursor <= row.DateTo:
                result_rows.append(row.model_copy(update={
                    "DateFrom": cursor,
                    "DateTo":   row.DateTo,
                }))

        return PriceList(result_rows)
    
    def apply_percentage(self, percent: float) -> "PriceList":
        """Apply a percantage change to all amounts in the Pricelist.

        apply_percentage(10)   +10%
        apply_percentage(-15)  -15%
        """
        multiplier = 1 + percent / 100
        return self._map_amounts(lambda a: round(a * multiplier, 2))

    def apply_flat(self, amount: float) -> "PriceList":
        """Return a new PriceList with a flat amount added to every cell.
        dunder add does the same with the + operator"""
        return self._map_amounts(lambda a: round(a + amount, 2))
    



    def set_flat_price(self, price: float) -> "PriceList":
        """Return a new PriceList where every cell is set to a fixed price. Kind of useless for daily pricing operations
          but it does not hurt having it"""
        return self._map_amounts(lambda _: round(price, 2))
    
    def ensure_minimum_cutoff_price(self, minimum_price: float) -> "PriceList":
        """Check if any prices in the whole pricelist are bellow a certain amount. If found replace with minimum, ensure no price is bellow the minimum.
        serves to enforce minimum prices mostly to guard against human error. Single Hard cutoff.- Does not take into account categories durations date periods or anything else"""
        return self._map_amounts(lambda a: round(max(a, minimum_price), 2))

    # conversion and serialization  (output)

    def to_payload(self) -> list[dict]:
        """Serialise to the exact JSON structure expected by SavePrices. Payload for a post request"""
        return [row.model_dump(mode="json") for row in self.rows]
    
    # def to_dict(self) -> dict:
    #     pass

    
    def to_excel(self, path: str, office_map: dict[int, str] | BiDirectionalDictionary|None = None) -> None:
        """Export to an Excel file matching Renteon's 'Import Pricelist' format. 
        Use this to create an excel file meant to be manually imported to Renteon

        Args:
            path:       Output file path.
            office_map: Optional {OfficeId: OfficeCode} mapping used to resolve
                        integer OfficeIds back to the code strings Renteon expects.
                        Pass it from the client

                        get it from client.offices_map which returns a BiDirectionalDictionary object.
                        which means OfficeCodes can be accessed with their OfficeIds and vice versa
                          
                        If omitted, OfficeIds are written as-is and Renteon will
                         reject the file if you attempt to upload it.

        Raises:
            ValueError: If the file cannot be written.
        """
        if office_map is None:
            warnings.warn(
                "No office_map provided. OfficeId integers will be written to the 'Office' column "
                "and Renteon's import will reject them. "
                "Pass an Code:ID key:value dictionary or a BiDirectionalDictionary with a RenteonClient instance's .office_map()",
                 UserWarning,
                stacklevel=2,
            )

        # Collect all unique duration bands across all rows, sorted
        seen: set = set()
        all_bands: list[tuple[int, int | None]] = []
        for row in self.rows:
            for d in row.Durations:
                key = (d.DurationFrom, d.DurationTo)
                if key not in seen:
                    seen.add(key)
                    all_bands.append(key)
        all_bands.sort(key=lambda b: (b[0], b[1] if b[1] is not None else float("inf")))

        def _col_name(band: tuple[int, int | None]) -> str:
            return f"{band[0]}-{band[1] if band[1] is not None else ''}"

        #office_col = "Office" if office_map is not None else "OfficeId"

        records = []
        for row in self.rows:
            amount_by_band = {(d.DurationFrom, d.DurationTo): d.Amount for d in row.Durations}
            office_cell = (
                office_map.get(row.OfficeId) if (office_map is not None and row.OfficeId is not None)
                else row.OfficeId
            )
            record: dict = {
                "ServiceName": row.CarCategorySipp,
                "Office":      office_cell,

                "DateFrom":    row.DateFrom.date(),
                "DateTo":      row.DateTo.date(),
            }
            for band in all_bands:
                record[_col_name(band)] = amount_by_band.get(band)
            records.append(record)

        df = pd.DataFrame(records)

        try:
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                pd.DataFrame().to_excel(writer, sheet_name="Blank", index=False)
                df.to_excel(writer, sheet_name="Prices", index=False)
        except Exception as e:
            raise ValueError(f"Could not write Excel file '{path}': {e}") from e
    
    # def to_csv(self, path) -> None:
    #     pass

    def to_dataframe(self, unpack_durations: bool = False, up_to: int = 0) -> pd.DataFrame:
        """Convert to a pandas DataFrame.

        Args:
            unpack_durations: If False (default), duration bands become column
                              headers (e.g. "1-1", "2-3"). If True, each day
                              number gets its own column.
                    example: duration "2-5" becomes 4 columns: 2,3,4,5
            up_to:            When unpacking, the maximum day number to generate
                              for open-ended bands (DurationTo=None).
                    example: for up_to=30 "28-" becomes 3 columns: 28,29,30
            
        """
        records = []
        for row in self.rows:
            if unpack_durations:
                duration_cols = {
                    day: d.Amount
                    for d in row.Durations
                    for day in range(
                        d.DurationFrom,
                        (d.DurationTo + 1) if d.DurationTo is not None
                        else max(d.DurationFrom + 1, up_to + 1),
                    )
                }
            else:
                duration_cols = {
                    f"{d.DurationFrom}-{d.DurationTo if d.DurationTo is not None else ''}": d.Amount
                    for d in row.Durations
                }

            records.append({
                "SIPP":     row.CarCategorySipp,
                "OfficeId": row.OfficeId,
                "DateFrom": row.DateFrom,
                "DateTo":   row.DateTo,
                **duration_cols,
                "Discount": row.DiscountPercentage,
            })

        return pd.DataFrame(records)

    #private

    @staticmethod
    def _parse_duration_column(colname: str) -> tuple[int, int | None] | None:
        """Parse a duration column name like '1-8' or '22-' into their components.
        Returns None if the column name is not a duration column.
        Used for converting an excel to a PriceList object
        """
        try:
            left, right = str(colname).split('-')
            return int(left), (int(right) if right else None)
        except (ValueError, AttributeError):
            return None

    def _map_amounts(self, fn) -> "PriceList":
        """Return a deep copy with fn (function) applied to every DurationPrice.Amount."""
        new_rows = []
        for row in self.rows:
            new_durations = [
                DurationPrice(
                    DurationFrom=d.DurationFrom,
                    DurationTo=d.DurationTo,
                    Amount=fn(d.Amount),
                )
                for d in row.Durations
            ]
            new_rows.append(row.model_copy(update={"Durations": new_durations}))
        return PriceList(new_rows)

