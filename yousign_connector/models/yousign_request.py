# Copyright 2018-2024 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.phone_validation.tools import phone_validation
from odoo.tools.safe_eval import safe_eval, time
from unidecode import unidecode
from io import BytesIO
# from pprint import pprint
import re
import logging
logger = logging.getLogger(__name__)

try:
    import requests
except (ImportError, IOError) as err:
    logger.debug('Cannot import requests')
    logger.debug(err)
try:
    import pypdf
except (ImportError, IOError) as err:
    logger.debug('Cannot import pypdf')
    logger.debug(err)

TIMEOUT = 30

# ROADMAP:
# POST /consent_processes + POST /consent_process_values

# Added features:
# . statut rejet
# . commentaire en cas de rejet
# . ordered
# . mention, mention2


class YousignRequest(models.Model):
    _name = 'yousign.request'
    _description = 'Yousign Request'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mail.render.mixin']

    name = fields.Char(default=lambda self: _('New'))
    res_name = fields.Char(
        compute='_compute_res_name', string="Related Document Name", store=True)
    model = fields.Char(
        string='Related Document Model', index=True, readonly=True,
        tracking=True)
    res_id = fields.Integer(
        string='Related Document ID', index=True, readonly=True,
        tracking=True)
    ordered = fields.Boolean(
        string='Sign One after the Other',
        readonly=True, states={'draft': [('readonly', False)]})
    init_mail_subject = fields.Char(
        'Init Mail Subject', readonly=True,
        states={'draft': [('readonly', False)]})
    init_mail_body = fields.Html(
        'Init Mail Body', readonly=True,
        states={'draft': [('readonly', False)]})
    lang = fields.Selection(
        '_lang_get', string='Language',
        readonly=True, states={'draft': [('readonly', False)]},
        tracking=True)
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
        tracking=True)
    sign_position = fields.Selection(
        [('top', 'Top'), ('bottom', 'Bottom')],
        string='Sign Position', default='top',
        readonly=True, states={'draft': [('readonly', False)]})
    company_id = fields.Many2one(
        'res.company', string='Company', ondelete='cascade',
        readonly=True, states={'draft': [('readonly', False)]},
        tracking=True,
        default=lambda self: self.env.company)
    ys_identifier = fields.Char(
        string='Yousign ID', readonly=True, tracking=True)
    last_update = fields.Datetime(string='Last Status Update', readonly=True)
    remind_auto = fields.Boolean(
        string='Automatic Reminder',
        readonly=True, states={'draft': [('readonly', False)]})
    remind_mail_subject = fields.Char(
        string='Reminder Mail Subject',
        readonly=True, states={'draft': [('readonly', False)]})
    remind_mail_body = fields.Html(
        string='Reminder Mail Body',
        readonly=True, states={'draft': [('readonly', False)]})
    remind_interval = fields.Integer(
        string='Remind Interval', default=3,
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
        res = self.env['res.lang'].get_installed()
        return res

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
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
                "No Yousign Request Template for model '%s'.") % model)
        # print "model=%s, res_id=%s" % (model, res_id)
        if model != template.model:
            raise UserError(_(
                "Wrong active_model (%(ctx_model)s should be %(template_model)s)",
                ctx_model=self._context.get('active_model'), template_model=template.model))
        source_obj = self.env[model].browse(int(res_id))
        signatory_ids = []
        for signatory in template.signatory_ids:
            signatory_vals = signatory._prepare_template2request(
                model, res_id)
            signatory_ids.append((0, 0, signatory_vals))
        notification_ids = []
        for notif in template.notification_ids:
            notif_vals = notif._prepare_template2request(model, res_id)
            notification_ids.append((0, 0, notif_vals))
        attachment_ids = []
        if template.report_id:
            report = template.report_id
            report_data_bin, filename_ext = report._render([res_id])

            full_filename = 'document_to_sign.%s' % filename_ext
            if report.print_report_name:
                full_filename = safe_eval(report.print_report_name, {'object': source_obj, 'time': time})
            elif source_obj.display_name:
                tmp_filename = source_obj.display_name[:50]
                tmp_filename = tmp_filename.replace(' ', '_')
                tmp_filename = unidecode(tmp_filename)
                full_filename = '%s.%s' % (tmp_filename, filename_ext)
            attach_vals = {
                'name': full_filename,
                # 'res_id': Signature request is not created yet
                'res_model': self._name,
                'raw': report_data_bin,
                }
            attach = iao.create(attach_vals)
            attachment_ids.append((6, 0, [attach.id]))
        lang = self._render_template(
            template.lang, model, [res_id])[res_id]
        if lang:
            template = template.with_context(lang=lang)
        dyn_fields = {
            'init_mail_subject': template.init_mail_subject,
            'init_mail_body': template.init_mail_body,
            'remind_mail_subject': template.remind_mail_subject,
            'remind_mail_body': template.remind_mail_body,
            }
        for field_name, field_content in dyn_fields.items():
            dyn_fields[field_name] = self._render_template(
                dyn_fields[field_name], model, [res_id])[res_id]
        res.update(dyn_fields)
        res.update(template._prepare_template2request())
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'company_id' in vals:
                self = self.with_company(vals['company_id'])
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'yousign.request') or _('New')
        return super().create(vals_list)

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
    def yousign_init(self):
        apikey = tools.config.get('yousign_apikey', False)
        environment = tools.config.get('running_env', 'test')
        if not apikey or not environment:
            raise UserError(_(
                "One of the Yousign config parameters is missing in the Odoo "
                "server config file."))

        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' % apikey,
        }
        if environment == 'prod':
            url_base = 'https://api.yousign.com'
        else:
            url_base = 'https://staging-api.yousign.com'

        return (url_base, headers)

    @api.model
    def yousign_request(
            self, method, url, expected_status_code=201,
            json=None, return_raw=False, raise_if_ko=True):
        url_base, headers = self.yousign_init()
        full_url = url_base + url
        logger.info(
            'Sending %s request on %s. Expecting status code %d.',
            method, full_url, expected_status_code)
        logger.debug('JSON data sent: %s', json)
        try:
            res = requests.request(
                method, full_url, headers=headers, json=json, timeout=TIMEOUT)
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
                expected_status_code, res_json.get('error'),
                res_json.get('error_description', 'no detail'))
            if raise_if_ko:
                raise UserError(_(
                    "The HTTP %s request on Yousign webservice %s returned status "
                    "code %d whereas %d was expected. Error message: %s (%s).")
                    % (method, full_url, res.status_code,
                       expected_status_code, res_json.get('error'),
                        res_json.get('error_description', _('no detail'))))
            return None
        if return_raw:
            return res
        res_json = res.json()
        logger.debug('JSON webservice answer: %s', res_json)
        return res_json

    def name_get(self):
        res = []
        for req in self:
            name = req.name
            if req.res_name:
                name = f"{name} ({req.res_name})"
            res.append((req.id, name))
        return res

    @api.model
    def signature_position(self, sign_position, signatory_rank):
        # sign_position is passed as parameter because this method
        # is decorated by api.model

        # return "llx,lly,urx,ury".
        # llx=left lower x coordinate,
        # lly=left lower y coordinate,
        # urx=upper right x coordinate,
        # ury = upper right y coordinate
        TOPRANK2POSITION = {
            1: '70,600,285,690',  # width = 215 - height = 90
            2: '310,600,525,690',
            3: '70,460,285,550',
            4: '310,460,525,550',
        }
        BOTTOMRANK2POSITION = {
            1: '95,195,245,245',  # width = 150 - height = 50
            2: '330,195,480,245',
            3: '95,150,245,200',
            4: '330,145,480,195',
        }
        rank2position = (
            TOPRANK2POSITION
            if sign_position == 'top'
            else BOTTOMRANK2POSITION
        )

        if signatory_rank not in rank2position:
            logger.warning(
                'Requesting signature position for undeclared '
                'signatory_rank %d',
                signatory_rank
            )

        return rank2position.get(signatory_rank, '56,392,296,464')

    @api.model
    def include_url_tag(self, mail_body, mail_name, raise_if_not_found=False):
        if not mail_body:
            raise UserError(_(
                "Mail body of %s is empty.") % mail_name)
        regexp = r'{yousignUrl\|.+}'
        re_match = re.search(regexp, mail_body, re.IGNORECASE)
        if not re_match:
            if raise_if_not_found:
                raise UserError(_(
                    "Missing special tag {yousignUrl|Access to documents} "
                    "in the mail body of %s. The special tag will be replaced "
                    "by the button with the label "
                    "'Access to documents'.") % mail_name)
            elif 'yousignUrl' in mail_body:
                raise UserError(_(
                    "In mail body of %s, it seems you tried to "
                    "include the yousign URL, but the regular expression "
                    "didn't match. Please check the special expression "
                    "for the yousign URL.") % mail_name)
            else:
                return mail_body
        found = re_match.group(0)
        button_label = found.split('|')[1][:-1].strip()
        button_label_txt = tools.html2plaintext(button_label)
        html_button = '<tag data-tag-type="button" data-tag-name="url" '\
                      'data-tag-title="%s">%s</tag>' % (button_label_txt,
                                                        button_label_txt)
        new_mail_body = re.sub(regexp, html_button, mail_body)
        return new_mail_body

    def send(self):
        self.ensure_one()
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
        init_mail_body = self.include_url_tag(
            self.init_mail_body, 'init', raise_if_not_found=True)
        data = {
            'name': self.name,
            'description': 'Created by Odoo connector',
            'start': False,
            'ordered': self.ordered,
            'config': {
                'email': {
                    'member.started': [{
                        'subject': self.init_mail_subject,
                        'message': init_mail_body,
                        'to': ['@member'],
                        }]
                    }
                }
            }
        for notif in self.notification_ids:
            to = []
            if notif.creator:
                to.append('@creator')
            if notif.members:
                to.append('@members')
            if notif.subscribers:
                to.append('@subscribers')
            for p in notif.partner_ids.filtered(lambda x: x.email):
                to.append(p.email)
            data['config']['email'][notif.notif_type] = [{
                'subject': notif.subject,
                'message': self.include_url_tag(notif.body, notif.notif_type),
                'to': to,
                }]
        if self.remind_auto:
            if not self.remind_mail_subject:
                raise UserError(_("Missing Remind Mail Subject"))
            if not self.remind_mail_body:
                raise UserError(_("Missing Remind Mail Body"))
            remind_mail_body = self.include_url_tag(
                self.remind_mail_body, 'reminder', raise_if_not_found=True)
            data['config']['reminders'] = [{
                'interval': self.remind_interval,
                'limit': self.remind_limit,
                'config': {
                    'email': {
                        'reminder.executed': [{
                            'subject': self.remind_mail_subject,
                            'message': remind_mail_body,
                            'to': ["@members.auto"],
                            }],
                        },
                    },
                }]
        rproc_res = self.yousign_request('POST', '/procedures', json=data)
        if rproc_res.get('status') != 'draft':
            raise UserError(_('Wrong status, should be draft'))
        if not rproc_res.get('id'):
            raise UserError(_('Missing ID'))
        ys_id = rproc_res['id']
        attach_data = {}
        # key = attach recordset
        # value = {'pagenum': 4, 'filename': 'tutu.pdf', 'ys_id': 'JLDKSJDKL'}
        for attach in self.attachment_ids:
            # We decide to always add signature on last page
            filename = attach.name
            pdf_file = BytesIO(attach.raw)
            try:
                pdf_reader = pypdf.PdfReader(pdf_file)
            except pypdf.utils.PdfReadError:
                raise UserError(_(
                    "File to sign '%s' is not a valid PDF file. You "
                    "must convert it to PDF before including it in a "
                    "Yousign request.") % filename)
            num_pages = len(pdf_reader.pages)
            logger.info('PDF %s has %d pages', filename, num_pages)
            attach_data[attach] = {
                'filename': filename,
                'base64': attach.datas,
                'num_pages': num_pages,
                }

        members_data = {}

        for signat in self.signatory_ids:
            rank += 1
            if not signat.lastname:
                raise UserError(_(
                    "Missing lastname on one of the signatories of request %s")
                    % self.display_name)
            if not signat.firstname:
                raise UserError(_(
                    "Missing firstname on signatory '%s'" % signat.lastname))
            if not signat.email:
                raise UserError(_(
                    "Missing email on the signatory '%s'") % signat.lastname)

            if not signat.mobile and signat.auth_mode == 'sms':
                raise UserError(_(
                    "Missing mobile phone number on signatory '%s'.")
                    % signat.lastname)
            members_data[signat] = {
                'firstname':
                signat.firstname and signat.firstname.strip() or '',
                'lastname': signat.lastname and signat.lastname.strip(),
                'phone':
                signat.mobile and signat.mobile.replace(' ', '') or '',
                'email': signat.email.strip(),
                'rank': rank,
                'mention': signat.mention_top or '',
                'mention2': signat.mention_bottom or '',
                }

        for attach, attach_vals in attach_data.items():
            json = {
                'name': attach_vals['filename'],
                'content': attach_vals['base64'],
                'procedure': ys_id,
                }
            rattach_res = self.yousign_request('POST', '/files', json=json)
            ys_attach_id = rattach_res.get('id')
            assert ys_attach_id
            attach_data[attach]['ys_attach_id'] = ys_attach_id

        for member, member_vals in members_data.items():
            json = {
                'firstname': member_vals['firstname'],
                'lastname': member_vals['lastname'],
                'email': member_vals['email'],
                'procedure': ys_id,
                'operationLevel': "custom",
                'operationCustomModes': [member.auth_mode],
                }
            if member_vals.get('phone'):
                json['phone'] = member_vals['phone']
            else:
                json['phone'] = '+33699089246'
            if self.ordered:
                json['position'] = member_vals['rank']
            rmember_res = self.yousign_request('POST', '/members', json=json)
            ys_member_id = rmember_res.get('id')
            assert ys_member_id
            members_data[member]['ys_member_id'] = ys_member_id
            member.ys_identifier = ys_member_id

            for attach_id, attach_vals in attach_data.items():
                json_fo = {
                    'file': attach_vals['ys_attach_id'],
                    'member': ys_member_id,
                    'page': attach_vals['num_pages'],
                    'position': self.signature_position(
                        self.sign_position, member_vals['rank']),
                    'mention': member_vals.get('mention'),
                    'mention2': member_vals.get('mention2'),
                    # 'reason': ,
                    }
                self.yousign_request('POST', '/file_objects', json=json_fo)

        try:
            logger.debug('Start YS initSign on req ID %d', self.id)
            self.yousign_request('PUT', ys_id, 200, json={'start': True})
        except Exception as err:
            logger.error(
                'YS initSign failed on req ID %d with error %s',
                self.id, err)
            raise UserError(_(
                "Failure when sending the signing request %s to "
                "Yousign.\n\n"
                "Error: %s") % (self.display_name, err))
        self.write({
            'state': 'sent',
            'ys_identifier': ys_id,
            })
        self.signatory_ids.write({'state': 'pending'})
        src_obj = self.get_source_object_with_chatter()
        if src_obj:
            # for v10, add link to request in message
            src_obj.sudo().message_post(body=_(
                "Yousign request <a href=# data-oe-model=yousign.request "
                "data-oe-id=%(req_id)s>%(req_name)s</a> "
                "generated with %(signatory_count)s signatories.",
                req_id=self.id, req_name=self.name, signatory_count=len(self.signatory_ids)))
        return

    def cancel(self):
        for req in self:
            if req.state == 'sent' and req.ys_identifier:
                self.yousign_request(
                    'DELETE', req.ys_identifier, 204, return_raw=True)
                logger.info(
                    'Yousign request %s ID %s successfully cancelled.',
                    req.name, req.id)
                req.message_post(body=_(
                    "Request successfully cancelled via Yousign "
                    "webservices."))
        self.write({'state': 'cancel'})

    def update_status(self, raise_if_ko=True):
        now = fields.Datetime.now()
        ystate2ostate = {
            'pending': 'pending',
            'processing': 'pending',
            'done': 'signed',
            'refused': 'refused',
            }
        for req in self.filtered(lambda x: x.state == 'sent'):
            logger.info(
                'Start getInfosFromSignatureDemand request on YS req %s ID %d',
                req.name, req.id)
            sign_state = {}  # key = member, value = state
            for signer in req.signatory_ids:
                sign_state[signer] = 'draft'  # initialize
                if not signer.ys_identifier:
                    logger.warning(
                        'Signer ID %s has no YS identifier', signer.id)
                    continue
                res = self.yousign_request(
                    'GET', signer.ys_identifier, 200, raise_if_ko=raise_if_ko)
                if res is None:
                    logger.warning('Skipping YS req %s ID %d', req.name, req.id)
                    continue
                ystate = res.get('status')
                if ystate not in ystate2ostate:
                    logger.warning(
                        'Bad state value for member ID %d: %s',
                        signer.id, ystate)
                    continue
                ostate = ystate2ostate[ystate]
                sign_state[signer] = ostate
                signature_date = False
                if ostate == 'signed':
                    # TODO: take into account timezone
                    # shouldn't we convert this field to datetime ?
                    signature_date = res.get('finishedAt', '')[:10]
                signer.write({
                    'state': ostate,
                    'signature_date': signature_date,
                    'comment': res.get('comment', False),
                    })

            vals = {'last_update': now}
            if all([x == 'signed' for x in sign_state.values()]):
                vals['state'] = 'signed'
                logger.info(
                    'Yousign request %s switched to signed state', req.name)
                src_obj = req.get_source_object_with_chatter()
                if src_obj:
                    src_obj.sudo().message_post(body=_(
                        "Yousign request <a href=# data-oe-model=yousign.request "
                        "data-oe-id=%(req_id)s>%(req_name)s</a> has been signed by all "
                        "signatories.", req_id=req.id, req_name=req.name))
                    req._signed_hook(src_obj)
            req.write(vals)

    def _signed_hook(self, source_recordset):
        '''Designed to be inherited by custom modules'''
        self.ensure_one()
        return

    @api.model
    def cron_update(self):
        # Filter-out the YS requests of the old-API plateform
        domain_base = [('ys_identifier', '=like', '/procedures/%')]
        requests_to_update = self.search(
            domain_base + [('state', '=', 'sent')])
        requests_to_update.update_status(raise_if_ko=False)
        requests_to_archive = self.search(
            domain_base + [('state', '=', 'signed')])
        requests_to_archive.archive(raise_if_ko=False)

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

            res = self.yousign_request(
                'GET', req.ys_identifier, 200, raise_if_ko=raise_if_ko)
            if res is None:
                logger.warning("Skipping Yousign request %s ID %s", req.name, req.id)
                continue
            if not res.get('files'):
                continue
            signed_filenames = [
                att.name for att in req.signed_attachment_ids]
            if req.res_id and req.model:
                res_model = req.model
                res_id = req.res_id
            else:
                res_model = self._name
                res_id = req.id

            for sfile in res['files']:
                file_id = sfile.get('id')
                if file_id:
                    dl = self.yousign_request(
                        'GET', file_id + '/download', 200, return_raw=True,
                        raise_if_ko=raise_if_ko)
                    if dl is None:
                        logger.warning(
                            "Skipping Yousign request %s ID %s due to download failure",
                            req.name, req.id)
                        continue
                    original_filename = sfile.get('name')
                    logger.debug(
                        "original_filename=%s", original_filename)
                    if original_filename:
                        if (
                                original_filename[-4:] and
                                original_filename[-4:].lower() == '.pdf'):
                            signed_filename =\
                                '%s_signed.pdf' % original_filename[:-4]
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
                            'datas': dl.content,
                            })
                        req.signed_attachment_ids = [(4, attach.id)]
                        signed_filenames.append(signed_filename)
                        logger.info(
                            'Signed file %s attached on %s ID %d',
                            signed_filename, res_model, res_id)
            if len(signed_filenames) == docs_to_sign_count:
                req.state = 'archived'
                req.message_post(body=_(
                    "%(doc_count)d signed document(s) are now attached. "
                    "Request %(req_name)s is archived.",
                    doc_count=len(signed_filenames), req_name=req.name))

        return


