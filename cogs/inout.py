import io
import os
import re
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import db

WHITE_INT = 0xFFFFFF
MAX_IMG_BYTES = 3_500_000
HAS_LABEL = hasattr(discord.ui, "Label")
HAS_UPLOAD = HAS_LABEL and hasattr(discord.ui, "FileUpload")

# ───────── อีโมจิ ─────────
E902 = "<a:1000035902:1556012107110158407>"
E901 = "<a:1000035901:1556012131093184583>"
E876 = "<a:1000035876:1555348098048462970>"
E903 = "<a:1000035903:1556012933182660719>"
E905 = "<a:1000035905:1556014618831233085>"
E906 = "<a:1000035906:1556014806346113185>"
E908 = "<a:1000035908:1556015707181944882>"
E804 = "<a:1000035804:1555025773742526615>"
E907 = "<a:1000035907:1556015174555803688>"
E904 = "<a:1000035904:1556014608353861643>"
E910 = "<a:1000035910:1556020302063075429>"
E790 = "<:1000035790:1554970748232147004>"

KIND_NAME = {"welcome": "welcome", "goodbye": "goodbey"}


def pe(s: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(s)


def emb(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=discord.Color(WHITE_INT))


# ═════════════ ฐานข้อมูล ═════════════
def q(sql: str, args=(), one=False):
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, args)
        res = cur.fetchone() if one else None
        conn.commit()
        return res
    finally:
        conn.close()


def init_tables():
    q("""CREATE TABLE IF NOT EXISTS io_config (
        guild_id INTEGER, kind TEXT, title TEXT, body TEXT, color INTEGER, image BLOB, ext TEXT,
        image_url TEXT, channel_id INTEGER, enabled INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, kind))""")


COLS = ("title", "body", "color", "image", "ext", "image_url", "channel_id", "enabled")


def get_cfg(gid: int, kind: str) -> dict:
    row = q(f"SELECT {', '.join(COLS)} FROM io_config WHERE guild_id=? AND kind=?", (gid, kind), one=True)
    return dict(zip(COLS, row)) if row else {c: None for c in COLS}


def save_cfg(gid: int, kind: str, **kw):
    cols = ", ".join(kw)
    ph = ", ".join("?" * len(kw))
    upd = ", ".join(f"{k}=excluded.{k}" for k in kw)
    q(f"INSERT INTO io_config (guild_id, kind, {cols}) VALUES (?, ?, {ph}) "
      f"ON CONFLICT(guild_id, kind) DO UPDATE SET {upd}", (gid, kind, *kw.values()))


def configured(cfg: dict) -> bool:
    return bool((cfg["title"] or "").strip() or (cfg["body"] or "").strip())


# ═════════════ สี ═════════════
COLOR_NAMES = {
    "ขาว": 0xFFFFFF, "white": 0xFFFFFF, "ดำ": 0x000000, "black": 0x000000, "เทา": 0x808080, "gray": 0x808080,
    "แดง": 0xED4245, "red": 0xED4245, "ส้ม": 0xFF8C00, "orange": 0xFF8C00, "เหลือง": 0xFEE75C, "yellow": 0xFEE75C,
    "เขียว": 0x57F287, "green": 0x57F287, "ฟ้า": 0x3BA8FF, "cyan": 0x00E5FF, "น้ำเงิน": 0x2F4BFF, "blue": 0x2F4BFF,
    "ม่วง": 0x9B59B6, "purple": 0x9B59B6, "ชมพู": 0xFF9ECF, "pink": 0xFF9ECF, "น้ำตาล": 0x8B5A2B, "brown": 0x8B5A2B,
    "ทอง": 0xFFD700, "gold": 0xFFD700, "เงิน": 0xC0C0C0, "silver": 0xC0C0C0,
}


def parse_color(text: str) -> Optional[int]:
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in COLOR_NAMES:
        return COLOR_NAMES[t]
    m = re.fullmatch(r"#?([0-9a-f]{6})", t) or re.fullmatch(r"0x([0-9a-f]{6})", t)
    if m:
        return int(m.group(1), 16)
    m = re.fullmatch(r"#?([0-9a-f]{3})", t)
    if m:
        return int("".join(c * 2 for c in m.group(1)), 16)
    return -1   # ใช้ไม่ได้


