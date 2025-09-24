# -*- coding: utf-8 -*-
# © 2018 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from openerp import api, fields, models, _
from openerp.exceptions import Warning as UserError, ValidationError
import logging
logger = logging.getLogger(__name__)


class YousignRequestTemplate(models.Model):
    _name = 'yousign.request.template'
    _description = 'Yousign Request Template'
    _order = 'name'

    name = fields.Char(required=True)
    model_id = fields.Many2one(
        'ir.model', string='Applies to', required=True)
    model = fields.Char(related='model_id.model', readonly=True, store=True)
    lang = fields.Char('Language')
    ordered = fields.Boolean(string='Sign one after the other')
    init_mail_subject = fields.Char(
        'Init Mail Subject', translate=True, size=150)
    init_mail_body = fields.Char(
        'Init Mail Body', translate=True,
        size=500)
    remind_auto = fields.Boolean(string='Automatic Reminder')
    remind_mail_subject = fields.Char(
        'Reminder Mail Subject', translate=True, size=150)
    remind_mail_body = fields.Char(
        'Reminder Mail Body', translate=True, size=500)
    remind_interval = fields.Selection(
        [
            (1, '1 day'),
            (2, '2 days'),
            (7, '7 days'),
            (14, '14 days'),
        ],
        string='Remind Interval', default=2,
        help="Number of days between 2 auto-reminders by email.")
    remind_limit = fields.Integer(string='Remind Limit', default=10)
    report_id = fields.Many2one(
        'ir.actions.report.xml', string='Default Report to Sign')
    company_id = fields.Many2one(
        'res.company', string='Company', ondelete='cascade',
        default=lambda self: self.env['res.company']._company_default_get(
            'yousign.request.template'))
    signatory_ids = fields.One2many(
        'yousign.request.template.signatory', 'parent_id',
        string='Signatories')
    notification_ids = fields.One2many(
        'yousign.request.template.notification', 'parent_id',
        string='E-mail Notifications')
    ir_act_window_id = fields.Many2one(
        'ir.actions.act_window', string='Sidebar Action', readonly=True,
        copy=False, help="Sidebar action to make this template available on "
        "records of the related document model")
    ir_value_id = fields.Many2one(
        'ir.values', string='Sidebar Button', readonly=True, copy=False,
        help="Sidebar button to open the sidebar action")
    sign_position = fields.Selection(
        [('top', 'Top'), ('bottom', 'Bottom')],
        string='Sign position', default='top')

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
    def create_button(self):
        iaao = self.env['ir.actions.act_window']
        ivo = self.env['ir.values']
        for template in self:
            src_obj = template.model_id.model
            view = self.env.ref('yousign_connector.new_yousign_request_form')
            button_name = _('Yousign Request (%s)') % template.name
            action = iaao.sudo().create({
                'name': button_name,
                'type': 'ir.actions.act_window',
                'res_model': 'yousign.request',
                'src_model': src_obj,
                'view_mode': 'form',
                'view_id': view.id,
                'target': 'new',
                'context': "{'yousign_template_id': %d}" % template.id,
                })
            ir_value = ivo.sudo().create({
                'name': button_name,
                'model': src_obj,
                'key2': 'client_action_multi',
                'value': "ir.actions.act_window,%d" % action.id,
                })

            template.write({
                'ir_act_window_id': action.id,
                'ir_value_id': ir_value.id,
                })
        return

    @api.multi
    def unlink_button(self):
        for template in self:
            if template.ir_act_window_id:
                template.ir_act_window_id.sudo().unlink()
            if template.ir_value_id:
                template.ir_value_id.sudo().unlink()
        return

    @api.multi
    def prepare_template2request(self):
        self.ensure_one()
        res = {
            'ordered': self.ordered,
            'remind_auto': self.remind_auto,
            'remind_interval': self.remind_interval,
            'remind_limit': self.remind_limit,
            'sign_position': self.sign_position,
            }
        return res


