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
# from pprint import pprint
import re
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
    _inherit = ['mail.thread']

    name = fields.Char()
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
        states={'draft': [('readonly', False)]})
    init_mail_body = fields.Html(
        'Init Mail Body', readonly=True,
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
        readonly=True, states={'draft': [('readonly', False)]})
    remind_mail_body = fields.Html(
        'Reminder Mail Body',
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
        # print "model=%s, res_id=%s" % (model, res_id)
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
    def yousign_init(self):
        apikey = tools.config.get('yousign_apikey', False)
        environment = tools.config.get('yousign_envir', 'demo')
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
            json=None, return_raw=False):
        url_base, headers = self.yousign_init()
        full_url = url_base + url
        logger.info(
            'Sending %s request on %s. Expecting status code %d.',
            method, full_url, expected_status_code)
        logger.debug('JSON data sent: %s', json)
        res = requests.request(method, full_url, headers=headers, json=json)
        if res.status_code != expected_status_code:
            logger.error('Status code received: %s.', res.status_code)
            try:
                res_json = res.json()
            except Exception:
                res_json = {}
            raise UserError(_(
                "The HTTP %s request on Yousign webservice %s returned status "
                "code %d whereas %d was expected. Error message: %s (%s).")
                % (method, full_url, res.status_code,
                   expected_status_code, res_json.get('title'),
                   res_json.get('detail', _('no detail'))))
        if return_raw:
            return res
        res_json = res.json()
        logger.debug('JSON webservice answer: %s', res_json)
        return res_json

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
        # llx,lly,urx,ury".
        # llx=left lower x coordinate,
        # lly=left lower y coordinate,
        # urx=upper right x coordinate,
        # ury = upper right y coordinate
        rank2position = {
            1: '70,600,285,690',  # width = 215 - height = 90
            2: '310,600,525,690',
            3: '70,460,285,550',
            4: '310,460,525,550',
            }
        if signatory_rank not in rank2position:
            logger.warning(
                'Requesting signature position for undeclared '
                'signatory_rank %d',
                signatory_rank)
        return rank2position.get(signatory_rank, '56,392,296,464')

    @api.model
    def simple_html2txt(self, html):
        reg = re.compile('<.*?>')
        text = re.sub(reg, '', html)
        return text

    @api.model
    def include_url_tag(self, mail_body, mail_name, raise_if_not_found=False):
        if not mail_body:
            raise UserError(_(
                "Mail body of %s is empty.") % mail_name)
        regexp = '{yousignUrl\|.+}'
        match = re.search(regexp, mail_body, re.IGNORECASE)
        if not match:
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
        found = match.group(0)
        button_label = found.split('|')[1][:-1].strip()
        button_label_txt = self.simple_html2txt(button_label)
        html_button = '<tag data-tag-type="button" data-tag-name="url" '\
                      'data-tag-title="%s">%s</tag>' % (button_label_txt,
                                                        button_label_txt)
        new_mail_body = re.sub(regexp, html_button, mail_body)
        return new_mail_body

    @api.multi
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
            filename = attach.datas_fname or attach.name
            pdf_file = StringIO(attach.datas.decode('base64'))
            try:
                pdf = PyPDF2.PdfFileReader(pdf_file)
            except PyPDF2.utils.PdfReadError:
                raise UserError(_(
                    "File to sign '%s' is not a valid PDF file. You "
                    "must convert it to PDF before including it in a "
                    "Yousign request.") % filename)
            num_pages = pdf.getNumPages()
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

            if not signat.mobile:
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
                    'position': self.signature_position(member_vals['rank']),
                    'mention': member_vals.get('mention'),
                    'mention2': member_vals.get('mention2'),
                    # 'reason': ,
                    }
                self.yousign_request('POST', '/file_objects', json=json_fo)

        try:
            logger.debug('Start YS initSign on req ID %d', self.id)
            self.yousign_request('PUT', ys_id, 200, json={'start': True})
        except Exception as e:
            err_msg = str(e).decode('utf-8')
            logger.error(
                'YS initSign failed on req ID %d with error %s',
                self.id, err_msg)
            raise UserError(_(
                "Failure when sending the signing request %s to "
                "Yousign.\n\n"
                "Error: %s") % (self.display_name, err_msg))
        self.write({
            'state': 'sent',
            'ys_identifier': ys_id,
            })
        self.signatory_ids.write({'state': 'pending'})
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
                self.yousign_request(
                    'DELETE', req.ys_identifier, 204, return_raw=True)
                logger.info(
                    'Yousign request %s ID %s successfully cancelled.',
                    req.name, req.id)
                req.message_post(_(
                    "Request successfully cancelled via Yousign "
                    "webservices."))
        self.write({'state': 'cancel'})

    @api.multi
    def update_status(self):
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
                res = self.yousign_request('GET', signer.ys_identifier, 200)
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
        domain_base = [('ys_identifier', '=like', '/procedures/%')]
        requests_to_update = self.search(
            domain_base + [('state', '=', 'sent')])
        requests_to_update.update_status()
        requests_to_archive = self.search(
            domain_base + [('state', '=', 'signed')])
        requests_to_archive.archive()

    @api.multi
    def archive(self):
        for req in self.filtered(
                lambda x: x.state == 'signed' and x.ys_identifier):
            logger.info(
                "Getting signed files on Yousign request %s ID %s",
                req.name, req.id)
            import pdb
            pdb.set_trace()
            docs_to_sign_count = len(req.attachment_ids)
            if not docs_to_sign_count:
                logger.warning(
                    "Skip Yousign request %s ID %s: no documents to sign, "
                    "so nothing to archive", req.name, req.id)

            res = self.yousign_request('GET', req.ys_identifier, 200)
            if not res.get('files'):
                continue
            signed_filenames = [
                att.datas_fname for att in req.signed_attachment_ids]
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
                        'GET', file_id + '/download', 200, return_raw=True)
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
    firstname = fields.Char()
    lastname = fields.Char()
    email = fields.Char('E-mail')
    mobile = fields.Char('Mobile')
    auth_mode = fields.Selection([
        ('sms', 'SMS'),
        ('email', 'E-Mail'),  # TODO mig script old value : mail
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
