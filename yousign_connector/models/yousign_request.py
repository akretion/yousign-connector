# -*- coding: utf-8 -*-
# Copyright 2018-2020 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import api, fields, models, tools, _
from openerp.exceptions import Warning as UserError
from openerp.exceptions import ValidationError
from openerp.addons.email_template import email_template
from unidecode import unidecode
from StringIO import StringIO
from unidecode import unidecode_expect_nonascii
import logging
logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    logger.debug('Cannot import requests')
try:
    import PyPDF2
except ImportError:
    logger.debug('Cannot import PyPDF2')

TIMEOUT = 30

# Added features:
# . statut rejet
# . commentaire en cas de rejet


class YousignRequest(models.Model):
    _name = 'yousign.request'
    _description = 'Yousign Request'
    _order = 'id desc'
    _inherit = ['mail.thread']

    name = fields.Char(size=128)
    res_name = fields.Char(
        compute='_compute_res_name', string="Related Document Name",
        store=True, readonly=True)
    model = fields.Char(
        string='Related Document Model', select=True, readonly=True,
        track_visibility='onchange')
    res_id = fields.Integer(
        string='Related Document ID', select=True, readonly=True,
        track_visibility='onchange')
    ordered = fields.Boolean(string='Sign one after the other')
    init_mail_subject = fields.Char(
        'Init Mail Subject', readonly=True,
        size=150,
        states={'draft': [('readonly', False)]})
    init_mail_body = fields.Char(
        'Init Mail Body', readonly=True,
        size=500,
        states={'draft': [('readonly', False)]})
    lang = fields.Selection(
        '_lang_get', string='Language',
        readonly=True, states={'draft': [('readonly', False)]},
        track_visibility='onchange')
    attachment_ids = fields.Many2many(
        'ir.attachment', string='Documents to Sign',
        readonly=True, states={'draft': [('readonly', False)]})
    signed_attachment_ids = fields.Many2many(
        'ir.attachment', 'yousign_request_signed_attachment_rel',
        'request_id', 'attachment_id', string='Signed Documents',
        readonly=True)
    signatory_ids = fields.One2many(
        'yousign.request.signatory', 'parent_id',
        string='Signatories',
        readonly=True, states={'draft': [('readonly', False)]})
    notification_ids = fields.One2many(
        'yousign.request.notification', 'parent_id',
        string='E-mail Notifications',
        readonly=True, states={'draft': [('readonly', False)]})
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('signed', 'Signed'),
        ('archived', 'Archived'),
        ('cancel', 'Cancelled'),
        ], string='State', default='draft', readonly=True,
        track_visibility='onchange')
    sign_position = fields.Selection(
        [('top', 'Top'), ('bottom', 'Bottom')],
        string='Sign position', default='top')
    company_id = fields.Many2one(
        'res.company', string='Company', ondelete='cascade',
        readonly=True, states={'draft': [('readonly', False)]},
        track_visibility='onchange',
        default=lambda self: self.env['res.company']._company_default_get(
            'yousign.request'))
    ys_identifier = fields.Char(
        'Yousign ID', readonly=True, track_visibility='onchange')
    last_update = fields.Datetime(string='Last Status Update', readonly=True)
    remind_auto = fields.Boolean(
        string='Automatic Reminder',
        readonly=True, states={'draft': [('readonly', False)]})
    remind_mail_subject = fields.Char(
        'Reminder Mail Subject',
        size=150,
        readonly=True, states={'draft': [('readonly', False)]})
    remind_mail_body = fields.Char(
        'Reminder Mail Body',
        size=500,
        readonly=True, states={'draft': [('readonly', False)]})
    remind_interval = fields.Selection(
        [
            (1, '1 day'),
            (2, '2 days'),
            (7, '7 days'),
            (14, '14 days'),
        ],
        string='Remind Interval', default=2,
        readonly=True, states={'draft': [('readonly', False)]},
        help="Number of days between 2 auto-reminders by email.")
    remind_limit = fields.Integer(
        string='Remind Limit', default=10,
        readonly=True, states={'draft': [('readonly', False)]})

    _sql_constraints = [
        (
            'remind_interval_positive',
            'CHECK(remind_interval >= 0)',
            'The Remind Interval must be positive or null.'),
        (
            'remind_limit_positive',
            'CHECK(remind_limit >= 0)',
            'The Remind Limit must be positive or null.'),
        ]

    @api.multi
    @api.depends('model', 'res_id')
    def _compute_res_name(self):
        for req in self:
            name = 'None'
            if req.res_id and req.model:
                obj = self.env[req.model].browse(req.res_id)
                name = obj.display_name
            req.res_name = name

    @api.model
    def _lang_get(self):
        langs = self.env['res.lang'].search([])
        return [(lang.code, lang.name) for lang in langs]

    @api.model
    def default_get(self, fields_list):
        res = super(YousignRequest, self).default_get(fields_list)
        eto = self.env['email.template']
        iarxo = self.env['ir.actions.report.xml']
        iao = self.env['ir.attachment']
        yrto = self.env['yousign.request.template']
        model = self._context.get('active_model')
        res_id = self._context.get('active_id')
        if not model or not res_id:
            logger.debug(
                'No active_model or no active_id in context, so no '
                'no generation from yousign request template')
            return res
        if model == self._name:
            return res
        template = False
        if self._context.get('yousign_template_xmlid'):
            try:
                template = self.env.ref(
                    self._context['yousign_template_xmlid'])
            except Exception:
                pass
        if self._context.get('yousign_template_id'):
            try:
                template = yrto.browse(self._context['yousign_template_id'])
                logger.debug(
                    'Using yousign request template %s ID %d',
                    template.name, template.id)
            except Exception:
                pass
        if not template:
            templates = yrto.search([('model', '=', model)])
            if templates:
                template = templates[0]
        if not template:
            raise UserError(_(
                "No Yousign Request Template for model %s") % model)
        if model != template.model:
            raise UserError(_(
                "Wrong active_model (%s should be %s)")
                % (self._context.get('active_model'), template.model))
        source_obj = self.env[model].browse(int(res_id))
        signatory_ids = []
        for signatory in template.signatory_ids:
            signatory_vals = signatory.prepare_template2request(
                model, res_id)
            signatory_ids.append((0, 0, signatory_vals))
        notification_ids = []
        for notif in template.notification_ids:
            notif_vals = notif.prepare_template2request(model, res_id)
            notification_ids.append((0, 0, notif_vals))
        attachment_ids = []
        if template.report_id:
            report = template.report_id
            report_data_bin, filename_ext = iarxo.render_report(
                [res_id], report.report_name, {})

            full_filename = 'document_to_sign.%s' % filename_ext
            if report.download_filename:
                full_filename = email_template.mako_template_env\
                    .from_string(report.download_filename)\
                    .render({
                        'objects': source_obj,
                        'o': source_obj,
                        'object': source_obj,
                        'ext': report.report_type.replace('qweb-', ''),
                    })
            elif source_obj.display_name:
                tmp_filename = source_obj.display_name[:50]
                tmp_filename = tmp_filename.replace(' ', '_')
                tmp_filename = unidecode(tmp_filename)
                full_filename = '%s.%s' % (tmp_filename, filename_ext)
            attach_vals = {
                'name': full_filename,
                # 'res_id': Signature request is not created yet
                'res_model': self._name,
                'datas': report_data_bin.encode('base64'),
                'datas_fname': full_filename,
                }
            attach = iao.create(attach_vals)
            attachment_ids.append((6, 0, [attach.id]))
        lang = eto.render_template_batch(
            template.lang, model, [res_id])[res_id]
        if lang:
            template = template.with_context(lang=lang)
        dyn_fields = {
            'init_mail_subject': template.init_mail_subject,
            'init_mail_body': template.init_mail_body,
            'remind_mail_subject': template.remind_mail_subject,
            'remind_mail_body': template.remind_mail_body,
            }
        for field_name, field_content in dyn_fields.iteritems():
            dyn_fields[field_name] = eto.render_template_batch(
                dyn_fields[field_name], model, [res_id])[res_id]
        res.update(dyn_fields)
        res.update(template.prepare_template2request())
        res.update({
            'name': source_obj.display_name,
            'model': model,
            'res_id': res_id,
            'lang': lang,
            'signatory_ids': signatory_ids,
            'notification_ids': notification_ids,
            'attachment_ids': attachment_ids,
            })
        return res

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code(
                'yousign.request')
        return super(YousignRequest, self).create(vals)

    def get_source_object(self):
        self.ensure_one()
        if self.model and self.res_id:
            src_obj = self.env[self.model].browse(self.res_id)
            return src_obj
        else:
            return None

    def get_source_object_with_chatter(self):
        self.ensure_one()
        src_obj = self.get_source_object()
        if src_obj and hasattr(src_obj, 'message_post'):
            return src_obj
        else:
            return None

    @api.model
    def yousign_init(self, has_file=False):
        apikey = tools.config.get('yousign_apikey', False)
        environment = tools.config.get('yousign_envir', 'demo')
        if not apikey or not environment:
            raise UserError(_(
                "One of the Yousign config parameters is missing in the Odoo "
                "server config file."))

        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'authorization': 'Bearer %s' % apikey,
        }
        if has_file:
            del headers['content-type']

        if environment == 'prod':
            url_base = 'https://api.yousign.app/v3'
        else:
            url_base = 'https://api-sandbox.yousign.app/v3'

        return (url_base, headers)

    @api.model
    def yousign_request(
            self, method, url, expected_status_code=201,
            json=None, data=None, files=None, return_raw=False, raise_if_ko=True):
        url_base, headers = self.yousign_init(has_file=bool(True if files else False))
        full_url = url_base + url
        logger.info(
            'Sending %s request on %s. Expecting status code %d.',
            method, full_url, expected_status_code)
        logger.debug('JSON data sent: %s', json)
        logger.debug('data data sent: %s', data)
        logger.debug('files data sent: %s', files)

        try:
            res = requests.request(
                method, full_url, headers=headers, json=json, data=data, files=files,
                timeout=TIMEOUT)
        except requests.exceptions.ConnectionError as e:
            logger.error("Connection to %s failed. Error: %s", full_url, e)
            if raise_if_ko:
                raise UserError(
                    _(
                        "Connection to %s failed. "
                        "Check the Internet connection of the Odoo server.\n\n"
                        "Error details: %s"
                    ) % (full_url, e))
            return None
        except requests.exceptions.RequestException as e:
            logger.error("%s request %s failed. Error: %s", method, full_url, e)
            if raise_if_ko:
                raise UserError(
                    _(
                        "Technical failure when trying to connect to Yousign.\n\n"
                        "Error details: URL %s method %s. Error: %s"
                    )
                    % (full_url, method, e))
            return None
        if res.status_code != expected_status_code:
            logger.error('Status code received: %s.', res.status_code)
            try:
                res_json = res.json()
            except Exception:
                res_json = {}
            logger.error(
                "HTTP %s request on %s returned HTTP Code %s (%s was expected). "
                "Error message: %s (%s).", method, full_url, res.status_code,
                expected_status_code, res_json.get('type'),
                res_json.get('detail', 'no detail'))
            if raise_if_ko:
                raise UserError(_(
                    "The HTTP %s request on Yousign webservice %s returned status "
                    "code %d whereas %d was expected. Error message: %s (%s).")
                    % (method, full_url, res.status_code,
                       expected_status_code, res_json.get('title'),
                        res_json.get('detail', _('no detail'))))
            return None

        if return_raw:
            return res
        res_json = res.json()
        logger.debug('JSON webservice answer: %s', res_json)
        return res_json

    def check_has_ys_identidifier(self):
        if not self.ys_identifier:
            raise UserError(_('No YS request identifier found'))

    def api_post_signature_requests(self):
        json = {
            'name': self.name,
            'delivery_mode': 'email',
            # timezone  TODO
            "audit_trail_locale": self.lang and self.lang[:2] or 'fr',
            "ordered_signers": self.ordered,
        }
        if self.remind_auto:
            json["reminder_settings"] = {
                "interval_in_days": self.remind_interval,
                "max_occurrences": self.remind_limit,
            }
        return self.yousign_request(
            'POST',
            '/signature_requests',
            201,
            json=json,
        )

    def api_get_signature_requests(self, raise_if_ko=True):
        self.check_has_ys_identidifier()
        return self.yousign_request(
            'GET',
            '/signature_requests/%s' % self.ys_identifier,
            200,
            raise_if_ko=raise_if_ko,
        )

    def api_cancel_signature_requests(self):
        self.check_has_ys_identidifier()
        json = {
            "reason": "other",
            "custom_note": "cancel by %s" % self.env.user.partner_id.name,
        }
        return self.yousign_request(
            'POST',
            '/signature_requests/%s/cancel' % self.ys_identifier,
            201,
            json=json,
            raise_if_ko=True,
        )

    def api_activate_signature_requests(self):
        self.check_has_ys_identidifier()
        return self.yousign_request(
            'POST',
            '/signature_requests/%s/activate' % self.ys_identifier,
            201,
        )

    def api_post_document(self, attachment):
        self.check_has_ys_identidifier()
        filename = unidecode_expect_nonascii(
            attachment.datas_fname or attachment.name
        )
        if len(filename) >= 128:  # max size for yousign
            filename = filename[:118] + '[...].pdf'

        pdf_content = attachment.datas.decode('base64')
        pdf_file = StringIO(pdf_content)
        try:
            pdf = PyPDF2.PdfFileReader(pdf_file)
        except PyPDF2.utils.PdfReadError:
            raise UserError(_(
                "File to sign '%s' is not a valid PDF file. You "
                "must convert it to PDF before including it in a "
                "Yousign request.") % filename)
        num_pages = pdf.getNumPages()
        logger.info('PDF %s has %d pages', filename, num_pages)

        data = {
            "nature": "signable_document",
        }
        files = {
            'file': (
                filename,
                pdf_content,
                'application/pdf'
            )
        }
        res = self.yousign_request(
            'POST',
            '/signature_requests/%s/documents' % self.ys_identifier,
            201,
            data=data,
            files=files,
        )
        return (res['id'], num_pages)

    def api_post_signer(self, signer, rank, documents):
        self.check_has_ys_identidifier()
        if not signer.lastname:
            raise UserError(_(
                "Missing lastname on one of the signatories of request %s")
                % self.display_name)

        if not signer.firstname:
            raise UserError(_(
                "Missing firstname on signatory '%s'" % signer.lastname))

        if not signer.email:
            raise UserError(_(
                "Missing email on the signatory '%s'") % signer.lastname)

        if not signer.mobile and signer.auth_mode == 'otp_sms':
            raise UserError(_(
                "Missing mobile phone number on signatory '%s'.")
                % signer.lastname)

        json = {
            "custom_text": {
                "request_subject": self.init_mail_subject,
                "request_body": self.init_mail_body,
            },
            "info": {
                "locale": self.lang and self.lang[:2] or 'fr',
                "first_name": signer.firstname and signer.firstname.strip() or '',
                "last_name": signer.lastname and signer.lastname.strip(),
                "email": signer.email.strip(),
                "phone_number": signer.mobile and signer.mobile.replace(' ', '') or ''
            },
            "signature_level": "electronic_signature",
            "fields": [],
            "signature_authentication_mode": signer.auth_mode
        }
        if not json['info']['phone_number']:
            json['info']['phone_number'] = '+33699089246'

        if self.remind_mail_subject:
            json['custom_text']['reminder_subject'] = self.remind_mail_subject

        if self.remind_mail_body:
            json['custom_text']['reminder_body'] = self.remind_mail_body

        x, y, width, height = self.signature_position(rank)
        for document_id, num_page in documents:
            json['fields'].append({
                "document_id": document_id,
                "type": "signature",
                "page": num_page,
                "x": x,
                "y": y,
                "height": height,
                "width": width,
            })
            if signer.mention_top:
                json['fields'].append({
                    "document_id": document_id,
                    "type": "mention",
                    "page": num_page,
                    "x": x,
                    "y": y - height,
                    "mention": signer.mention_top,
                })
            if signer.mention_bottom:
                json['fields'].append({
                    "document_id": document_id,
                    "type": "mention",
                    "page": num_page,
                    "x": x,
                    "y": y + height,
                    "mention": signer.mention_bottom,
                })

        res = self.yousign_request(
            'POST',
            '/signature_requests/%s/signers' % self.ys_identifier,
            201,
            json=json,
        )
        signer.write({
            'state': 'pending',
            'ys_identifier': res['id'],
        })

    def api_get_signer(self, signer, raise_if_ko=True):
        ystate2ostate = {
            'initiated': 'draft',
            'declined': 'refused',
            "notified": 'pending',
            'verified': 'verified',
            'processing': 'processing',
            'consent_given': 'consent_given',
            'signed': 'signed',
            'aborted': 'aborted',
            'error': 'error',
        }
        if signer.state == 'signed':
            return True

        if not signer.ys_identifier:
            logger.warning(
                'Signer ID %s has no YS identifier', signer.id)
            return False

        res = self.yousign_request(
            'GET',
            '/signature_requests/%s/signers/%s' % (
                self.ys_identifier,
                signer.ys_identifier,
            ),
            200,
            raise_if_ko=raise_if_ko,
        )
        if res is None:
            logger.warning('Skipping YS req %s ID %d', self.name, self.id)
            return False

        ystate = res.get('status')
        if ystate not in ystate2ostate:
            logger.warning(
                'Bad state value for member ID %d: %s',
                signer.id, ystate)
            return False

        ostate = ystate2ostate[ystate]
        signed = False
        signature_date = None
        if ostate == "signed":
            signed = True
            res = self.yousign_request(
                'GET',
                '/signature_requests/%s/signers/%s/audit_trails' % (
                    self.ys_identifier,
                    signer.ys_identifier,
                ),
                200,
                raise_if_ko=raise_if_ko,
            )
            signature_date = res["signer"]["signature_process_completed_at"]

        signer.write({
            'state': ostate,
            'signature_date': signature_date,
        })
        return signed

    def api_dowload_document(self, document_id, raise_if_ko=True):
        self.check_has_ys_identidifier()
        doc_url = '/signature_requests/%s/documents/%s'
        download_url = doc_url + '/download'
        document = self.yousign_request(
            'GET',
            doc_url % (self.ys_identifier, document_id),
            200,
            raise_if_ko=raise_if_ko
        )
        download = self.yousign_request(
            'GET',
            download_url % (self.ys_identifier, document_id),
            200,
            return_raw=True,
            raise_if_ko=raise_if_ko
        )
        return document['filename'], download

    @api.multi
    def webhook_signature_request_done(self, atDate, data):
        self.ensure_one()

        self.write({
            'last_update': atDate,
            'state': 'signed',
        })
        logger.info("Yousign request %s switched to signed state", self.ys_identifier)

        src_obj = self.get_source_object_with_chatter()
        if src_obj:
            # for v10, add link to request in message
            src_obj.suspend_security().message_post(_(
                "Yousign request <b>%s</b> has been signed by all "
                "signatories") % self.name)
            self.signed_hook(src_obj)

        docs_to_sign_count = len(self.attachment_ids)
        signed_filenames = [
            att.datas_fname for att in self.signed_attachment_ids]
        if self.res_id and self.model:
            res_model = self.model
            res_id = self.res_id
        else:
            res_model = self._name
            res_id = self.id

        for document in data['signature_request']['documents']:
            if document["nature"] != "signable_document":
                continue

            document_id = document['id']
            original_filename, dl = self.api_dowload_document(
                document_id, raise_if_ko=False)
            if not original_filename or not dl:
                continue

            if (
                original_filename[-4:] and
                original_filename[-4:].lower() == '.pdf'
            ):
                signed_filename = '%s_signed.pdf' % original_filename[:-4]
            else:
                signed_filename = original_filename
            if signed_filename in signed_filenames:
                logger.debug(
                    'File %s is already attached as '
                    'signed_attachment_ids', signed_filename)
                continue

            attach = self.env['ir.attachment'].create({
                'name': signed_filename,
                'res_id': res_id,
                'res_model': res_model,
                'datas': dl.content.encode('base64'),
                'datas_fname': signed_filename,
                })
            self.signed_attachment_ids = [(4, attach.id)]
            signed_filenames.append(signed_filename)
            logger.info(
                'Signed file %s attached on %s ID %d',
                signed_filename, res_model, res_id)

        if len(signed_filenames) == docs_to_sign_count:
            self.state = 'archived'
            self.message_post(_(
                "%d signed document(s) are now attached. "
                "Request %s is archived")
                % (len(signed_filenames), self.name))
            logger.info(
                "Yousign request %s switched to archived state",
                self.ys_identifier)

        return self.read(['state', 'last_update', 'ys_identifier'])[0]

    @api.multi
    def webhook_signature_request_expired(self, atDate, data):
        return self.webhook_signature_request_declined(atDate, data)

    @api.multi
    def webhook_signature_request_declined(self, atDate, data):
        self.ensure_one()

        self.write({
            'last_update': atDate,
            'state': 'cancel',
        })
        logger.info("Yousign request %s switched to canceled state",
                    self.ys_identifier)
        return self.read(['state', 'last_update', 'ys_identifier'])[0]

    @api.multi
    def webhook_signer_done(self, atDate, data):
        self.ensure_one()
        signer = self.env['yousign.request.signatory'].search([
            ('ys_identifier', '=', data['signer']['id'])
        ])
        signer.ensure_one()
        signer.write({
            'state': 'signed',
            'signature_date': atDate,
        })
        logger.info("Yousign signer %s switched to signed state",
                    self.ys_identifier)
        return signer.read(['state', 'signature_date', 'ys_identifier'])[0]

    @api.multi
    def webhook_signer_declined(self, atDate, data):
        self.ensure_one()
        signer = self.env['yousign.request.signatory'].search([
            ('ys_identifier', '=', data['signer']['id'])
        ])
        signer.ensure_one()
        signer.write({
            'state': 'refused',
            'signature_date': atDate,
        })
        logger.info("Yousign signer %s switched to refused state",
                    self.ys_identifier)
        return signer.read(['state', 'signature_date', 'ys_identifier'])[0]

    @api.multi
    def name_get(self):
        res = []
        for req in self:
            name = req.name
            if req.res_name:
                name = u'%s (%s)' % (name, req.res_name)
            res.append((req.id, name))
        return res

    @api.model
    def signature_position(self, signatory_rank):
        # sign_position is passed as parameter because this method
        # is decorated by api.model

        # return "x,y,width,height". the origin is the top/left of the page
        TOPRANK2POSITION = {
            1: (70, 173, 215, 50),
            2: (310, 173, 215, 50),
            3: (70, 203, 215, 50),
            4: (310, 203, 215, 50),
        }
        BOTTOMRANK2POSITION = {
            1: (95, 594, 150, 50),  # width = 150 - height = 50
            2: (330, 594, 150, 50),
            3: (95, 637, 150, 50),
            4: (330, 637, 150, 50),
        }
        rank2position = (
            TOPRANK2POSITION
            if self.sign_position == 'top'
            else BOTTOMRANK2POSITION
        )

        if signatory_rank not in rank2position:
            logger.warning(
                'Requesting signature position for undeclared '
                'signatory_rank %d',
                signatory_rank
            )

        return rank2position.get(signatory_rank, (56, 392, 140, 72))

    @api.one
    def send(self):
        logger.info('Start to send YS request %s ID %d', self.name, self.id)
        if not self.signatory_ids:
            raise UserError(_(
                "There are no signatories on request %s!") % self.display_name)
        if not self.attachment_ids:
            raise UserError(_(
                "There are no documents to sign on request %s!")
                % self.display_name)
        if not self.init_mail_subject:
            raise UserError(_(
                "Missing init mail subject on request %s.")
                % self.display_name)
        if not self.init_mail_body:
            raise UserError(_(
                "Missing init mail body on request %s.") % self.display_name)

        rank = 0
        sign_request = self.api_post_signature_requests()

        if sign_request.get('status') != 'draft':
            raise UserError(_('Wrong status, should be draft'))
        if not sign_request.get('id'):
            raise UserError(_('Missing ID'))

        self.ys_identifier = sign_request['id']

        documents = []
        for attachment in self.attachment_ids:
            documents.append(self.api_post_document(attachment))

        for signat in self.signatory_ids:
            rank += 1
            self.api_post_signer(signat, rank, documents)

        try:
            logger.debug('Start YS initSign on req ID %d', self.id)
            self.api_activate_signature_requests()
        except Exception as e:
            err_msg = str(e).decode('utf-8')
            logger.error(
                'YS initSign failed on req ID %d with error %s',
                self.id, err_msg)
            raise UserError(_(
                "Failure when sending the signing request %s to "
                "Yousign.\n\n"
                "Error: %s") % (self.display_name, err_msg))

        self.state = 'sent'

        src_obj = self.get_source_object_with_chatter()
        if src_obj:
            # for v10, add link to request in message
            src_obj.suspend_security().message_post(_(
                "Yousign request <b>%s</b> generated with %d signatories")
                % (self.name, len(self.signatory_ids)))
        return

    @api.multi
    def cancel(self):
        for req in self:
            if req.state == 'sent' and req.ys_identifier:
                self.api_cancel_signature_requests()
                logger.info(
                    'Yousign request %s ID %s successfully cancelled.',
                    req.name, req.id)
                req.message_post(_(
                    "Request successfully cancelled via Yousign "
                    "webservices."))
        self.write({'state': 'cancel'})

    @api.multi
    def update_status(self, raise_if_ko=True):
        now = fields.Datetime.now()
        for req in self.filtered(lambda x: x.state == 'sent'):
            logger.info(
                'Start getInfosFromSignatureDemand request on YS req %s ID %d',
                req.name, req.id)
            signed_state = []
            for signer in req.signatory_ids:
                signed_state.append(req.api_get_signer(
                    signer, raise_if_ko=raise_if_ko))

            vals = {'last_update': now}
            if all(signed_state):
                vals['state'] = 'signed'
                logger.info(
                    'Yousign request %s switched to signed state', req.name)
                src_obj = req.get_source_object_with_chatter()
                if src_obj:
                    # for v10, add link to request in message
                    src_obj.suspend_security().message_post(_(
                        "Yousign request <b>%s</b> has been signed by all "
                        "signatories") % req.name)
                    req.signed_hook(src_obj)
            req.write(vals)

    @api.multi
    def signed_hook(self, source_recordset):
        '''Designed to be inherited by custom modules'''
        self.ensure_one()
        return

    @api.model
    def cron_update(self):
        # Filter-out the YS requests of the old-API plateform
        domain_base = [('ys_identifier', '!=', False)]

        requests_to_archive = self.search(
            domain_base + [('state', '=', 'signed')], limit=None)
        for request in requests_to_archive:
            request.archive(raise_if_ko=False)

        requests_to_update = self.search(
            domain_base + [('state', '=', 'sent')], limit=None)
        for request in requests_to_update:
            request.update_status(raise_if_ko=False)

    @api.multi
    def archive(self, raise_if_ko=True):
        for req in self.filtered(
                lambda x: x.state == 'signed' and x.ys_identifier):
            logger.info(
                "Getting signed files on Yousign request %s ID %s",
                req.name, req.id)
            docs_to_sign_count = len(req.attachment_ids)
            if not docs_to_sign_count:
                logger.warning(
                    "Skip Yousign request %s ID %s: no documents to sign, "
                    "so nothing to archive", req.name, req.id)

            res = req.api_get_signature_requests(raise_if_ko=raise_if_ko)
            if res is None:
                logger.warning("Skipping Yousign request %s ID %s", req.name, req.id)
                continue

            if not res.get('documents'):
                continue

            signed_filenames = [
                att.datas_fname for att in req.signed_attachment_ids]
            if req.res_id and req.model:
                res_model = req.model
                res_id = req.res_id
            else:
                res_model = self._name
                res_id = req.id

            for document in res['documents']:
                if document["nature"] != "signable_document":
                    continue

                document_id = document['id']
                original_filename, dl = req.api_dowload_document(
                    document_id, raise_if_ko=raise_if_ko)
                if dl is None:
                    logger.warning(
                        "Skipping Yousign request %s ID %s due to download failure",
                        req.name, req.id)
                    continue

                logger.debug("original_filename=%s", original_filename)
                if original_filename:
                    if (
                        original_filename[-4:] and
                        original_filename[-4:].lower() == '.pdf'
                    ):
                        signed_filename = '%s_signed.pdf' % original_filename[:-4]
                    else:
                        signed_filename = original_filename
                    if signed_filename in signed_filenames:
                        logger.debug(
                            'File %s is already attached as '
                            'signed_attachment_ids', signed_filename)
                        continue
                    attach = self.env['ir.attachment'].create({
                        'name': signed_filename,
                        'res_id': res_id,
                        'res_model': res_model,
                        'datas': dl.content.encode('base64'),
                        'datas_fname': signed_filename,
                        })
                    req.signed_attachment_ids = [(4, attach.id)]
                    signed_filenames.append(signed_filename)
                    logger.info(
                        'Signed file %s attached on %s ID %d',
                        signed_filename, res_model, res_id)

            if len(signed_filenames) == docs_to_sign_count:
                req.state = 'archived'
                req.message_post(_(
                    "%d signed document(s) are now attached. "
                    "Request %s is archived")
                    % (len(signed_filenames), req.name))

        return