# ═════════════ Variable ═════════════
VARIABLES = [
    ("{user}", "เเท็กคนที่เข้า/ออก"),
    ("{user.name}", "ชื่อบัญชี (username)"),
    ("{user.display}", "ชื่อที่เเสดงในเซิร์ฟ"),
    ("{user.id}", "ไอดีของคนนั้น"),
    ("{user.avatar}", "ลิงก์รูปโปรไฟล์"),
    ("{user.created}", "วันที่สร้างบัญชี"),
    ("{user.created.ago}", "สร้างบัญชีมานานเเค่ไหน (เช่น 3 ปีที่เเล้ว)"),
    ("{user.joined}", "วันที่เข้าเซิร์ฟ"),
    ("{user.joined.ago}", "เข้าเซิร์ฟมานานเเค่ไหน"),
    ("{user.roles}", "ยศทั้งหมดที่คนนั้นมี (เเท็กยศ)"),
    ("{user.bot}", "เป็นบอทมั้ย (ใช่/ไม่ใช่)"),
    ("{server}", "ชื่อเซิร์ฟเวอร์"),
    ("{server.id}", "ไอดีเซิร์ฟเวอร์"),
    ("{server.icon}", "ลิงก์รูปเซิร์ฟเวอร์"),
    ("{server.owner}", "เเท็กเจ้าของเซิร์ฟเวอร์"),
    ("{count}", "จำนวนสมาชิกในเซิร์ฟตอนนี้"),
    ("{count.ordinal}", "ลำดับสมาชิก เช่น คนที่ 1234"),
    ("{date}", "วันที่ตอนนี้"),
    ("{time}", "เวลาตอนนี้"),
    ("{datetime}", "วันที่เเละเวลาตอนนี้"),
]
NATIVE = [
    ("<@&IDยศ>", "ใช้สำหรับเเท็กยศ"),
    ("<@IDคน>", "ใช้สำหรับเเท็กคน"),
    ("<#IDห้อง>", "ใช้สำหรับลิงก์ไปห้องนั้น (เช่น ห้องกฎ ห้องรับยศ)"),
    ("<a:ชื่อ:ID> หรือ <:ชื่อ:ID>", "ใช้ใส่อีโมจิ (ต้องเป็นอีโมจิที่บอทเข้าถึงได้)"),
    ("<t:เลข:F>", "เเสดงเวลาตามเวลาของคนอ่าน (F=เต็ม, R=เมื่อกี้/ผ่านมา, D=วันที่, t=เวลา)"),
    ("**ตัวหนา**  *ตัวเอียง*  __ขีดเส้นใต้__  ~~ขีดฆ่า~~", "ตัวอักษรของ Discord ใช้ได้ปกติ"),
]


def variables_embed(kind: str) -> discord.Embed:
    who = "คนเข้า" if kind == "welcome" else "คนออก"
    lines = [f"# {E910} Variableที่สามารถใช้กับ{KIND_NAME[kind]}ได้", "",
             f"**Variable ของบอท** (เเทนค่าของ{who}เเละเซิร์ฟเวอร์ให้เอง)"]
    lines += [f"`{k}` {v}" for k, v in VARIABLES]
    lines += ["", "**ใช้ของ Discord ตรงๆ ได้เลย**"]
    lines += [f"`{k}` {v}" for k, v in NATIVE]
    lines += ["", "ใส่ได้ทั้งในหัวข้อเเละเนื้อหา เเล้วกด **ทดสอบ** เพื่อดูผลก่อนได้เลยน้า"]
    return emb("\n".join(lines))


def ago_text(dt) -> str:
    return f"<t:{int(dt.timestamp())}:R>" if dt else "-"


