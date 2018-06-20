# -*- coding: utf-8 -*-
# © 2018 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import api, fields, models, tools, _
from openerp.exceptions import Warning as UserError
from unidecode import unidecode
from StringIO import StringIO
import logging
logger = logging.getLogger(__name__)

try:
    import ysApi
except ImportError:
    logger.debug('Cannot import ysApi')
try:
    import PyPDF2
except ImportError:
    logger.debug('Cannot import PyPDF2')


class YousignRequest(models.Model):
    _name = 'yousign.request'
    _description = 'Yousign Request'
    _order = 'id desc'
    _inherit = ['mail.thread']

    name = fields.Char()
    res_name = fields.Char(
        compute='compute_res_name', string="Related Document Name",
        store=True, readonly=True)
    model = fields.Char(
        string='Related Document Model', select=True, readonly=True,
        track_visibility='onchange')
    res_id = fields.Integer(
        string='Related Document ID', select=True, readonly=True,
        track_visibility='onchange')
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
    ys_lang = fields.Char(
        compute='compute_ys_lang', string='Yousign Lang', readonly=True,
        store=True)
    attachment_ids = fields.Many2many(
        'ir.attachment', string='Documents to Sign',
        readonly=True, states={'draft': [('readonly', False)]})
    signatory_ids = fields.One2many(
        'yousign.request.signatory', 'parent_id',
        'Signatories', readonly=True, states={'draft': [('readonly', False)]})
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
    ys_identifier = fields.Integer(
        'Yousign ID', readonly=True, track_visibility='onchange')

    @api.multi
    @api.depends('model', 'res_id')
    def compute_res_name(self):
        for req in self:
            name = 'None'
            if req.res_id and req.model:
                obj = self.env[req.model].browse(req.res_id)
                name = obj.display_name
            req.res_name = name

    @api.multi
    @api.depends('lang')
    def compute_ys_lang(self):
        for req in self:
            lang = req.lang or (self.env.user.lang or 'fr_FR')
            req.ys_lang = lang[:2].upper()

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
        # print "self._context=", self._context
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
            except:
                pass
        if self._context.get('yousign_template_id'):
            try:
                template = yrto.browse(self._context['yousign_template_id'])
                logger.debug(
                    'Using yousign request template %s ID %d',
                    template.name, template.id)
            except:
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
        default_signatory_ids = []
        for signatory in template.signatory_ids:
            dynamic_partner_id = None
            if signatory.partner_type == 'dynamic':
                dynamic_partner_str = eto.render_template_batch(
                    signatory.partner_tmpl, model, [res_id])[res_id]
                dynamic_partner_id = int(dynamic_partner_str)
            signatory_vals = signatory.prepare_template2request(
                dynamic_partner_id=dynamic_partner_id)
            default_signatory_ids.append((0, 0, signatory_vals))
        default_attachment_ids = []
        if template.report_id:
            report_data_bin, filename_ext = iarxo.render_report(
                [res_id], template.report_id.report_name, False)

            filename = 'report'
            if source_obj.display_name:
                tmp_filename = source_obj.display_name[:50]
                tmp_filename = tmp_filename.replace(' ', '_')
                filename = unidecode(tmp_filename)
            full_filename = '%s.%s' % (filename, filename_ext)
            attach_vals = {
                'name': full_filename,
                # 'res_id': Signature request is not created yet
                'res_model': self._name,
                'datas': report_data_bin.encode('base64'),
                'datas_fname': full_filename,
                }
            attach = iao.create(attach_vals)
            default_attachment_ids.append((6, 0, [attach.id]))
        lang = eto.render_template_batch(
            template.lang, model, [res_id])[res_id]
        if lang:
            template = template.with_context(lang=lang)
        dyn_fields = {
            'init_mail_subject': template.init_mail_subject,
            'init_mail_body': template.init_mail_body,
            }
        for field_name, field_content in dyn_fields.iteritems():
            dyn_fields[field_name] = eto.render_template_batch(
                dyn_fields[field_name], model, [res_id])[res_id]
        res.update(dyn_fields)
        res.update({
            'name': source_obj.display_name,
            'model': model,
            'res_id': res_id,
            'lang': lang,
            'signatory_ids': default_signatory_ids,
            'attachment_ids': default_attachment_ids,
            })
        # from pprint import pprint
        # pprint(res)
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
        username = tools.config.get('yousign_user', False)
        password = tools.config.get('yousign_password', False)
        apikey = tools.config.get('yousign_apikey', False)
        environment = tools.config.get('yousign_envir', 'demo')
        if not username or not password or not apikey or not environment:
            raise UserError(_(
                "One of the Yousign config parameters is missing in the Odoo "
                "server config file."))

        logger.info(
            'Initialising connection to Yousign with username %s '
            'on environment %s', username, environment)
        hash_passwd = ysApi.ApiClient.hashPassword(password)
        try:
            conn = ysApi.ApiClient(
                None, username, hash_passwd, apikey, environment)
            logger.debug('YS connection result: conn=%s', conn)
        except Exception, e:
            err_msg = str(e).decode('utf-8')
            logger.warning(
                'Failed to initialize connection to YS. Error: %s', err_msg)
            raise UserError(_(
                "Failed to initialize connection to Yousign with username %s "
                "on environment %s. \n\nTechnical error message: %s")
                % (username, environment, err_msg))
        return conn

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

    @api.multi
    def send(self):
        self.ensure_one()
        logger.info('Start to send YS request %s ID %d', self.name, self.id)
        conn = self.yousign_init()
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
        listSignersInfos = []
        listSignedFile = []
        options = []
        rank = 0
        for signat in self.signatory_ids:
            rank += 1
            if not signat.lastname:
                raise UserError(_(
                    "Missing lastname on one of the signatories of request %s")
                    % self.display_name)
            if not signat.email:
                raise UserError(_(
                    "Missing email on the signatory '%s'") % signat.lastname)
            if signat.auth_mode == 'sms' and not signat.mobile:
                raise UserError(_(
                    "Missing mobile phone number on signatory '%s' "
                    "whose authentication mode is SMS")
                    % signat.lastname)
            if signat.auth_mode == 'manual' and not signat.auth_value:
                raise UserError(_(
                    "You have selected 'manual' as authentication mode for "
                    "the signatory %s, so you must set the authentication "
                    "value for this signatory.") % signat.email)
            ysigner = {
                'firstName':
                signat.firstname and signat.firstname.strip() or '',
                'lastName': signat.lastname and signat.lastname.strip(),
                'phone':
                signat.mobile and signat.mobile.replace(' ', '') or '',
                'mail': signat.email.strip(),
                'authenticationMode': signat.auth_mode,
                'proofLevel':
                signat.proof_level and signat.proof_level.upper() or "LOW",
                'authenticationValue': signat.auth_value or '',
                }
            listSignersInfos.append(ysigner)
            position = self.signature_position(rank)

            yoption = {
                'isVisibleSignature': True,
                'visibleRectangleSignature': position,
                'mail': signat.email,
                }
            options.append(yoption)
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
            # add visibleSignaturePage on all options
            for yoption in options:
                yoption['visibleSignaturePage'] = num_pages
            yfiletosign = {
                'name': filename,
                'content': attach.datas,
                'visibleOptions': options,
                'pdfPassword': '',
                }
            listSignedFile.append(yfiletosign)

        ys_identifier = False
        try:
            logger.debug('Start YS initSign on req ID %d', self.id)
            res = conn.initSign(
                listSignedFile,
                listSignersInfos,
                '',  # message
                '',  # title
                self.init_mail_subject,  # initMailSubject,
                self.init_mail_body,  # initMail,
                '',  # endMailSubject,
                '',  # endMail,
                self.ys_lang,
                '',     # mode
                '',  # archive
                )
            logger.debug('YS initSign on req ID %d. Result=%s', self.id, res)
            ys_identifier = res.idDemand
        except Exception, e:
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
            'ys_identifier': ys_identifier,
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
        self.write({'state': 'cancel'})

    @api.multi
    def update_status(self):
        conn = False
        for req in self:
            logger.info(
                'Start getInfosFromSignatureDemand request on YS req %s ID %d',
                req.name, req.id)
            if req.state != 'sent':
                continue
            if not req.ys_identifier:
                continue
            if not conn:
                conn = self.yousign_init()
            try:
                res = conn.getInfosFromSignatureDemand(req.ys_identifier)
                logger.debug(
                    'Result of getInfosFromSignatureDemand on YS req '
                    'ID %d: %s', req.id, res)
            except Exception, e:
                err_msg = str(e).decode('utf-8')
                logger.error(
                    'getInfosFromSignatureDemand request failed on YS req '
                    'ID %d. Error: %s', req.id, err_msg)
                req.message_post(_(
                    "<b>Failed to update status.</b> <br/>"
                    "Technical error: %s") % err_msg)
                continue
            mail2obj = {}
            ysid2obj = {}
            for signer in req.signatory_ids:
                if signer.ys_identifier:
                    ysid2obj[signer.ys_identifier] = signer
                else:
                    mail2obj[signer.email.strip()] = signer
            # update ys_identifier on signatories  : move to send() ?
            # No, because we don't have the info in the answer of the WS
            for signerinfo in res.cosignerInfos:
                if signerinfo.mail and signerinfo.mail in mail2obj:
                    signer = mail2obj[signerinfo.mail]
                    signer.ys_identifier = signerinfo.id
                    ysid2obj[signerinfo.id] = signer

            # get status
            ysid2status = {}
            for fileinfo in res.fileInfos:
                for signstat in fileinfo.cosignersWithStatus:
                    if signstat.id in ysid2status:
                        ysid2status[signstat.id].append(signstat.status)
                    else:
                        ysid2status[signstat.id] = [signstat.status]
            all_signed = True
            for signer in req.signatory_ids:
                if signer.ys_identifier in ysid2status:
                    if all([
                            state == 'COSIGNATURE_FILE_SIGNED' for state
                            in ysid2status[signer.ys_identifier]]):
                        signer.state = 'signed'
                    elif (
                            'COSIGNATURE_FILE_SIGNED' in
                            ysid2status[signer.ys_identifier]):
                        signer.state = 'partially_signed'
                        all_signed = False
                    else:
                        all_signed = False
            if all_signed:
                req.state = 'signed'
                logger.info(
                    'Yousign request %s switched to signed state', req.name)
                src_obj = req.get_source_object_with_chatter()
                if src_obj:
                    # for v10, add link to request in message
                    src_obj.suspend_security().message_post(_(
                        "Yousign request <b>%s</b> has been signed by all "
                        "signatories") % req.name)

    @api.model
    def cron_update(self):
        requests_to_update = self.search([('state', '=', 'sent')])
        requests_to_update.update_status()
        requests_to_archive = self.search([('state', '=', 'signed')])
        requests_to_archive.archive()

    @api.multi
    def remind(self):
        conn = False
        for req in self:
            logger.info(
                'Start alertSigners request on YS req %s ID %d',
                req.name, req.id)
            if req.state != 'sent':
                logger.info(
                    'Skip Yousign request %s ID %d in state %s',
                    req.name, req.id, req.state)
                continue
            if not req.ys_identifier:
                logger.warning(
                    "Skip Yousign request %s ID %s: missing identifier",
                    req.name, req.id)
                continue
            if not conn:
                conn = self.yousign_init()
            try:
                res = conn.alertSigners(
                    req.ys_identifier, language=req.ys_lang)
                logger.debug(
                    'Successful request alertSigners on YS req ID %d '
                    'result %s', req.id, res)
                req.message_post(_("Reminder sent to late signatories"))
            except Exception, e:
                err_msg = str(e).decode('utf-8')
                logger.error(
                    'alertSigners request failed on YS req. ID %d '
                    'with error %s', req.id, err_msg)
                req.message_post(_(
                    "<b>Failed to send reminder to late signatories.</b> <br/>"
                    "Technical error: %s") % err_msg)

    @api.multi
    def archive(self):
        conn = False
        for req in self:
            logger.info(
                "Getting signed files on Yousign request %s ID %s",
                req.name, req.id)
            if req.state != 'signed':
                logger.info(
                    'Skip Yousign request %s ID %d in state %s',
                    req.name, req.id, req.state)
                continue
            if not req.ys_identifier:
                logger.warning(
                    "Skip Yousign request %s ID %s: missing identifier",
                    req.name, req.id)
            docs_to_sign_count = len(req.attachment_ids)
            if not docs_to_sign_count:
                logger.warning(
                    "Skip Yousign request %s ID %s: no documents to sign, "
                    "so nothing to archive", req.name, req.id)
            if not conn:
                conn = self.yousign_init()
            res = False
            try:
                res = conn.getSignedFilesFromDemand(req.ys_identifier)
                logger.debug(
                    "getSignedFilesFromDemand on YS req ID %d result=%s",
                    req.id, res)
            except Exception, e:
                err_msg = str(e).decode('utf-8')
                logger.error(
                    "getSignedFilesFromDemand request failed on YS "
                    "req. ID %d with error %s", req.id, err_msg)
                req.message_post(_(
                    "<b>Failed to archive signed documents.</b><br/>"
                    "Technical error: %s") % err_msg)
            if res:
                attach_created = 0
                for signed_file in res:
                    logger.debug(
                        "signed_file.filename=%s", signed_file.fileName)
                    if signed_file.fileName and signed_file.file:
                        filename = signed_file.fileName
                        if filename[-4:] and filename[-4:].lower() == '.pdf':
                            filename = '%s_signed.pdf' % filename[:-4]
                        self.env['ir.attachment'].create({
                            'name': filename,
                            'res_id': req.id,
                            'res_model': self._name,
                            'datas': signed_file.file,
                            'datas_fname': filename,
                            })
                        attach_created += 1
                        logger.info(
                            'File %s attached on Yousign request %s ID %d',
                            filename, req.name, req.id)
                if attach_created == docs_to_sign_count:
                    req.message_post(_(
                        "%d signed document(s) have been added as attachment")
                        % attach_created)
                    req.state = 'archived'
        return


