import asyncio
import hashlib
import io
import os
import sqlite3
import time
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import truemoney
from database import db

# ───────────────────────── ตั้งค่า ─────────────────────────
DONATE_CHANNEL = "╭•donate"          # Discord จะเเปลงชื่อห้องเป็นตัวพิมพ์เล็กให้เอง
LOG_CHANNEL = "╰•log-donate"
COLOR = 0xF2A6C8
TRY_COOLDOWN = 8                      # กันกดโดเนทรัวๆ (วินาที)
TOP_LIMIT = 10
BANNER_URL = ("https://media.discordapp.net/attachments/1201027737004019782/1244129061194829897/"
              "unknown_3.jpg?ex=6ac3187a&is=6ac1c6fa&hm=3871aa3ce71fd9db828121e2b76d16bbd4639a29587c9a3428d9f0292b35c2c5"
              "&format=webp&width=550&height=275&")

E_DONATE = "<:1000035915:1556300571659608146>"
E_HEART = "<a:1000035876:1555348098048462970>"
E_TOTAL = "<a:1000035804:1555025773742526615>"
E_OK = "<a:1000035910:1556020302063075429>"
E_NAME = "<:1000035866:1555310612341461084>"
E_DONOR = "<a:1000035906:1556014806346113185>"
E_AMOUNT = "<a:1000035608:1554844998506123274>"
E_SUM = "<a:1000035725:1554844594175483904>"
E_TOP = "<a:1000035904:1556014608353861643>"