def render_text(text: str, member: discord.Member, guild: discord.Guild) -> str:
    now = int(time.time())
    roles = " ".join(r.mention for r in getattr(member, "roles", []) if r != guild.default_role)
    if len(roles) > 800:
        roles = roles[:800] + "…"
    joined = getattr(member, "joined_at", None)
    count = guild.member_count or len(guild.members)
    values = {
        "user": member.mention, "user.name": member.name, "user.display": member.display_name,
        "user.id": str(member.id), "user.avatar": member.display_avatar.url,
        "user.created": f"<t:{int(member.created_at.timestamp())}:F>", "user.created.ago": ago_text(member.created_at),
        "user.joined": f"<t:{int(joined.timestamp())}:F>" if joined else "-", "user.joined.ago": ago_text(joined),
        "user.roles": roles or "ไม่มี", "user.bot": "ใช่" if member.bot else "ไม่ใช่",
        "server": guild.name, "server.id": str(guild.id),
        "server.icon": guild.icon.url if guild.icon else "-",
        "server.owner": f"<@{guild.owner_id}>", "count": str(count), "count.ordinal": f"คนที่ {count}",
        "date": f"<t:{now}:D>", "time": f"<t:{now}:t>", "datetime": f"<t:{now}:F>",
    }
    return re.sub(r"\{([A-Za-z_.]+)\}", lambda m: values.get(m.group(1).lower(), m.group(0)), text)


def build_message(cfg: dict, member: discord.Member, guild: discord.Guild, tag: bool):
    """คืน (embed, file|None, content|None)"""
    title = render_text(cfg["title"] or "", member, guild).strip()
    body = render_text(cfg["body"] or "", member, guild).strip()
    desc = (f"# {title}\n\n" if title else "") + body
    color = cfg["color"] if cfg["color"] is not None else WHITE_INT
    e = discord.Embed(description=desc[:4000] or "\u200b", color=discord.Color(color))
    e.set_thumbnail(url=member.display_avatar.url)   # โปรไฟล์คนนั้นอยู่ขวาบน
    file = None
    if cfg["image"]:
        file = discord.File(io.BytesIO(cfg["image"]), filename=f"image{cfg['ext'] or '.png'}")
        e.set_image(url=f"attachment://image{cfg['ext'] or '.png'}")
    elif cfg["image_url"]:
        e.set_image(url=cfg["image_url"])
    return e, file, (member.mention if tag else None)


# ═════════════ Views / Modals ═════════════
class AdminView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=900)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
            return False
        return True


class SetModal(discord.ui.Modal):
    def __init__(self, kind: str, parent: discord.ui.View, cfg: dict):
        super().__init__(title=f"เซ็ต{KIND_NAME[kind]}")
        self.kind, self.parent, self.old_url = kind, parent, cfg["image_url"] or ""
        k = lambda label: {} if HAS_LABEL else {"label": label}
        self.t_in = discord.ui.TextInput(max_length=150, required=False, default=cfg["title"] or None,
                                         placeholder="หัวข้อ เช่น ยินดีต้อนรับ {user.display}", **k("หัวข้อ"))
        self.b_in = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=2000, required=False,
                                         default=cfg["body"] or None, placeholder="เนื้อหาข้างใน (ใช้ Variable ได้)",
                                         **k("เนื้อหาข้างใน"))
        hexcolor = f"#{cfg['color']:06X}" if cfg["color"] is not None else None
        self.c_in = discord.ui.TextInput(max_length=30, required=False, default=hexcolor,
                                         placeholder="เช่น #FF99CC หรือ ชมพู / แดง / blue (ว่าง = สีขาว)", **k("สีembed"))
        self.u_in = discord.ui.TextInput(max_length=500, required=False, default=cfg["image_url"] or None,
                                         placeholder="ลิงก์รูป/gif (ใส่ - เพื่อลบรูป)", **k("ลิงก์รูป/gif (ไม่บังคับ)"))
        self.f_in = None
        if HAS_LABEL:
            self.add_item(discord.ui.Label(text="หัวข้อ", component=self.t_in))
            self.add_item(discord.ui.Label(text="เนื้อหาข้างใน", component=self.b_in))
            self.add_item(discord.ui.Label(text="สีembed (ไม่บังคับ)", description="ว่าง = สีขาว", component=self.c_in))
            self.add_item(discord.ui.Label(text="ลิงก์รูป/gif (ไม่บังคับ)", component=self.u_in))
            if HAS_UPLOAD:
                self.f_in = discord.ui.FileUpload(required=False, min_values=0, max_values=1)
                self.add_item(discord.ui.Label(text="หรืออัปโหลดรูป/gif (ไม่บังคับ)",
                                               description="ถ้าอัปโหลด จะใช้ไฟล์นี้เเทนลิงก์", component=self.f_in))
        else:
            for it in (self.t_in, self.b_in, self.c_in, self.u_in):
                self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        color_raw = self.c_in.value.strip()
        color = parse_color(color_raw)
        await interaction.response.edit_message(view=self.parent)   # รีเซ็ตเมนู
        if color == -1:
            return await interaction.followup.send(embed=emb(
                f"{E790} สีไม่ถูกต้องน้า ใช้ hex เช่น #FF99CC หรือชื่อสี เช่น ชมพู แดง ฟ้า"), ephemeral=True)

        gid = interaction.guild.id
        kw = {"title": self.t_in.value.strip(), "body": self.b_in.value.strip(),
              "color": color if color_raw else None}
        url = self.u_in.value.strip()
        atts = list(getattr(self.f_in, "values", None) or []) if self.f_in else []
        if atts:
            att = atts[0]
            data = await att.read()
            ct = (att.content_type or "").lower()
            if not ct.startswith("image/") or len(data) > MAX_IMG_BYTES:
                return await interaction.followup.send(embed=emb(
                    f"{E790} ไฟล์ต้องเป็นรูป/gif ขนาดไม่เกิน {MAX_IMG_BYTES / 1_000_000:g} MB น้า"), ephemeral=True)
            ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}.get(
                ct.split(";")[0], os.path.splitext(att.filename)[1] or ".png")
            kw.update(image=data, ext=ext, image_url=None)
        elif url == "-":
            kw.update(image=None, ext=None, image_url=None)
        elif url:
            if not url.startswith(("http://", "https://")):
                return await interaction.followup.send(embed=emb(f"{E790} ลิงก์รูปต้องขึ้นต้นด้วย http:// หรือ https:// น้า"),
                                                       ephemeral=True)
            kw.update(image=None, ext=None, image_url=url)
        elif self.old_url:       # เคยมีลิงก์แล้วเคลียร์ช่องออก = เอารูปออก
            kw.update(image_url=None)
        save_cfg(gid, self.kind, **kw)
        await interaction.followup.send(embed=emb(
            f"{E904} เซ็ตเสร็จสิ้น สามารถกดเริ่มหรือทดสอบลองดูก่อนได้"), ephemeral=True)


