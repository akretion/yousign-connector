.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

======================
Odoo-Yousign connector
======================

This module connects Odoo and `Yousign <https://yousign.com/>`_ via the `Yousign API <http://developer.yousign.fr/>`_. It allows to easily create a signature request from any Odoo object (quotation, contract, ...). You can define signature templates (like email templates) to make it easier to create signature requests.

The development of this connector has been sponsored by `Akuit <https://www.akuit.com/>`_, a French umbrella company located in Paris.

Installation
============

To install this module, you need several Python librairies:

* PyPDF2 (available on `pypi <https://pypi.python.org/pypi/PyPDF2>`_ or as Debian/Ubuntu package *python-pypdf2*)
* unidecode (available on `pypi <https://pypi.python.org/pypi/Unidecode>`_ or as Debian/Ubuntu package *python-unidecode*)
* requests (available on `pypi <https://pypi.org/project/requests/>`_) or as Debian/Ubuntu package *python-requests*).

This modules depends on 2 OCA modules:

* `base_phone <https://github.com/OCA/connector-telephony/tree/8.0/base_phone>`_ from the `connector-telephony <https://github.com/OCA/connector-telephony>`_ OCA project,
* `base_suspend_security <https://github.com/OCA/server-tools/tree/8.0/base_suspend_security>`_ from the `server-tools <https://github.com/OCA/server-tools/>`_ OCA project.

The installation of the OCA module `partner_firstname <https://github.com/OCA/partner-contact/tree/8.0/partner_firstname>`_ is recommended, but not required.

Configuration
=============

You must edit the Odoo server configuration file and add the following keys:

* yousign_apikey = Yousign API key
* yousign_envir = demo or prod

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
* The position of the signatures on the last page are not configurable in Odoo,
  but you can inherit the method *signature_position()* of the class *yousign.request*
  to modify the default position.

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
