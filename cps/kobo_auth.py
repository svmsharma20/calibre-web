#!/usr/bin/env python
# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2018-2019 shavitmichael, OzzieIsaacs
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.


"""This module is used to control authentication/authorization of Kobo sync requests.
This module also includes research notes into the auth protocol used by Kobo devices.

Log-in:
When first booting a Kobo device the user must sign into a Kobo (or affiliate) account.
Upon successful sign-in, the user is redirected to 
    https://auth.kobobooks.com/CrossDomainSignIn?id=<some id>
which serves the following response:
    <script type='text/javascript'>location.href='kobo://UserAuthenticated?userId=<redacted>&userKey<redacted>&email=<redacted>&returnUrl=https%3a%2f%2fwww.kobo.com';</script>.
And triggers the insertion of a userKey into the device's User table.

IMPORTANT SECURITY CAUTION:
Together, the device's DeviceId and UserKey act as an *irrevocable* authentication 
token to most (if not all) Kobo APIs. In fact, in most cases only the UserKey is
required to authorize the API call.

Changing Kobo password *does not* invalidate user keys! This is apparently a known
issue for a few years now https://www.mobileread.com/forums/showpost.php?p=3476851&postcount=13
(although this poster hypothesised that Kobo could blacklist a DeviceId, many endpoints
will still grant access given the userkey.)

Official Kobo Store Api authorization:
* For most of the endpoints we care about (sync, metadata, tags, etc), the userKey is
passed in the x-kobo-userkey header, and is sufficient to authorize the API call.
* Some endpoints (e.g: AnnotationService) instead make use of Bearer tokens pass through
an authorization header. To get a BearerToken, the device makes a POST request to the
v1/auth/device endpoint with the secret UserKey and the device's DeviceId.
* The book download endpoint passes an auth token as a URL param instead of a header.

Our implementation:
For now, we rely on the official Kobo store's UserKey for authentication.
Once authenticated, we set the login cookie on the response that will be sent back for
the duration of the session to authorize subsequent API calls.
Ideally we'd only perform UserKey-based authentication for the v1/initialization or the
v1/device/auth call, however sessions don't always start with those calls.

Because of the irrevocable power granted by the key, we only ever store and compare a
hash of the key. To obtain their UserKey, a user can query the user table from the
.kobo/KoboReader.sqlite database found on their device.
This isn't exactly user friendly however.

Some possible alternatives that require more research:
 * Instead of having users query the device database to find out their UserKey, we could
 provide a list of recent Kobo sync attempts in the calibre-web UI for users to
 authenticate sync attempts (e.g: 'this was me' button).
 * We may be able to craft a sign-in flow with a redirect back to the CalibreWeb
 server containing the KoboStore's UserKey (if the same as the devices?). 
 * Can we create our own UserKey instead of relying on the real store's userkey?
  (Maybe using something like location.href=kobo://UserAuthenticated?userId=...?)
"""

from functools import wraps
from flask import request, make_response
from flask_login import login_user
from werkzeug.security import check_password_hash

from . import logger, ub, lm

USER_KEY_HEADER = "x-kobo-userkey"
USER_KEY_URL_PARAM = "kobo_userkey"

log = logger.create()


def disable_failed_auth_redirect_for_blueprint(bp):
    lm.blueprint_login_views[bp.name] = None


@lm.request_loader
def load_user_from_kobo_request(request):
    user_key = request.headers.get(USER_KEY_HEADER)
    if user_key:
        for user in (
            ub.session.query(ub.User).filter(ub.User.kobo_user_key_hash != "").all()
        ):
            if check_password_hash(str(user.kobo_user_key_hash), user_key):
                # The Kobo device won't preserve the cookie accross sessions, even if we
                # were to set remember_me=true.
                login_user(user)
                return user
    log.info("Received Kobo request without a recognizable UserKey.")
    return None