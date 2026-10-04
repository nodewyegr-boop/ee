import asyncio
import json
import os
import re
import time
from collections import defaultdict, deque
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)
REDEEM_URL = "https://gift.truemoney.com/campaign/vouchers/{code}/redeem"
PANEL_IMG = ("https://media.discordapp.net/attachments/1201027737004019782/1244129061194829897/unknown_3.jpg"
             "?ex=6ac3187a&is=6ac1c6fa&hm=3871aa3ce71fd9db828121e2b76d16bbd4639a29587c9a3428d9f0292b35c2c5"
             "&format=webp&width=550&height=275&")
PANEL_NAME = "╭•Donate"
LOG_NAME = "╰•log-Donate"
MIN_GAP, MAX_TRIES, TRY_WINDOW = 20, 5, 600   # กันคนมาเดาโค้ดผ่านบอท

E915 = "<:1000035915:1556300571659608146>"
E876 = "<a:1000035876:1555348098048462970>"
E804 = "<a:1000035804:1555025773742526615>"
E910 = "<a:1000035910:1556020302063075429>"
E866 = "<:1000035866:1555310612341461084>"
E906 = "<a:1000035906:1556014806346113185>"
E608 = "<a:1000035608:1554844998506123274>"
E725 = "<a:1000035725:1554844594175483904>"
E904 = "<a:1000035904:1556014608353861643>"
E_OK = "<a:1000035606:1554848463320129567>"
E_NO = "<:1000035790:1554970748232147004>"
E_WARN = "<a:1000035604:1554847795524141216>"


def pe(s: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(s)


def emb(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=WHITE)


# ═════════════ ฐานข้อมูล ═════════════
def q(sql: str, args=(), one=False, many=False):
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, args)
        res = cur.fetchone() if one else cur.fetchall() if many else None
        conn.commit()
        return res
    finally:
        conn.close()


def init_tables():
    q("""CREATE TABLE IF NOT EXISTS dn_config (
        guild_id INTEGER PRIMARY KEY, phone TEXT, enabled INTEGER DEFAULT 0,
        channel_id INTEGER, panel_message_id INTEGER, set_by INTEGER, log_channel_id INTEGER)""")
    q("""CREATE TABLE IF NOT EXISTS dn_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, amount REAL,
        status TEXT, code_tail TEXT, created_at INTEGER, donor_name TEXT)""")
    for sql in ("ALTER TABLE dn_config ADD COLUMN log_channel_id INTEGER",
                "ALTER TABLE dn_log ADD COLUMN donor_name TEXT"):
        try:   # อัปเกรดตารางเวอร์ชันเก่า
            q(sql)
        except Exception:
            pass


CFG_COLS = ("phone", "enabled", "channel_id", "panel_message_id", "log_channel_id")


def get_cfg(gid: int) -> dict:
    row = q(f"SELECT {', '.join(CFG_COLS)} FROM dn_config WHERE guild_id=?", (gid,), one=True)
    return dict(zip(CFG_COLS, row)) if row else {c: None for c in CFG_COLS}


def save_cfg(gid: int, **kw):
    cols = ", ".join(kw)
    ph = ", ".join("?" * len(kw))
    upd = ", ".join(f"{k}=excluded.{k}" for k in kw)
    q(f"INSERT INTO dn_config (guild_id, {cols}) VALUES (?, {ph}) ON CONFLICT(guild_id) DO UPDATE SET {upd}",
      (gid, *kw.values()))


def total_donated(gid: int) -> float:
    return q("SELECT COALESCE(SUM(amount),0) FROM dn_log WHERE guild_id=? AND status='SUCCESS'", (gid,), one=True)[0]


def user_total(gid: int, uid: int) -> float:
    return q("SELECT COALESCE(SUM(amount),0) FROM dn_log WHERE guild_id=? AND user_id=? AND status='SUCCESS'",
             (gid, uid), one=True)[0]


def mask(phone: Optional[str]) -> str:
    return f"{phone[:3]}-xxx-{phone[-4:]}" if phone and len(phone) == 10 else "ยังไม่ได้ตั้ง"


# ═════════════ ซองทรูมันนี่ ═════════════
def extract_code(text: str) -> Optional[str]:
    text = (text or "").strip()
    m = re.search(r"[?&]v=([0-9A-Za-z]+)", text)
    code = m.group(1) if m else text
    return code if re.fullmatch(r"[0-9A-Za-z]{10,64}", code) else None


