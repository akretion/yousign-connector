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
    title = fields.Char(
        'Title', translate=True,
        help="Corresponding field in Yousign API : title")
    message = fields.Text(
        'Message', translate=True,
        help="Corresponding field in Yousign API : message")
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
        string='Authentication Value',
        help="To be set only when Authentication Mode is Manual")

    @api.onchange('auth_mode')
    def auth_mode_change(self):
        if self.auth_mode != 'manual':
            self.auth_value = False

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
            'proof_level': self.proof_level,
            'auth_mode': self.auth_mode,
            'auth_value': self.auth_value,
        }
        if (
                hasattr(partner, 'firstname') and
                not partner.is_company):
            vals.update({
                'firstname': partner.firstname,
                'lastname': partner.lastname,
                })
        return vals