class YousignRequestTemplateSignatory(models.Model):
    _name = 'yousign.request.template.signatory'
    _description = 'Signatories of Yousign Request Template'
    _order = 'parent_id, sequence'

    parent_id = fields.Many2one(
        'yousign.request.template', string='Template', ondelete='cascade')
    sequence = fields.Integer()
    partner_type = fields.Selection([
        ('static', 'Static'),
        ('dynamic', 'Dynamic'),
        ], string='Partner Type', default='dynamic', required=True)
    partner_id = fields.Many2one(
        'res.partner', string='Fixed Partner', ondelete='restrict')
    partner_tmpl = fields.Char(string='Dynamic Partner')
    auth_mode = fields.Selection([
        ('otp_sms', 'SMS'),
        ('otp_email', 'E-Mail'),
        ('no_otp', 'No OTP'),
        ], default='otp_sms', string='Authentication Mode', required=True,
        help='Authentication mode used for the signer')
    mention_top = fields.Char(string='Top Mention')
    mention_bottom = fields.Char(string='Bottom Mention')

    @api.onchange('partner_type')
    def partner_type_change(self):
        if self.partner_type == 'static':
            self.partner_tmpl = False
        elif self.partner_type == 'dynamic':
            self.partner_id = False

    @api.constrains('partner_type', 'partner_id', 'partner_tmpl')
    def check_signatory_template(self):
        for signatory in self:
            if signatory.partner_type == 'static' and not signatory.partner_id:
                raise ValidationError(_(
                    "Fixed Partner is required when Partner Type is set "
                    "to 'Static'"))
            elif (
                    signatory.partner_type == 'dynamic' and
                    not signatory.partner_tmpl):
                raise ValidationError(_(
                    "Dynamic Partner is required when Partner Type is set "
                    "to 'Dynamic'"))

    @api.multi
    def prepare_template2request(self, model, res_id):
        self.ensure_one()
        eto = self.env['email.template']
        if self.partner_type == 'static':
            partner = self.partner_id
        elif self.partner_type == 'dynamic':
            dynamic_partner_str = eto.render_template_batch(
                self.partner_tmpl, model, [res_id])[res_id]
            dynamic_partner_id = int(dynamic_partner_str)
            partner = self.env['res.partner'].browse(dynamic_partner_id)
        else:
            raise UserError(_('Unsupported partner type'))
        vals = {
            'partner_id': partner.id,
            'email': partner.email,
            'lastname': partner.name,
            'mobile': partner.mobile,
            'auth_mode': self.auth_mode,
            'mention_top': self.mention_top,
            'mention_bottom': self.mention_bottom,
        }
        if (
                hasattr(partner, 'firstname') and
                not partner.is_company):
            vals.update({
                'firstname': partner.firstname,
                'lastname': partner.lastname,
                })
        return vals


class YousignRequestTemplateNotification(models.Model):
    _name = 'yousign.request.template.notification'
    _description = 'Notifications of Yousign Request Template'

    parent_id = fields.Many2one(
        'yousign.request.template', string='Template', ondelete='cascade')
    notif_type = fields.Selection(
        '_notif_type_selection', string='Notification Type', required=True)
    creator = fields.Boolean(string='Notify Creator')
    members = fields.Boolean(string='Notify Members')
    subscribers = fields.Boolean(string='Notify Subscribers')
    partner_ids = fields.Many2many(
        'res.partner', string='Partners to Notify',
        domain=[('email', '!=', False)])
    subject = fields.Char(required=True, translate=True)
    body = fields.Html(required=True, translate=True)

    _sql_constraints = [(
        'parent_type_uniq',
        'unique(parent_id, notif_type)',
        "This notification type already exists for this Yousign request "
        "template!")]

    @api.model
    def _notif_type_selection(self):
        return self.env['yousign.request.notification']._notif_type_selection()

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

    @api.multi
    def prepare_template2request(self, model, res_id):
        self.ensure_one()
        eto = self.env['email.template']
        vals = {
            'notif_type': self.notif_type,
            'creator': self.creator,
            'members': self.members,
            'subscribers': self.subscribers,
            'partner_ids': [(6, 0, self.partner_ids.ids)],
            }
        for dyn_field in ['subject', 'body']:
            vals[dyn_field] = eto.render_template_batch(
                self[dyn_field], model, [res_id])[res_id]
        return vals