class YousignRequestSignatory(models.Model):
    _name = 'yousign.request.signatory'
    _order = 'parent_id, sequence'
    _inherit = ['phone.common']
    _phone_fields = ['mobile']
    _partner_field = 'partner_id'
    _country_field = None

    parent_id = fields.Many2one(
        'yousign.request', string='Request', ondelete='cascade')
    sequence = fields.Integer()
    partner_id = fields.Many2one('res.partner', 'Partner', ondelete='restrict')
    firstname = fields.Char()
    lastname = fields.Char()
    email = fields.Char('E-mail')
    mobile = fields.Char('Mobile')
    proof_level = fields.Selection([
        ('low', 'Low'),
        ('high', 'High'),
        ], string='Proof Level', default='low',
        help="Proof level of the signer. In HIGH mode, signer(s) must upload "
        "ID cards to launch the signature (it will be checked immediately "
        "after the upload")
    auth_mode = fields.Selection([
        ('sms', 'SMS'),
        ('mail', 'Mail'),
        ('mass', 'Mass'),
        ('manual', 'Manual'),
        ('photo', 'Photo'),
        ], default='sms', string='Authentication Mode', required=True,
        help='Authentication mode used for the signer')
    auth_value = fields.Char(
        help="To be set only when Authentication Mode is Manual")
    ys_identifier = fields.Integer('Yousign ID', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('partially_signed', 'Partially Signed'),
        ('signed', 'Signed'),
        ], string='Signature Status', readonly=True, default='draft')

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

    @api.onchange('auth_mode')
    def auth_mode_change(self):
        if self.auth_mode != 'manual':
            self.auth_value = False

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