class YousignRequestSignatory(models.Model):
    _name = 'yousign.request.signatory'
    _order = 'parent_id, sequence'
    _inherit = ['phone.common']
    _phone_fields = ['mobile']
    _partner_field = 'partner_id'
    _country_field = None
    _rec_name = 'lastname'

    parent_id = fields.Many2one(
        'yousign.request', string='Request', ondelete='cascade')
    sequence = fields.Integer()
    partner_id = fields.Many2one('res.partner', 'Partner', ondelete='restrict')
    firstname = fields.Char(size=255)
    lastname = fields.Char(size=255)
    email = fields.Char('E-mail')
    mobile = fields.Char('Mobile')
    auth_mode = fields.Selection([
        ('otp_sms', 'SMS'),
        ('otp_email', 'E-Mail'),
        ('no_otp', 'No OTP'),
        ], default='otp_sms', string='Authentication Mode', required=True,
        help='Authentication mode used for the signer')
    mention_top = fields.Char(string='Top Mention')
    mention_bottom = fields.Char(string='Bottom Mention')
    ys_identifier = fields.Char('Yousign ID', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('signed', 'Signed'),
        ('refused', 'Refused'),
        ('verified', 'Verified'),
        ('processing', 'Processing'),
        ('consent_given', 'Consent given'),
        ('aborted', 'Aborted'),
        ('error', 'Error'),
        ], string='Signature Status', readonly=True, default='draft')
    comment = fields.Text(string='Comment')  # TODO
    signature_date = fields.Date(string='Signature Date', readonly=True)  # no signature date

    def create(self, cr, uid, vals, context=None):
        vals_reformated = self._generic_reformat_phonenumbers(
            cr, uid, None, vals, context=context)
        return super(YousignRequestSignatory, self).create(
            cr, uid, vals_reformated, context=context)

    def write(self, cr, uid, ids, vals, context=None):
        vals_reformated = self._generic_reformat_phonenumbers(
            cr, uid, ids, vals, context=context)
        return super(YousignRequestSignatory, self).write(
            cr, uid, ids, vals_reformated, context=context)

    @api.onchange('partner_id')
    def partner_id_change(self):
        if self.partner_id:
            self.email = self.partner_id.email or False
            self.mobile = self.partner_id.mobile
            if (
                    hasattr(self.partner_id, 'firstname') and
                    not self.partner_id.is_company):
                self.firstname = self.partner_id.firstname
                self.lastname = self.partner_id.lastname
            else:
                self.firstname = False
                self.lastname = self.partner_id.name


