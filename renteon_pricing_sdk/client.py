from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import requests
# from pydantic import BaseModel, model_validator

from .models import SippCode, GetPricesRequest
from .token import RenteonTokenManager, RenteonAuthError
from .pricing import PriceList
from .bi_directional_dictionary import BiDirectionalDictionary

from .exceptions import RenteonAPIError, RenteonNotFoundError, RenteonServerError, HTTP_EXCEPTION_MAP
#logger = logging.getLogger(__name__)


class RenteonClient:
    """HTTP client for the Renteon External Pricelist API.

    Handles authentication automatically via RenteonTokenManager.
    All methods return domain objects,no raw JSON leaks out.

    Usage:
        client = RenteonClient.from_env()

        # by ID
        prices = client.get_prices(pricelist_id=2426,
                                   date_from=datetime(2026, 1, 1),
                                   date_to=datetime(2026, 12, 31))

        # by name (catalog is fetched once and cached)
        prices = client.get_prices(pricelist_name="August Rates 2026",
                                   date_from=datetime(2026, 6, 1),
                                   date_to=datetime(2026, 8, 31))

        updated = prices.apply_percentage(-10)
        client.save_prices(pricelist_id=2426, price_list=updated)
    """

    def __init__(self, token_manager: RenteonTokenManager, base_url: str) -> None:
        self._token_manager = token_manager
        self._base_url = base_url.rstrip("/")
        self._available_pricelists_catalog_by_name: dict[str, int] | None = None
        self._available_pricelists_catalog_raw:     list[dict]      | None = None
        self._offices_catalog_by_code: dict[str, dict[str, int | str]] | None = None
        self._offices_catalog_raw :  list[dict]  | None = None
        self._offices_map : BiDirectionalDictionary | None = None 

    # Factory constructor classmethods


    @classmethod
    def from_env(cls) -> "RenteonClient":
        """Construct a client from environment variables (or a .env file)."""
        manager = RenteonTokenManager.from_env()
        return cls(token_manager=manager, base_url=manager._base_url)

    # 
    # Available Pricelists catalog. 

    """
    Ideally these following catalogues (either the parsed dict or the raw json ) will be persistent from outside reads.
    In any case they should be handled externally when possible.
    """
    # 

    @property
    def pricelists_catalog(self) -> dict[str, int]:
        """Name : id mapping of all available pricelists.

        Fetched once on first access and cached for the lifetime of this client.
        Call refresh_pricelist_catalog() to force a re-fetch.

        Important Note: Renteon does NOT enforce UNIQUE pricelist name on their platfrom nor do they enfore unique pricelist Code.
        There can exist a situation (due to bad naming conventions of users) where there are 2 pricelists with the same name.
        Use pricelist IDs in production which are guaranteed to be unique
        """
        if self._available_pricelists_catalog_by_name is None:
            self._fetch_pricelists_catalog()
        return self._available_pricelists_catalog_by_name 

    @property
    def raw_pricelists_catalog(self) -> list[dict]:
        """Raw API response from GET /api/ExPricelist, as returned by the server.

        Use this if you want to persist the catalog externally (db, redis,
        a local file, etc.). The structure is whatever Renteon sends,no
        processing is applied.
        """
        if self._available_pricelists_catalog_raw is None:
            self._fetch_pricelists_catalog()
        return self._available_pricelists_catalog_raw  

    @property
    def offices_catalog(self) -> dict[str, dict[str, int | str]]:
        """Name :  OfficeCode mapping of all available Offices.

        Fetched once on first access and cached for the lifetime of this client.
        .
        """
        if self._offices_catalog_by_code is None:
            self._fetch_offices_catalog()
        return self._offices_catalog_by_code  

    @property
    def raw_offices_catalog(self) -> list[dict]:
        """Raw API response from GET /api/office/, as returned by the server.

        Use this if you want to persist the catalog externally (db, redis,
        a local file, etc.). The structure is whatever Renteon sends,no
        processing is applied.
        """
        if self._offices_catalog_raw is None:
            self._fetch_offices_catalog()
        return self._offices_catalog_raw  
    
    @property
    def offices_map(self) -> BiDirectionalDictionary:
        """Returns a BiDirectionalDictionary class. This means you can fetch values in either direction (key-value/value-key)
        used to create a map of officeIDs and OfficeCodes. Usefull for the excel methods.
        Warning: This assumes that there won't be a case where an office on Renteon will have an ID 123 and another office will have a CODE '123'.
        Renteon allows naming offices as digits in both name and office code . 
        Good news is that on Renteon Ids are integers while names and codes are strings but it can be a bit confusing
        if you have an office named '123' and another office with the assigned id int of 123. 
        But if that issue comes up it is up to your questionable naming conventions I suppose..
        .
        """
        _map = { i['Id']:o for o,i in  self.offices_catalog.items()}
        return BiDirectionalDictionary(_map)
    def pricelists_map(self) :
        raise NotImplementedError
    def list_pricelists(self) -> list:
        """Return all pricelist names available on the server."""
        return list(self.pricelists_catalog.keys())
    def list_office_codes(self) -> list:
        """Return all office codes available on the server."""
        return list(self.offices_catalog.keys())

    def refresh_pricelist_catalog(self) -> None:
        """Force a refetch of the pricelist catalog from the API.

        Call this if pricelists have been added or renamed on the server since
        this client was created. Very unlikely. Good to have
        """
        self._fetch_pricelists_catalog()

    def refresh_office_catalog(self) -> None:
        """Force a refetch of the office catalog from the API.

        Call this if Offices have been added or renamed on the server since
        this client was created. Extremely unlikely to happen. Good to have for testing and such
        """
        self._fetch_offices_catalog()
    # External API requests


    def get_prices(
        self,
        *,
        pricelist_id:  int | None = None,
        pricelist_name: str | None = None,
        date_from:   datetime,
        date_to:    datetime,
        car_category_sipps: Optional[List[str]] = None,
        office_ids:       Optional[List[int]] = None,
        office_codes:   Optional[List[str | None]] = None,
    ) -> PriceList:
        """Fetch prices from the ExPricelist/GetPrices endpoint.

        Supply either pricelist_id (int) or pricelist (name string), not both not neither (XOR)

        Supply either a list office_codes or a list of office_ids or neither, not both  (NAND)

        Args:
            pricelist_id:       The numeric Renteon pricelist ID.
            pricelist_name:          The pricelist name (resolved via catalog).
            date_from:          Start of the date range. 
            date_to:            End of the date range.
            car_category_sipps: Filter by SIPP codes. Empty/None = all.
            office_ids:         Filter by office IDs. Empty/None = all.

        --------------------------------------------------------------------------
        Renteon External API Documentation for ExPricelist/GetPrices endpoint:

        CarCategorySipps:
        Car category SIPP identifiers, type: Collection of string  , Not required

        DateFrom:            	
        Booking date range start when price is applicable. Local date in ISO 8601 format without time zone designation.
         type:date  ,   Required

        DateTo:            	
        Booking date range start when price is applicable. Local date in ISO 8601 format without time zone designation.
         type:date  ,   Required


        OfficeIds:
        Office identifiers. For common prices (not defined per office) use -1  (Important bit )
        type: Collection of integer  , Not required

        PricelistId:
        Pricelist identifier , type: integer, Required
        --------------------------------------------------------------------------

        """
        if pricelist_id is None and pricelist_name is None:
            raise ValueError("Supply either pricelist_id or pricelist name.")
        if pricelist_id is not None and pricelist_name is not None:
            raise ValueError("Supply pricelist_id OR pricelist name, not both.")
        

        if office_ids is not None and office_codes is not None:
            raise ValueError("Supply a list of Office Ids OR a list of Office Codes, not both.")
        

        resolved_pricelist_id = (
            pricelist_id if pricelist_id is not None
            else self._resolve_pricelist(pricelist_name)  # type: ignore[arg-type]
        )

        if office_codes is not None:
            office_ids = [self._resolve_office(code).get('Id') for code in office_codes]
            

        request = GetPricesRequest(
            PricelistId=resolved_pricelist_id,
            DateFrom=date_from,
            DateTo=date_to,
            CarCategorySipps=car_category_sipps or [],
            OfficeIds=office_ids or [],
        )

        response = self._post(
            "/api/ExPricelist/GetPrices",
            json=request.model_dump(mode="json"),
        )
        return PriceList.from_getpricelist_api_response(response.json())

    def save_prices(self, pricelist_id: int, price_list: PriceList) -> None:
        """Push a PriceList to the ExPricelist/SavePrices endpoint.
        uses the PriceList instance's seriallization method .to_payload() to create a JSON payload for the POST request"""
        self._post(
            "/api/ExPricelist/SavePrices",
            params={"pricelistId": pricelist_id},
            json=price_list.to_payload(),
        )


    # private helpers


    @property
    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self._token_manager.token}"}
    

    """
    Note from Renteon API docs:
    ---IMPORTANT NOTE: Depending on your integration strategy,
      you may choose to map some of ID-s to your system ID-s 
      (e.g. car categories, offices, equipment, pricelists). If you do that, please note that ID-s WILL 
      BE DIFFERENT ON PRODUCTION AND TEST ENVIRONMENTS, so you should make it easily configurable on your side---.
      
      This means that this class does not rely too much on checking for pricelist IDs OfficeIDs etc and requesting validating cross-checking at runtime!
      There are some things like fetching the pricelist catalogue but ideally all of this information will be mapped in your system
      OR the cross-checking will be done seperately. 
      This client assumes you already know which pricelist ids and which office ids you want to work with:
      !!!!the caller is responsible for knowing which environment they're talking to and supplying the correct IDs for it!!!
      In production these data need to persist when necessary to avoid unecessary requests to the endpoint.
      e.g. This class will not constantly validate whether Office "Andromeda 1"'s Office ID is 1000 OR whether car category XXMR is included as valid or whether there are valid OfficeIDs linked to that pricelist or anything else.
      You can read the RenteonAPI docs  (your link)/en/api/help/referenceex
      """

    def _fetch_pricelists_catalog(self) -> None:
        response = self._get("/api/ExPricelist")
        self._available_pricelists_catalog_raw = response.json()
        self._available_pricelists_catalog_by_name = {p["Name"]: p["Id"] for p in self._available_pricelists_catalog_raw}
        #logger.debug("Catalog fetched: %d pricelists loaded.", len(self._available_pricelists_catalog_by_name))

    def _fetch_offices_catalog(self) -> None:
        response = self._get("/api/office/getSimpleList/", params= {'allowUserAllowedOfficesOnly' : True})
        self._offices_catalog_raw = response.json()
        self._offices_catalog_by_code = { r.get('Code'): {'Id' : r.get('Id'), 'Name': r.get('Translation').get('Name')}  for r in response.json()}
        self._offices_catalog_by_code.update({None: {'Id': -1, 'Name' : 'Common Prices'} # not ideal. list catalog prints a None. Not immediately clear to someone not familiar with renteons common prices
                                         } )

        #logger.debug("Pricelists catalog fetched: %d pricelists loaded.", len(self._available_pricelists_catalog_by_name))

    def _resolve_pricelist(self, name: str) -> int:
        if name not in self.pricelists_catalog:
            raise RenteonNotFoundError(
                f"No pricelist named '{name}'. "
                f"Available: {list(self.pricelists_catalog.keys())}"
            )
        return self.pricelists_catalog[name]
    

    def _resolve_office(self, officecode: str | None) -> int:
        
        if officecode not in self.offices_catalog:
            raise RenteonNotFoundError(
                f"No Office with OfficeCode '{officecode}'. "
                f"Available: {list(self.offices_catalog)}"
            )
        
        if officecode in (None, ''):
            return {'Id': -1, 'Name': 'Common Prices'} #for the special case of common prices
        # this is also hand;ed by adding a None key in the offices_catalog explicitly
        
        return self.offices_catalog[officecode]

    def _get(self, path: str, *, params: dict | None = None) -> requests.Response:
        try:
            response = requests.get(
                url=f"{self._base_url}{path}",
                headers=self._auth_header,
                params=params,
            )
        except requests.RequestException as exc:
            raise RenteonAPIError(f"GET {path} failed: {exc}") from exc
        self._raise_for_status(response, f"GET {path}")
        return response

    def _post(self, path: str, *, json: object, params: dict | None = None) -> requests.Response:
        try:
            response = requests.post(
                url=f"{self._base_url}{path}",
                headers={"Content-Type": "application/json", **self._auth_header},
                json=json,
                params=params,
            )
        except requests.RequestException as exc:
            raise RenteonAPIError(f"POST {path} failed: {exc}") from exc
        self._raise_for_status(response, f"POST {path}")
        return response

    def _raise_for_status(self, response: requests.Response, label: str) -> None:
        if response.ok:
            return
        specific_exception_class = HTTP_EXCEPTION_MAP.get(response.status_code, RenteonServerError)
        message = f"{label} [{response.status_code}]: {response.text}"
        #logger.error(message)
        raise specific_exception_class(message, status_code=response.status_code)
