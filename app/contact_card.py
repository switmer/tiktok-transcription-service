"""ScribeTok first-time SMS contact-card (vCard) helpers.

Delivery (authoritative Twilio docs, 2026-11-07):
- MMS accepts ``text/vcard`` and ``text/x-vcard`` via ``MediaUrl``.
  ``application/vcard`` is WhatsApp-only, not MMS.
  Source: https://www.twilio.com/docs/messaging/guides/accepted-mime-types
- Serve the .vcf publicly so Twilio can GET/HEAD it. Use
  ``Content-Type: text/x-vcard``, ``Content-Disposition: inline; filename=...``,
  and ``Cache-Control: no-cache``.
  Source: https://www.twilio.com/en-us/blog/send-vcard-twilio-sms
- Filename must be <= 20 ASCII letters/numbers/._-
- MMS is US/Canada-centric; some carriers render a download instead of a
  native contact card. The SMS body always includes the same HTTPS .vcf URL.
- Recipients must tap to save. PHOTO display depends on the handset/OS.
  This code never claims the avatar will auto-update later.

Policy: only genuinely new ``sms_users`` rows (insert path) are eligible.
Existing / legacy users are never backfilled. Compliance keywords never
trigger a send. Failures never raise into the inbound transcription path.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

VCARD_FILENAME = "ScribeTok.vcf"
PHOTO_FILENAME = "scribetok-icon.jpg"
VCARD_FN = "ScribeTok"
VCARD_ORG = "ScribeTok"

# Twilio reserved keywords (exact single-token inbound). Do not send a card.
# https://help.twilio.com/articles/223134027-Twilio-support-for-opt-out-keywords-SMS-STOP-filtering
OPT_OUT_KEYWORDS = frozenset({
    "stop", "stopall", "unsubscribe", "end", "quit", "revoke", "optout", "cancel",
})
OPT_IN_KEYWORDS = frozenset({"start", "yes", "unstop"})
HELP_KEYWORDS = frozenset({"help", "info"})
COMPLIANCE_KEYWORDS = OPT_OUT_KEYWORDS | OPT_IN_KEYWORDS | HELP_KEYWORDS

DEFAULT_BUSINESS_TEL = "+17744727423"
DEFAULT_WEBSITE = "https://scribetok.com"
DEFAULT_API_BASE = "https://api.scribetok.com"

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_BRAND_DIR = os.path.join(_APP_DIR, "static", "brand")
_JPEG_CANDIDATES = (
    os.path.join(_BRAND_DIR, PHOTO_FILENAME),
    os.path.join(_APP_DIR, "ScribeTok_icon2.png"),
)


def contact_card_enabled() -> bool:
    raw = (os.getenv("CONTACT_CARD_ENABLED") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def is_compliance_keyword(body: str) -> bool:
    """True for exact reserved STOP/START/HELP tokens (case-insensitive)."""
    if not body:
        return False
    return body.strip().lower() in COMPLIANCE_KEYWORDS


def escape_vcard_text(value: str) -> str:
    """RFC 6350 text escaping for FN/ORG/NOTE (backslash, newline, comma, semicolon)."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold_vcard_line(line: str, limit: int = 75) -> str:
    """Fold a content line per RFC 6350 §3.2 (CRLF + space, 75 octets)."""
    raw = line.encode("utf-8")
    if len(raw) <= limit:
        return line
    chunks = []
    remaining = raw
    first = True
    while remaining:
        budget = limit if first else limit - 1
        take = remaining[:budget]
        # Don't split in the middle of a UTF-8 sequence.
        while take and (take[-1] & 0xC0) == 0x80:
            take = take[:-1]
        if not take:
            take = remaining[:budget]
        piece = take.decode("utf-8", errors="strict")
        chunks.append(piece if first else " " + piece)
        remaining = remaining[len(take):]
        first = False
    return "\r\n".join(chunks)


def normalize_business_tel(raw: Optional[str]) -> str:
    """E.164 from configured sender. Never invent a personal number."""
    candidate = (raw or os.getenv("TWILIO_PHONE_NUMBER") or DEFAULT_BUSINESS_TEL).strip()
    digits = re.sub(r"\D", "", candidate)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if candidate.startswith("+") and 10 <= len(digits) <= 15:
        return f"+{digits}"
    logger.warning("Unusable TWILIO_PHONE_NUMBER %r; falling back to configured default", candidate)
    return DEFAULT_BUSINESS_TEL


def public_website_url() -> str:
    return (
        os.getenv("FRONTEND_URL")
        or os.getenv("PUBLIC_WEBSITE_URL")
        or DEFAULT_WEBSITE
    ).rstrip("/")


def public_api_base_url() -> str:
    return (
        os.getenv("CONTACT_CARD_MEDIA_BASE_URL")
        or os.getenv("BASE_URL")
        or DEFAULT_API_BASE
    ).rstrip("/")


def vcard_public_path() -> str:
    return "/api/public/contact/ScribeTok.vcf"


def photo_public_path() -> str:
    return "/api/public/contact/scribetok-icon.jpg"


def vcard_public_url() -> str:
    return f"{public_api_base_url()}{vcard_public_path()}"


def photo_public_url() -> str:
    return f"{public_api_base_url()}{photo_public_path()}"


