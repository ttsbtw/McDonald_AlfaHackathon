from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException


class APIError(HTTPException):
    def __init__(self, status, code, message, fields=None, headers=None):
        super().__init__(status, {"code": code, "message": message, "fields": fields or []}, headers)


def register_errors(app):
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        detail = error.detail if isinstance(error.detail, dict) else {
            "code": "HTTP_ERROR", "message": str(error.detail), "fields": [],
        }
        return JSONResponse(status_code=error.status_code, content={"error": detail}, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        fields = [{"field": ".".join(str(part) for part in item["loc"]),
                   "code": item["type"], "message": item["msg"]} for item in error.errors()]
        # Never echo invalid input: it can contain passwords or other private data.
        return JSONResponse(status_code=422, content={"error": {
            "code": "VALIDATION_ERROR", "message": "Проверьте поля запроса.", "fields": fields,
        }})

    @app.exception_handler(OperationalError)
    async def database_error(request: Request, error: OperationalError):
        return JSONResponse(status_code=503, content={"error": {
            "code": "DATABASE_UNAVAILABLE", "message": "База данных временно недоступна.", "fields": [],
        }})