class ChannelPickView(AdminView):
    def __init__(self, owner_id: int, kind: str):
        super().__init__(owner_id)
        self.kind = kind
        self.sel = discord.ui.ChannelSelect(
            placeholder=f"เลือกห้องที่จะเป็นห้อง{KIND_NAME[kind]}", min_values=1, max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=0)
        self.sel.callback = self.on_select
        self.add_item(self.sel)
        stop = discord.ui.Button(label=f"หยุดระบบ{KIND_NAME[kind]}", style=discord.ButtonStyle.secondary, row=1)
        stop.callback = self.stop_system
        self.add_item(stop)

    async def on_select(self, interaction: discord.Interaction):
        ch = interaction.guild.get_channel(self.sel.values[0].id)
        perms = ch.permissions_for(interaction.guild.me) if ch else None
        if ch is None or not (perms.view_channel and perms.send_messages and perms.embed_links):
            return await interaction.response.edit_message(embed=emb(
                f"{E790} น้องส่งข้อความ/embed ในห้องนั้นไม่ได้น้า ช่วยเปิดสิทธิ์ให้น้องก่อน"), view=None)
        save_cfg(interaction.guild.id, self.kind, channel_id=ch.id, enabled=1)
        who = "คนเข้าเซิร์ฟ" if self.kind == "welcome" else "คนออกจากเซิร์ฟ"
        await interaction.response.edit_message(embed=emb(
            f"{E904} เริ่มระบบ{KIND_NAME[self.kind]}เเล้วน้าา เมื่อมี{who} จะเเจ้งที่ห้อง {ch.mention}"), view=None)

    async def stop_system(self, interaction: discord.Interaction):
        save_cfg(interaction.guild.id, self.kind, enabled=0)
        await interaction.response.edit_message(embed=emb(f"{E901} หยุดระบบ{KIND_NAME[self.kind]}เเล้วน้า"), view=None)


def kind_embed(kind: str, gid: int) -> discord.Embed:
    cfg = get_cfg(gid, kind)
    state = "ยังไม่ได้เซ็ต" if not configured(cfg) else "เซ็ตเเล้ว"
    run = f"เปิดอยู่ที่ <#{cfg['channel_id']}>" if cfg["enabled"] and cfg["channel_id"] else "ยังไม่ได้เริ่ม"
    return emb(f"# {E876} เซ็ตการตั้งค่าต่างๆ\n\n{E804} เซ็ตการตั้งค่าต่างๆ\n\n"
               f"สถานะ{KIND_NAME[kind]}: **{state}** • **{run}**")


