import io
import os
import time
from datetime import timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)
HAS_LABEL = hasattr(discord.ui, "Label")
HAS_UPLOAD = HAS_LABEL and hasattr(discord.ui, "FileUpload")

# ───────── อีโมจิ ─────────
E804 = "<a:1000035804:1555025773742526615>"
E760 = "<a:1000035760:1554908193174589581>"
E763 = "<a:1000035763:1554920997382262874>"
E767 = "<a:1000035767:1554921960838926417>"
E762 = "<a:1000035762:1554919569682989166>"
E742 = "<a:1000035742:1554876309790793908>"
E727 = "<a:1000035727:1554859928957755393>"
E604 = "<a:1000035604:1554847795524141216>"
E725 = "<a:1000035725:1554844594175483904>"
E597 = "<a:1000035597:1554848439035240449>"
E608 = "<a:1000035608:1554844998506123274>"
E793 = "<:1000035793:1554977816431431850>"
E790 = "<:1000035790:1554970748232147004>"
E606 = "<a:1000035606:1554848463320129567>"
E728 = "<a:1000035728:1554860189125967894>"

DEFAULT_TITLE = f"{E725} ticket support {E725}"
DEFAULT_DESC = (f"{E597} หากพี่ๆต้องการเเจ้งปัญหาหรือสิ่งต่างๆสามารถกดticket "
                "พิมพ์สิ่งที่อยากจะเเจ้งให้พี่ๆเเอดมินได้เลยย")
TH_TZ = timezone(timedelta(hours=7))  # เวลาไทย แสดงในไฟล์บันทึกโดยไม่ต้องมีคำว่า UTC
PANEL_NAME = "╭・𝗧𝗶𝗰𝗸𝗲𝘁"
LOG_NAME = "╰・𝗧𝗶𝗰𝗸𝗲𝘁𝘀𝗟𝗼𝗴𝘀"


