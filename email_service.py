import os
import json
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


# ─── Resend Email Configuration ────────────────────────────────
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")

# Store last error for debugging
last_email_result = {"status": "not_called"}


def send_otp_email(to_email: str, otp_code: str, user_name: str) -> bool:
    global last_email_result
    
    if not RESEND_API_KEY:
        last_email_result = {"status": "error", "detail": "RESEND_API_KEY not set"}
        print(f"\n⚠️  RESEND_API_KEY not set. OTP for {to_email}: {otp_code}")
        return False

    html_body = f"""
<!DOCTYPE html>
<html>
<body style="margin:0; padding:0; background-color:#F5F5F0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#F5F5F0; padding: 40px 20px;">
    <tr>
      <td align="center">
        <table width="100%" style="max-width:420px; background:#FFFFFF; border-radius:16px; overflow:hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">
          <tr>
            <td style="background-color:#1C1917; padding: 32px 24px; text-align:center;">
              <div style="font-size:40px; margin-bottom:8px;">&#9749;</div>
              <h1 style="color:#FFFFFF; font-size:22px; margin:0; font-weight:800;">Cafe Diary</h1>
            </td>
          </tr>
          <tr>
            <td style="padding: 32px 24px;">
              <p style="color:#44403C; font-size:15px; margin:0 0 8px;">Hi <strong>{user_name}</strong>,</p>
              <p style="color:#78716C; font-size:14px; margin:0 0 24px; line-height:1.5;">
                Enter this code to verify your email and start your coffee journey.
              </p>
              <div style="background:#F5F5F0; border-radius:12px; padding:20px; text-align:center; margin-bottom:24px; border: 1px solid #E7E5E4;">
                <span style="font-size:32px; font-weight:800; letter-spacing:8px; color:#1C1917;">{otp_code}</span>
              </div>
              <p style="color:#A8A29E; font-size:12px; margin:0; text-align:center;">
                This code expires in <strong>10 minutes</strong>
              </p>
            </td>
          </tr>
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

    payload = json.dumps({
        "from": "Cafe Diary <onboarding@resend.dev>",
        "to": [to_email],
        "subject": f"Your Cafe Diary verification code: {otp_code}",
        "html": html_body,
    }).encode("utf-8")

    req = Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "CafeDiary/1.0",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
            result = json.loads(body)
            last_email_result = {"status": "success", "resend_id": result.get("id"), "to": to_email}
            print(f"✅ OTP email sent to {to_email} (id: {result.get('id')})")
            return True
    except HTTPError as e:
        body = e.read().decode()
        last_email_result = {"status": "http_error", "code": e.code, "body": body, "to": to_email}
        print(f"❌ HTTP {e.code} from Resend: {body}")
        return False
    except URLError as e:
        last_email_result = {"status": "url_error", "reason": str(e.reason), "to": to_email}
        print(f"❌ URL Error: {e.reason}")
        return False
    except Exception as e:
        last_email_result = {"status": "exception", "error": str(e), "to": to_email}
        print(f"❌ Exception: {e}")
        return False
