import hmac
import os
import re
import time
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request

API_KEY = os.environ.get("API_KEY", "")
if len(API_KEY) < 16:
    raise SystemExit("ต้องตั้งตัวแปร API_KEY ให้ยาวอย่างน้อย 16 ตัวอักษร")
PROXY_URL = os.environ.get("PROXY_URL", "").strip()
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

URL = "https://gift.truemoney.com/campaign/vouchers/{code}/redeem"
HEADERS = {
    "Content-Type": "application/json", "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Origin": "https://gift.truemoney.com",
}
RATE_PER_MIN = 30
HITS = defaultdict(deque)
app = Flask(__name__)


def mask(s: str) -> str:
    return s[:3] + "…" + s[-3:] if len(s) > 8 else "***"


def authorized() -> bool:
    return hmac.compare_digest(request.headers.get("X-API-Key", "").encode(), API_KEY.encode())


@app.get("/")
def health():
    return jsonify(ok=True, service="truemoney-redeem", proxy=bool(PROXIES))


@app.get("/diag")
def diag():
    """เช็กไอพีขาออก + TrueMoney บล็อกมั้ย (ไม่ได้รับซองจริง)"""
    if not authorized():
        return jsonify(ok=False, status="UNAUTHORIZED"), 401
    out = {"proxy": bool(PROXIES)}
    try:
        out["outbound_ip"] = requests.get("https://api.ipify.org", timeout=8, proxies=PROXIES).text.strip()
    except requests.RequestException as e:
        out["outbound_ip"] = f"error: {type(e).__name__}"
    try:
        r = requests.get("https://gift.truemoney.com/campaign/", headers=HEADERS, timeout=10, proxies=PROXIES)
        body = r.text.lower()
        out["truemoney_http"] = r.status_code
        out["blocked_hint"] = r.status_code in (403, 429) or "just a moment" in body or "attention required" in body
    except requests.RequestException as e:
        out["truemoney_http"] = f"error: {type(e).__name__}"
        out["blocked_hint"] = True
    return jsonify(out)


@app.post("/redeem")
def redeem():
    if not authorized():
        return jsonify(ok=False, status="UNAUTHORIZED"), 401
    now, dq = time.time(), HITS[request.remote_addr]
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= RATE_PER_MIN:
        return jsonify(ok=False, status="RATE_LIMITED"), 429
    dq.append(now)

    data = request.get_json(silent=True) or {}
    mobile, code = str(data.get("mobile", "")), str(data.get("code", ""))
    if not re.fullmatch(r"0\d{9}", mobile) or not re.fullmatch(r"[0-9A-Za-z]{10,64}", code):
        return jsonify(ok=False, status="BAD_REQUEST"), 400
    try:
        r = requests.post(URL.format(code=code), json={"mobile": mobile, "voucher_hash": code},
                          headers={**HEADERS, "Referer": f"https://gift.truemoney.com/campaign/?v={code}"},
                          timeout=15, proxies=PROXIES)
    except requests.RequestException:
        print(f"[redeem] {mask(code)} → NETWORK error")
        return jsonify(ok=False, status="NETWORK", http=0)
    try:
        j = r.json()
    except ValueError:
        status = "ACCESS_DENIED" if r.status_code in (403, 429) else f"HTTP_{r.status_code}"
        print(f"[redeem] {mask(code)} → ไม่ใช่ JSON (HTTP {r.status_code}) {status}")
        return jsonify(ok=False, status=status, http=r.status_code)

    status = (j.get("status") or {}).get("code", "UNKNOWN") if isinstance(j, dict) else "UNKNOWN"
    amount, name = 0.0, ""
    if status == "SUCCESS":
        d = j.get("data") or {}
        amt = (d.get("my_ticket") or {}).get("amount_baht") or (d.get("voucher") or {}).get("amount_baht") or "0"
        try:
            amount = float(str(amt).replace(",", ""))
        except ValueError:
            pass
        name = ((d.get("owner_profile") or {}).get("full_name")
                or (d.get("voucher") or {}).get("owner_full_name") or "")
    print(f"[redeem] {mask(code)} → {status} ({amount})")
    return jsonify(ok=status == "SUCCESS", amount=amount, name=name, status=status, http=r.status_code)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
