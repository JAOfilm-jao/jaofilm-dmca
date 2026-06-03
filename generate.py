from datetime import date
from config import COPYRIGHT_OWNER, BRAND_NAME, CONTACT_EMAIL, WEBSITE

def _today():
    return date.today().strftime("%B %d, %Y")

def _header(to_name):
    return f"""{_today()}

To: {to_name}

RE: DMCA Takedown Notice – Copyright Infringement

---
"""

def _footer():
    return f"""
I have a good faith belief that the use of the copyrighted material described above is not authorized by the copyright owner, its agent, or the law.

I declare under penalty of perjury that the information in this notification is accurate and that I am the copyright owner, or am authorized to act on behalf of the copyright owner.

Sincerely,

{COPYRIGHT_OWNER}
{BRAND_NAME}
{CONTACT_EMAIL}
{WEBSITE}
Date: {_today()}
"""

def _work_block(film_title, infringing_url):
    return f"""
COPYRIGHTED WORK:
  Title:        {film_title}
  Owner:        {COPYRIGHT_OWNER} / {BRAND_NAME}
  Official URL: {WEBSITE}/films/

INFRINGING CONTENT:
  {infringing_url}
"""

def generate_host(url, domain, film_title, hosting_org, abuse_email=None):
    to_line = f"Abuse Department, {hosting_org}"
    if abuse_email:
        to_line += f"\n{abuse_email}"
    return (
        f"Subject: DMCA Takedown Notice – {domain}\n\n"
        + _header(to_line)
        + f"""I am the copyright owner of the audiovisual work listed below. I am writing pursuant to the Digital Millennium Copyright Act (17 U.S.C. § 512) to request immediate removal of infringing content hosted on your network.

COPYRIGHT OWNER:
  {COPYRIGHT_OWNER} / {BRAND_NAME}
  {CONTACT_EMAIL}
  {WEBSITE}
"""
        + _work_block(film_title, url)
        + f"""The above URL is distributing my copyrighted film "{film_title}" without any authorization or license from me. I have not granted permission to {domain} or its operators to host, stream, or distribute this content.

Please remove or disable access to the infringing material immediately.
"""
        + _footer()
    )

def generate_cloudflare(url, domain, film_title):
    return (
        f"Subject: DMCA Takedown Notice – Cloudflare-Proxied Infringement at {domain}\n\n"
        + _header("Cloudflare Trust & Safety\nabuse@cloudflare.com")
        + f"""I am the copyright owner of the audiovisual work described below. The domain {domain} is distributing my copyrighted content without authorization and appears to be using Cloudflare's proxy/CDN services.

I am requesting that Cloudflare terminate its services (proxy, CDN, and any caching) to this infringing website pursuant to the DMCA (17 U.S.C. § 512).

COPYRIGHT OWNER:
  {COPYRIGHT_OWNER} / {BRAND_NAME}
  {CONTACT_EMAIL}
  {WEBSITE}
"""
        + _work_block(film_title, url)
        + f"""The website at {domain} is hosting/streaming my copyrighted film "{film_title}" without my authorization. I have not licensed this content to {domain} or any of its operators.
"""
        + _footer()
    )

def generate_platform(url, domain, film_title, platform_name, platform_email=None):
    to_line = f"{platform_name} DMCA / Content Team"
    if platform_email:
        to_line += f"\n{platform_email}"
    return (
        f"Subject: DMCA Copyright Infringement Notice – {film_title}\n\n"
        + _header(to_line)
        + f"""I am the copyright owner of the audiovisual work described below and am requesting immediate removal of infringing content from {platform_name}.

COPYRIGHT OWNER:
  {COPYRIGHT_OWNER} / {BRAND_NAME}
  {CONTACT_EMAIL}
  {WEBSITE}
"""
        + _work_block(film_title, url)
        + f"""This video has been uploaded to {platform_name} without my authorization. I have not licensed "{film_title}" to {platform_name} or any of its users. This content is exclusively available through my official channels.

Please remove the infringing content and prevent re-upload.
"""
        + _footer()
    )

def generate_google_checklist(url, film_title):
    return f"""GOOGLE DMCA – 行動清單
================================

提交頁面：https://support.google.com/legal/troubleshooter/1114905

填表時需要的資訊：

  Your name:              {COPYRIGHT_OWNER}
  Company (optional):     {BRAND_NAME}
  Email:                  {CONTACT_EMAIL}
  Country:                Taiwan

  Copyrighted work:       {film_title}
  Description:            Original film produced and exclusively owned by {BRAND_NAME} ({WEBSITE})

  Infringing URL:         {url}

  I am:                   The copyright owner

  Signature:              {COPYRIGHT_OWNER}

注意：Google 通常 7–14 天處理，完成後該 URL 不再出現在搜尋結果。
"""
