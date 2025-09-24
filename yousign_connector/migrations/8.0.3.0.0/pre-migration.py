# -*- coding: utf-8 -*-

def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        WITH request AS (
            SELECT
               id AS id2,
               SUBSTRING(ys_identifier, 13) AS ys_identifier
            FROM yousign_request
            WHERE ys_identifier != ''
        )
        UPDATE yousign_request
        SET
            ys_identifier=r.ys_identifier
        FROM request r
        WHERE id=r.id2;
    """)
    cr.execute("""
        WITH request AS (
            SELECT
               id AS id2,
               SUBSTRING(ys_identifier, 10) AS ys_identifier
            FROM yousign_request_signatory
            WHERE ys_identifier != ''
        )
        UPDATE yousign_request_signatory
        SET
            ys_identifier=r.ys_identifier
        FROM request r
        WHERE id=r.id2;
    """)
    cr.execute("""
        UPDATE yousign_request_signatory
        SET auth_mode = 'otp_' || auth_mode;
    """)
    cr.execute("""
        UPDATE yousign_request
        SET remind_interval=2
        WHERE remind_interval=3;
    """)
    cr.execute("""
        UPDATE yousign_request_template_signatory
        SET auth_mode = 'otp_' || auth_mode;
    """)
    cr.execute("""
        UPDATE yousign_request_template
        SET remind_interval=2
        WHERE remind_interval=3;
    """)
