#  Copyright 2018-2024 Akretion France (https://www.akretion.com/)
#  @author Alexis de Lattre <alexis.delattre@akretion.com>
#  License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


from odoo import models


class YousignRequestRemind(models.TransientModel):
    _name = 'yousign.request.remind'
    _description = 'Remind several Yousign requests'

    def run(self):
        self.ensure_one()
        assert self.env.context.get('active_model') == 'yousign.request', \
            'Source model must be yousign request'
        assert self.env.context.get('active_ids'), 'No requests selected'
        requests = self.env['yousign.request'].browse(
            self.env.context['active_ids'])
        requests.remind()