ERRORS = {
    "VOUCHER_NOT_FOUND": "ไม่พบซองนี้ ลิงก์อาจผิดหรือยังไม่ได้สร้างซอง",
    "VOUCHER_EXPIRED": "ซองนี้หมดอายุเเล้ว",
    "VOUCHER_OUT_OF_STOCK": "ซองนี้ถูกรับไปเเล้ว (หรือไม่เหลือเเล้ว)",
    "TARGET_USER_NOT_FOUND": "เบอร์ปลายทางของเซิร์ฟเวอร์นี้ไม่ได้ผูก TrueMoney Wallet ให้เเจ้งเจ้าของเซิร์ฟเวอร์",
    "CANNOT_GET_OWN_VOUCHER": "ซองนี้สร้างจากเบอร์เดียวกับผู้รับ รับเองไม่ได้",
    "ACCESS_DENIED": "TrueMoney ปฏิเสธคำขอ (น่าจะโดนบล็อกไอพี) แจ้งเจ้าของบอทให้เช็กเว็บ API น้า",
    "API_DOWN": "ต่อเว็บ API ตัวกลางไม่ได้ แจ้งเจ้าของบอทให้เช็กเซิร์ฟเวอร์ API น้า",
    "UNAUTHORIZED": "รหัสลับของเว็บ API ไม่ตรงกัน (REDEEM_API_KEY) แจ้งเจ้าของบอทน้า",
    "RATE_LIMITED": "มีคนใช้ถี่เกินไป รอสักครู่เเล้วลองใหม่น้า",
}


def interpret(data):
    """คืน (สำเร็จไหม, จำนวนเงิน, รหัสสถานะ, ชื่อเจ้าของซอง)"""
    status = (data.get("status") or {}).get("code", "") if isinstance(data, dict) else ""
    if status != "SUCCESS":
        return False, 0.0, status or "UNKNOWN", ""
    d = data.get("data") or {}
    amt = (d.get("my_ticket") or {}).get("amount_baht") or (d.get("voucher") or {}).get("amount_baht") or "0"
    name = (d.get("owner_profile") or {}).get("full_name") or (d.get("voucher") or {}).get("owner_full_name") or ""
    try:
        return True, float(str(amt).replace(",", "")), status, name
    except ValueError:
        return True, 0.0, status, name


SEM = asyncio.Semaphore(2)
UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"


async def redeem(phone: str, code: str):
    api_url = os.getenv("REDEEM_API_URL", "").strip().rstrip("/")
    if api_url:   # ผ่านเว็บ API ตัวกลางของเราเอง
        try:
            async with SEM:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                    async with s.post(f"{api_url}/redeem", json={"mobile": phone, "code": code},
                                      headers={"X-API-Key": os.getenv("REDEEM_API_KEY", "")}) as r:
                        body = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            print("[donate] ต่อเว็บ API ตัวกลางไม่ได้ (เช็ก REDEEM_API_URL / เซิร์ฟเวอร์ API เปิดอยู่มั้ย)")
            return False, 0.0, "API_DOWN", ""
        if not isinstance(body, dict):
            return False, 0.0, "API_BAD_RESPONSE", ""
        if not body.get("ok"):
            print(f"[donate] redeem ไม่สำเร็จ status={body.get('status')} http={body.get('http')}")
        return (bool(body.get("ok")), float(body.get("amount") or 0), body.get("status") or "UNKNOWN",
                body.get("name") or "")

    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA,
               "Origin": "https://gift.truemoney.com", "Referer": f"https://gift.truemoney.com/campaign/?v={code}"}
    try:
        async with SEM:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                async with s.post(REDEEM_URL.format(code=code), json={"mobile": phone, "voucher_hash": code},
                                  headers=headers, proxy=os.getenv("REDEEM_PROXY") or None) as r:
                    text, http = await r.text(), r.status
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False, 0.0, "NETWORK", ""
    try:
        return interpret(json.loads(text))
    except ValueError:
        print(f"[donate] TrueMoney ตอบไม่ใช่ JSON (HTTP {http}) — น่าจะโดนบล็อกไอพีของโฮสต์")
        return False, 0.0, "ACCESS_DENIED" if http in (403, 429) else f"HTTP_{http}", ""


TRIES: dict = defaultdict(deque)


def rate_check(gid: int, uid: int) -> Optional[int]:
    now, dq = time.time(), TRIES[(gid, uid)]
    while dq and now - dq[0] > TRY_WINDOW:
        dq.popleft()
    if dq and now - dq[-1] < MIN_GAP:
        return int(MIN_GAP - (now - dq[-1])) + 1
    if len(dq) >= MAX_TRIES:
        return int(TRY_WINDOW - (now - dq[0])) + 1
    return None


# ═════════════ แผง + ปุ่ม ═════════════
def panel_embed(gid: int) -> discord.Embed:
    cfg = get_cfg(gid)
    e = emb(f"# {E915} Donate Support {E915}\n\n"
            f"{E876} Donate ซัพพอร์ตเซิฟเวอร์\n\n"
            f"{E804} ยอดโดเนท **{total_donated(gid):,.2f}** บาท\n\n"
            f"-# เงินเข้าเบอร์ {mask(cfg['phone'])} ของเจ้าของเซิร์ฟเวอร์โดยตรง • บอทไม่เก็บเงินเเละไม่เก็บลิงก์ซอง")
    e.set_image(url=PANEL_IMG)
    return e


