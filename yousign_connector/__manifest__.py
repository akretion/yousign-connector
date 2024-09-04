# Copyright 2018-2024 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'Yousign Connector',
    'version': '14.0.1.0.0',
    'category': 'Signature',
    'license': 'AGPL-3',
    'summary': 'Odoo generates signature requests on Yousign',
    'author': 'Akretion',
    'website': 'https://github.com/akretion/yousign-connector',
    'depends': [
        'mail',
        'phone_validation',
        ],
    'external_dependencies': {'python': ['unidecode', 'pypdf>=3.1.0']},
    'data': [
        'data/yousign_seq.xml',
        'data/cron.xml',
        'views/yousign_request_template.xml',
        'views/yousign_request.xml',
        'security/ir.model.access.csv',
        'security/yousign_security.xml',
        'wizards/yousign_request_remind_view.xml',
    ],
    'installable': True,
}
