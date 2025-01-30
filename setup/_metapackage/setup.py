import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo8-addons-akretion-yousign-connector",
    description="Meta package for akretion-yousign-connector Odoo addons",
    version=version,
    install_requires=[
        'odoo8-addon-yousign_connector',
        'odoo8-addon-yousign_sale',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 8.0',
    ]
)
