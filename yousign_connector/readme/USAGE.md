The Yousign signature request templates are available in the menu
*Settings > Technical > Yousign > Request Templates*. Once you have finished
the configuration of a Yousign request template, you can click on the button
*Add Action* at the top right corner to add an entry in the *Action* menu of
the object.

If you prefer to have a directly accessible button on the form view of the
object to initiate the Yousign request instead of using the entry in the
*Action* menu, you should inherit the form view of that object and add a
button like below:

``` xml
<button name="%(yousign_connector.new_yousign_request_action)d" type="action" string="Send Yousign Request" context="{'yousign_template_xmlid': 'yousign_sale.sale_sign_template'}"/>
```

The link to the Yousign template is given by the context:

- either by giving the XMLID of the Yousign request template:
  `{'yousign_template_xmlid': 'yousign_sale.sale_sign_template'}`
- or by giving the ID of the Yousign request template:
  `{'yousign_template_id': 42}`

The Yousign signature requests are available in the menu
*Settings > Technical > Yousign > Signature Requests*.

In the menu *Settings > Technical > Automation > Scheduled Actions*, you will
find a scheduled action called *Yousign Requests Update*, inactive by default.
It updates the status of the Yousign requests with pending signature and
downloads the signed files of the Yousign requests that are signed by all
signatories. Activate it if you don't use the webhook, or as a fallback.

In the sandbox environment, the email of the signatories must belong to your
Yousign organization and the SMS one-time password is always `123456`.