def load_photo_jpeg_bytes() -> Optional[bytes]:
    """Load the square brand JPEG. PNG sources are converted. Missing file → None."""
    jpg_path = os.path.join(_BRAND_DIR, PHOTO_FILENAME)
    if os.path.isfile(jpg_path):
        with open(jpg_path, "rb") as handle:
            data = handle.read()
        if data[:2] == b"\xff\xd8":
            return data
    png_path = os.path.join(_BRAND_DIR, "scribetok-icon.png")
    for path in (png_path, os.path.join(_APP_DIR, "ScribeTok_icon2.png")):
        if not os.path.isfile(path):
            continue
        try:
            from PIL import Image
            from io import BytesIO
            image = Image.open(path)
            if image.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", image.size, (255, 255, 255))
                bg.paste(image, mask=image.split()[-1])
                image = bg
            else:
                image = image.convert("RGB")
            buf = BytesIO()
            image.save(buf, format="JPEG", quality=88, optimize=True)
            return buf.getvalue()
        except Exception as exc:
            logger.warning("Could not convert brand icon %s: %s", path, exc)
    return None


def build_vcard(
    tel: Optional[str] = None,
    website: Optional[str] = None,
    photo_jpeg: Optional[bytes] = None,
    include_photo: bool = True,
) -> str:
    """RFC 2426/6350 vCard 3.0 (widest MMS / iOS client support). CRLF endings."""
    tel_value = normalize_business_tel(tel)
    url_value = (website or public_website_url()).strip()
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        "PRODID:-//ScribeTok//Contact Card//EN",
        fold_vcard_line(f"FN:{escape_vcard_text(VCARD_FN)}"),
        fold_vcard_line(f"N:{escape_vcard_text(VCARD_FN)};;;;"),
        fold_vcard_line(f"ORG:{escape_vcard_text(VCARD_ORG)}"),
        f"TEL;TYPE=CELL,VOICE,PREF:{tel_value}",
        fold_vcard_line(f"URL:{url_value}"),
        "NOTE:Save this contact so ScribeTok texts are easier to recognize. "
        "The avatar appears only if your phone imports contact images.",
    ]
    jpeg = photo_jpeg if photo_jpeg is not None else (load_photo_jpeg_bytes() if include_photo else None)
    if jpeg:
        b64 = base64.b64encode(jpeg).decode("ascii")
        # vCard 3.0 embedded photo — TYPE=JPEG is the widely implemented form.
        photo_line = f"PHOTO;ENCODING=b;TYPE=JPEG:{b64}"
        lines.append(fold_vcard_line(photo_line))
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def welcome_sms_body(vcard_url: Optional[str] = None) -> str:
    url = vcard_url or vcard_public_url()
    return (
        "Save ScribeTok to your contacts so these texts are easier to spot.\n"
        "If a contact card is attached, tap it to add us. "
        "Some phones show a file instead — open this link to download the same card:\n"
        f"{url}"
    )


def vcard_http_headers() -> dict:
    return {
        "Content-Type": "text/x-vcard; charset=utf-8",
        "Content-Disposition": f'inline; filename="{VCARD_FILENAME}"',
        "Cache-Control": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }


def photo_http_headers() -> dict:
    return {
        "Content-Type": "image/jpeg",
        "Content-Disposition": f'inline; filename="{PHOTO_FILENAME}"',
        "Cache-Control": "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    }


async def claim_contact_card_send(phone: str, supabase_client) -> bool:
    """Atomically claim the one-time send. True only for the winning caller."""
    if not supabase_client:
        return False
    try:
        import asyncio
        response = await asyncio.to_thread(
            lambda: supabase_client.rpc(
                "claim_sms_contact_card",
                {"p_phone": phone},
            ).execute()
        )
        data = response.data
        if data is True:
            return True
        if isinstance(data, list) and data:
            return bool(data[0])
        return bool(data)
    except Exception as exc:
        logger.error("claim_sms_contact_card failed for %s: %s", phone, exc)
        return False


async def complete_contact_card_send(
    phone: str,
    supabase_client,
    success: bool,
    error: Optional[str] = None,
    message_sid: Optional[str] = None,
) -> None:
    if not supabase_client:
        return
    try:
        import asyncio
        await asyncio.to_thread(
            lambda: supabase_client.rpc(
                "complete_sms_contact_card",
                {
                    "p_phone": phone,
                    "p_success": success,
                    "p_error": (error or "")[:500] or None,
                    "p_message_sid": message_sid,
                },
            ).execute()
        )
    except Exception as exc:
        logger.error("complete_sms_contact_card failed for %s: %s", phone, exc)


async def send_welcome_contact_card(
    phone: str,
    supabase_client=None,
    send_fn=None,
) -> Tuple[str, Optional[str]]:
    """Claim + send MMS vCard. Never raises. Returns (status, detail).

    status: disabled | skipped | sent | failed
    """
    if not contact_card_enabled():
        return "disabled", "CONTACT_CARD_ENABLED is off"
    phone = (phone or "").strip()
    if not phone:
        return "skipped", "missing phone"

    claimed = await claim_contact_card_send(phone, supabase_client)
    if not claimed:
        return "skipped", "not claimed (existing user, in-flight, or already sent)"

    media_url = vcard_public_url()
    body = welcome_sms_body(media_url)
    try:
        if send_fn is None:
            from .sms import SMSHandler
            send_fn = SMSHandler.send_sms
        ok = await send_fn(phone, body, media_url=media_url)
        if ok:
            await complete_contact_card_send(phone, supabase_client, True, message_sid=None)
            return "sent", media_url
        await complete_contact_card_send(
            phone, supabase_client, False, error="twilio_send_returned_false"
        )
        return "failed", "twilio_send_returned_false"
    except Exception as exc:
        logger.error("welcome contact card send failed for %s: %s", phone, exc)
        await complete_contact_card_send(phone, supabase_client, False, error=str(exc)[:500])
        return "failed", str(exc)[:200]
