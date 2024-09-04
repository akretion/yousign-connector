.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

======================
Odoo-Yousign connector
======================

This module connects Odoo and `Yousign <https://yousign.com/>`_ via the `Yousign API <https://dev.yousign.com/>`_. It allows to easily create a signature request from any Odoo object (quotation, contract, ...). You can define signature templates (like email templates) to make it easier to create signature requests.

The development of this connector has been sponsored by `Akuit <https://www.akuit.com/>`_, a French umbrella company located in Paris.

Installation
============

To install this module, you need several Python librairies:

* `pypdf <https://pypi.org/project/pypdf/>`_
* `unidecode <https://pypi.org/project/Unidecode>`_

The installation of the OCA module `partner_firstname <https://github.com/OCA/partner-contact/tree/14.0/partner_firstname>`_ is recommended, but not required.

Configuration
=============

You must edit the Odoo server configuration file and add the following keys:

* yousign_apikey = Yousign API key
* running_env = test or prod

Then restart the Odoo server with the updated configuration file.

Usage
=====

The Yousign signature request templates are available in the menu *Settings > Technical > Yousign > Request Templates*. Once you have finished the configuration of a Yousign request template, you can click on the button *Add Action* at the top right corner to add an entry in the *Action* menu of the object.

If you prefer to have a directly accessible button on the form view of the object to initiate the Yousign request instead of using the entry in the *Action* menu, you should inherit the form view of that object and add a button like below:

.. code::

  <button name="%(yousign_connector.new_yousign_request_action)d" type="action" string="Send Yousign Request" context="{'yousign_template_xmlid': 'yousign_sale.sale_sign_template'}"/>

The link to the Yousign template is given by the context:

* either by giving the XMLID of the Yousign request template: **{'yousign_template_xmlid': 'yousign_sale.sale_sign_template'}**

* or by giving the ID of the Yousign request template: **{'yousign_template_id: 42}**

The Yousign signature requests are available in the menu *Settings > Technical > Yousign > Signature Requests*.

In the menu *Settings > Technical > Automation > Scheduled Actions*, you will find a cron called *Yousign Requests Update*. It updates the status of the Yousign requests with pending signature and downloads signed files for the Yousign requests that are signed by all signatories. By default, this task is executed every day, but you can change its frequency.

Known issues / Roadmap
======================

* The images of the signatures are always included on the last page of each PDF.

Bug Tracker
===========

Bugs are tracked on `GitHub Issues
<https://github.com/akretion/yousign-connector/issues>`_. In case of trouble, please
check there if your issue has already been reported. If you spotted it first,
help us smashing it by providing a detailed and welcomed feedback.

Credits
=======

Contributors
------------

* Alexis de Lattre <alexis.delattre@akretion.com>
