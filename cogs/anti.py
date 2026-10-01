import asyncio
import math
import re
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)

# ───────── ค่าที่ปรับได้ ─────────
RATE_N = 5          # ครบกี่ครั้ง ...
RATE_WINDOW = 5.0   # ... ภายในกี่วินาที (ใช้กับ spam และ nuke ทุกแบบ)
ROUNDS = 3          # สเเปม/ลิ้ง ครบกี่รอบถึงลงโทษ (รอบที่ 1-2 เตือน รอบที่ 3 ลงโทษ)
WARN_DELETE_AFTER = 5

# ───────── อีโมจิ ─────────
E793 = "<:1000035793:1554977816431431850>"
E790 = "<:1000035790:1554970748232147004>"
E604 = "<a:1000035604:1554847795524141216>"
E602 = "<a:1000035602:1554844971931275325>"
E607 = "<a:1000035607:1554874918632562788>"
E739 = "<a:1000035739:1554873266987081742>"
E742 = "<a:1000035742:1554876309790793908>"
E743 = "<a:1000035743:1554882610134524034>"
E767 = "<a:1000035767:1554921960838926417>"
E800 = "<a:1000035800:1555024595050963005>"
E801 = "<a:1000035801:1555024761606639747>"
E802 = "<a:1000035802:1555024928133226557>"
E803 = "<a:1000035803:1555025202482516100>"
E744 = "<a:1000035744:1554884849406451762>"
E804 = "<a:1000035804:1555025773742526615>"
E597 = "<a:1000035597:1554848439035240449>"
E727 = "<a:1000035727:1554859928957755393>"
E763 = "<a:1000035763:1554920997382262874>"
E764 = "<a:1000035764:1554920142146904164>"
E762 = "<a:1000035762:1554919569682989166>"
E608 = "<a:1000035608:1554844998506123274>"
E603 = "<a:1000035603:1554845277071089736>"
E725 = "<a:1000035725:1554844594175483904>"
E728 = "<a:1000035728:1554860189125967894>"
E729 = "<a:1000035729:1554863632528052315>"

A = discord.AuditLogAction