class YousignRequestNotification(models.Model):
    _name = 'yousign.request.notification'
    _description = 'Notifications of Yousign Request'

    parent_id = fields.Many2one(
        'yousign.request', string='Request', ondelete='cascade')
    notif_type = fields.Selection(
        '_notif_type_selection', string='Notification Type', required=True)
    creator = fields.Boolean(string='Notify Creator')
    members = fields.Boolean(string='Notify Members')
    subscribers = fields.Boolean(string='Notify Subscribers')
    partner_ids = fields.Many2many(
        'res.partner', string='Partners to Notify',
        domain=[('email', '!=', False)])
    subject = fields.Char(required=True)
    body = fields.Html(required=True)

    _sql_constraints = [(
        'parent_type_uniq',
        'unique(parent_id, notif_type)',
        'This notification type already exists for this Yousign request!')]

    @api.model
    def _notif_type_selection(self):
        return [
            ('procedure.started', 'Procedure created'),
            ('procedure.finished', 'Procedure finished'),
            ('procedure.refused', 'Procedure refused'),
            ('procedure.expired', 'Procedure expired'),
            ('member.finished', 'Member has signed'),
            ('comment.created', 'Someone commented'),
        ]

    @api.constrains('creator', 'members', 'subscribers', 'partner_ids')
    def _notif_check(self):
        for notif in self:
            if (
                    not notif.creator and
                    not notif.members and
                    not notif.subscribers and
                    not notif.partner_ids):
                raise ValidationError(_(
                    "You must select who should be notified."))