def emo(s: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(s)


def baht(satang: int) -> str:
    return f"{satang // 100:,} บาท" if satang % 100 == 0 else f"{satang / 100:,.2f} บาท"


def sniff_ext(data: bytes) -> Optional[str]:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


# ───────────────────────── ฐานข้อมูล ─────────────────────────
def _init_tables():
    conn = db.get_connection()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS donate_config (
            guild_id INTEGER PRIMARY KEY, phone TEXT NOT NULL, channel_id INTEGER,
            log_channel_id INTEGER, panel_msg_id INTEGER);
        CREATE TABLE IF NOT EXISTS donate_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            satang INTEGER NOT NULL, name TEXT, code_hash TEXT UNIQUE, ts REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_donate_guild_user ON donate_log (guild_id, user_id);
        CREATE TABLE IF NOT EXISTS donate_assets (
            name TEXT PRIMARY KEY, data BLOB, ext TEXT);
        """)
        conn.commit()
    finally:
        conn.close()


def _run(sql, params=(), fetch=None):
    conn = db.get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        result = cur.rowcount
        if fetch == "one":
            result = cur.fetchone()
        elif fetch == "all":
            result = cur.fetchall()
        conn.commit()
        return result
    finally:
        conn.close()


async def q(sql, params=(), fetch=None):
    return await asyncio.to_thread(_run, sql, params, fetch)


async def get_config(gid: int):
    return await q("SELECT * FROM donate_config WHERE guild_id=?", (gid,), "one")


async def total_satang(gid: int) -> int:
    r = await q("SELECT COALESCE(SUM(satang),0) AS t FROM donate_log WHERE guild_id=?", (gid,), "one")
    return int(r["t"])


async def user_total(gid: int, uid: int) -> int:
    r = await q("SELECT COALESCE(SUM(satang),0) AS t FROM donate_log WHERE guild_id=? AND user_id=?",
                (gid, uid), "one")
    return int(r["t"])


async def top_donors(gid: int, limit: int):
    return await q("SELECT user_id, SUM(satang) AS t FROM donate_log WHERE guild_id=? "
                   "GROUP BY user_id ORDER BY t DESC, MIN(ts) ASC LIMIT ?", (gid, limit), "all")


async def code_used(code_hash: str) -> bool:
    return await q("SELECT 1 FROM donate_log WHERE code_hash=?", (code_hash,), "one") is not None


async def add_donation(gid, uid, satang, name, code_hash) -> bool:
    try:
        await q("INSERT INTO donate_log (guild_id, user_id, satang, name, code_hash, ts) "
                "VALUES (?,?,?,?,?,?)", (gid, uid, satang, name, code_hash, time.time()))
        return True
    except sqlite3.IntegrityError:
        return False


# ───────────────────────── Embed ─────────────────────────
def panel_embed(total: int, image_name: Optional[str]) -> discord.Embed:
    e = discord.Embed(
        title=f"{E_DONATE} Donate Support {E_DONATE}", colour=COLOR,
        description=(f"{E_HEART} Donate ซัพพอร์ตเซิฟเวอร์\n\n"
                     f"{E_TOTAL} ยอดโดเนท {baht(total)}"))
    if image_name:
        e.set_image(url=f"attachment://{image_name}")
    return e


def success_embed(user: discord.abc.User, name: str, satang: int) -> discord.Embed:
    e = discord.Embed(
        title=f"{E_OK} โดเนทสำเร็จ", colour=COLOR, timestamp=discord.utils.utcnow(),
        description=(f"{E_NAME} ชื่อ: {name or 'ไม่ระบุ'}\n"
                     f"{E_DONATE} จำนวน: {baht(satang)}"))
    e.set_thumbnail(url=user.display_avatar.url)
    return e


def log_embed(user: discord.abc.User, satang: int, user_sum: int) -> discord.Embed:
    e = discord.Embed(
        title=f"{E_DONATE} มีผู้ใจดีโดเนทมา {E_DONATE}", colour=COLOR, timestamp=discord.utils.utcnow(),
        description=(f"{E_DONOR} ผู้บริจาค: {user.mention}\n"
                     f"{E_AMOUNT} จำนวนเงิน: {baht(satang)}\n"
                     f"{E_SUM} ยอดรวมที่เคยโด: {baht(user_sum)}"))
    e.set_thumbnail(url=user.display_avatar.url)
    return e


def err_embed(text: str) -> discord.Embed:
    return discord.Embed(description=text, colour=COLOR)


# ───────────────────────── UI ─────────────────────────
def is_server_owner(interaction: discord.Interaction) -> bool:
    """เจ้าของเซิฟเวอร์เท่านั้น (ไม่รวมเเอดมิน/เจ้าของบอท)"""
    return interaction.guild is not None and interaction.user.id == interaction.guild.owner_id


NOT_OWNER = "คำสั่งนี้ใช้ได้เฉพาะ **เจ้าของเซิฟเวอร์** เท่านั้นน้า"


class PhoneModal(discord.ui.Modal, title="ตั้งค่าระบบโดเนท"):
    phone = discord.ui.TextInput(label="เบอร์ TrueMoney Wallet ที่จะรับเงิน", placeholder="08xxxxxxxx",
                                 min_length=9, max_length=15)

    def __init__(self, cog):
        super().__init__(timeout=600)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not is_server_owner(interaction):
            return await interaction.response.send_message(embed=err_embed(NOT_OWNER), ephemeral=True)
        phone = truemoney.normalize_phone(self.phone.value)
        if not phone:
            return await interaction.response.send_message(
                embed=err_embed("เบอร์ไม่ถูกต้อง ต้องเป็นเบอร์มือถือไทย 10 หลัก เช่น 0812345678"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            ch, log = await self.cog.setup_guild(interaction.guild, phone)
        except discord.Forbidden:
            return await interaction.followup.send(embed=err_embed(
                "บอทไม่มีสิทธิ์สร้างห้อง/ส่งข้อความ (ต้องมี Manage Channels, Send Messages, Embed Links)"),
                ephemeral=True)
        await interaction.followup.send(embed=err_embed(
            f"ตั้งค่าระบบโดเนทเเล้ว\nเบอร์รับเงิน: `{phone[:3]}-xxx-{phone[-4:]}`\n"
            f"ห้องโดเนท: {ch.mention}\nห้องล็อก: {log.mention}"), ephemeral=True)


class PayModal(discord.ui.Modal, title="โดเนทด้วยซองอั่งเปา"):
    link = discord.ui.TextInput(label="ลิงก์ซองอั่งเปา TrueMoney",
                                placeholder="https://gift.truemoney.com/campaign/?v=...", max_length=300)

    def __init__(self, cog):
        super().__init__(timeout=600)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.process_donation(interaction, self.link.value)


class DonateView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="โดเนท", emoji=emo(E_DONATE), style=discord.ButtonStyle.success,
                       custom_id="donate:pay")
    async def pay(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PayModal(self.cog))

    @discord.ui.button(label="ท็อปโด", emoji=emo(E_TOP), style=discord.ButtonStyle.primary,
                       custom_id="donate:top")
    async def top(self, interaction: discord.Interaction, button: discord.ui.Button):
        rows = await top_donors(interaction.guild_id, TOP_LIMIT)
        if not rows:
            text = "ยังไม่มีผู้โดเนทเลยน้า เป็นคนเเรกได้เลย"
        else:
            medals = ["🥇", "🥈", "🥉"]
            text = "\n".join(
                f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{r['user_id']}> • {baht(int(r['t']))}"
                for i, r in enumerate(rows))
        await interaction.response.send_message(
            embed=discord.Embed(title=f"{E_TOP} ท็อปโดเนท", description=text, colour=COLOR), ephemeral=True)


# ───────────────────────── Cog ─────────────────────────
class Donate(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inflight: set = set()
        self.last_try: dict = {}

    async def cog_load(self):
        await asyncio.to_thread(_init_tables)
        self.bot.add_view(DonateView(self))

    # ---- รูปเเบนเนอร์ (เก็บในฐานข้อมูล เพราะลิงก์ Discord หมดอายุ) ----
    async def get_banner(self):
        for ext in ("png", "jpg", "jpeg", "webp", "gif"):
            path = f"donate_banner.{ext}"
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return f.read(), ("jpg" if ext == "jpeg" else ext)
        row = await q("SELECT data, ext FROM donate_assets WHERE name='banner'", fetch="one")
        if row and row["data"]:
            return bytes(row["data"]), row["ext"]
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.get(BANNER_URL, headers={"User-Agent": "Mozilla/5.0"}) as r:
                    if r.status == 200:
                        data = await r.read()
                        ext = sniff_ext(data)
                        if ext:
                            await q("INSERT OR REPLACE INTO donate_assets (name, data, ext) "
                                    "VALUES ('banner', ?, ?)", (data, ext))
                            return data, ext
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        print("[donate] โหลดรูปเเบนเนอร์ไม่ได้ (ลิงก์อาจหมดอายุ) → วางไฟล์ donate_banner.png ไว้ข้าง main.py")
        return None

    async def send_panel(self, channel: discord.TextChannel, total: int) -> discord.Message:
        banner = await self.get_banner()
        if banner:
            name = f"donate_banner.{banner[1]}"
            return await channel.send(embed=panel_embed(total, name),
                                      file=discord.File(io.BytesIO(banner[0]), filename=name),
                                      view=DonateView(self))
        return await channel.send(embed=panel_embed(total, None), view=DonateView(self))

    async def refresh_panel(self, guild: discord.Guild, cfg):
        """อัปเดตยอดโดเนทในเเผงหลัก (เเก้เฉพาะ embed รูปเดิมยังอยู่)"""
        try:
            ch = guild.get_channel(cfg["channel_id"])
            msg = await ch.fetch_message(cfg["panel_msg_id"])
            name = msg.attachments[0].filename if msg.attachments else None
            await msg.edit(embed=panel_embed(await total_satang(guild.id), name))
        except (discord.HTTPException, AttributeError):
            pass

    # ---- /donate ----
    async def setup_guild(self, guild: discord.Guild, phone: str):
        cfg = await get_config(guild.id)
        everyone = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=False, add_reactions=False,
            create_public_threads=False, create_private_threads=False, send_messages_in_threads=False)
        me = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, embed_links=True, attach_files=True,
            read_message_history=True, manage_messages=True, use_external_emojis=True)
        overwrites = {guild.default_role: everyone, guild.me: me}

        async def ensure(channel_id, name):
            ch = guild.get_channel(channel_id) if channel_id else None
            if ch is None:
                return await guild.create_text_channel(name, overwrites=overwrites, reason="ระบบโดเนท")
            await ch.set_permissions(guild.default_role, overwrite=everyone)
            await ch.set_permissions(guild.me, overwrite=me)
            return ch

        ch = await ensure(cfg["channel_id"] if cfg else None, DONATE_CHANNEL)
        log = await ensure(cfg["log_channel_id"] if cfg else None, LOG_CHANNEL)
        if cfg and cfg["panel_msg_id"]:
            try:
                await (await ch.fetch_message(cfg["panel_msg_id"])).delete()
            except discord.HTTPException:
                pass
        msg = await self.send_panel(ch, await total_satang(guild.id))
        await q("INSERT OR REPLACE INTO donate_config (guild_id, phone, channel_id, log_channel_id, "
                "panel_msg_id) VALUES (?,?,?,?,?)", (guild.id, phone, ch.id, log.id, msg.id))
        return ch, log

    @app_commands.command(name="donate",
                          description="ตั้งค่าระบบโดเนท ใส่เบอร์รับเงินเเละสร้างห้อง (เจ้าของเซิฟเวอร์เท่านั้น)")
    @app_commands.guild_only()
    async def donate(self, interaction: discord.Interaction):
        if not is_server_owner(interaction):
            return await interaction.response.send_message(embed=err_embed(NOT_OWNER), ephemeral=True)
        await interaction.response.send_modal(PhoneModal(self))

    # ---- โดเนท ----
    async def process_donation(self, interaction: discord.Interaction, raw: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild, user = interaction.guild, interaction.user
        send = interaction.followup.send
        cfg = await get_config(guild.id)
        if not cfg:
            return await send(embed=err_embed("ระบบโดเนทยังไม่พร้อมใช้งาน เเจ้งเจ้าของเซิฟน้า"), ephemeral=True)
        now = time.monotonic()
        if now - self.last_try.get(user.id, 0) < TRY_COOLDOWN:
            return await send(embed=err_embed("ใจเย็นๆน้า รอสักครู่เเล้วลองใหม่"), ephemeral=True)
        self.last_try[user.id] = now

        code = truemoney.extract_code(raw)
        if not code:
            return await send(embed=err_embed(truemoney.GENERIC["INVALID_CODE"]), ephemeral=True)
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        if code in self.inflight:
            return await send(embed=err_embed("ซองนี้กำลังตรวจสอบอยู่น้า"), ephemeral=True)
        if await code_used(code_hash):
            return await send(embed=err_embed("ซองนี้ถูกใช้โดเนทไปเเล้วน้า"), ephemeral=True)

        self.inflight.add(code)
        try:
            res = await truemoney.redeem(code, cfg["phone"])
        finally:
            self.inflight.discard(code)
        if not res.ok:
            if res.detail:
                print(f"[donate] redeem ไม่สำเร็จ ({res.code}): {res.detail}")
            return await send(embed=err_embed(res.message), ephemeral=True)

        await add_donation(guild.id, user.id, res.satang, res.owner_name, code_hash)
        await send(embed=success_embed(user, res.owner_name, res.satang), ephemeral=True)
        await self.refresh_panel(guild, cfg)
        log_ch = guild.get_channel(cfg["log_channel_id"])
        if log_ch:
            try:
                await log_ch.send(embed=log_embed(user, res.satang, await user_total(guild.id, user.id)))
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Donate(bot))