def pe(s: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(s)


def emb(desc: str) -> discord.Embed:
    return discord.Embed(description=desc, color=WHITE)


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
    q("""CREATE TABLE IF NOT EXISTS aw_config (
        guild_id INTEGER, system TEXT, enabled INTEGER DEFAULT 0, mode TEXT DEFAULT 'warn',
        timeout_min INTEGER DEFAULT 0, link_mode TEXT DEFAULT 'all',
        status_by INTEGER, set_by INTEGER,
        PRIMARY KEY (guild_id, system))""")
    q("""CREATE TABLE IF NOT EXISTS aw_whitelist (
        guild_id INTEGER, kind TEXT, user_id INTEGER, added_by INTEGER,
        PRIMARY KEY (guild_id, kind, user_id))""")
    q("""CREATE TABLE IF NOT EXISTS aw_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
        kind TEXT, reason TEXT, extra INTEGER DEFAULT 0, created_at INTEGER)""")
    q("CREATE INDEX IF NOT EXISTS idx_aw_log ON aw_log (guild_id, kind, created_at)")


SYSTEMS = ("spam", "link", "nuke")
SYS_NAME = {"spam": "anti spam", "link": "anti link", "nuke": "anti nuke"}
MODE_NAME = {"warn": "เตือนเฉยๆ", "kick": "เตะ", "ban": "เเบน", "timeout": "หมดเวลา"}
LINK_NAME = {
    "skip_discord": "ข้ามลิ้งดิส (ลิ้งดิสไม่โดน)",
    "only_discord": "ลิ้งทั่วไปยกเว้นลิ้งดิส (anti เเค่ลิ้งดิส)",
    "all": "anti ทุกลิ้ง",
}
WL_NAME = {
    "spam": "anti spam", "link": "anti link", "nuke": "anti nuke",
    "all": "ทุกระบบ (ยกเว้นเชิญบอทไม่มีติ๊ก)",
    "botinvite": "คนเชิญบอทไม่มีติ๊ก (หัวดิสเท่านั้น)",
}

CACHE: dict = {}


def invalidate(gid: int):
    CACHE.pop(gid, None)


def load(gid: int) -> dict:
    if gid in CACHE:
        return CACHE[gid]
    c = {s: dict(enabled=0, mode="warn", timeout=0, link_mode="all", status_by=None, set_by=None)
         for s in SYSTEMS}
    for s, en, mode, tm, lm, sb, sby in q(
            "SELECT system, enabled, mode, timeout_min, link_mode, status_by, set_by "
            "FROM aw_config WHERE guild_id=?", (gid,), many=True):
        if s in c:
            c[s] = dict(enabled=en, mode=mode, timeout=tm, link_mode=lm, status_by=sb, set_by=sby)
    c["wl"] = {(k, u) for k, u in q("SELECT kind, user_id FROM aw_whitelist WHERE guild_id=?", (gid,), many=True)}
    CACHE[gid] = c
    return c


def upsert(gid: int, system: str, **kw):
    cols = ", ".join(kw)
    ph = ", ".join("?" * len(kw))
    upd = ", ".join(f"{k}=excluded.{k}" for k in kw)
    q(f"INSERT INTO aw_config (guild_id, system, {cols}) VALUES (?, ?, {ph}) "
      f"ON CONFLICT(guild_id, system) DO UPDATE SET {upd}", (gid, system, *kw.values()))
    invalidate(gid)


def whitelisted(c: dict, uid: int, system: str) -> bool:
    return (system, uid) in c["wl"] or ("all", uid) in c["wl"]


def toggle_wl(gid: int, kind: str, uid: int, by: int) -> bool:
    if q("SELECT 1 FROM aw_whitelist WHERE guild_id=? AND kind=? AND user_id=?", (gid, kind, uid), one=True):
        q("DELETE FROM aw_whitelist WHERE guild_id=? AND kind=? AND user_id=?", (gid, kind, uid))
        added = False
    else:
        q("INSERT INTO aw_whitelist VALUES (?,?,?,?)", (gid, kind, uid, by))
        added = True
    invalidate(gid)
    return added


def log_event(gid: int, uid: int, kind: str, reason: str, extra: int = 0):
    q("INSERT INTO aw_log (guild_id, user_id, kind, reason, extra, created_at) VALUES (?,?,?,?,?,?)",
      (gid, uid, kind, reason, extra, int(time.time())))


# ═════════════ ข้อความ/Embed ═════════════
def status_line(c: dict, s: str) -> str:
    cfg = c[s]
    who = f"<@{cfg['status_by']}>" if cfg["status_by"] else "ไม่มี"
    return (f"{E739} ระบบ{SYS_NAME[s]}: " + (f"เปิด {E742}" if cfg["enabled"] else f"ปิด {E743}")
            + f" (เปิดเเละปิดระบบโดย {who})")


def main_embed(gid: int) -> discord.Embed:
    c = load(gid)
    return emb(
        f"# {E793} anti spam system\n\n"
        f"พี่ๆเลือกได้เลยย ว่าจะให้น้องป้องกันอะไรบ้าง {E604}\n\n"
        "เมื่อเปิดระบบ anti nuke เมื่อมีแอดมินเชิญบอทที่ไม่ได้ยืนยันติ๊กถูกเข้ามาภายเซิฟ "
        "น้องจะเตะบอทตัวนั้นออกทันที พร้อมเเจ้งไปที่แอดมินทุกคนผ่านDm\n\n"
        f"{E602} พี่ๆแอดมินสามารถเซ็ตระบบต่างๆได้ เเต่ถ้าจะปิดanti nuke ต้องให้พี่เจ้าของดิสมาปิดเท่านั้นน้าาา "
        "เเต่ลิ้งกับสเเปมพี่ๆแอดมินปิดด้ายย\n\n"
        f"มีทั้ง กันสแปม กันยิงดิส กันลิ้ง {E607}\n\n"
        + "\n\n".join(status_line(c, s) for s in ("spam", "link", "nuke"))
        + f"\n\n{E767} พี่ๆแอดมินสามารถมอบ whitelist ให้คนธรรมดาได้ เเต่ถ้าเป็นบอท ต้องให้พี่หัวดิสเท่านั้นน้าา")


def system_embed(gid: int, s: str) -> discord.Embed:
    c = load(gid)
    cfg = c[s]
    if s == "nuke":
        return emb(
            f"# {E804} anti nuke {E804}\n\n"
            f"{E803} พี่ๆแอดมินกดเปิดได้เลย เเต่ถ้าจะปิด ปิดได้เเค่พี่หัวดิสนะน้าา\n\n"
            "ระบบนี้จะเตะ **บอท** ออกทันที เมื่อ\n"
            "• เป็นบอทที่ไม่มีติ๊กถูกยืนยัน (ตอนถูกเชิญเข้ามา)\n"
            f"• ลบ/สร้างห้อง หมวดหมู่ VC เร็วเกิน {RATE_N} ต่อ {int(RATE_WINDOW)} วิ\n"
            f"• ลบ/สร้าง webhook เร็วเกิน {RATE_N} อันต่อ {int(RATE_WINDOW)} วิ\n"
            f"• เตะ/เเบน/หมดเวลาสมาชิกเร็วเกิน {RATE_N} คนต่อ {int(RATE_WINDOW)} วิ\n"
            f"• สเเปมข้อความรวมทุกห้องเร็วเกิน {RATE_N} ข้อความต่อ {int(RATE_WINDOW)} วิ\n"
            f"• เเท็ก @everyone @here หรือยศ เร็วเกิน {RATE_N} เเท็กต่อ {int(RATE_WINDOW)} วิ\n\n"
            + status_line(c, s))
    extra = f"\nโหมดลงโทษ: **{MODE_NAME[cfg['mode']]}**"
    if cfg["mode"] == "timeout":
        extra += f" ({cfg['timeout']} นาที)"
    if s == "link":
        extra += f"\nประเภทลิ้ง: **{LINK_NAME[cfg['link_mode']]}**"
    return emb(
        f"# {E804} {SYS_NAME[s]} {E804}\n\n"
        f"{E803} พี่ๆแอดมินกดได้เลยว่าจะเปิดหรือปิด เเละเลือกว่าจะ เตือน เตะ หมดเวลา หรือเเบน\n\n"
        + status_line(c, s) + extra)


# ═════════════ Views (ฝั่งแอดมิน) ═════════════
class AdminView(discord.ui.View):
    def __init__(self, owner_id: int, timeout=900):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
            return False
        return True


class TimeoutModal(discord.ui.Modal, title="ตั้งเวลาหมดเวลา"):
    minutes = discord.ui.TextInput(label="หมดเวลากี่นาที (สูงสุด 10080 = 7 วัน)", placeholder="เช่น 60", max_length=5)

    def __init__(self, system: str):
        super().__init__()
        self.system = system

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.minutes.value.strip()
        m = int(raw) if raw.isdigit() and 1 <= int(raw) <= 10080 else None
        if m is None:
            return await interaction.response.send_message(
                embed=emb(f"{E790} กรอกเป็นตัวเลข 1-10080 เท่านั้นน้าา"), ephemeral=True)
        upsert(interaction.guild.id, self.system, mode="timeout", timeout_min=m, set_by=interaction.user.id)
        await interaction.response.edit_message(embed=emb(
            f"{E725} พี่เซ็ตระบบหมดเวลาเเล้วน้าา หมดเวลาไป **{m}** นาที\n"
            f"ถ้าเป็นชั่วโมงจะเท่ากับ: {round(m / 60, 2):g}\nถ้าเป็นวัน: {round(m / 1440, 2):g}"), view=None)


class ModePickView(AdminView):
    def __init__(self, owner_id: int, system: str):
        super().__init__(owner_id)
        self.system = system
        sel = discord.ui.Select(placeholder="เลือกการลงโทษ", options=[
            discord.SelectOption(label="เตะ", value="kick", emoji=pe(E790)),
            discord.SelectOption(label="เตือน", value="warn", emoji=pe(E793)),
            discord.SelectOption(label="หมดเวลา", value="timeout", emoji=pe(E727)),
            discord.SelectOption(label="เเบน", value="ban", emoji=pe(E743)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        if v == "timeout":
            return await interaction.response.send_modal(TimeoutModal(self.system))
        upsert(interaction.guild.id, self.system, mode=v, timeout_min=0, set_by=interaction.user.id)
        await interaction.response.edit_message(
            embed=emb(f"{E725} พี่เซ็ตระบบ **{MODE_NAME[v]}** เเล้วน้าา"), view=None)


class SystemView(AdminView):
    """แผง anti spam / anti link / anti nuke"""
    def __init__(self, owner_id: int, system: str):
        super().__init__(owner_id)
        self.system = system
        opts = []
        if system != "nuke":
            opts.append(discord.SelectOption(label="เซ็ต เตะ เตือน เเบน หมดเวลา", value="mode", emoji=pe(E597)))
        opts += [discord.SelectOption(label="เริ่ม/หยุด", value="toggle", emoji=pe(E597)),
                 discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E597))]
        sel = discord.ui.Select(placeholder="เลือกระบบ", options=opts, row=0)
        sel.callback = self.on_select
        self.add_item(sel)
        if system == "link":
            ls = discord.ui.Select(placeholder="ต้องการให้ข้ามลิ้งประเภทไหนมั้ย", row=1, options=[
                discord.SelectOption(label="1. ข้ามลิ้งดิส", value="skip_discord",
                                     description="ลิ้งดิสจะไม่ถูกลบหรือนับว่าเป็นการส่งลิ้ง"),
                discord.SelectOption(label="2. ลิ้งทั่วไปยกเว้นลิ้งดิส", value="only_discord",
                                     description="จะ anti เเค่ลิ้งดิส"),
                discord.SelectOption(label="3. anti ทุกลิ้ง", value="all"),
            ])
            ls.callback = self.on_link_type
            self.add_item(ls)

    async def on_link_type(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        upsert(interaction.guild.id, "link", link_mode=v, set_by=interaction.user.id)
        await interaction.response.edit_message(embed=system_embed(interaction.guild.id, "link"), view=self)
        await interaction.followup.send(embed=emb(f"{E725} เซ็ตประเภทลิ้งเป็น **{LINK_NAME[v]}** เเล้วน้าา"),
                                        ephemeral=True)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        gid, s = interaction.guild.id, self.system
        if v == "toggle":
            cfg = load(gid)[s]
            on = not cfg["enabled"]
            if s == "nuke" and not on and interaction.user.id != interaction.guild.owner_id:
                await interaction.response.edit_message(view=self)
                return await interaction.followup.send(
                    embed=emb(f"{E790} ปิด anti nuke ได้เเค่พี่หัวดิสเท่านั้นน้าา"), ephemeral=True)
            upsert(gid, s, enabled=int(on), status_by=interaction.user.id)
            await interaction.response.edit_message(embed=system_embed(gid, s), view=self)
            msg = (f"{E742} เปิดระบบ **{SYS_NAME[s]}** เเล้วน้าา" if on
                   else f"{E743} ปิดระบบ **{SYS_NAME[s]}** เเล้วน้าา")
            return await interaction.followup.send(embed=emb(msg), ephemeral=True)

        await interaction.response.edit_message(view=self)  # รีเซ็ตเมนู
        if v == "mode":
            await interaction.followup.send(
                embed=emb(f"{E597} เลือกว่าจะให้น้อง เตะ เตือน หมดเวลา หรือเเบน"),
                view=ModePickView(self.owner_id, s), ephemeral=True)
        else:
            await interaction.followup.send(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"), ephemeral=True)


# ---- whitelist ----
def wl_embed(gid: int, kind: str) -> discord.Embed:
    c = load(gid)
    users = [u for k, u in c["wl"] if k == kind]
    text = " ".join(f"<@{u}>" for u in users) or "ไม่มี"
    if len(text) > 3000:
        text = text[:3000] + "…"
    return emb(
        f"# {E803} whitelist\n\n"
        f"พี่ๆแอดมินมอบ whitelist ให้คนธรรมดาได้ เเต่ถ้าเป็นบอท หรือข้อ \"คนเชิญบอทไม่มีติ๊ก\" ต้องพี่หัวดิสเท่านั้นน้าา\n\n"
        f"ประเภทที่เลือก: **{WL_NAME[kind]}**\n"
        "เลือกคนด้านล่าง (เลือกซ้ำ = เอาออก)\n\n"
        f"{E767} รายชื่อที่ whitelist อยู่: {text}")


class WhitelistView(AdminView):
    def __init__(self, owner_id: int, kind: str = "all"):
        super().__init__(owner_id)
        self.kind = kind
        ks = discord.ui.Select(placeholder="เลือกว่าจะ whitelist ระบบไหน", row=0, options=[
            discord.SelectOption(label=WL_NAME[k][:100], value=k, default=(k == kind))
            for k in ("spam", "link", "nuke", "all", "botinvite")])
        us = discord.ui.UserSelect(placeholder="เลือกคน/บอท", min_values=1, max_values=10, row=1)
        ks.callback = self.on_kind
        us.callback = self.on_users
        self.ks, self.us = ks, us
        self.add_item(ks)
        self.add_item(us)

    async def on_kind(self, interaction: discord.Interaction):
        kind = self.ks.values[0]
        await interaction.response.edit_message(embed=wl_embed(interaction.guild.id, kind),
                                                view=WhitelistView(self.owner_id, kind))

    async def on_users(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        is_owner = interaction.user.id == interaction.guild.owner_id
        if self.kind == "botinvite" and not is_owner:
            await interaction.response.edit_message(embed=wl_embed(gid, self.kind), view=WhitelistView(self.owner_id, self.kind))
            return await interaction.followup.send(
                embed=emb(f"{E790} whitelist คนเชิญบอทไม่มีติ๊ก ให้ได้เเค่พี่หัวดิสเท่านั้นน้าา"), ephemeral=True)
        denied = 0
        for u in self.us.values:
            if u.bot and not is_owner:
                denied += 1
                continue
            toggle_wl(gid, self.kind, u.id, interaction.user.id)
        await interaction.response.edit_message(embed=wl_embed(gid, self.kind), view=WhitelistView(self.owner_id, self.kind))
        if denied:
            await interaction.followup.send(
                embed=emb(f"{E790} มี **{denied}** บอทที่ข้ามไป เพราะ whitelist บอทต้องพี่หัวดิสเท่านั้นน้าา"),
                ephemeral=True)


# ---- เช็คคนกระทำผิด ----
KINDS = ["warn", "ban", "kick", "timeout"]
KIND_TITLE = {"warn": "รายชื่อผู้ถูกบอทเตือน", "ban": "รายชื่อผู้ถูกเเบน",
              "kick": "รายชื่อผู้ถูกเตะ", "timeout": "รายชื่อผู้ถูกหมดเวลา"}
KIND_SHORT = {"warn": "เตือน", "ban": "เเบน", "kick": "เตะ", "timeout": "หมดเวลา"}
PAGE_SIZE = 50


def log_embeds(gid: int, kind: str, page: int, avatar_url: str):
    total = q("SELECT COUNT(*) FROM aw_log WHERE guild_id=? AND kind=?", (gid, kind), one=True)[0]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    rows = q("SELECT user_id, reason, extra, created_at FROM aw_log WHERE guild_id=? AND kind=? "
             "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
             (gid, kind, PAGE_SIZE, page * PAGE_SIZE), many=True)
    head = (f"# {KIND_TITLE[kind]} {E608}\n\n"
            f"{E603} หากต้องการดูรายชื่อผู้ถูกเเบน เตะ หมดเวลา โปรดกดปุ่มด้านล่าง\n\n")
    if total == 0:
        chunks = [f"ยังไม่มีคนโดน{KIND_SHORT[kind]}เยยย"]
    elif not rows:
        chunks = ["ยังไม่ถึงหน้านี้น้าา"]
    else:
        lines = []
        for uid, reason, extra, ts in rows:
            line = f"<@{uid}> เนื่องจาก{reason} เมื่อเวลา <t:{ts}:f>"
            if kind == "timeout" and extra:
                line += f" ({extra} นาที)"
            lines.append(line)
        chunks = ["\n".join(lines[:25])] + (["\n".join(lines[25:])] if len(lines) > 25 else [])
    embeds = []
    for i, c in enumerate(chunks):
        e = emb((head if i == 0 else "") + c)
        if i == 0:
            e.set_thumbnail(url=avatar_url)
        embeds.append(e)
    embeds[-1].set_footer(text=f"หน้า {page + 1}/{pages} • ทั้งหมด {total} รายการ")
    return embeds


class LogView(AdminView):
    def __init__(self, owner_id: int, kind_i: int = 0, page: int = 0):
        super().__init__(owner_id)
        self.kind_i, self.page = kind_i, page
        prev_b = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary, row=0, disabled=page <= 0)
        next_b = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary, row=0)
        back_b = discord.ui.Button(
            label=f"กลับหน้า{KIND_SHORT[KINDS[kind_i - 1]]}" if kind_i > 0 else "กลับ",
            emoji="⏪", style=discord.ButtonStyle.primary, row=1, disabled=kind_i == 0)
        fwd_b = discord.ui.Button(
            label=f"ไปหน้า{KIND_SHORT[KINDS[kind_i + 1]]}" if kind_i < len(KINDS) - 1 else "สุดเเล้ว",
            emoji="⏩", style=discord.ButtonStyle.primary, row=1, disabled=kind_i == len(KINDS) - 1)
        prev_b.callback = lambda i: self.go(i, self.kind_i, max(0, self.page - 1))
        next_b.callback = lambda i: self.go(i, self.kind_i, self.page + 1)
        back_b.callback = lambda i: self.go(i, self.kind_i - 1, 0)
        fwd_b.callback = lambda i: self.go(i, self.kind_i + 1, 0)
        for b in (prev_b, next_b, back_b, fwd_b):
            self.add_item(b)

    async def go(self, interaction: discord.Interaction, kind_i: int, page: int):
        embeds = log_embeds(interaction.guild.id, KINDS[kind_i], page,
                            interaction.client.user.display_avatar.url)
        await interaction.response.edit_message(embeds=embeds, view=LogView(self.owner_id, kind_i, page))


# ---- เมนูหลัก ----
class MainView(AdminView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        sel = discord.ui.Select(placeholder="เลือกระบบ", options=[
            discord.SelectOption(label="anti spam", value="spam", emoji=pe(E800)),
            discord.SelectOption(label="anti nuke", value="nuke", emoji=pe(E801)),
            discord.SelectOption(label="anti link", value="link", emoji=pe(E802)),
            discord.SelectOption(label="whitelist", value="wl", emoji=pe(E803)),
            discord.SelectOption(label="เช็คคนกระทำผิด", value="check", emoji=pe(E744)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E790)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v, gid = interaction.data["values"][0], interaction.guild.id
        await interaction.response.edit_message(embed=main_embed(gid), view=self)  # รีเซ็ตเมนู + อัปเดตสถานะ
        send = lambda **kw: interaction.followup.send(ephemeral=True, **kw)
        if v in SYSTEMS:
            await send(embed=system_embed(gid, v), view=SystemView(interaction.user.id, v))
        elif v == "wl":
            await send(embed=wl_embed(gid, "all"), view=WhitelistView(interaction.user.id, "all"))
        elif v == "check":
            await send(embeds=log_embeds(gid, "warn", 0, interaction.client.user.display_avatar.url),
                       view=LogView(interaction.user.id))
        else:
            await send(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"))


# ═════════════ ตัวตรวจจริง ═════════════
SPAM: dict = defaultdict(deque)      # (gid, uid) -> เวลาข้อความ
EVENTS: dict = defaultdict(deque)    # (gid, bot_id, kind) -> เวลาเหตุการณ์ nuke
STRIKES: dict = {}                   # (gid, uid, system) -> จำนวนรอบที่ทำผิด
NUKED: dict = {}                     # (gid, bot_id) -> เวลาที่เพิ่งเตะ

ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
URL_RE = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|(?<![\w@.-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|gg|io|me|xyz|co|th|info|app|dev|tv|ly|link|to|cc|ru|cn|shop|store|site|online|click|top)\b(?:/\S*)?",
    re.I)
DISCORD_RE = re.compile(r"(?:discord\.gg|discord(?:app)?\.com/invite|dsc\.gg|discord\.me|discord\.io)/", re.I)

NUKE_REASON = {
    "chdel": f"ลบห้องเร็วเกิน {RATE_N} ห้องต่อ {int(RATE_WINDOW)} วิ",
    "whdel": f"ลบ webhook เร็วเกิน {RATE_N} อันต่อ {int(RATE_WINDOW)} วิ",
    "whnew": f"สร้าง webhook จำนวนมาก ({RATE_N} อันต่อ {int(RATE_WINDOW)} วิ)",
    "chnew": f"สร้างห้องไวเกิน {RATE_N} ห้องต่อ {int(RATE_WINDOW)} วิ",
    "catnew": f"สร้างหมวดหมู่เร็วเกิน {RATE_N} อันต่อ {int(RATE_WINDOW)} วิ",
    "vcnew": f"สร้าง VC เร็วเกิน {RATE_N} ห้องต่อ {int(RATE_WINDOW)} วิ",
    "punish": f"เตะ/เเบน/หมดเวลาสมาชิกเร็วเเละเยอะเกิน {RATE_N} คนต่อ {int(RATE_WINDOW)} วิ",
    "msg": f"สเเปมข้อความเร็วเกิน {RATE_N} ข้อความต่อ {int(RATE_WINDOW)} วิ (ทุกห้อง)",
    "tag": f"เเท็ก @everyone/@here/ยศ เร็วเกิน {RATE_N} เเท็กต่อ {int(RATE_WINDOW)} วิ",
    "unverified": "ไม่มีติ๊กถูกยืนยันบอทมีความเสี่ยง",
}


def window_count(dq: deque, now: float, weight: int = 1) -> int:
    for _ in range(weight):
        dq.append(now)
    while dq and now - dq[0] > RATE_WINDOW:
        dq.popleft()
    return len(dq)


def dv(entry: discord.AuditLogEntry, name: str):
    for side in (entry.before, entry.after):
        try:
            v = getattr(side, name)
            if v is not None:
                return v
        except AttributeError:
            pass
    return None


class AntiSystemCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()

    @app_commands.command(name="anti_system", description="ระบบป้องกันต่างๆ (แอดมินเท่านั้น)")
    @app_commands.guild_only()
    async def anti_system(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
        await interaction.response.send_message(
            embed=main_embed(interaction.guild.id), view=MainView(interaction.user.id), ephemeral=True)

    # ───────── ข้อความ ─────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        guild, author = message.guild, message.author
        if guild is None or author.id == self.bot.user.id or message.webhook_id:
            return
        c = load(guild.id)

        if author.bot:  # บอท → anti nuke เท่านั้น (เตะบอทอย่างเดียว)
            if c["nuke"]["enabled"] and not whitelisted(c, author.id, "nuke"):
                now = time.monotonic()
                if window_count(EVENTS[(guild.id, author.id, "msg")], now) >= RATE_N:
                    return await self.nuke_trigger(guild, author, "msg")
                tags = int(message.mention_everyone or "@everyone" in message.content or "@here" in message.content)
                tags += len(message.role_mentions)
                if tags and window_count(EVENTS[(guild.id, author.id, "tag")], now, tags) >= RATE_N:
                    await self.nuke_trigger(guild, author, "tag")
            return

        if c["spam"]["enabled"] and not whitelisted(c, author.id, "spam"):
            key = (guild.id, author.id)
            if window_count(SPAM[key], time.monotonic()) >= RATE_N:
                SPAM[key].clear()  # เริ่มนับรอบใหม่ (ไม่สนเนื้อหา กันพวกต่อท้ายด้วยตัวอักษรเเปลกๆ)
                await self.violation(message, "spam", c["spam"], "หยุดสเเปมได้เเล้วค่ะพี่",
                                     f"สเเปมข้อความเร็วเกิน {RATE_N} ข้อความต่อ {int(RATE_WINDOW)} วิ", delete=False)

        if c["link"]["enabled"] and not whitelisted(c, author.id, "link") and message.content:
            if self.has_bad_link(message.content, c["link"]["link_mode"]):
                await self.violation(message, "link", c["link"], "หยุดส่งลิ้งได้เเล้วค่ะพี่",
                                     "ส่งลิ้งที่ไม่อนุญาต", delete=True)

    @staticmethod
    def has_bad_link(content: str, mode: str) -> bool:
        text = content.translate(ZW)
        has_discord = bool(DISCORD_RE.search(text))
        if mode == "only_discord":
            return has_discord
        urls = [m.group(0) for m in URL_RE.finditer(text)]
        if mode == "skip_discord":
            return any(not DISCORD_RE.search(u) for u in urls)
        return bool(urls) or has_discord

    async def violation(self, message: discord.Message, system: str, cfg: dict,
                        stop_text: str, reason: str, delete: bool):
        guild, member = message.guild, message.author
        if delete:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        mode = cfg["mode"]
        key = (guild.id, member.id, system)
        n = STRIKES.get(key, 0) + 1

        async def say(text: str):
            try:
                if delete:
                    await message.channel.send(f"{member.mention} {text}", delete_after=WARN_DELETE_AFTER,
                                               allowed_mentions=discord.AllowedMentions(users=[member]))
                else:
                    await message.reply(text, delete_after=WARN_DELETE_AFTER, mention_author=False)
            except discord.HTTPException:
                pass

        if mode != "warn" and n >= ROUNDS:
            if await self.punish(member, mode, cfg["timeout"], f"{reason} (ครบ {ROUNDS} รอบ)"):
                STRIKES.pop(key, None)
                log_event(guild.id, member.id, mode, reason, cfg["timeout"] if mode == "timeout" else 0)
                return
            n = ROUNDS - 1  # ลงโทษไม่ได้ (ยศบอทไม่ถึง) → เตือนต่อ

        STRIKES[key] = n
        conseq = {"warn": "", "kick": " ไม่งั้นหนูคงต้องเตะพี่", "ban": " ไม่งั้นหนูคงต้องเเบนพี่",
                  "timeout": " ไม่งั้นหนูคงต้องหมดเวลาพี่"}[mode]
        log_event(guild.id, member.id, "warn", reason)
        await say(f"{E727} {stop_text}{conseq}")

    async def punish(self, member: discord.Member, mode: str, minutes: int, reason: str) -> bool:
        guild, me = member.guild, member.guild.me
        perms = me.guild_permissions
        ok = {"kick": perms.kick_members, "ban": perms.ban_members, "timeout": perms.moderate_members}[mode]
        if (not ok or member.id == guild.owner_id or member.top_role >= me.top_role
                or member.guild_permissions.administrator):
            return False

        if mode == "timeout":
            until = discord.utils.utcnow() + timedelta(minutes=minutes)
            fmt = "f" if minutes >= 1440 else "t"
            footer = "โดนหมดเวลาเมื่อ"
            desc = (f"# {E607} เเจ้งการโดนหมดเวลา\n\nพี่โดนหมดเวลาจากดิส **{guild.name}** (`{guild.id}`) "
                    f"เนื่องจาก{reason} พี่โดนไป **{minutes}** นาที เดี๋ยวตอน {discord.utils.format_dt(until, fmt)} ปลด")
        else:
            action, footer = ("ถูกเตะจาก", "ถูกเตะเมื่อ") if mode == "kick" else ("ถูกเเบนจาก", "ถูกเเบนเมื่อ")
            desc = (f"พี่{action}ดิส **{guild.name}** (`{guild.id}`) เนื่องจาก{reason} "
                    f"ไว้มีโอกาสเราค่อยเจอกันใหม่นะคะพี่ {E729}")
        dm = discord.Embed(description=desc, color=WHITE, timestamp=discord.utils.utcnow())
        dm.set_thumbnail(url=member.display_avatar.url)
        dm.set_footer(text=footer)
        try:
            await member.send(embed=dm)
        except discord.HTTPException:
            pass

        try:
            if mode == "kick":
                await member.kick(reason=f"anti_system: {reason}")
            elif mode == "ban":
                await guild.ban(member, reason=f"anti_system: {reason}", delete_message_days=0)
            else:
                await member.timeout(timedelta(minutes=minutes), reason=f"anti_system: {reason}")
        except discord.HTTPException:
            return False
        return True

    # ───────── Audit log: เชิญบอท + พฤติกรรม nuke ─────────
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        c = load(guild.id)
        if not c["nuke"]["enabled"]:
            return

        if entry.action is A.bot_add:
            return await self.check_bot_invite(entry, c)

        actor = entry.user
        if actor is None or not actor.bot or actor.id == self.bot.user.id or whitelisted(c, actor.id, "nuke"):
            return
        a, kind = entry.action, None
        if a is A.channel_delete:
            kind = "chdel"
        elif a is A.webhook_delete:
            kind = "whdel"
        elif a is A.webhook_create:
            kind = "whnew"
        elif a is A.channel_create:
            t = dv(entry, "type")
            kind = ("catnew" if t == discord.ChannelType.category
                    else "vcnew" if t in (discord.ChannelType.voice, discord.ChannelType.stage_voice)
                    else "chnew")
        elif a in (A.kick, A.ban):
            kind = "punish"
        elif a is A.member_update and getattr(entry.after, "timed_out_until", None) is not None:
            kind = "punish"
        if kind is None:
            return
        # เตะ/เเบน/หมดเวลา นับรวมกันเป็นตัวนับเดียว
        if window_count(EVENTS[(guild.id, actor.id, kind)], time.monotonic()) >= RATE_N:
            member = guild.get_member(actor.id) or actor
            await self.nuke_trigger(guild, member, kind)

    async def check_bot_invite(self, entry: discord.AuditLogEntry, c: dict):
        guild, inviter = entry.guild, entry.user
        if inviter is None or ("botinvite", inviter.id) in c["wl"]:
            return
        member = None
        for _ in range(4):  # รอให้บอทเข้ามาในแคชก่อน
            member = guild.get_member(entry.target.id)
            if member is None:
                try:
                    member = await guild.fetch_member(entry.target.id)
                except discord.HTTPException:
                    member = None
            if member:
                break
            await asyncio.sleep(1)
        if member is None or member.id == self.bot.user.id or member.public_flags.verified_bot:
            return
        await self.nuke_trigger(guild, member, "unverified", inviter=inviter)

    async def nuke_trigger(self, guild: discord.Guild, bot_user, kind: str, inviter=None):
        key = (guild.id, bot_user.id)
        now = time.monotonic()
        if now - NUKED.get(key, -999) < 30:
            return
        NUKED[key] = now
        for k in [k for k in EVENTS if k[0] == guild.id and k[1] == bot_user.id]:
            EVENTS[k].clear()

        reason = NUKE_REASON[kind]
        me = guild.me
        kicked = False
        member = bot_user if isinstance(bot_user, discord.Member) else guild.get_member(bot_user.id)
        if (member and me.guild_permissions.kick_members and member.top_role < me.top_role):
            try:
                await member.kick(reason=f"anti nuke: {reason}")
                kicked = True
            except discord.HTTPException:
                pass
        log_event(guild.id, bot_user.id, "kick", f"บอทโดน anti nuke ({reason})")

        if kind == "unverified":
            title = f"{E739} ระบบป้องกันการเชิญบอทแปลกๆ {E739}"
            lines = [
                f"{E763} มีการเชิฟบอทชื่อ: {bot_user} ({bot_user.id})",
                f"{E764} ผู้ที่เชิญบอทตัวนี้เข้ามา: {inviter.mention if inviter else 'ไม่ทราบ'} ({inviter.id if inviter else '-'})",
                f"{E762} จากเซิฟ: {guild.name} ({guild.id})",
                f"{E763} เหตุผลที่เตะ: {reason}",
            ]
            thumb, footer = (inviter or bot_user).display_avatar.url, "ถูกเชิญเมื่อ"
        else:
            title = f"{E739} ระบบป้องกันบอทอันตราย {E739}"
            lines = [
                f"{E763} บอทที่โดนเตะ: {bot_user} ({bot_user.id})",
                f"{E762} จากเซิฟ: {guild.name} ({guild.id})",
                f"{E763} เหตุผลที่เตะ: {reason}",
            ]
            thumb, footer = bot_user.display_avatar.url, "เตะเมื่อ"
        if not kicked:
            lines.append(f"{E729} เตะไม่สำเร็จ (ยศบอทไม่ถึง หรือไม่มีสิทธิ์) รบกวนพี่ๆจัดการเอง")

        e = discord.Embed(description=f"# {title}\n\n" + "\n\n".join(lines), color=WHITE,
                          timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=thumb)
        e.set_footer(text=footer)
        await self.dm_admins(guild, e)

    async def dm_admins(self, guild: discord.Guild, embed: discord.Embed):
        targets = {m.id: m for m in guild.members if not m.bot and m.guild_permissions.administrator}
        if guild.owner and guild.owner.id not in targets:
            targets[guild.owner.id] = guild.owner
        for m in targets.values():
            try:
                await m.send(embed=embed)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiSystemCog(bot))