class KindMenuView(AdminView):
    def __init__(self, owner_id: int, kind: str):
        super().__init__(owner_id)
        self.kind = kind
        n = KIND_NAME[kind]
        sel = discord.ui.Select(placeholder="ลิสคำสั่ง", options=[
            discord.SelectOption(label=f"เซ็ต{n}", value="set", emoji=pe(E907)),
            discord.SelectOption(label="ดูVariable", value="vars", emoji=pe(E907)),
            discord.SelectOption(label=f"ทดสอบ{n}", value="test", emoji=pe(E905)),
            discord.SelectOption(label="เริ่ม", value="start", emoji=pe(E904)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E901)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v, gid, kind = interaction.data["values"][0], interaction.guild.id, self.kind
        cfg = get_cfg(gid, kind)
        if v == "set":
            return await interaction.response.send_modal(SetModal(kind, self, cfg))
        await interaction.response.edit_message(view=KindMenuView(self.owner_id, kind))  # รีเซ็ตเมนู
        send = lambda **kw: interaction.followup.send(ephemeral=True, **kw)
        if v == "vars":
            return await send(embed=variables_embed(kind))
        if v == "clear":
            return await send(embed=emb(f"{E901} ล้างตัวเลือกสำเร็จจ"))
        if not configured(cfg):
            return await send(embed=emb(f"{E790} ยังไม่ได้เซ็ต{KIND_NAME[kind]}น้า กดเซ็ตก่อนเลย"))
        if v == "test":
            e, file, content = build_message(cfg, interaction.user, interaction.guild, tag=True)
            return await send(content=content, embed=e, **({"file": file} if file else {}),
                              allowed_mentions=discord.AllowedMentions.none())
        await send(embed=emb(f"{E804} เลือกห้องที่จะเป็นห้อง{KIND_NAME[kind]}ได้เลย"),
                   view=ChannelPickView(self.owner_id, kind))


class MainView(AdminView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        sel = discord.ui.Select(placeholder="ลิสคำสั่ง", options=[
            discord.SelectOption(label="เซ็ตwelcome", value="welcome", emoji=pe(E905)),
            discord.SelectOption(label="เซ็ตgoodbey", value="goodbye", emoji=pe(E906)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E908)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        await interaction.response.edit_message(view=MainView(self.owner_id))  # รีเซ็ตเมนู
        if v == "clear":
            return await interaction.followup.send(embed=emb(f"{E908} ล้างตัวเลือกสำเร็จจ"), ephemeral=True)
        await interaction.followup.send(embed=kind_embed(v, interaction.guild.id),
                                        view=KindMenuView(self.owner_id, v), ephemeral=True)


# ═════════════ Cog ═════════════
class InOutCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()

    @app_commands.command(name="in_out", description="เซ็ตระบบเข้าออก (แอดมินเท่านั้น)")
    @app_commands.guild_only()
    async def in_out(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
        e = emb(f"# {E902} เซ็ตระบบคนเข้าออก {E901}\n\n"
                f"{E876} เลือกเซ็ตการเข้าออกเซิฟเวอร์\n"
                f"{E903} สามารถดู Variable ที่สามารถใช้ได้\n"
                f"{E876} สามารถทดสอบwelcomeหรือgoodbeyได้")
        await interaction.response.send_message(embed=e, view=MainView(interaction.user.id), ephemeral=True)

    async def announce(self, member: discord.Member, kind: str):
        if member.bot:
            return
        guild = member.guild
        cfg = get_cfg(guild.id, kind)
        if not cfg["enabled"] or not configured(cfg):
            return
        ch = guild.get_channel(cfg["channel_id"] or 0)
        if ch is None:
            return
        e, file, content = build_message(cfg, member, guild, tag=(kind == "welcome"))
        try:
            await ch.send(content=content, embed=e, **({"file": file} if file else {}),
                          allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False))
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.announce(member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.announce(member, "goodbye")


async def setup(bot: commands.Bot):
    await bot.add_cog(InOutCog(bot))