async def refresh_panel(guild: discord.Guild):
    cfg = get_cfg(guild.id)
    ch = guild.get_channel(cfg["channel_id"] or 0)
    if ch is None or not cfg["panel_message_id"]:
        return
    try:
        msg = await ch.fetch_message(cfg["panel_message_id"])
        await msg.edit(embed=panel_embed(guild.id))
    except discord.HTTPException:
        pass


class DonateModal(discord.ui.Modal, title="โดเนทด้วยซองทรูมันนี่"):
    link = discord.ui.TextInput(label="ลิงก์ซองของขวัญ TrueMoney", max_length=300,
                                placeholder="https://gift.truemoney.com/campaign/?v=...")

    async def on_submit(self, interaction: discord.Interaction):
        guild, user = interaction.guild, interaction.user
        cfg = get_cfg(guild.id)
        if not cfg["enabled"] or not cfg["phone"]:
            return await interaction.response.send_message(embed=emb(f"{E_NO} ระบบโดเนทยังไม่เปิดน้า"), ephemeral=True)
        wait = rate_check(guild.id, user.id)
        if wait:
            return await interaction.response.send_message(
                embed=emb(f"{E_NO} ลองถี่เกินไปน้า รออีก {wait} วินาทีค่อยลองใหม่"), ephemeral=True)
        code = extract_code(self.link.value)
        if not code:
            return await interaction.response.send_message(embed=emb(
                f"{E_NO} ลิงก์ไม่ถูกต้องน้า ต้องเป็นลิงก์ซองที่ขึ้นต้น https://gift.truemoney.com/campaign/?v=..."), ephemeral=True)

        TRIES[(guild.id, user.id)].append(time.time())
        await interaction.response.defer(ephemeral=True)
        ok, amount, status, name = await redeem(cfg["phone"], code)
        q("INSERT INTO dn_log (guild_id, user_id, amount, status, code_tail, created_at, donor_name) VALUES (?,?,?,?,?,?,?)",
          (guild.id, user.id, amount, "SUCCESS" if ok else status, code[-4:], int(time.time()), name))
        if not ok:
            return await interaction.followup.send(
                embed=emb(f"{E_NO} {ERRORS.get(status, f'ทำรายการไม่สำเร็จ ({status})')}"), ephemeral=True)

        # 1) ตอบคนโดเนท
        e = discord.Embed(
            description=(f"# {E910} โดเนทสำเร็จ\n\n{E866} ชื่อ: {name or 'ไม่ระบุ'}\n\n"
                         f"{E915} จำนวน: **{amount:,.2f}** บาท"),
            color=WHITE, timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=user.display_avatar.url)
        e.set_footer(text="โดเนทเมื่อ")
        await interaction.followup.send(embed=e, ephemeral=True)

        # 2) ประกาศในห้อง log-Donate (ทุกคนเห็น)
        log_ch = guild.get_channel(cfg["log_channel_id"] or 0)
        if log_ch:
            le = discord.Embed(
                description=(f"# {E915} มีผู้ใจดีโดเนทมา {E915}\n\n"
                             f"{E906} ผู้บริจาค: {user.mention}\n\n"
                             f"{E608} จำนวนเงิน: **{amount:,.2f}** บาท\n\n"
                             f"{E725} ยอดรวมที่เคยโด: **{user_total(guild.id, user.id):,.2f}** บาท"),
                color=WHITE, timestamp=discord.utils.utcnow())
            le.set_thumbnail(url=user.display_avatar.url)
            le.set_footer(text="โดเนทเมื่อ")
            try:
                await log_ch.send(embed=le, allowed_mentions=discord.AllowedMentions(users=[user]))
            except discord.HTTPException:
                pass
        # 3) อัปเดตยอดรวมที่แผง
        await refresh_panel(guild)


