This module connects Odoo and [Yousign](https://yousign.com/) via the
[Yousign API v3](https://developers.yousign.com/). It allows to easily create
a signature request from any Odoo object (quotation, contract, ...). You can
define signature templates (like email templates) to make it easier to create
signature requests.

When all the signatories have signed, the signed PDF files are automatically
downloaded and attached to the source object, either in real time via the
Yousign webhook or via a scheduled action.
