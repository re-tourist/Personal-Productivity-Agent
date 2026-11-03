"""Business HTTP status/error mapping; never return internal storage exceptions."""
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from productivity_agent.domain.tasks import IdempotencyConflict, VersionConflict


def install_business_errors(app):
    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse(status_code=400, content={"detail": "invalid_request"})


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, "task_not_found") from None
    except (VersionConflict, IdempotencyConflict):
        raise HTTPException(409, "conflict_read_again") from None
    except ValueError:
        raise HTTPException(400, "invalid_request") from None

def require_approval(body):
    if body.approved is not True:
        raise HTTPException(400, "explicit_approval_required")
