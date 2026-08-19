"""Application-wide, user-safe error responses."""

from uuid import uuid4

from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException


HTTP_ERROR_CONTENT = {
    400: (
        "We could not process that request",
        "Please check the information you entered and try again.",
    ),
    403: (
        "You do not have access to this page",
        "Your account does not have permission to view this resource.",
    ),
    404: (
        "We could not find that page",
        "It may have been moved, deleted, or the link may be out of date.",
    ),
    405: (
        "That action is not available",
        "Please return to the previous page and try the action again.",
    ),
}


def _expects_json():
    """Keep API callers from receiving an HTML error document."""
    if request.is_json:
        return True
    if request.accept_mimetypes.best == "application/json":
        return True
    # The app's mutation requests use this header. GET requests that refresh a
    # report panel still expect HTML, so they intentionally remain HTML here.
    return (
        request.method != "GET"
        and request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def _error_response(status_code, title, message, reference_id=None):
    if _expects_json():
        payload = {"error": message, "status": status_code}
        if reference_id:
            payload["reference_id"] = reference_id
        return jsonify(payload), status_code

    return (
        render_template(
            "error_page.html",
            status_code=status_code,
            title=title,
            message=message,
            reference_id=reference_id,
        ),
        status_code,
    )


def register_error_handlers(app):
    """Register consistent browser and API error responses for the app."""

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        status_code = error.code or 500
        title, message = HTTP_ERROR_CONTENT.get(
            status_code,
            ("Something went wrong", "Please try again in a moment."),
        )
        return _error_response(status_code, title, message)

    @app.errorhandler(Exception)
    def handle_unexpected_exception(error):
        reference_id = uuid4().hex[:10].upper()
        app.logger.exception(
            "Unhandled application error [%s] for %s %s",
            reference_id,
            request.method,
            request.path,
        )
        return _error_response(
            500,
            "We hit an unexpected problem",
            "The issue has been recorded. Please try again shortly; if it keeps happening, share the reference code with support.",
            reference_id,
        )
