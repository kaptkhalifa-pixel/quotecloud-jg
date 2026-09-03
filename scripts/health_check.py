"""Production health check, invoked by a Render Cron Job every 10 minutes
(command: `python scripts/health_check.py`) - not a Flask route, a one-shot
batch script. Same pattern as this project's other real Render Cron Job
scripts (imports from app to reuse its Firebase/Resend init; app.run() is
guarded behind __main__ in app.py, so importing it here never starts a
second web server).

This directly addresses the real blind spot behind tonight's own deploy-
timing investigation on the sibling QC Aero project: a curl/200 check on
a login page never actually touches the database. This performs a genuine
Firestore read against JG's own single tenant document.

No Daraja check here - JG has no M-Pesa/Daraja integration (that's a
QC Aero-only feature).

On any failure, alerts via Resend email - not silently logged somewhere
no one checks. The WhatsApp link in the alert email is a fast-action
shortcut for the person reading the alert, not the alert mechanism itself.
"""
import datetime
import os
import sys

# `python scripts/health_check.py` puts scripts/ on sys.path, not the repo
# root - `from app import ...` fails without this, regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db, TENANT_ID, get_resend_api_key

ALERT_EMAIL = "khalif@jetman.co.ke"


def send_alert(subject, body_lines):
    try:
        import resend
        resend.api_key = get_resend_api_key()
        wa_text = "Quotecloud JG health check alert - need to check this now"
        wa_link = "https://wa.me/254701007777?text=" + wa_text.replace(" ", "%20")
        body_html = "<br>".join(body_lines)
        html = (
            f"<div style='font-family:monospace;white-space:pre-wrap'>{body_html}</div>"
            f"<p style='margin-top:20px'><a href='{wa_link}'>Message support on WhatsApp &rarr;</a></p>"
        )
        resend.Emails.send({
            "from": "Quotecloud JG Monitor <noreply@jetman.co.ke>",
            "to": [ALERT_EMAIL],
            "subject": subject,
            "html": html,
        })
    except Exception as e:
        print(f"[health_check] ALERT EMAIL FAILED: {e}")


def main():
    try:
        db.collection("tenants").document(TENANT_ID).get()
        print(f"[health_check] OK at {datetime.datetime.now().isoformat()}")
    except Exception as e:
        print(f"[health_check] FAILURE: {e}")
        send_alert(
            "\U0001F534 Quotecloud JG health check FAILED",
            [f"Checked at {datetime.datetime.now().isoformat()}", f"Firestore read failed: {e}"],
        )


if __name__ == "__main__":
    main()
