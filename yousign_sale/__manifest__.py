# Copyright 2018-2024 Akretion France (https://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    'name': 'YouSign Sale',
    'version': '14.0.1.0.0',
    'category': 'Sales Management',
    'license': 'AGPL-3',
    'summary': 'Create Yousign signature requests from quotations',
    'author': 'Akretion',
    'website': 'https://github.com/akretion/yousign-connector',
    'depends': ['sale', 'yousign_connector'],
    'data': [
        'views/sale_order.xml',
        'data/sign_template.xml',
    ],
    'installable': True,
}