class DonateView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="โดเนท", style=discord.ButtonStyle.success, emoji=pe(E915), custom_id="dn:donate")
    async def donate(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_cfg(interaction.guild.id)
        if not cfg["enabled"] or not cfg["phone"]:
            return await interaction.response.send_message(embed=emb(f"{E_NO} ระบบโดเนทยังไม่เปิดน้า"), ephemeral=True)
        await interaction.response.send_modal(DonateModal())

    @discord.ui.button(label="ท็อปโด", style=discord.ButtonStyle.primary, emoji=pe(E904), custom_id="dn:top")
    async def top(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = q("SELECT user_id, SUM(amount) s FROM dn_log WHERE guild_id=? AND status='SUCCESS' "
                 "GROUP BY user_id ORDER BY s DESC LIMIT 10", (interaction.guild.id,), many=True)
        if not rows:
            return await interaction.response.send_message(
                embed=emb(f"# {E904} ท็อปโดเนท\n\nยังไม่มีใครโดเนทเลยน้า มาเป็นคนแรกกัน"), ephemeral=True)
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{u}> — **{s:,.2f}** บาท" for i, (u, s) in enumerate(rows)]
        await interaction.response.send_message(embed=emb(f"# {E904} ท็อปโดเนท\n\n" + "\n".join(lines)), ephemeral=True)


# ═════════════ /donate (เจ้าของเซิร์ฟเวอร์) ═════════════
class PhoneModal(discord.ui.Modal, title="ตั้งเบอร์รับเงิน"):
    def __init__(self, current: Optional[str]):
        super().__init__()
        self.phone = discord.ui.TextInput(label="เบอร์ TrueMoney Wallet ที่จะรับเงิน", min_length=10, max_length=10,
                                          default=current, placeholder="0812345678")
        self.add_item(self.phone)

    async def on_submit(self, interaction: discord.Interaction):
        phone = self.phone.value.strip()
        if not re.fullmatch(r"0\d{9}", phone):
            return await interaction.response.send_message(
                embed=emb(f"{E_NO} เบอร์ต้องเป็นตัวเลข 10 หลักขึ้นต้นด้วย 0 น้า"), ephemeral=True)
        guild, me = interaction.guild, interaction.guild.me
        if not me.guild_permissions.manage_channels:
            return await interaction.response.send_message(
                embed=emb(f"{E_NO} น้องต้องมีสิทธิ์ จัดการช่อง ก่อนน้า"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        cfg = get_cfg(guild.id)
        bot_ow = discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                             read_message_history=True)
        read_only = discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False,
                                                read_message_history=True)   # ทุกคนเห็น แต่พิมพ์ไม่ได้
        try:
            panel_ch = guild.get_channel(cfg["channel_id"] or 0)
            if panel_ch is None:
                panel_ch = await guild.create_text_channel(PANEL_NAME, overwrites={guild.default_role: read_only, me: bot_ow})
            log_ch = guild.get_channel(cfg["log_channel_id"] or 0)
            if log_ch is None:
                log_ch = await guild.create_text_channel(LOG_NAME, overwrites={guild.default_role: read_only, me: bot_ow})
            if cfg["panel_message_id"]:
                try:
                    await (await panel_ch.fetch_message(cfg["panel_message_id"])).delete()
                except discord.HTTPException:
                    pass
            save_cfg(guild.id, phone=phone, enabled=1, set_by=interaction.user.id)
            msg = await panel_ch.send(embed=panel_embed(guild.id), view=DonateView())
        except discord.HTTPException as e:
            return await interaction.followup.send(
                embed=emb(f"{E_NO} สร้างห้องไม่สำเร็จ ({e.status}) เช็คสิทธิ์บอทเเล้วลองใหม่น้า"), ephemeral=True)
        save_cfg(guild.id, channel_id=panel_ch.id, log_channel_id=log_ch.id, panel_message_id=msg.id)
        await interaction.followup.send(embed=emb(
            f"{E_OK} ตั้งระบบโดเนทเเล้วน้าา เบอร์รับเงิน **{mask(phone)}**\n"
            f"{E915} ห้องโดเนท: {panel_ch.mention}\n{E915} ห้องบันทึก: {log_ch.mention}\n\n"
            f"{E_WARN} เบอร์นี้ต้องผูก TrueMoney Wallet ไว้ เเละลองโดเนทซอง 1 บาท (สร้างจากเบอร์อื่น) เพื่อทดสอบก่อนใช้จริง\n"
            "ถ้าอยากเปลี่ยนเบอร์ ใช้ /donate อีกครั้งได้เลย"), ephemeral=True)


class DonateCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()
        self.bot.add_view(DonateView())   # ปุ่มยังกดได้หลังรีสตาร์ท

    @app_commands.command(name="donate", description="ตั้งระบบรับโดเนทด้วยซองทรูมันนี่ (เจ้าของเซิร์ฟเวอร์เท่านั้น)")
    @app_commands.guild_only()
    async def donate(self, interaction: discord.Interaction):
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message(
                embed=emb(f"{E_NO} ไม่ได้น้าา ระบบนี้ใช้ได้เฉพาะเจ้าของเซิร์ฟเวอร์ เพราะเกี่ยวกับเบอร์รับเงิน"), ephemeral=True)
        await interaction.response.send_modal(PhoneModal(get_cfg(interaction.guild.id)["phone"]))


async def setup(bot: commands.Bot):
    await bot.add_cog(DonateCog(bot))
