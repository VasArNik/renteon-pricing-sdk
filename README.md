# renteon-pricing-sdk

A Python SDK for interacting with the [Renteon](https://www.renteon.com/) External Pricelist API with python.

Covers the full pricing workflow: authentication, fetching pricelists, manipulating prices, and saving them back. Built with [Pydantic](https://docs.pydantic.dev/) validation throughout.

> This SDK is focused on pricing and integrating Renteon Pricelist and pricing endpoints into custom or external data-pipelines (e.g. pricing/yielding)
It covers the `ExPricelist` endpoints of the Renteon External API only. It does not cover bookings, offices, fleet, invoices, or other endpoints.

---

## Features

--Client:
- Bearer token authentication with automatic re-fetch on expiry
- Fetch pricelists by numeric ID or by name
- Lazy-cached pricelist catalog (only hits the API when you use name-based lookup)
- Full Pydantic validation on all API inputs and responses

--Modeling of Pricing data:
- Rich `PriceList` object modeling Renteon's pricelists for integrating Renteon with ETLs 
- Filtering, Querying, Arithmetic operations, and transformation / serialisation
- Pythonic operator support (`+`, `-`, `*`, `/`, slice notation, square bracket notation)
- Structured exception hierarchy with HTTP status codes preserved
- DataFrame export via pandas

---

## Installation

```bash
pip install -r requirements.txt
```

> A PyPI package is not yet published. Clone the repo and install from source.

---

## Configuration

Copy `.env.example` to `.env` and fill in your Renteon API credentials:

```bash
cp .env.example .env
```

```env
RENTEON_BASEURL=https://your-tenant.s2.renteon.com/en
RENTEON_EXAPI_USERNAME=api_username
RENTEON_EXAPI_PASSWORD=your_password
RENTEON_EXAPI_SECRET=your_secret
RENTEON_CLIENT_ID=External.General
```


Configure an External API user by logging into Renteon and going to 'Code book' > 'Users' .
Make sure your account has the rights to create users and give permissions.
If unsure Renteon's support can guide you through this process.
Fill in your new credentials to the .env

> The SDK loads these automatically via `python-dotenv`. Never commit `.env` to version control.

---

## Quick Start

```python
from datetime import datetime
from renteon_pricing_sdk import RenteonClient

client = RenteonClient.from_env()

YOUR_PRICELIST_ID = 1000

prices = client.get_prices(
    pricelist_id=YOUR_PRICELIST_ID,
    date_from=datetime(2026, 1, 1),
    date_to=datetime(2026, 12, 31),
)

discounted = prices.apply_percentage(-10)
client.save_prices(pricelist_id=YOUR_PRICELIST_ID, price_list=discounted)
```

---

## Usage

### Authentication

Authentication is handled automatically by `RenteonTokenManager`. Tokens are cached in memory and re-fetched transparently when they expire (tokens are valid for 24 hours).
In this current vesion of the tokens do not persist externally. Each time a client is created the token is re-fetched.
You can easily set up persistence in your system if you want to launch multiple clients in a period of 22 hours with the same authorization. 
Tokens from Renteon are valid for 24 hous but in the RenteonTokenManager the expiry time is set to 22: `self._token_expiry - timedelta(hours=2)`



```python
from renteon_pricing_sdk import RenteonClient

client = RenteonClient.from_env()
```

The client reads credentials from your `.env` file. No manual token handling is needed.

---

### Fetching Prices

**By pricelist ID:**
```python
prices = client.get_prices(
    pricelist_id=1000,
    date_from=datetime(2026, 1, 1),
    date_to=datetime(2026, 12, 31),
)
```

**By pricelist name:**
```python
prices = client.get_prices(
    pricelist_name="Andromeda Intergalactic Spaceport",
    date_from=datetime(2026, 6, 1),
    date_to=datetime(2026, 8, 31),
)
```


When using `pricelist_name`, the SDK fetches the full pricelist catalog from `GET /api/ExPricelist` on the first call and caches it. Subsequent name-based calls use the in memory cache. Calls by ID never touch the above endpoint.

Warning! Renteon DOES NOT enforce UNIQUE pricelist names or codes. There can arrise a situation where 2 pricelists with the same name exist.
This relies too much on whether the account user practices terrible naming conventions or not, it is not recommended to do sensitive pricing operations on pricelists `by name` in production. For production systems resolve by ID only (which is unique)
The clients .pricelists_catalogue is a name:id  dictionary created from the json response of the get response to the 'exPricelist' endpoint. 
This means the key:value pairs are deduplicated by default. If 2 pricelists with the same name exist only the latest created one (higher office id int) will be kept. This can lead to bugs. Always use pricelist_id in production


**Filtering by SIPP or office:**
```python
prices = client.get_prices(
    pricelist_id=1000,
    date_from=datetime(2026, 1, 1),
    date_to=datetime(2026, 12, 31),
    car_category_sipps=["MDMR", "CDMR"],
    office_ids=[101, 102],
)
```

---

### The Pricelist Catalog


```python
# All available pricelist names
client.list_pricelists()

# Name : ID mapping. You need to be mindful of multiple possible pricelists with the same name. 
# in such a case only 1 will be stored in the dict
client.pricelists_catalog

# Raw API response (persist this in your system to avoid re-fetching)
client.raw_pricelists_catalog


# Force a re-fetch
client.refresh_pricelist_catalog()
```

> Per the Renteon API documentation, pricelist IDs differ between test and production environments. It is recommended to persist the catalog externally and load it on startup rather than resolving pricelist names at runtime each time. In any case it should be
handled externaly
This means that this class does not rely too much on checking for pricelist IDs OfficeIDs etc and requesting validating cross-checking at runtime!
It does offer fetching the pricelist catalogue but ideally all of this information will be mapped in your system
OR the cross-checking will be done seperately. 
This client assumes you already know which pricelist ids and which office ids you want to work with ,
the caller is responsible for knowing which environment they're talking to and supplying the correct IDs it.

E.g. production these data need to persist when necessary to avoid unecessary requests to the endpoint.
e.g. This class will not constantly validate whether Office "Andromeda 1"'s Office ID is 1000 OR whether car category XXMR is included as valid or whether there are valid OfficeIDs linked to that pricelist or anything else.
You can read the RenteonAPI docs  (your personal link)/en/api/help/referenceex

---

### Saving Prices

```python
client.save_prices(pricelist_id=1000, price_list=updated_prices)
```

`price_list` is serialised to the exact JSON structure expected by `SavePrices` automatically.


Quick Note: Renteon's API does not allow concurrent operations.

---

### Working with PriceList

PriceList is a class that models a Car Rental pricelist using pydantic validation. 

It is a collection of PriceRows (think excel rows) that are themselves collections of DurationPrice objects (think excel cell).
While PriceList has many built in pricing-related operation methods, it can also be converted to and from a pandas DataFrame allowing for more powerful data manipulation and analysis with dedicated methods.

All car-rental pricelists ,regardless of the environment, have AT LEAST the following defining properties:
Car Category (whether it be Acriss (e.g. MDMR) or Groups (e.g. A, B) or other categorization methods),
Pickup Location ,Pickup date (Either 1 date or a date-range), Duration (a.k.a LOR /Lenght of Rental)
The combination of the above determine the price amount.
The above is true for all types of car-rental rate-tables/pricelists. 
What differs is in the details: the data structure / the schema/ the shape/ the whatever.

This class models this data in a way the Renteon API can understand with the goal of integrating it to more complex systems

It is not limited to just storing fetched API responses to be used for API calls.
It can be more than that.

It can be used to construct a pricelist that Renteon understands from any data-input source .

E.g.:

Constructing PriceLists from external Car-rental pricing data pipelines based on unique business logic.

Integrating Renteon with custom ETL pipelines.


Transforming Rate tables from other sources (e.g. other car rental management systems) to a PriceList instance compatible with Renteon. A mediator between different Carrental management platform's pricelist format and Renteon, Which eliminates manual work that I personally know so many car-rental companies do.

At this current version PriceList instances are constructed with classmethods directly from API responses from Renteon directly (json).

Additional construction methods can be added based on any pricing data source you fancy, 
integrating this class into your ETL pipeline



#### Filtering

```python
# By SIPP code
prices.sipp("MDMR", "CDMR")

# By office
prices.by_office(office_id=101)     # specific office
prices.by_office(office_id=None)    # rows with no office (called common prices)

# By date range returns rows whose date window OVERLAPS the given range.

# A row is included if it is active at any point within [date_from, date_to].
# The row's own DateFrom/DateTo are NOT cropped; they are returned as is.
# Use crop=True on by_date_range() if you want the rows trimmed to the query range.





#Example: Give me all rows that define prices for the range 1/March/2026 to 30/June/2026
prices.by_date_range(date_from=datetime(2026, 3, 1), date_to=datetime(2026, 6, 30))

#crop
#Example case: Raising prices for valentines day by 10%

val_day_pricelist = prices.by_date_range(datetime(2026,2,14),datetime(2026,2,14),crop=True)

val_day_pricelist *= 1.1
#OR
val_day_pricelist = val_day_pricelist.apply_percentage(10)
#Now there is a completely seperate pricelist just for 14th of february.
#saving it will split the daterange into a seperate pricelist on Renteon



# Slice notation calls by_date_range() internally same overlap semantics.
# A row spanning Jan 1st–Dec 31st will appear in prices[mar:jun] because it covers that period.
prices[datetime(2026, 3, 1) : datetime(2026, 6, 30)]
prices[datetime(2026, 3, 1) :]     # open end: all rows active from Mar 1 onwards
prices[: datetime(2026, 6, 30)]    # open start: all rows active up to Jun 30
```

#### Iteration and indexing

```python
len(prices)         # number of rows
prices[0]           # first row (PriceRow)
prices[-1]          # last row

for row in prices:
    print(row.CarCategorySipp, row.DateFrom, row.DateTo)
```

#### Price operations

All operations return a new `PriceList` instance. The original is never modified in-place.

```python
prices.apply_percentage(10)       # +10%
prices.apply_percentage(-5)       # -5%
prices.apply_flat(20)             # add 20 to every cell
prices.set_flat_price(99.99)      # set every cell to 99.99. Not very useful for daily pricing operations though
prices.ensure_minimum_cutoff_price(50)  # raise any cell below 50 to 50. Enforce minimum price, mitigate human error
```

**Operator shortcuts:**
```python
prices + 10     # flat add to all prices
prices - 10     # flat subtract to all prices
prices * 1.5    # multiply all prices by number
prices / 2      # divide all prices by number
10 + prices     # commutative
2  * prices     # commutative
```

**Prices cannot be negative.** Pydantic enforces this at the model level , any operation producing a negative amount raises a `ValidationError`.

#### Merging two PriceLists

`merge_add` is a method to add the prices of each pricelist together. 
This is a bit of a specific operation that depends entirely on my personal perceived business logic requirements.

A lot of things -could- be considered logical outcomes of a PriceList + PriceList operation..
It could be merging the pricelists together into a big one (like concatenation) 
It could mean a lot of things potentially.

What I've chosen for this operation to do though is the following:

The first pricelist will be referred to as 'self' and the other as 'other'

Rows are matched by SIPP and OfficeId.


Self's full date range is preserved.
Each self row is matched against ALL other rows that share the same SIPP+OfficeId and overlap in date (not just the first one).
For each matching other row, self's date range is split into segments as needed:
pre-overlap (self values only), overlap between self+other (amounts of matching cells summed), post-overlap (self values only).
Gaps between consecutive other rows within self's range are emitted as self-only segments.

Self's duration ranges are kept unchanged. This is extremelly important because Renteon will not accept a change in pricelist structure after a pricelist is created (and has bookings under its name). E.g. you can't split 1-7 to 1-3, 4-7 and save the pricelist, the back-end will not accept it. 

Thus I had to make the decision of keeping the duration changes as they are based on one of the 2 pricelists (the first one in this case)
There wouldn't be a point in spliting the duration ranges based on overlaps between the 2 as I did with pickup date ranges. I tried it. Not useful.

Ok so what if the self's duration ranges are: 1-28: 99.99 and the 'other's duration ranges are 1-7: 10.00, 8-28: 5.00 ?
Both 10.00 and 5.00 match the self's date range which one is added?
Good question. No clear answer, depends entirely on business logic. For this method I've chosen to add the first (leftmost) price.
In our example that would be 10.00 so the final result of the operation for that cell would be 109.00

Idealy you wouldn't be adding any 2 random pricelists together. 
What example I had in mind: Adding a car -rental pricelist and an extras pricelist together and matching prices per office, sipp, date range etc.

Rows in self with no SIPP match in other are kept unchanged.

In conclusion, the resulting PriceList is:
All rows of self.
Extra rows of self created on date overlap with other.

all 'columns' of self as they where.

cells values whose row and column matches 'other' in SIPP , OfficeID , or overlapping date are summed between the 2.

TL;DR: if a price from pricelist 1 is for the same category and the same location and is for the same pickup date as in pricelist 2 then the 2 prices are added. Non matching rows of pricelist 1 are kept as is. Overlapping pickup-date periods are split into seperate periods.



```python
base_prices   = client.get_prices(pricelist_id=1000, ...)
extras_prices = PriceList.from_excel(path)

combined = base_prices.merge_add(extras_prices)
# or equivalently:
combined = base_prices + extras_prices
```
====================================================================================================================

#### Serialisation and export

```python
# Payload for SavePrices Post request (list of dicts). Used for posting the PriceList to Renteon API thereby saving the changes
prices.to_payload()

# Pandas DataFrame
prices.to_dataframe()

# Unpacked durations (one column per rental day)
prices.to_dataframe(unpack_durations=True, up_to=28)
```
Unpacked here means that if the LOR range is defined as e.g. 1-7 in Renteon the Dataframe will be unpacked to columns 1,2,3,4,5,6,7.
up_to is for when a range is open ended e.g. 21-. The range is unpacked up to the up_to value. e.g. up_to=30 column 21- will be unpacked to  ...21,22,23,24,25.....,30 


### Validation

The SDK validates all data with Pydantic. Errors are raised before any HTTP call is made.

```python
from renteon_pricing_sdk.models import GetPricesRequest

# DateTo before DateFrom raises ValidationError immediately
client.get_prices(
    pricelist_id=1000,
    date_from=datetime(2026, 12, 31),
    date_to=datetime(2026, 1, 1),     # ValidationError 
)

# SIPP codes must be exactly 4 characters as per the ACRISS standard. More or less than 4 char long str are rejected at the model level


# Negative Amounts for prices are rejected at the model level
```

---

### Exception Handling

```python
from renteon_pricing_sdk.exceptions import (
    RenteonAPIError,              # base , catch all
    RenteonBadRequestError,       # 400
    RenteonUnauthorizedError,     # 401
    RenteonForbiddenError,        # 403
    RenteonNotFoundError,         # 404
    RenteonUnprocessableEntityError,  # 422
    RenteonServerError,           # 5xx
)

try:
    prices = client.get_prices(pricelist_name="Does Not Exist", ...)
except RenteonNotFoundError as e:
    print(e)


empty = PriceList([]) # empty pricelist
try:
    client.save_prices(pricelist_id=2426, price_list=empty)
except RenteonUnprocessableEntityError as e:
    print(f"{e}")

try:
    client.save_prices(pricelist_id=0, price_list=prices) #non valid pricelist id
except RenteonServerError as e:
    print(f"Renteon server error: {e}")

```

Every exception carries a `status_code` attribute (`int | None`). `None` means the error occurred before any HTTP call was made (e.g. a name lookup failure against the local catalog).



---

## Structure

```
renteon_pricing_sdk/
├── token.py        RenteonTokenManager   — auth, token lifecycle
├── exceptions.py   Exception hierarchy   — HTTP error mapping
├── models.py       Pydantic models       — DurationPrice, PriceRow, GetPricesRequest
├── pricing.py      PriceList             — domain operations, filtering, arithmetic
└── client.py       RenteonClient         — HTTP transport, catalog
```

**Design principles:**

- `token.py` handles only auth. It knows nothing about pricing.
- `models.py` holds data shapes and validation only. No HTTP.
- `pricing.py` owns all operations on pricing data. It is an object that represents a Renteon Pricelist and handles pricing operations. It never makes HTTP calls.
- `client.py` is a thin transport layer. It builds requests, fires them, and returns responses. It does not implement pricing logic.

---

## Renteon API Notes

- This SDK covers endpoints relating to pricing only.
- The API requires both `DateFrom` and `DateTo` for `GetPrices`.
- Pricelist IDs **differ between test and production environments**. Do not hardcode IDs. Persist the catalog and make ID mappings configurable per environment.
- SIPP codes (car categories) follow the [ACRISS standard](https://www.acriss.org/) and are always 4 characters.
- `DurationTo: null` in the API means open-ended (e.g. "22 days or more").


---

