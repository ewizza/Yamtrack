"""Authentication helpers for the companion-app JSON API."""

import logging
from functools import wraps

from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from users.models import User

logger = logging.getLogger(__name__)


def token_auth(view_func):
    """Authenticate a request using the requesting user's API token.

    Expects an ``Authorization: Token <token>`` header, matching it against
    the same ``User.token`` field used for webhook/calendar auth elsewhere
    in the app. Attaches the resolved user to ``request.user`` on success,
    or returns a 401 response if the header is missing or the token doesn't
    match a user. Also exempts the view from CSRF checks, since a token,
    not a session cookie, is what proves the request is legitimate here.
    """

    @login_not_required
    @csrf_exempt
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme != "Token" or not token:
            logger.warning("API request missing or malformed Authorization header")
            return HttpResponse(status=401)

        try:
            user = User.objects.get(token=token)
        except ObjectDoesNotExist:
            logger.warning("API request with invalid token")
            return HttpResponse(status=401)

        request.user = user
        return view_func(request, *args, **kwargs)

    return wrapper
