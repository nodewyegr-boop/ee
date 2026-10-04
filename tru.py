import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

import aiohttp

API_URL = os.getenv("DONATE_API_URL", "https://api.kasawa.pro/api/wallet/topup")
TIMEOUT = 25

# รหัส error ของ TrueMoney → ข้อความไทย (เช็คจากข้อความที่ API ตอบกลับมา)
MESSAGES = {
    "VOUCHER_NOT_FOUND": "ไม่พบซองนี้ ตรวจสอบลิงก์อีกครั้งน้า",
    "VOUCHER_EXPIRED": "ซองนี้หมดอายุเเล้ว",
    "VOUCHER_OUT_OF_STOCK": "ซองนี้ถูกรับไปหมดเเล้ว",
    "TARGET_USER_REDEEMED": "ซองนี้ถูกรับไปเเล้ว",
    "CANNOT_GET_OWN_VOUCHER": "ซองนี้เป็นของเจ้าของเบอร์รับเงิน ใช้โดเนทกับตัวเองไม่ได้น้า",
    "TARGET_USER_NOT_FOUND": "ไม่พบบัญชี TrueMoney Wallet ของเบอร์ที่รับเงิน เเจ้งเจ้าของเซิฟน้า",
    "INTERNAL_ERROR": "ระบบ TrueMoney ขัดข้องชั่วคราว ลองใหม่อีกครั้งน้า",
}
GENERIC = {
    "INVALID_CODE": "ลิงก์ซองไม่ถูกต้อง ต้องเป็นลิงก์เเบบ https://gift.truemoney.com/campaign/?v=...",
    "INVALID_PHONE": "เบอร์รับเงินไม่ถูกต้อง เเจ้งเจ้าของเซิฟน้า",
    "NETWORK": "เชื่อมต่อระบบตรวจซองไม่ได้ในตอนนี้ ลองใหม่อีกครั้งน้า",
    "RATE_LIMIT": "ระบบตรวจซองถูกใช้งานถี่เกินไป รอสักครู่เเล้วลองใหม่น้า",
    "BAD_RESPONSE": "ระบบตรวจซองตอบกลับผิดรูปเเบบ ลองใหม่อีกครั้งน้า",
    "FAILED": "ซองนี้ใช้โดเนทไม่ได้ ตรวจสอบลิงก์เเล้วลองใหม่น้า",
}


@dataclass
class RedeemResult:
    ok: bool
    code: str                 # SUCCESS หรือรหัส error
    message: str              # ข้อความภาษาไทยสำหรับผู้ใช้
    satang: int = 0           # จำนวนเงินเป็นสตางค์ (กันเลขทศนิยมเพี้ยน)
    owner_name: str = ""      # ชื่อ-นามสกุลเจ้าของซอง (owner_profile.full_name)
    detail: str = ""          # รายละเอียดสำหรับล็อกของเจ้าของบอท (ไม่โชว์ผู้ใช้)

    @property
    def baht(self) -> float:
        return self.satang / 100


def normalize_phone(text: str) -> Optional[str]:
    """เเปลงเบอร์เป็น 0XXXXXXXXX (รับ 08x-xxx-xxxx, +668xxxxxxxx, 668xxxxxxxx)"""
    digits = re.sub(r"\D", "", text or "")
    if digits.startswith("66") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if re.fullmatch(r"0\d{9}", digits) else None


def extract_code(text: str) -> Optional[str]:
    """ดึงโค้ดซองจากลิงก์ https://gift.truemoney.com/campaign/?v=XXXX หรือโค้ดล้วนๆ"""
    text = (text or "").strip()
    m = re.search(r"[?&]v=([0-9A-Za-z]+)", text)
    code = m.group(1) if m else (text if re.fullmatch(r"[0-9A-Za-z]{18,64}", text) else None)
    return code if code and 18 <= len(code) <= 64 else None


def _satang(value) -> int:
    try:
        return int((Decimal(str(value)) * 100).to_integral_value())
    except (InvalidOperation, ValueError, TypeError):
        return 0


def parse_response(http_status: int, text: str) -> RedeemResult:
    """เเปลงคำตอบของ API เป็น RedeemResult (ฟังก์ชันล้วนๆ ทดสอบได้โดยไม่ต้องต่อเน็ต)"""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        code = "RATE_LIMIT" if http_status == 429 else "BAD_RESPONSE"
        return RedeemResult(False, code, GENERIC[code],
                            detail=f"HTTP {http_status} ไม่ใช่ JSON: {(text or '')[:200]!r}")
    if not isinstance(data, dict):
        return RedeemResult(False, "BAD_RESPONSE", GENERIC["BAD_RESPONSE"], detail=str(data)[:200])

    msg = data.get("message")
    if data.get("status") is True and isinstance(msg, dict) and msg.get("voucher"):
        voucher = msg["voucher"] or {}
        ticket = msg.get("my_ticket") or {}
        satang = (_satang(ticket.get("amount_baht")) or _satang(voucher.get("redeemed_amount_baht"))
                  or _satang(voucher.get("amount_baht")))
        if satang <= 0:
            return RedeemResult(False, "BAD_RESPONSE", GENERIC["BAD_RESPONSE"],
                                detail="status=True เเต่อ่านจำนวนเงินไม่ได้")
        name = ((msg.get("owner_profile") or {}).get("full_name") or ticket.get("full_name") or "").strip()
        return RedeemResult(True, "SUCCESS", "สำเร็จ", satang=satang, owner_name=name)

    # ไม่สำเร็จ: หารหัส error ของ TrueMoney ในข้อความที่ตอบกลับมา
    raw = msg if isinstance(msg, str) else json.dumps(msg, ensure_ascii=False) if msg else ""
    raw = raw or json.dumps(data, ensure_ascii=False)
    upper = raw.upper()
    for code, th in MESSAGES.items():
        if code in upper:
            return RedeemResult(False, code, th, detail=f"HTTP {http_status} {raw[:200]}")
    code = "RATE_LIMIT" if http_status == 429 else "FAILED"
    return RedeemResult(False, code, GENERIC[code], detail=f"HTTP {http_status} {raw[:200]}")


async def _post(payload: dict):
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(API_URL, json=payload) as r:
            return r.status, await r.text()


async def redeem(link_or_code: str, phone: str) -> RedeemResult:
    """เเลกซองอั่งเปาเข้าเบอร์ phone เเล้วคืนผลลัพธ์"""
    code = extract_code(link_or_code)
    if not code:
        return RedeemResult(False, "INVALID_CODE", GENERIC["INVALID_CODE"])
    mobile = normalize_phone(phone)
    if not mobile:
        return RedeemResult(False, "INVALID_PHONE", GENERIC["INVALID_PHONE"])
    link = f"https://gift.truemoney.com/campaign/?v={code}"
    try:
        status, text = await _post({"phone": mobile, "vouch": link})
    except Exception as e:  # noqa: BLE001  (timeout / DNS / เซิร์ฟเวอร์ API ล่ม)
        return RedeemResult(False, "NETWORK", GENERIC["NETWORK"], detail=f"{type(e).__name__}: {e}")
    return parse_response(status, text)
