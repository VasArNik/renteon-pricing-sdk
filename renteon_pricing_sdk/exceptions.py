
# Exceptions 


class RenteonAPIError(Exception):
    """Base exception for all Renteon API errors. Carries the HTTP status code
    and the raw server message so nothing is lost."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RenteonBadRequestError(RenteonAPIError):
    """400,r equest was rejected by the server.
    """


class RenteonUnauthorizedError(RenteonAPIError):
    """401 , token is missing, expired, or invalid."""


class RenteonForbiddenError(RenteonAPIError):
    """403 , authenticated but not permitted to access this resource. e.g. 'User does not have required role.'"""


class RenteonNotFoundError(RenteonAPIError):
    """404 , the requested resource does not exist."""

class RenteonUnprocessableEntityError(RenteonAPIError):
    """422 , The request is invalid. Non existent Search Parameters
    Common causes: mismatched dates, unknown SIPP code, invalid pricelist ID, invalid OfficeID etc"""

class RenteonServerError(RenteonAPIError):
    """5xx,server-side failure, nothing you can do on the client."""

class RenteonAuthError(Exception):
    """Raised when credentials are missing or authentication fails. Used in token"""

HTTP_EXCEPTION_MAP: dict[int, type[RenteonAPIError]] = {
    400: RenteonBadRequestError,
    401: RenteonUnauthorizedError,
    403: RenteonForbiddenError,
    404: RenteonNotFoundError,
    422: RenteonUnprocessableEntityError,

}