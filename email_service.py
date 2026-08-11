import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ─── Gmail SMTP Configuration ──────────────────────────────────
# Set these as environment variables on Render:
#   SMTP_EMAIL = your Gmail address
#   SMTP_PASSWORD = your Gmail App Password (NOT your regular password)

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_otp_email(to_email: str, otp_code: str, user_name: str) -> bool:
    """
    Send a 6-digit OTP verification email via Gmail SMTP.
    Returns True if sent successfully, False otherwise.
    """
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        print(f"\n⚠️  SMTP not configured. OTP for {to_email}: {otp_code}")
        return False

    # Build the email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Cafe Diary - Your verification code is {otp_code}"
    msg["From"] = f"Cafe Diary <{SMTP_EMAIL}>"
    msg["To"] = to_email

    # Plain text fallback
    text_body = f"""
Hi {user_name},

Your Cafe Diary verification code is: {otp_code}

This code expires in 10 minutes. If you didn't create an account, please ignore this email.

- Cafe Diary Team
"""

    # HTML email (looks great on mobile)
    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#F5F5F0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#F5F5F0; padding: 40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" style="max-width:420px; background:#FFFFFF; border-radius:16px; overflow:hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">
          <!-- Header -->
          <tr>
            <td style="background-color:#1C1917; padding: 32px 24px; text-align:center;">
              <div style="font-size:40px; margin-bottom:8px;">&#9749;</div>
              <h1 style="color:#FFFFFF; font-size:22px; margin:0; font-weight:800; letter-spacing:-0.3px;">Cafe Diary</h1>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding: 32px 24px;">
              <p style="color:#44403C; font-size:15px; margin:0 0 8px;">Hi <strong>{user_name}</strong>,</p>
              <p style="color:#78716C; font-size:14px; margin:0 0 24px; line-height:1.5;">
                Enter this code to verify your email and start your coffee journey.
              </p>
              <!-- OTP Code Box -->
              <div style="background:#F5F5F0; border-radius:12px; padding:20px; text-align:center; margin-bottom:24px; border: 1px solid #E7E5E4;">
                <span style="font-size:32px; font-weight:800; letter-spacing:8px; color:#1C1917;">{otp_code}</span>
              </div>
              <p style="color:#A8A29E; font-size:12px; margin:0; text-align:center;">
                This code expires in <strong>10 minutes</strong>
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding: 16px 24px 24px; border-top: 1px solid #F5F5F0;">
              <p style="color:#A8A29E; font-size:11px; margin:0; text-align:center; line-height:1.5;">
                If you didn't create a Cafe Diary account, you can safely ignore this email.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        print(f"✅ OTP email sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email to {to_email}: {e}")
        print(f"   Fallback — OTP code: {otp_code}")
        return False
