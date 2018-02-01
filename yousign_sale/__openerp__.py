# -*- coding: utf-8 -*-
# © 2018 Akretion (Alexis de Lattre <alexis.delattre@akretion.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'YouSign Sale',
    'version': '8.0.1.0.0',
    'category': 'Sales Management',
    'license': 'AGPL-3',
    'summary': 'Create Yousign signature requests from quotations',
    'author': 'Akretion',
    'website': 'http://www.akretion.com',
    'depends': ['sale', 'yousign_connector'],
    'data': [
        'views/sale_order.xml',
        'data/sign_template.xml',
    ],
    'installable': True,
    'application': True,
}
