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
        'Init Mail Subject', translate=True)
    init_mail_body = fields.Html(
        'Init Mail Body', translate=True,
        help="You must insert '{yousignUrl}' in the body where you want to "
        "insert the URL to access Yousign.")
    remind_auto = fields.Boolean(string='Automatic Reminder')
    remind_mail_subject = fields.Char(
        'Reminder Mail Subject', translate=True)
    remind_mail_body = fields.Html(
        'Reminder Mail Body', translate=True)
    remind_interval = fields.Integer(
        string='Remind Interval', default=3,
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
        'Signatories')
    ir_act_window_id = fields.Many2one(
        'ir.actions.act_window', string='Sidebar Action', readonly=True,
        copy=False, help="Sidebar action to make this template available on "
        "records of the related document model")
    ir_value_id = fields.Many2one(
        'ir.values', string='Sidebar Button', readonly=True, copy=False,
        help="Sidebar button to open the sidebar action")

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
        ('sms', 'SMS'),
        ('email', 'E-Mail'),
        ], default='sms', string='Authentication Mode', required=True,
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
    def prepare_template2request(self, dynamic_partner_id=None):
        self.ensure_one()
        if self.partner_type == 'static':
            partner = self.partner_id
        elif self.partner_type == 'dynamic':
            if not dynamic_partner_id:
                raise UserError(_(
                    "dynamic_partner_id is a required argument when "
                    "partner_type is dynamic"))
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
