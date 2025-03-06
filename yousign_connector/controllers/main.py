import simplejson
import hmac
import hashlib
import werkzeug
from datetime import datetime
from openerp.http import Controller, route, request, JsonRequest, _logger
from openerp.api import Environment
from openerp.modules.registry import RegistryManager
from openerp import SUPERUSER_ID, tools
from werkzeug.exceptions import BadRequest
from logging import getLogger


logger = getLogger(__name__)


class WebHookBadRequest(BadRequest):
    pass


# Monkey patch of the _json_response
odoo_json_response = JsonRequest._json_response


def yousign_json_response(self, result=None, error=None):
    if result and isinstance(result, WebHookBadRequest):
        logger.warning(str(result))
        return result

    return odoo_json_response(self, result=result, error=error)


JsonRequest._json_response = yousign_json_response
# / Monkey patch of the _json_response


# Monkey patch of the _handle_exception
odoo_handle_exception = JsonRequest._handle_exception


def yousign_handle_exception(self, exception):
    if isinstance(exception, WebHookBadRequest):
        return exception

    return odoo_handle_exception(self, exception)


JsonRequest._handle_exception = yousign_handle_exception
# / Monkey patch of the _handle_exception


# Monkey patch of the __init__
def yousign_init(self, *args):
    super(JsonRequest, self).__init__(*args)

    self.jsonp_handler = None

    args = self.httprequest.args
    jsonp = args.get('jsonp')
    self.jsonp = jsonp
    request = None
    request_id = args.get('id')

    if jsonp and self.httprequest.method == 'POST':
        # jsonp 2 steps step1 POST: save call
        def handler():
            self.session['jsonp_request_%s' % (request_id,)] = self.httprequest.form['r']
            self.session.modified = True
            headers = [('Content-Type', 'text/plain; charset=utf-8')]
            r = werkzeug.wrappers.Response(request_id, headers=headers)
            return r
        self.jsonp_handler = handler
        return
    elif jsonp and args.get('r'):
        # jsonp method GET
        request = args.get('r')
    elif jsonp and request_id:
        # jsonp 2 steps step2 GET: run and return result
        request = self.session.pop('jsonp_request_%s' % (request_id,), '{}')
    else:
        # regular jsonrpc2
        request = self.httprequest.stream.read()

    # Read POST content or POST Form Data named "request"
    try:
        self.jsonrequest = simplejson.loads(request)
    except simplejson.JSONDecodeError:
        msg = 'Invalid JSON data: %r' % (request,)
        _logger.error('%s: %s', self.httprequest.path, msg)
        raise BadRequest(msg)

    self.params = dict(self.jsonrequest.get("params", {}))
    self.context = self.params.pop('context', dict(self.session.context))
    self.original_request = request  # need for signature check


JsonRequest.__init__ = yousign_init
# / Monkey patch of the __init__


class YouSignController(Controller):

    @route('/<db>/yousign/webhook', type='json', auth='none', methods=['post'])
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

        # ## check the signature
        signature = request.httprequest.headers.get(
            'X-Yousign-Signature-256', '').encode('utf-8')
        if not signature:
            return WebHookBadRequest("The header has not a signature")

        digest = hmac.new(
            secret.encode("utf-8"),
            request.original_request.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        computed_signature = "sha256=%s" % digest
        matches = hmac.compare_digest(signature, computed_signature)
        if not matches:
            return WebHookBadRequest("Wrong signature")

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

        db = request.endpoint_arguments['db']
        registry = RegistryManager.get(db)
        with registry.cursor() as cr:
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
