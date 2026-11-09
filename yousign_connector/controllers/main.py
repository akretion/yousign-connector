# Copyright 2018-2026 Akretion France (http://www.akretion.com/)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import hashlib
import hmac
from datetime import datetime
from logging import getLogger

from werkzeug.exceptions import BadRequest

from odoo import SUPERUSER_ID, tools
from odoo.api import Environment
from odoo.http import Controller, request, route
from odoo.modules.registry import Registry

logger = getLogger(__name__)


class WebHookBadRequest(BadRequest):
    pass


class YouSignController(Controller):
    @route(
        "/<db>/yousign/webhook",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def webhook(self, db, **kw):
        try:
            return self._webhook(db)
        except WebHookBadRequest as e:
            logger.warning("Yousign webhook rejected: %s", e.description)
            return request.make_json_response({"error": e.description}, status=400)

    def _webhook(self, dbname):
        secret = tools.config.get("yousign_secret", False)
        if not secret:
            raise WebHookBadRequest("No secret defined")

        # ## Headers
        # Content-Type:            application/json
        # X-Yousign-Signature-256: The sha256 signature of the raw body,
        #                          see Webhook Signature. (string)
        # X-Yousign-Retry:         The number of retry operated, see Delivery
        #                          Retry. (integer)
        # X-Yousign-Issued-At:     The moment when this specific webhook was
        #                          sent. (timestamp)
        # User-Agent:              Yousign Webhook Bot
        # ## check the signature
        # Yousign signs the raw request body (bytes as sent), so the HMAC
        # must be computed on it, never on a re-serialized JSON.
        signature = request.httprequest.headers.get("X-Yousign-Signature-256", "")
        if not signature:
            raise WebHookBadRequest("Missing X-Yousign-Signature-256 header")
        raw_body = request.httprequest.get_data()
        digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        computed_signature = f"sha256={digest}"
        if not hmac.compare_digest(signature, computed_signature):
            raise WebHookBadRequest("Wrong signature")

        try:
            data = request.get_json_data()
        except ValueError as e:
            raise WebHookBadRequest("Invalid JSON payload") from e
        logger.info("Webhook received:\n %s", data)

        # ## payload
        # {
        #   "event_id": "d09f0367-d80a-309c-a2ed-7083991fc564",
        #   "event_name": "signature_request.done",
        #   "event_time": "1348177752",
        #   "subscription_id": "d09f0367-d80a-309c-a2ed-7083991fc564",
        #   "subscription_description": "A great webhook",
        #   "sandbox": false,
        #   "data": { ... }
        # }
        try:
            funcname = "webhook_" + data["event_name"].replace(".", "_")
            event_time = data["event_time"]
            ys_identifier = data["data"]["signature_request"]["id"]
        except (KeyError, TypeError) as e:
            raise WebHookBadRequest(f"Missing key in payload: {e}") from e

        with Registry(dbname).cursor() as cr:
            env = Environment(cr, SUPERUSER_ID, {})
            Request = env["yousign.request"]
            if not hasattr(Request, funcname):
                raise WebHookBadRequest(f"The webhook {funcname} does not exist")

            odoo_request = Request.search([("ys_identifier", "=", ys_identifier)])
            if not odoo_request:
                raise WebHookBadRequest(f"No signature_request for id {ys_identifier}")
            # No user session here: use the language of the user who
            # created the request so chatter messages are translated.
            lang = odoo_request[:1].create_uid.lang
            if lang:
                odoo_request = odoo_request.with_context(lang=lang)

            try:
                res = getattr(odoo_request, funcname)(
                    datetime.fromtimestamp(float(event_time)), data["data"]
                )
            except Exception as e:
                cr.rollback()  # all exception force to rollback environ
                logger.exception("Yousign webhook %s failed", funcname)
                raise WebHookBadRequest(str(e)) from e
        return request.make_json_response(res)
