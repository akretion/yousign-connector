# -*- coding: utf-8 -*-
# Copyright 2020 Akretion France (http://www.akretion.com/)
# @author: Alexis de Lattre <alexis.delattre@akretion.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        "UPDATE yousign_request_signatory SET auth_mode='email' "
        "WHERE auth_mode='mail'")
    cr.execute(
        "UPDATE yousign_request_template_signatory SET auth_mode='email' "
        "WHERE auth_mode='mail'")
