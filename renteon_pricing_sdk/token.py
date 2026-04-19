import os
import hashlib
import base64
import threading
import requests
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv
from .exceptions import RenteonAuthError




class RenteonTokenManager:

    __slots__ = (
        "_username", "_password", "_client_id",
        "_secret", "_base_url", "_salt",
        "_token", "_token_expiry", "_lock",
    )

    _REQUIRED_VARS = (
        "RENTEON_EXAPI_USERNAME",
        "RENTEON_EXAPI_PASSWORD",
        "RENTEON_EXAPI_SECRET",
        "RENTEON_CLIENT_ID",
        "RENTEON_BASEURL",
    )

    def __init__(
        self,
        username:  str,
        password:  str,
        client_id: str,
        secret:    str,
        base_url:  str,
        salt:      str = "00000000",
    ) -> None:
        self._username  = username
        self._password  = password
        self._client_id = client_id
        self._secret    = secret
        self._base_url  = base_url.rstrip("/")
        self._salt      = salt

        self._token:        str | None      = None
        self._token_expiry: datetime | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "RenteonTokenManager":
        """Construct a manager from environment variables (or a .env file).

        Raises RenteonAuthError if any required variable is missing.
        """
        load_dotenv()

        missing = [var for var in cls._REQUIRED_VARS if not os.getenv(var)]
        if missing:
            raise RenteonAuthError(
                f"Missing required environment variable(s): {', '.join(missing)}"
            )

        return cls(
            username  = os.environ["RENTEON_EXAPI_USERNAME"],
            password  = os.environ["RENTEON_EXAPI_PASSWORD"],
            client_id = os.environ["RENTEON_CLIENT_ID"],
            secret    = os.environ["RENTEON_EXAPI_SECRET"],
            base_url  = os.environ["RENTEON_BASEURL"],
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def token(self) -> str:
        """Return a valid bearer token, fetching a new one if necessary."""
        with self._lock:
            if not self._token_is_valid():
                self._fetch_token()
            return self._token  # type: ignore[return-value]

    def __repr__(self) -> str:
        authenticated = self._token is not None and self._token_is_valid()
        return (
            f"RenteonTokenManager("
            f"base_url={self._base_url!r}, "
            f"authenticated={authenticated})"
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _token_is_valid(self) -> bool:
        if self._token is None or self._token_expiry is None:
            return False
        return datetime.now(timezone.utc) <= (self._token_expiry - timedelta(hours=2))

    def _build_signature(self) -> str:
        key = (
            self._username +
            self._salt     + self._secret +
            self._password +
            self._salt     + self._secret +
            self._client_id
        )
        digest = hashlib.sha512(key.encode("utf-8")).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _fetch_token(self) -> None:
        try:
            response = requests.post(
                url=f"{self._base_url}/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "password",
                    "username":   self._username,
                    "password":   self._password,
                    "client_id":  self._client_id,
                    "signature":  self._build_signature(),
                    "salt":       self._salt,
                },
            )
            if not response.ok:
                raise RenteonAuthError(
                    f"Token request failed: {response.status_code} — {response.text}"
                )
        except requests.RequestException as exc:
            raise RenteonAuthError(f"Token request failed: {exc}") from exc

        body = response.json()

        if "access_token" not in body or ".expires" not in body:
            raise RenteonAuthError(
                f"Unexpected token response — missing fields: {list(body.keys())}"
            )

        self._token        = body["access_token"]
        self._token_expiry = parsedate_to_datetime(body[".expires"])


if __name__ == "__main__":
    manager = RenteonTokenManager.from_env()
    print(repr(manager))
    print(manager.token)