def pe(s: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(s)


def emb(desc: str) -> discord.Embed:
    return discord.Embed(description=desc, color=WHITE)


def safe(s: str) -> str:
    return (s or "").replace("`", "'")


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
    q("""CREATE TABLE IF NOT EXISTS tk_config (
        guild_id INTEGER PRIMARY KEY, category_id INTEGER, panel_channel_id INTEGER,
        log_channel_id INTEGER, panel_message_id INTEGER, counter INTEGER DEFAULT 0,
        title TEXT, description TEXT, banner TEXT)""")
    q("""CREATE TABLE IF NOT EXISTS tk_mentions (
        guild_id INTEGER, kind TEXT, target_id INTEGER, PRIMARY KEY (guild_id, kind, target_id))""")
    q("""CREATE TABLE IF NOT EXISTS tk_tickets (
        guild_id INTEGER, channel_id INTEGER PRIMARY KEY, number INTEGER, opener_id INTEGER,
        title TEXT, description TEXT, image_url TEXT, created_at INTEGER)""")


COLS = ("category_id", "panel_channel_id", "log_channel_id", "panel_message_id", "counter",
        "title", "description", "banner")


def get_cfg(gid: int) -> dict:
    row = q(f"SELECT {', '.join(COLS)} FROM tk_config WHERE guild_id=?", (gid,), one=True)
    return dict(zip(COLS, row)) if row else {c: None for c in COLS} | {"counter": 0}


def set_cfg(gid: int, **kw):
    cols = ", ".join(kw)
    ph = ", ".join("?" * len(kw))
    upd = ", ".join(f"{k}=excluded.{k}" for k in kw)
    q(f"INSERT INTO tk_config (guild_id, {cols}) VALUES (?, {ph}) "
      f"ON CONFLICT(guild_id) DO UPDATE SET {upd}", (gid, *kw.values()))


def get_mentions(gid: int) -> list:
    return q("SELECT kind, target_id FROM tk_mentions WHERE guild_id=?", (gid,), many=True)


def mention_text(gid: int) -> str:
    return " ".join(f"<@&{i}>" if k == "role" else f"<@{i}>" for k, i in get_mentions(gid)) or "ไม่มี"


def next_number(gid: int) -> int:
    q("INSERT INTO tk_config (guild_id, counter) VALUES (?, 1) "
      "ON CONFLICT(guild_id) DO UPDATE SET counter=counter+1", (gid,))
    return q("SELECT counter FROM tk_config WHERE guild_id=?", (gid,), one=True)[0]


# ═════════════ Embed ═════════════
def panel_embed(gid: int) -> discord.Embed:
    cfg = get_cfg(gid)
    e = emb(f"# {cfg['title'] or DEFAULT_TITLE}\n\n{cfg['description'] or DEFAULT_DESC}")
    if cfg["banner"]:
        e.set_image(url=cfg["banner"])
    return e


def setup_embed() -> discord.Embed:
    return emb(f"# {E804} เซ็ตTicket {E804}\n\n"
               f"{E760} พี่ๆกดลิสด้านล่างเซ็ตการทำงานได้เลยย หรือจะให้เป็นค่าเริ่มต้นของระบบก็ด้ายยย")


async def refresh_panel(guild: discord.Guild):
    """อัปเดตแผงที่ส่งไปแล้ว ให้ตรงกับหัวข้อ/คำอธิบาย/แบนเนอร์ล่าสุด"""
    cfg = get_cfg(guild.id)
    ch = guild.get_channel(cfg["panel_channel_id"] or 0)
    if ch is None or not cfg["panel_message_id"]:
        return
    try:
        msg = await ch.fetch_message(cfg["panel_message_id"])
        await msg.edit(embed=panel_embed(guild.id))
    except discord.HTTPException:
        pass


# ═════════════ ฝั่งแอดมิน: /ticket ═════════════
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


async def finish_modal(interaction: discord.Interaction, parent: discord.ui.View, embed: discord.Embed):
    try:
        await interaction.response.edit_message(view=parent)
    except discord.HTTPException:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


class TitleModal(discord.ui.Modal, title="เซ็ตหัวข้อ"):
    value = discord.ui.TextInput(label="หัวข้อของแผง Ticket", max_length=150,
                                 placeholder="เช่น ticket support (ใส่อีโมจิได้)")

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        set_cfg(interaction.guild.id, title=self.value.value.strip())
        await refresh_panel(interaction.guild)
        await finish_modal(interaction, self.parent, emb(f"{E606} เซ็ตหัวข้อเเล้วน้าา"))


class DescModal(discord.ui.Modal, title="เซ็ตคำอธิบาย"):
    value = discord.ui.TextInput(label="คำอธิบายในแผง Ticket", style=discord.TextStyle.paragraph,
                                 max_length=1500, placeholder="พิมพ์คำอธิบายที่ต้องการ")

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        set_cfg(interaction.guild.id, description=self.value.value.strip())
        await refresh_panel(interaction.guild)
        await finish_modal(interaction, self.parent, emb(f"{E606} เซ็ตคำอธิบายเเล้วน้าา"))


class BannerModal(discord.ui.Modal, title="เซ็ตภาพเเบนเนอร์"):
    value = discord.ui.TextInput(label="ลิงก์รูปภาพ (เว้นว่าง = ไม่มีเเบนเนอร์)", required=False,
                                 placeholder="https://...png / .gif")

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        url = self.value.value.strip()
        if url and not url.startswith(("http://", "https://")):
            return await finish_modal(interaction, self.parent,
                                      emb(f"{E790} ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https:// น้าา"))
        set_cfg(interaction.guild.id, banner=url or None)
        await refresh_panel(interaction.guild)
        await finish_modal(interaction, self.parent,
                           emb(f"{E606} เซ็ตภาพเเบนเนอร์เเล้วน้าา" if url else f"{E606} เอาเเบนเนอร์ออกเเล้วน้าา"))


class TextMenuView(AdminView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        sel = discord.ui.Select(placeholder="เซ็ตคำต่างๆเอง", options=[
            discord.SelectOption(label="หัวข้อ", value="title", emoji=pe(E727)),
            discord.SelectOption(label="คำอธิบาย", value="desc", emoji=pe(E727)),
            discord.SelectOption(label="ภาพเเบนเนอร์", value="banner", emoji=pe(E727)),
            discord.SelectOption(label="รีการตั้งค่า", value="reset", emoji=pe(E604)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        if v == "title":
            return await interaction.response.send_modal(TitleModal(self))
        if v == "desc":
            return await interaction.response.send_modal(DescModal(self))
        if v == "banner":
            return await interaction.response.send_modal(BannerModal(self))
        set_cfg(interaction.guild.id, title=None, description=None, banner=None)
        await refresh_panel(interaction.guild)
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(embed=emb(f"{E606} รีการตั้งค่าเป็นค่าเริ่มต้นเเล้วน้าา"), ephemeral=True)


class MentionView(AdminView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.sel = discord.ui.MentionableSelect(
            placeholder="เลือกคนหรือบทบาทที่จะให้เเท็ก", min_values=1, max_values=10, row=0)
        self.sel.callback = self.on_select
        self.add_item(self.sel)

    async def on_select(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        q("DELETE FROM tk_mentions WHERE guild_id=?", (gid,))
        for obj in self.sel.values:
            kind = "role" if isinstance(obj, discord.Role) else "user"
            q("INSERT OR IGNORE INTO tk_mentions VALUES (?,?,?)", (gid, kind, obj.id))
        await interaction.response.edit_message(
            embed=emb(f"{E606} เซ็ตเเล้วน้าา ตอนมีคนเปิด ticket จะเเท็ก: {mention_text(gid)}"), view=None)

    @discord.ui.button(label="ไม่เเท็กใครเลย", style=discord.ButtonStyle.secondary, row=1)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        q("DELETE FROM tk_mentions WHERE guild_id=?", (interaction.guild.id,))
        await interaction.response.edit_message(
            embed=emb(f"{E606} ล้างคนเเละบทบาทที่เเท็กเเล้วน้าา"), view=None)


class SetupView(AdminView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        sel = discord.ui.Select(placeholder="เซ็ตการทำงานTicket", options=[
            discord.SelectOption(label="เซ็ตการแท็กคนหรือบทบาทที่เกี่ยวข้อง", value="mention", emoji=pe(E763)),
            discord.SelectOption(label="เซ็ตคำต่างๆเอง", value="text", emoji=pe(E767)),
            discord.SelectOption(label="เริ่มระบบ Ticket", value="start", emoji=pe(E606)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E762)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        await interaction.response.edit_message(view=self)  # รีเซ็ตเมนู
        send = lambda **kw: interaction.followup.send(ephemeral=True, **kw)
        if v == "mention":
            await send(embed=emb(f"# {E742} เลือกคนหรือบทบาทที่จะให้เเท็ก {E742}\n\n"
                                 f"ตอนนี้: {mention_text(interaction.guild.id)}"),
                       view=MentionView(self.owner_id))
        elif v == "text":
            await send(embed=emb(f"{E727} เลือกสิ่งที่จะเซ็ตได้เลยน้าา"), view=TextMenuView(self.owner_id))
        elif v == "start":
            await self.start(interaction)
        else:
            await send(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"))

    async def start(self, interaction: discord.Interaction):
        guild, me = interaction.guild, interaction.guild.me
        send = lambda **kw: interaction.followup.send(ephemeral=True, **kw)
        if not me.guild_permissions.manage_channels:
            return await send(embed=emb(f"{E790} น้องต้องมีสิทธิ์ **จัดการช่อง** ก่อนน้าา"))

        cfg = get_cfg(guild.id)
        bot_ow = discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                             attach_files=True, read_message_history=True,
                                             manage_channels=True, manage_messages=True)
        try:
            category = guild.get_channel(cfg["category_id"] or 0)
            if category is None:
                category = await guild.create_category("ticket", overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False), me: bot_ow})

            panel = guild.get_channel(cfg["panel_channel_id"] or 0)
            if panel is None:  # ╭・Ticket เห็นทุกคน (อ่านได้อย่างเดียว)
                panel = await guild.create_text_channel(PANEL_NAME, category=category, overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True, send_messages=False, add_reactions=False, read_message_history=True),
                    me: bot_ow})

            log = guild.get_channel(cfg["log_channel_id"] or 0)
            if log is None:  # ╰・TicketsLogs เห็นเเค่แอดม
                log = await guild.create_text_channel(LOG_NAME, category=category, overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False), me: bot_ow})

            if cfg["panel_message_id"]:  # ลบแผงเก่า (ถ้ามี) แล้วส่งใหม่
                try:
                    await (await panel.fetch_message(cfg["panel_message_id"])).delete()
                except discord.HTTPException:
                    pass
            msg = await panel.send(embed=panel_embed(guild.id), view=TicketOpenView())
        except discord.HTTPException as e:
            return await send(embed=emb(f"{E790} สร้างระบบไม่สำเร็จ ({e.status}) เช็คสิทธิ์บอทเเล้วลองใหม่น้าา"))

        set_cfg(guild.id, category_id=category.id, panel_channel_id=panel.id,
                log_channel_id=log.id, panel_message_id=msg.id)
        await send(embed=emb(f"{E606} สร้างระบบ Ticket เเล้วน้าา\n{E767} ห้องเปิดตั๋ว: {panel.mention}\n"
                             f"{E767} ห้องบันทึก (เเอดมินเห็น): {log.mention}"))


# ═════════════ ฝั่งผู้ใช้: เปิด / ปิด ticket ═════════════
class TicketModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="เปิด Ticket")
        kw_t = {} if HAS_LABEL else {"label": "หัวข้อเรื่อง / Title"}
        kw_d = {} if HAS_LABEL else {"label": "รายละเอียดปัญหา / Description"}
        self.t_in = discord.ui.TextInput(placeholder="พิมพ์หัวข้อสั้นๆ...", max_length=100, **kw_t)
        self.d_in = discord.ui.TextInput(style=discord.TextStyle.paragraph, placeholder="ระบุรายละเอียดเพิ่มเติม...",
                                         max_length=1000, **kw_d)
        self.f_in = None
        if HAS_LABEL:
            self.add_item(discord.ui.Label(text="หัวข้อเรื่อง / Title",
                                           description="ระบุหัวข้อปัญหา หรือเรื่องที่ต้องการสอบถาม...",
                                           component=self.t_in))
            self.add_item(discord.ui.Label(text="รายละเอียดปัญหา / Description",
                                           description="อธิบายรายละเอียดปัญหา หรือสิ่งที่ต้องการให้ช่วยเหลือ...",
                                           component=self.d_in))
            if HAS_UPLOAD:
                self.f_in = discord.ui.FileUpload(required=False, min_values=0, max_values=1)
                self.add_item(discord.ui.Label(text="แนบรูปภาพ (ถ้ามี) / Image (Optional)",
                                               description="ลากวางหรืออัปโหลดรูปภาพปัญหา (ถ้ามี)",
                                               component=self.f_in))
        else:
            self.add_item(self.t_in)
            self.add_item(self.d_in)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild, user = interaction.guild, interaction.user
        cfg = get_cfg(guild.id)
        category = guild.get_channel(cfg["category_id"] or 0)
        if category is None:
            return await interaction.followup.send(
                embed=emb(f"{E790} ระบบ Ticket ยังไม่พร้อมน้าา ให้เเอดมินกดเริ่มระบบก่อน"), ephemeral=True)

        title, desc = self.t_in.value.strip(), self.d_in.value.strip()
        files, img_name = [], None
        atts = list(getattr(self.f_in, "values", None) or []) if self.f_in else []
        if atts and (atts[0].content_type or "").startswith("image/"):
            ext = os.path.splitext(atts[0].filename)[1] or ".png"
            img_name = f"image{ext}"
            files.append(discord.File(io.BytesIO(await atts[0].read()), filename=img_name))

        n = next_number(guild.id)
        member_ow = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                                attach_files=True, embed_links=True)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                                  attach_files=True, read_message_history=True,
                                                  manage_channels=True),
            user: member_ow,
        }
        pings = []
        for kind, tid in get_mentions(guild.id):
            obj = guild.get_role(tid) if kind == "role" else guild.get_member(tid)
            if obj is not None:
                overwrites[obj] = member_ow
                pings.append(obj.mention)
        try:
            channel = await guild.create_text_channel(
                f"ticket-{n}", category=category, overwrites=overwrites,
                topic=f"ticket ของ {user} ({user.id})", reason=f"ticket #{n}")
        except discord.HTTPException:
            return await interaction.followup.send(embed=emb(f"{E790} สร้างห้อง ticket ไม่สำเร็จน้า ลองใหม่อีกที"),
                                                   ephemeral=True)

        e = discord.Embed(
            description=(f"# {E793} Ticket Support {E793}\n\n"
                         f"**ผู้เปิดตั๋ว** {user.mention}\n"
                         f"**บทบาทที่เกี่ยวข้อง** {' '.join(pings) or 'ไม่มี'}\n\n"
                         f"**หัวข้อเรื่อง** ``{safe(title)}``\n\n"
                         f"**ปัญหาร้องเรียน**\n```{safe(desc)}```"),
            color=WHITE, timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=user.display_avatar.url)
        e.set_footer(text="เปิดตั๋วเมื่อ")
        if img_name:
            e.set_image(url=f"attachment://{img_name}")
        sent = await channel.send(
            content=" ".join([user.mention] + pings), embed=e, files=files, view=TicketCloseView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        image_url = sent.attachments[0].url if sent.attachments else None
        q("INSERT OR REPLACE INTO tk_tickets VALUES (?,?,?,?,?,?,?,?)",
          (guild.id, channel.id, n, user.id, title, desc, image_url, int(time.time())))
        await interaction.followup.send(embed=emb(f"{E606} เปิด ticket เเล้วน้าา {channel.mention}"), ephemeral=True)


class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="open", style=discord.ButtonStyle.primary, emoji=pe(E608), custom_id="ticket:open")
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal())


