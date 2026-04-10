import simplejson
import werkzeug
from datetime import datetime
from odoo.http import Controller, route, request, JsonRequest, _logger
from odoo.api import Environment
from odoo import SUPERUSER_ID, tools, registry
from werkzeug.exceptions import BadRequest
from logging import getLogger

logger = getLogger(__name__)


class WebHookBadRequest(BadRequest):
    pass


class YouSignController(Controller):

    @route('/<db>/yousign/webhook', type='json', auth='public', methods=['POST'])
    def webhook(self, *a, **kw):
        
        secret = tools.config.get('yousign_secret', False)
        if not secret:
            return WebHookBadRequest("No secret defined")

        # ## Headers
        # Content-Type:            application/json
        # X-Yousign-Signature-256: The sha256 signature of the raw body,
        #                          see Webhook Signature. (string)
        # X-Yousign-Retry:         The number of retry operated, see Delivery
        #                          Retry. (integer)
        # X-Yousign-Issued-At:     The moment when this specific webhook was
        #                          sent. (timestamp)
        # User-Agent:              Yousign Webhook Bot
        data = request.jsonrequest
        logger.info("Webhook received:\n %s", data)
        # ## check the signature
        # signature = request.httprequest.headers.get(
        #     'X-Yousign-Signature-256', '')
        # if not signature:
        #     return WebHookBadRequest("The header has not a signature")

        # digest = hmac.new(
        #     secret.encode("utf-8"),
        #     simplejson.dumps(data).encode("utf-8"),
        #     hashlib.sha256
        # ).hexdigest()
        # computed_signature = "sha256=%s" % digest
        # matches = hmac.compare_digest(signature, computed_signature)
        # if not matches:
        #     return WebHookBadRequest("Wrong signature")

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
            funcname = "webhook_" + data['event_name'].replace('.', '_')
            event_time = data['event_time']
            data['data']['signature_request']['id']
        except KeyError as e:
            return WebHookBadRequest(str(e))

        dbname = request.endpoint_arguments['db']
        
        with registry(dbname).cursor() as cr:
            env = Environment(cr, SUPERUSER_ID, {})
            Request = env['yousign.request']
            if not hasattr(Request, funcname):
                return WebHookBadRequest(
                    "The webhook %s does not exist" % funcname)

            ys_identifier = data['data']['signature_request']['id']
            odoo_request = Request.search(
                [('ys_identifier', '=', ys_identifier)])
            if not odoo_request:
                return WebHookBadRequest(
                    "No signature_request for id %s" % ys_identifier)

            try:
                return getattr(odoo_request, funcname)(
                    datetime.fromtimestamp(float(event_time)), data['data'])
            except Exception as e:
                env.cr.rollback()  # all exception force to rollback environ
                return WebHookBadRequest(str(e))
