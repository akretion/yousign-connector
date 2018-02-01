# -*- coding: utf-8 -*-
# © 2018 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'YouSign Connector',
    'version': '8.0.1.0.0',
    'category': 'Signature',
    'license': 'AGPL-3',
    'summary': 'Odoo generates signature requests on YouSign',
    'author': 'Akretion',
    'website': 'http://www.akretion.com',
    'depends': ['report', 'base_phone', 'mail'],
    'external_dependencies': {'python': ['ysApi', 'unidecode', 'PyPDF2']},
    'data': [
        'data/yousign_seq.xml',
        'data/cron.xml',
        'views/yousign_request_template.xml',
        'views/yousign_request.xml',
        'security/ir.model.access.csv',
        'wizard/yousign_request_remind_view.xml',
    ],
    'installable': True,
    'application': True,
}