CLOSING: set = set()


def build_transcript(history: list, channel, guild, closer) -> str:
    fmt = "%Y-%m-%d %H:%M:%S"
    out = [f"TICKET TRANSCRIPT ({channel.name})",
           f"Server: {guild.name} ({guild.id})", f"Closed By: {closer} ({closer.id})",
           f"Closed At: {discord.utils.utcnow().astimezone(TH_TZ).strftime(fmt)}", ""]
    for m in history:
        out.append(f"[{m.created_at.astimezone(TH_TZ).strftime(fmt)}] {m.author} ({m.author.id}):")
        for ln in (m.content or "").split("\n") if m.content else []:
            out.append("  " + ln)
        for e in m.embeds:
            if e.title:
                out.append(f"  [Embed Title: {e.title}]")
            if e.description:
                out.append(f"  [Embed Description: {e.description}]")
            for f in e.fields:
                out.append(f"  [Embed Field: {f.name}: {f.value}]")
        for a in m.attachments:
            out.append(f"  [Attachment: {a.filename} {a.url}]")
        out.append("")
    return "\n".join(out)


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ปิด Ticket", style=discord.ButtonStyle.danger, emoji=pe(E790),
                       custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ปิดไม่ได้น้าาพี่ไม่ใช่แอดมิน"), ephemeral=True)

        guild, channel, closer = interaction.guild, interaction.channel, interaction.user
        if channel.id in CLOSING:
            return await interaction.response.send_message(embed=emb("กำลังปิดอยู่น้าา รอแปปนึง"), ephemeral=True)
        CLOSING.add(channel.id)
        await interaction.response.send_message(embed=emb(f"{E606} รอสักครู่"))
        try:
            row = q("SELECT number, opener_id, title, description, image_url FROM tk_tickets WHERE channel_id=?",
                    (channel.id,), one=True)
            number, opener_id, title, desc, image_url = row if row else ("?", 0, "ไม่ทราบ", "ไม่ทราบ", None)
            cfg = get_cfg(guild.id)
            log_ch = guild.get_channel(cfg["log_channel_id"] or 0)
            if log_ch is None:
                return await channel.send(embed=emb(f"{E790} ไม่พบห้อง TicketsLogs เลยยังไม่ลบห้องน้าา"))

            history = [m async for m in channel.history(limit=None, oldest_first=True)]
            txt = build_transcript(history, channel, guild, closer)
            files = [discord.File(io.BytesIO(txt.encode("utf-8")), filename=f"transcript-{channel.name}.txt")]

            e = discord.Embed(
                description=(f"# {E767} บันทึกรายงานการตอบticket {E767}\n\n"
                             f"**ผู้เปิดตั๋ว** <@{opener_id}>\n**ผู้ปิดตั๋ว** {closer.mention}\n"
                             f"**หัวข้อเรื่องที่เเจ้ง** ``{safe(title)}``\n"
                             f"**เนื้อหารายละเอียด** ``{safe(desc)[:800]}``\n\n"
                             f"**รูปที่เเนบมา**{'' if image_url else ' ไม่มี'}\n\n"
                             f"**ticketที่ {number}**"),
                color=WHITE, timestamp=discord.utils.utcnow())
            e.set_footer(text="ปิดตั๋วเมื่อ")
            if image_url:  # โหลดรูปมาแนบใหม่ เพราะห้องนี้กำลังจะถูกลบ
                try:
                    async with aiohttp.ClientSession() as s, s.get(image_url) as r:
                        data = await r.read()
                    ext = os.path.splitext(urlparse(image_url).path)[1] or ".png"
                    files.append(discord.File(io.BytesIO(data), filename=f"image{ext}"))
                    e.set_image(url=f"attachment://image{ext}")
                except Exception:
                    pass
            await log_ch.send(embed=e, files=files)

            q("DELETE FROM tk_tickets WHERE channel_id=?", (channel.id,))
            await channel.delete(reason=f"ปิด ticket #{number} โดย {closer}")
        except discord.HTTPException:
            try:
                await channel.send(embed=emb(f"{E790} ปิด ticket ไม่สำเร็จ เช็คสิทธิ์บอทเเล้วลองใหม่"))
            except discord.HTTPException:
                pass
        finally:
            CLOSING.discard(channel.id)


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()
        self.bot.add_view(TicketOpenView())   # ปุ่มยังกดได้หลังรีสตาร์ท
        self.bot.add_view(TicketCloseView())

    @app_commands.command(name="ticket", description="เซ็ตระบบ Ticket (แอดมินเท่านั้น)")
    @app_commands.guild_only()
    async def ticket(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
        await interaction.response.send_message(
            embed=setup_embed(), view=SetupView(interaction.user.id), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))