class YousignRequestSignatory(models.Model):
    _name = 'yousign.request.signatory'
    _order = 'parent_id, sequence, id'
    _description = "Yousign Signatories"
    _rec_name = 'lastname'

    parent_id = fields.Many2one(
        'yousign.request', string='Request', ondelete='cascade')
    sequence = fields.Integer()
    partner_id = fields.Many2one('res.partner', 'Partner', ondelete='restrict')
    firstname = fields.Char()
    lastname = fields.Char()
    email = fields.Char('E-mail')
    mobile = fields.Char('Mobile')
    auth_mode = fields.Selection([
        ('sms', 'SMS'),
        ('email', 'E-Mail'),
        ], default='sms', string='Authentication Mode', required=True,
        help='Authentication mode used for the signer')
    mention_top = fields.Char(string='Top Mention')
    mention_bottom = fields.Char(string='Bottom Mention')
    ys_identifier = fields.Char('Yousign ID', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('signed', 'Signed'),
        ('refused', 'Refused'),
        ], string='Signature Status', readonly=True, default='draft')
    comment = fields.Text(string='Comment')
    signature_date = fields.Date(string='Signature Date', readonly=True)

    @api.onchange('mobile', 'partner_id')
    def _onchange_mobile_validation(self):
        if self.mobile:
            country = self.partner_id and self.partner_id.country_id or self.env.company.country_id
            if country:
                self.mobile = phone_validation.phone_format(
                    self.mobile, country.code, country.phone_code,
                    force_format='INTERNATIONAL', raise_exception=True)

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
