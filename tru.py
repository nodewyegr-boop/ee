import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

import aiohttp

API_BASE = os.getenv("TRUEMONEY_API_URL", "https://gift.truemoney.com").rstrip("/")
PROXY = (os.getenv("TRUEMONEY_PROXY") or "").strip() or None
TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

try:  # ตัวเลือกเสริม
    from curl_cffi import requests as _cffi
except Exception:  # noqa: BLE001
    _cffi = None

# ข้อความที่เเสดงให้ผู้ใช้ (ภาษาไทย) ตามรหัสที่ TrueMoney ตอบกลับมา
MESSAGES = {
    "VOUCHER_NOT_FOUND": "ไม่พบซองนี้ ตรวจสอบลิงก์อีกครั้งน้า",
    "VOUCHER_EXPIRED": "ซองนี้หมดอายุเเล้ว",
    "VOUCHER_OUT_OF_STOCK": "ซองนี้ถูกรับไปหมดเเล้ว",
    "TARGET_USER_REDEEMED": "ซองนี้ถูกรับไปเเล้ว",
    "CANNOT_GET_OWN_VOUCHER": "ซองนี้เป็นของเจ้าของเบอร์รับเงิน ใช้โดเนทกับตัวเองไม่ได้น้า",
    "TARGET_USER_NOT_FOUND": "ไม่พบบัญชี TrueMoney Wallet ของเบอร์ที่รับเงิน เเจ้งเเอดมินน้า",
    "INTERNAL_ERROR": "ระบบ TrueMoney ขัดข้องชั่วคราว ลองใหม่อีกครั้งน้า",
    "INVALID_CODE": "ลิงก์ซองไม่ถูกต้อง ต้องเป็นลิงก์เเบบ https://gift.truemoney.com/campaign/?v=...",
    "INVALID_PHONE": "เบอร์รับเงินไม่ถูกต้อง เเจ้งเเอดมินน้า",
    "NETWORK": "เชื่อมต่อ TrueMoney ไม่ได้ในตอนนี้ ลองใหม่อีกครั้งน้า",
    "BLOCKED": "ระบบตรวจซองใช้งานไม่ได้ชั่วคราว เเจ้งเเอดมินน้า",
    "BAD_RESPONSE": "TrueMoney ตอบกลับผิดรูปเเบบ ลองใหม่อีกครั้งน้า",
}


@dataclass
class RedeemResult:
    ok: bool
    code: str                 # SUCCESS หรือรหัส error
    message: str              # ข้อความภาษาไทยสำหรับผู้ใช้
    satang: int = 0           # จำนวนเงินเป็นสตางค์ (กันเลขทศนิยมเพี้ยน)
    owner_name: str = ""      # ชื่อ-นามสกุลเจ้าของซอง (จาก owner_profile)
    detail: str = ""          # รายละเอียดสำหรับเเอดมิน/ล็อก (ไม่โชว์ผู้ใช้)

    @property
    def baht(self) -> float:
        return self.satang / 100


def normalize_phone(text: str) -> Optional[str]:
    """เเปลงเบอร์เป็นรูปเเบบ 0XXXXXXXXX (รับ 08x-xxx-xxxx, +668xxxxxxxx, 668xxxxxxxx)"""
    digits = re.sub(r"\D", "", text or "")
    if digits.startswith("66") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if re.fullmatch(r"0\d{9}", digits) else None


def extract_code(text: str) -> Optional[str]:
    """ดึงโค้ดซองจากลิงก์ https://gift.truemoney.com/campaign/?v=XXXX หรือโค้ดล้วนๆ"""
    text = (text or "").strip()
    m = re.search(r"[?&]v=([0-9A-Za-z]+)", text)
    if m:
        code = m.group(1)
    elif re.fullmatch(r"[0-9A-Za-z]{18,64}", text):
        code = text
    else:
        return None
    return code if 18 <= len(code) <= 64 else None


def _satang(value) -> int:
    try:
        return int((Decimal(str(value)) * 100).to_integral_value())
    except (InvalidOperation, ValueError, TypeError):
        return 0


def parse_response(http_status: int, text: str) -> RedeemResult:
    """เเปลงคำตอบจาก TrueMoney เป็น RedeemResult (ฟังก์ชันล้วนๆ ทดสอบได้โดยไม่ต้องต่อเน็ต)"""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        low = (text or "").lower()
        blocked = http_status in (403, 429) or "cloudflare" in low or "just a moment" in low
        code = "BLOCKED" if blocked else "BAD_RESPONSE"
        return RedeemResult(False, code, MESSAGES[code],
                            detail=f"HTTP {http_status} ไม่ใช่ JSON: {(text or '')[:200]!r}")
    status = (data.get("status") or {}) if isinstance(data, dict) else {}
    code = str(status.get("code") or "BAD_RESPONSE")
    if code != "SUCCESS":
        return RedeemResult(False, code, MESSAGES.get(code, f"ซองใช้ไม่ได้ ({code})"),
                            detail=f"HTTP {http_status} {status}")
    body = data.get("data") or {}
    voucher = body.get("voucher") or {}
    ticket = body.get("my_ticket") or {}
    satang = (_satang(ticket.get("amount_baht"))
              or _satang(voucher.get("redeemed_amount_baht"))
              or _satang(voucher.get("amount_baht")))
    name = ((body.get("owner_profile") or {}).get("full_name") or "").strip()
    if satang <= 0:
        return RedeemResult(False, "BAD_RESPONSE", MESSAGES["BAD_RESPONSE"],
                            detail="SUCCESS เเต่อ่านจำนวนเงินไม่ได้")
    return RedeemResult(True, "SUCCESS", "สำเร็จ", satang=satang, owner_name=name)


async def _post(url: str, payload: dict, headers: dict):
    """ส่ง POST ผ่าน proxy (ถ้าตั้งไว้) คืน (http_status, text)"""
    if _cffi is not None:
        proxies = {"http": PROXY, "https": PROXY} if PROXY else None
        async with _cffi.AsyncSession(impersonate="chrome", proxies=proxies, timeout=TIMEOUT) as s:
            r = await s.post(url, json=payload, headers=headers)
            return r.status_code, r.text
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(url, json=payload, headers={**headers, "User-Agent": UA},
                          proxy=PROXY) as r:
            return r.status, await r.text()


async def redeem(link_or_code: str, phone: str) -> RedeemResult:
    """เเลกซองอั่งเปาเข้าเบอร์ phone เเล้วคืนผลลัพธ์"""
    code = extract_code(link_or_code)
    if not code:
        return RedeemResult(False, "INVALID_CODE", MESSAGES["INVALID_CODE"])
    mobile = normalize_phone(phone)
    if not mobile:
        return RedeemResult(False, "INVALID_PHONE", MESSAGES["INVALID_PHONE"])
    url = f"{API_BASE}/campaign/vouchers/{code}/redeem"
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "Origin": API_BASE, "Referer": f"{API_BASE}/campaign/?v={code}"}
    try:
        status, text = await _post(url, {"mobile": mobile, "voucher_hash": code}, headers)
    except Exception as e:  # noqa: BLE001  (timeout / proxy ล่ม / DNS ฯลฯ)
        return RedeemResult(False, "NETWORK", MESSAGES["NETWORK"],
                            detail=f"{type(e).__name__}: {e}")
    return parse_response(status, text)
