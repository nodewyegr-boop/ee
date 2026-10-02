import asyncio
import io
import math
import os
import random
import string
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)
REVIEW_CHANNEL_ID = 1490346694813024276   # ห้องที่ส่งผลงานมาให้แอดมินกด ผ่าน/ไม่ผ่าน
REPORT_CHANNEL_ID = 1488612764854390846   # ห้องที่รับรายงาน
SUBMIT_CD = 600       # ลงผลงานได้ 1 ผลงานต่อ 10 นาที
REPORT_CD = 1800      # แจ้งปัญหาได้ 1 ครั้งต่อ 30 นาที
MAX_IMG_BYTES = 3_500_000   # ขนาดรูปสูงสุดที่เก็บ (เกินนี้บอทจะบีบอัดให้ถ้ามี Pillow)
HAS_LABEL = hasattr(discord.ui, "Label")
HAS_UPLOAD = HAS_LABEL and hasattr(discord.ui, "FileUpload")

# ───────── อีโมจิ ─────────
E874 = "<a:1000035874:1555340049212506242>"
E863 = "<:1000035863:1555305403305295912>"
E790 = "<:1000035790:1554970748232147004>"
E803 = "<a:1000035803:1555025202482516100>"
E793 = "<:1000035793:1554977816431431850>"
E739 = "<a:1000035739:1554873266987081742>"
E804 = "<a:1000035804:1555025773742526615>"
E866 = "<:1000035866:1555310612341461084>"
E865 = "<:1000035865:1555310615478931616>"
E727 = "<a:1000035727:1554859928957755393>"
E742 = "<a:1000035742:1554876309790793908>"
E607 = "<a:1000035607:1554874918632562788>"
E729 = "<a:1000035729:1554863632528052315>"
E767 = "<a:1000035767:1554921960838926417>"
E876 = "<a:1000035876:1555348098048462970>"
E764 = "<a:1000035764:1554920142146904164>"
E763 = "<a:1000035763:1554920997382262874>"
E606 = "<a:1000035606:1554848463320129567>"
E728 = "<a:1000035728:1554860189125967894>"

CATS = {"draw": "งานวาด", "game": "เกม", "system": "ระบบต่างๆ", "promo": "การโปรโมท", "general": "ผลงานทั่วไป"}
STATUS_TH = {"pending": "รออนุมัติ", "approved": "อนุมัติเเล้ว", "rejected": "ไม่ผ่านการอนุมัติ"}


def pe(s: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(s)


def emb(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=WHITE)


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
    q("CREATE TABLE IF NOT EXISTS pf_config (guild_id INTEGER PRIMARY KEY, channel_id INTEGER, panel_message_id INTEGER)")
    q("""CREATE TABLE IF NOT EXISTS pf_works (
        id TEXT PRIMARY KEY, owner_id INTEGER, title TEXT, description TEXT, category TEXT,
        status TEXT, private INTEGER DEFAULT 0, image BLOB, ext TEXT, created_at INTEGER,
        approved_at INTEGER, review_msg_id INTEGER)""")
    q("CREATE INDEX IF NOT EXISTS idx_pf_works ON pf_works (status, private, category)")
    q("CREATE TABLE IF NOT EXISTS pf_hearts (work_id TEXT, user_id INTEGER, PRIMARY KEY (work_id, user_id))")
    q("""CREATE TABLE IF NOT EXISTS pf_comments (
        cid TEXT PRIMARY KEY, work_id TEXT, user_id INTEGER, text TEXT, created_at INTEGER,
        UNIQUE (work_id, user_id))""")
    q("CREATE TABLE IF NOT EXISTS pf_bans (user_id INTEGER PRIMARY KEY, banned_by INTEGER, created_at INTEGER)")
    q("CREATE TABLE IF NOT EXISTS pf_cd (user_id INTEGER, kind TEXT, last_at INTEGER, PRIMARY KEY (user_id, kind))")
    q("""CREATE TABLE IF NOT EXISTS pf_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER, title TEXT, work_id TEXT,
        comment_id TEXT, detail TEXT, created_at INTEGER, msg_id INTEGER, handled INTEGER DEFAULT 0)""")


WORK_COLS = ("id", "owner_id", "title", "description", "category", "status", "private", "image", "ext",
             "created_at", "approved_at", "review_msg_id")


def get_work(wid: str) -> Optional[dict]:
    row = q(f"SELECT {', '.join(WORK_COLS)} FROM pf_works WHERE id=?", (wid,), one=True)
    return dict(zip(WORK_COLS, row)) if row else None


def hearts(wid: str) -> int:
    return q("SELECT COUNT(*) FROM pf_hearts WHERE work_id=?", (wid,), one=True)[0]


def is_banned(uid: int) -> bool:
    return q("SELECT 1 FROM pf_bans WHERE user_id=?", (uid,), one=True) is not None


def cd_left(uid: int, kind: str, seconds: int) -> int:
    """คืนเวลา (unix) ที่ใช้ได้อีกครั้ง ถ้ายังไม่ถึง; 0 = ใช้ได้เลย"""
    row = q("SELECT last_at FROM pf_cd WHERE user_id=? AND kind=?", (uid, kind), one=True)
    return int(row[0] + seconds) if row and row[0] + seconds > time.time() else 0


def set_cd(uid: int, kind: str):
    q("INSERT OR REPLACE INTO pf_cd VALUES (?,?,?)", (uid, kind, int(time.time())))


def new_work_id() -> str:
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    while True:
        wid = "".join(random.choices(alphabet, k=6))
        if not get_work(wid):
            return wid


COMMENT_SYMBOLS = "!@#$%&*+?~=^"


def new_comment_id() -> str:
    """ไอดีคำแนะนำ 3 หลัก: ตัวอักษรอังกฤษ 1 + ตัวเลข 1 + เครื่องหมาย 1 (ถ้าเต็มจริงๆ ต่อท้ายเลขเพิ่ม)"""
    base = lambda: random.choice(string.ascii_uppercase) + random.choice(string.digits) + random.choice(COMMENT_SYMBOLS)
    for _ in range(300):
        cid = base()
        if not q("SELECT 1 FROM pf_comments WHERE cid=?", (cid,), one=True):
            return cid
    while True:
        cid = base() + random.choice(string.digits)
        if not q("SELECT 1 FROM pf_comments WHERE cid=?", (cid,), one=True):
            return cid


def delete_work(wid: str):
    q("DELETE FROM pf_hearts WHERE work_id=?", (wid,))
    q("DELETE FROM pf_comments WHERE work_id=?", (wid,))
    q("DELETE FROM pf_works WHERE id=?", (wid,))


# ═════════════ รูปภาพ ═════════════
def prepare_image(data: bytes, content_type: str, filename: str):
    """คืน (bytes, นามสกุล) หรือ None ถ้าใช้ไม่ได้ ; บีบอัดถ้าใหญ่เกิน (ต้องมี Pillow)"""
    ct = (content_type or "").lower()
    if not ct.startswith("image/"):
        return None
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}.get(
        ct.split(";")[0], os.path.splitext(filename)[1].lower() or ".png")
    if len(data) > MAX_IMG_BYTES * 0.6 and PIL_OK and ext != ".gif":
        try:
            im = Image.open(io.BytesIO(data))
            im = im.convert("RGB")
            im.thumbnail((1920, 1920))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85, optimize=True)
            data, ext = buf.getvalue(), ".jpg"
        except Exception:
            pass
    return (data, ext) if len(data) <= MAX_IMG_BYTES else None


def work_file(w: dict) -> discord.File:
    return discord.File(io.BytesIO(w["image"]), filename=f"work{w['ext']}")


# ═════════════ Embed ═════════════
def public_embed(w: dict) -> discord.Embed:
    e = emb(f"# {E865} การส่องผลงานคนอื่น\n\n"
            f"{E607} **หัวข้อผลงานนี้**: ``{safe(w['title'])}``\n"
            f"{E729} **ลายละเอียดผลงานนี้**\n```{safe(w['description'])}```\n"
            f"{E767} **รูปที่เเนบมา**\n\n"
            f"ID ผลงาน: `{w['id']}`\n"
            f"{E876} **การกดหัวใจ** {hearts(w['id'])}\n"
            f"หมวดหมู่ของผลงานนี้: **{CATS.get(w['category'], 'ไม่ระบุ')}**")
    e.set_image(url=f"attachment://work{w['ext']}")
    return e


def own_embed(w: dict, idx: int, total: int) -> discord.Embed:
    status = "ไพรเวท (เห็นคนเดียว)" if (w["status"] == "approved" and w["private"]) else STATUS_TH.get(w["status"], w["status"])
    e = emb(f"# {E866} ผลงานของตัวเอง\n\n"
            f"{E607} **หัวข้อ**: ``{safe(w['title'])}``\n"
            f"สถานะ: **{status}**\n"
            f"หมวดหมู่: **{CATS.get(w['category'], 'ยังไม่ได้จัดหมวด')}**\n"
            f"{E876} **การกดหัวใจ** {hearts(w['id'])}\n"
            f"ID ผลงาน: `{w['id']}`\n\n"
            f"{E729} **ลายละเอียด**\n```{safe(w['description'])}```")
    e.set_image(url=f"attachment://work{w['ext']}")
    e.set_footer(text=f"ผลงานที่ {idx + 1}/{total}")
    return e


def comments_embed(wid: str, title: str = "คำเเนะนำของผลงาน") -> discord.Embed:
    rows = q("SELECT cid, text FROM pf_comments WHERE work_id=? ORDER BY created_at", (wid,), many=True)
    if not rows:
        return emb(f"# {E767} {title}\n\nยังไม่มีคำเเนะนำเลยน้า")
    lines, size = [], 0
    for i, (cid, text) in enumerate(rows):
        line = f"`{cid}` {safe(text)}"
        if size + len(line) > 3500:
            lines.append(f"…เเละอีก {len(rows) - i} คำเเนะนำ")
            break
        lines.append(line)
        size += len(line) + 2
    return emb(f"# {E767} {title}\n\n" + "\n\n".join(lines))


async def is_staff(interaction: discord.Interaction) -> bool:
    u = interaction.user
    if isinstance(u, discord.Member) and u.guild_permissions.administrator:
        return True
    return await interaction.client.is_owner(u)


# ═════════════ ส่งผลงานเข้าห้องตรวจ ═════════════
PENDING_IMG: dict = {}   # uid -> {"title","desc","expires"}  (โหมดสำรอง ส่งรูปทาง DM)


async def create_submission(bot, user, title: str, desc: str, data: bytes, ext: str) -> Optional[str]:
    """สร้างผลงานสถานะรออนุมัติ แล้วส่งไปห้องตรวจ คืนข้อความ error หรือ None ถ้าสำเร็จ"""
    wid, now = new_work_id(), int(time.time())
    q("INSERT INTO pf_works (id, owner_id, title, description, status, private, image, ext, created_at) "
      "VALUES (?,?,?,?,?,0,?,?,?)", (wid, user.id, title, desc, "pending", data, ext, now))
    w = get_work(wid)
    e = discord.Embed(
        description=(f"# ผลงานใหม่รอตรวจ\n\n**เจ้าของผลงาน** {user.mention} (ID: `{user.id}`)\n"
                     f"**ส่งมาเมื่อ** <t:{now}:F>\n\n**หัวข้อ** ``{safe(title)}``\n"
                     f"**ลายละเอียดผลงาน**\n```{safe(desc)}```"),
        color=WHITE, timestamp=discord.utils.utcnow())
    e.set_image(url=f"attachment://work{ext}")
    e.set_footer(text=f"ID ผลงาน: {wid}")
    try:
        ch = bot.get_channel(REVIEW_CHANNEL_ID) or await bot.fetch_channel(REVIEW_CHANNEL_ID)
        msg = await ch.send(embed=e, file=work_file(w), view=ReviewView())
    except discord.HTTPException:
        delete_work(wid)
        return "ส่งผลงานไปให้เเอดมินตรวจไม่สำเร็จน้า ลองใหม่อีกที"
    q("UPDATE pf_works SET review_msg_id=? WHERE id=?", (msg.id, wid))
    set_cd(user.id, "submit")
    PENDING_IMG.pop(user.id, None)
    return None


class WorkModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="ลงผลงานของตัวเอง")
        kt = {} if HAS_LABEL else {"label": "หัวข้อผลงาน"}
        kd = {} if HAS_LABEL else {"label": "คำอธิบายผลงาน"}
        self.t_in = discord.ui.TextInput(max_length=100, placeholder="พิมพ์หัวข้อผลงานของพี่", **kt)
        self.d_in = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=1000,
                                         placeholder="อธิบายผลงานของพี่ได้เลยย", **kd)
        self.f_in = None
        if HAS_LABEL:
            self.add_item(discord.ui.Label(text="หัวข้อผลงาน", component=self.t_in))
            self.add_item(discord.ui.Label(text="คำอธิบายผลงาน", component=self.d_in))
            if HAS_UPLOAD:
                self.f_in = discord.ui.FileUpload(required=True, min_values=1, max_values=1)
                self.add_item(discord.ui.Label(text="รูปภาพ (บังคับ)", description="แนบรูปผลงานของพี่",
                                               component=self.f_in))
        else:
            self.add_item(self.t_in)
            self.add_item(self.d_in)

    async def on_submit(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if is_banned(uid):
            return await interaction.response.send_message(embed=emb(f"{E790} พี่โดนเเบนไม่ให้ลงผลงานน้า"), ephemeral=True)
        again = cd_left(uid, "submit", SUBMIT_CD)
        if again:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ส่งผลงานได้ 1 ผลงานต่อ 10 นาทีน้า ลงได้อีกครั้ง <t:{again}:R>"), ephemeral=True)
        title, desc = self.t_in.value.strip(), self.d_in.value.strip()

        if self.f_in is None:   # โหมดสำรอง: รอรูปทาง DM
            PENDING_IMG[uid] = {"title": title, "desc": desc, "expires": time.time() + 180}
            return await interaction.response.send_message(embed=emb(
                f"{E742} ส่ง **รูปภาพผลงาน** มาที่ DM ของบอทภายใน 3 นาทีได้เลยน้า เเล้วน้องจะส่งผลงานให้เเอดมินตรวจ"),
                ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        atts = list(self.f_in.values or [])
        prep = prepare_image(await atts[0].read(), atts[0].content_type, atts[0].filename) if atts else None
        if prep is None:
            return await interaction.followup.send(embed=emb(
                f"{E790} รูปต้องเป็นไฟล์ภาพ (png/jpg/gif/webp) ขนาดไม่เกิน {MAX_IMG_BYTES // 1_000_000} MB น้า"), ephemeral=True)
        err = await create_submission(interaction.client, interaction.user, title, desc, *prep)
        await interaction.followup.send(embed=emb(
            f"{E790} {err}" if err else
            f"{E606} ส่งผลงานให้เเอดมินตรวจเเล้วน้าา รออนุมัติเเล้วจะเเจ้งทาง DM (ส่งได้อีกครั้ง <t:{int(time.time()) + SUBMIT_CD}:R>)"),
            ephemeral=True)


# ═════════════ แอดมินตรวจผลงาน ═════════════
class CategoryPickView(discord.ui.View):
    def __init__(self, wid: str, review_msg: discord.Message):
        super().__init__(timeout=300)
        self.wid, self.review_msg = wid, review_msg
        sel = discord.ui.Select(placeholder="เลือกหมวดหมู่ผลงาน", options=[
            discord.SelectOption(label=name, value=key) for key, name in CATS.items()])
        sel.callback = self.on_select
        self.sel = sel
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        w = get_work(self.wid)
        if not w or w["status"] != "pending":
            return await interaction.response.edit_message(embed=emb("ผลงานนี้ถูกจัดการไปเเล้วน้า"), view=None)
        cat, now = self.sel.values[0], int(time.time())
        q("UPDATE pf_works SET status='approved', category=?, approved_at=? WHERE id=?", (cat, now, self.wid))
        # DM เจ้าของผลงาน
        e = discord.Embed(
            description=(f"# {E866} ผลงานของคุณได้ถูกอนุมัติเเล้ว\n\n"
                         f"{E863} IDผลงานของคุณ: `{self.wid}`\n\n"
                         f"{E727} หมวดหมู่ผลงาน: **{CATS[cat]}**\n\n"
                         f"{E742} รายละเอียดผลงานของคุณ\n\n"
                         f"**{safe(w['title'])}**\n{safe(w['description'])}"),
            color=WHITE, timestamp=discord.utils.utcnow())
        e.set_image(url=f"attachment://work{w['ext']}")
        e.set_footer(text="อนุมัติเมื่อ")
        try:
            user = await interaction.client.fetch_user(w["owner_id"])
            await user.send(embed=e, file=work_file(w))
        except discord.HTTPException:
            pass
        await self._mark(f"{E606} อนุมัติเเล้ว โดย {interaction.user.mention} → หมวด **{CATS[cat]}**")
        await interaction.response.edit_message(embed=emb(f"{E606} อนุมัติผลงาน `{self.wid}` เข้าหมวด **{CATS[cat]}** เเล้ว"),
                                                view=None)

    async def _mark(self, text: str):
        try:
            e = self.review_msg.embeds[0]
            e.description += f"\n\n{text}"
            await self.review_msg.edit(embed=e, view=None)
        except (discord.HTTPException, IndexError):
            pass


class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _work_for(self, interaction: discord.Interaction):
        if not await is_staff(interaction):
            await interaction.response.send_message(embed=emb(f"{E790} เฉพาะเเอดมินน้า"), ephemeral=True)
            return None
        row = q("SELECT id FROM pf_works WHERE review_msg_id=?", (interaction.message.id,), one=True)
        w = get_work(row[0]) if row else None
        if not w or w["status"] != "pending":
            await interaction.response.send_message(embed=emb("ผลงานนี้ถูกจัดการไปเเล้ว หรือไม่มีในระบบเเล้วน้า"), ephemeral=True)
            return None
        return w

    @discord.ui.button(label="ผ่าน", style=discord.ButtonStyle.success, custom_id="pf:ok")
    async def ok(self, interaction: discord.Interaction, button: discord.ui.Button):
        w = await self._work_for(interaction)
        if w:
            await interaction.response.send_message(
                embed=emb(f"{E742} เลือกหมวดหมู่ที่ผลงานนี้จะไปอยู่"), view=CategoryPickView(w["id"], interaction.message),
                ephemeral=True)

    @discord.ui.button(label="ไม่ผ่าน", style=discord.ButtonStyle.danger, custom_id="pf:no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        w = await self._work_for(interaction)
        if not w:
            return
        q("UPDATE pf_works SET status='rejected' WHERE id=?", (w["id"],))
        try:
            user = await interaction.client.fetch_user(w["owner_id"])
            await user.send(embed=emb(f"# {E790} ผลงานไม่ผ่านการอนุมัติ\n\nผลงาน **{safe(w['title'])}** (ID `{w['id']}`) "
                                      "ไม่ผ่านการอนุมัติน้า ลองปรับเเล้วส่งมาใหม่ได้เลย"))
        except discord.HTTPException:
            pass
        e = interaction.message.embeds[0]
        e.description += f"\n\n{E790} ไม่ผ่าน โดย {interaction.user.mention}"
        await interaction.response.edit_message(embed=e, view=None)


# ═════════════ เยี่ยมชมผลงานคนอื่น ═════════════
class Session:
    def __init__(self, uid: int, ids: list, cat: str = "all"):
        self.uid, self.ids, self.idx, self.cat = uid, ids, 0, cat
        self.origin: Optional[discord.Interaction] = None

    def current(self) -> Optional[str]:
        return self.ids[self.idx] if self.ids else None


def visible_ids(cat: str) -> list:
    if cat == "all":
        rows = q("SELECT id FROM pf_works WHERE status='approved' AND private=0", many=True)
    else:
        rows = q("SELECT id FROM pf_works WHERE status='approved' AND private=0 AND category=?", (cat,), many=True)
    ids = [r[0] for r in rows]
    random.shuffle(ids)   # สุ่มลำดับทุกครั้งที่เปิด
    return ids


def browse_payload(s: Session):
    # ตัดผลงานที่ถูกลบ/ปรับเป็นไพรเวทไปแล้วออกจากรายการ
    while s.ids:
        w = get_work(s.ids[s.idx])
        if w and w["status"] == "approved" and not w["private"]:
            break
        s.ids.pop(s.idx)
        s.idx = min(s.idx, len(s.ids) - 1)
    if not s.ids:
        name = {"all": "ทั้งหมด", "id": "ที่ค้นหา"}.get(s.cat, CATS.get(s.cat, ""))
        e = emb(f"# {E865} การส่องผลงานคนอื่น\n\nยังไม่มีผลงานในหมวดหมู่ **{name}** เลยน้า")
        return e, [], BrowseView(s)
    return public_embed(w), [work_file(w)], BrowseView(s)


async def refresh_origin(s: Session):
    if s.origin is None:
        return
    embed, files, view = browse_payload(s)
    try:
        await s.origin.edit_original_response(embed=embed, attachments=files, view=view)
    except discord.HTTPException:
        pass


async def finish_modal(interaction: discord.Interaction, view: discord.ui.View, embed: discord.Embed):
    try:
        await interaction.response.edit_message(view=view)
    except discord.HTTPException:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


class SuggestModal(discord.ui.Modal, title="คำเเนะนำผลงาน"):
    text = discord.ui.TextInput(label="คำเเนะนำของพี่", style=discord.TextStyle.paragraph, max_length=500,
                                placeholder="เเนะนำหรือติผลงานได้ตามสบาย เเต่ขอให้สุภาพน้า")

    def __init__(self, s: Session, wid: str):
        super().__init__()
        self.s, self.wid = s, wid

    async def on_submit(self, interaction: discord.Interaction):
        w = get_work(self.wid)
        if not w or w["status"] != "approved":
            return await finish_modal(interaction, BrowseView(self.s), emb(f"{E790} ผลงานนี้ไม่อยู่เเล้วน้า"))
        if q("SELECT 1 FROM pf_comments WHERE work_id=? AND user_id=?", (self.wid, interaction.user.id), one=True):
            return await finish_modal(interaction, BrowseView(self.s),
                                      emb(f"{E790} พี่ให้คำเเนะนำผลงานนี้ไปเเล้วน้า (ได้ 1 ครั้งต่อผลงาน)"))
        cid = new_comment_id()
        q("INSERT INTO pf_comments VALUES (?,?,?,?,?)",
          (cid, self.wid, interaction.user.id, self.text.value.strip(), int(time.time())))
        await finish_modal(interaction, BrowseView(self.s),
                           emb(f"{E606} ส่งคำเเนะนำเเล้วน้าา (ID คำเเนะนำ `{cid}`) ดูได้ที่ **ดูคำเเนะนำของผลงาน**"))


class IdSearchModal(discord.ui.Modal, title="ค้นหาผลงานจาก ID"):
    wid = discord.ui.TextInput(label="ID ผลงาน", max_length=12, placeholder="เช่น 7KQ2MX")

    def __init__(self, s: Session):
        super().__init__()
        self.s = s

    async def on_submit(self, interaction: discord.Interaction):
        wid = self.wid.value.strip().upper()
        w = get_work(wid)
        if not w or w["status"] != "approved" or w["private"]:
            return await finish_modal(interaction, BrowseView(self.s), emb(f"{E790} ไม่พบผลงาน ID นี้น้า"))
        self.s.ids, self.s.idx, self.s.cat = [wid], 0, "id"
        embed, files, view = browse_payload(self.s)
        await interaction.response.edit_message(embed=embed, attachments=files, view=view)


class HeartView(discord.ui.View):
    def __init__(self, s: Session, wid: str):
        super().__init__(timeout=300)
        self.s, self.wid = s, wid
        add = discord.ui.Button(label="กดใจ", style=discord.ButtonStyle.success, emoji=pe(E876))
        rem = discord.ui.Button(label="ลบหัวใจ", style=discord.ButtonStyle.secondary, emoji=pe(E790))
        add.callback, rem.callback = self.add, self.remove
        self.add_item(add)
        self.add_item(rem)

    async def add(self, interaction: discord.Interaction):
        if q("SELECT 1 FROM pf_hearts WHERE work_id=? AND user_id=?", (self.wid, interaction.user.id), one=True):
            return await interaction.response.edit_message(
                embed=emb(f"{E790} พี่กดใจผลงานนี้ไปเเล้วน้า (กดได้ 1 รอบต่อผลงาน)"), view=None)
        q("INSERT INTO pf_hearts VALUES (?,?)", (self.wid, interaction.user.id))
        await interaction.response.edit_message(embed=emb(f"{E876} กดใจเเล้วน้าา"), view=None)
        await refresh_origin(self.s)

    async def remove(self, interaction: discord.Interaction):
        if not q("SELECT 1 FROM pf_hearts WHERE work_id=? AND user_id=?", (self.wid, interaction.user.id), one=True):
            return await interaction.response.edit_message(
                embed=emb(f"{E790} พี่ไม่เคยกดใจผลงานนี้ ลบไม่ได้น้า"), view=None)
        q("DELETE FROM pf_hearts WHERE work_id=? AND user_id=?", (self.wid, interaction.user.id))
        await interaction.response.edit_message(embed=emb(f"{E606} เอาหัวใจที่เคยกดออกเเล้วน้า"), view=None)
        await refresh_origin(self.s)


class BrowseView(discord.ui.View):
    def __init__(self, s: Session):
        super().__init__(timeout=900)
        self.s = s
        cmd = discord.ui.Select(placeholder="เลือกคำสั่ง", row=0, options=[
            discord.SelectOption(label="คำเเนะนำผลงาน", value="suggest"),
            discord.SelectOption(label="การกดใจ", value="heart"),
            discord.SelectOption(label="ดูคำเเนะนำของผลงาน", value="comments"),
        ])
        cmd.callback = self.on_cmd
        self.add_item(cmd)
        pv = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary, row=1, disabled=s.idx <= 0)
        nx = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary, row=1, disabled=s.idx >= len(s.ids) - 1)
        pv.callback = lambda i: self.go(i, -1)
        nx.callback = lambda i: self.go(i, 1)
        self.add_item(pv)
        self.add_item(nx)
        cat = discord.ui.Select(placeholder="หมวดหมู่ของผลงาน", row=2, options=(
            [discord.SelectOption(label="ทั้งหมด (ค่าเริ่มต้น)", value="all", default=s.cat == "all"),
             discord.SelectOption(label="ค้นหาผลงานจากID", value="id", default=s.cat == "id")]
            + [discord.SelectOption(label=n, value=k, default=s.cat == k) for k, n in CATS.items()]))
        cat.callback = self.on_cat
        self.cat_sel = cat
        self.add_item(cat)

    async def go(self, interaction: discord.Interaction, delta: int):
        self.s.idx = max(0, min(len(self.s.ids) - 1, self.s.idx + delta))
        embed, files, view = browse_payload(self.s)
        await interaction.response.edit_message(embed=embed, attachments=files, view=view)

    async def on_cat(self, interaction: discord.Interaction):
        v = self.cat_sel.values[0]
        if v == "id":
            return await interaction.response.send_modal(IdSearchModal(self.s))
        self.s.cat, self.s.ids, self.s.idx = v, visible_ids(v), 0
        embed, files, view = browse_payload(self.s)
        await interaction.response.edit_message(embed=embed, attachments=files, view=view)

    async def on_cmd(self, interaction: discord.Interaction):
        v, wid = interaction.data["values"][0], self.s.current()
        if not wid:
            await interaction.response.edit_message(view=BrowseView(self.s))
            return await interaction.followup.send(embed=emb(f"{E790} ตอนนี้ไม่มีผลงานให้ใช้คำสั่งน้า"), ephemeral=True)
        if v == "suggest":
            return await interaction.response.send_modal(SuggestModal(self.s, wid))
        await interaction.response.edit_message(view=BrowseView(self.s))  # รีเซ็ตเมนู
        if v == "heart":
            await interaction.followup.send(embed=emb(f"{E876} จะกดใจหรือเอาหัวใจออก?"),
                                            view=HeartView(self.s, wid), ephemeral=True)
        else:
            await interaction.followup.send(embed=comments_embed(wid), ephemeral=True)


# ═════════════ ผลงานของตัวเอง ═════════════
def own_ids(uid: int) -> list:
    return [r[0] for r in q("SELECT id FROM pf_works WHERE owner_id=? ORDER BY created_at DESC", (uid,), many=True)]


def mine_payload(s: Session):
    s.ids = [i for i in s.ids if get_work(i)]
    s.idx = max(0, min(s.idx, len(s.ids) - 1))
    if not s.ids:
        return emb(f"# {E866} ผลงานของตัวเอง\n\nพี่ยังไม่มีผลงานเลยน้า"), [], None
    w = get_work(s.ids[s.idx])
    return own_embed(w, s.idx, len(s.ids)), [work_file(w)], MineView(s)


async def refresh_mine(s: Session):
    if s.origin is None:
        return
    embed, files, view = mine_payload(s)
    try:
        await s.origin.edit_original_response(embed=embed, attachments=files, view=view)
    except discord.HTTPException:
        pass


class ConfirmView(discord.ui.View):
    def __init__(self, yes_label: str, no_label: str, on_yes):
        super().__init__(timeout=120)
        self.on_yes = on_yes
        y = discord.ui.Button(label=yes_label, style=discord.ButtonStyle.danger)
        n = discord.ui.Button(label=no_label, style=discord.ButtonStyle.secondary)
        y.callback, n.callback = self.yes, self.no
        self.add_item(y)
        self.add_item(n)

    async def yes(self, interaction: discord.Interaction):
        await self.on_yes(interaction)

    async def no(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=emb("ยกเลิกเเล้วน้า"), view=None)


class MineView(discord.ui.View):
    def __init__(self, s: Session):
        super().__init__(timeout=900)
        self.s = s
        w = get_work(s.ids[s.idx])
        opts = [discord.SelectOption(label="ดูคำเเนะนำ", value="comments"),
                discord.SelectOption(label="ลบผลงาน", value="delete")]
        if w and w["status"] == "approved":
            opts.append(discord.SelectOption(label="กลับมาเเสดงผลงาน" if w["private"] else "ปรับผลงานเป็นไพรเวท",
                                             value="public" if w["private"] else "private"))
        sel = discord.ui.Select(placeholder="เลือกคำสั่ง", row=0, options=opts)
        sel.callback = self.on_cmd
        self.add_item(sel)
        pv = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary, row=1, disabled=s.idx <= 0)
        nx = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary, row=1, disabled=s.idx >= len(s.ids) - 1)
        pv.callback = lambda i: self.go(i, -1)
        nx.callback = lambda i: self.go(i, 1)
        self.add_item(pv)
        self.add_item(nx)

    async def go(self, interaction: discord.Interaction, delta: int):
        self.s.idx = max(0, min(len(self.s.ids) - 1, self.s.idx + delta))
        embed, files, view = mine_payload(self.s)
        await interaction.response.edit_message(embed=embed, attachments=files, view=view)

    async def on_cmd(self, interaction: discord.Interaction):
        v, s = interaction.data["values"][0], self.s
        wid = s.ids[s.idx]
        await interaction.response.edit_message(view=MineView(s))  # รีเซ็ตเมนู
        send = lambda **kw: interaction.followup.send(ephemeral=True, **kw)
        if v == "comments":
            return await send(embed=comments_embed(wid))
        if v == "delete":
            async def do_delete(i: discord.Interaction):
                delete_work(wid)
                await i.response.edit_message(embed=emb(f"{E606} ลบผลงานออกจากระบบเเล้วน้า"), view=None)
                await refresh_mine(s)
            return await send(embed=emb(f"{E790} ต้องการลบจริงๆหรอ? ผลงานจะหายไปจากระบบเลยน้า"),
                              view=ConfirmView("ลบ", "ยกเลิก", do_delete))
        if v == "private":
            async def do_private(i: discord.Interaction):
                q("UPDATE pf_works SET private=1 WHERE id=?", (wid,))
                await i.response.edit_message(embed=emb(f"{E606} ปรับผลงานเป็นไพรเวทเเล้วน้า เห็นได้เเค่พี่คนเดียว"), view=None)
                await refresh_mine(s)
            return await send(embed=emb("ต้องการปรับผลงานนี้เป็นไพรเวทใช่มั้ย? คนอื่นจะไม่เห็นผลงานนี้ในหน้าเยี่ยมชมน้า"),
                              view=ConfirmView("ใช่", "ไม่", do_private))
        q("UPDATE pf_works SET private=0 WHERE id=?", (wid,))
        await send(embed=emb(f"{E606} เอาผลงานกลับมาเเสดงให้ทุกคนเห็นเเล้วน้า"))
        await refresh_mine(s)


# ═════════════ รายงาน ═════════════
class ReportModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="รายงานผลงานหรือคำหยาบคาย")
        k = lambda label: {} if HAS_LABEL else {"label": label}
        self.t_in = discord.ui.TextInput(max_length=100, placeholder="หัวข้อเรื่องที่จะมาติดต่อ", **k("หัวข้อเรื่อง"))
        self.w_in = discord.ui.TextInput(max_length=12, placeholder="อยู่ล่างสุดของผลงานนั้น", **k("ID ผลงาน"))
        self.c_in = discord.ui.TextInput(max_length=8, required=False, placeholder="ดูท้ายสุดของคำเเนะนำนั้น",
                                         **k("ID ข้อความ (ไม่บังคับ)"))
        self.d_in = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=800, required=False,
                                         placeholder="ลายละเอียดที่เเจ้งเพิ่มเติม", **k("ลายละเอียด"))
        self.f_in = None
        if HAS_LABEL:
            self.add_item(discord.ui.Label(text="หัวข้อเรื่องที่จะมาติดต่อ", component=self.t_in))
            self.add_item(discord.ui.Label(text="IDผลงาน", description="อยู่ล่างสุดของผลงานนั้น", component=self.w_in))
            self.add_item(discord.ui.Label(text="ID ข้อความ (ไม่บังคับ)",
                                           description="ถ้าเเจ้งเรื่องคำหยาบ ใส่ ID คำเเนะนำนั้น", component=self.c_in))
            self.add_item(discord.ui.Label(text="ลายละเอียดที่เเจ้งเพิ่มเติม", component=self.d_in))
            if HAS_UPLOAD:
                self.f_in = discord.ui.FileUpload(required=False, min_values=0, max_values=1)
                self.add_item(discord.ui.Label(text="เเนบรูปมั้ย (ไม่บังคับ)", component=self.f_in))
        else:
            for it in (self.t_in, self.w_in, self.c_in, self.d_in):
                self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        uid, now = interaction.user.id, int(time.time())
        again = cd_left(uid, "report", REPORT_CD)
        if again:
            return await interaction.response.send_message(
                embed=emb(f"{E790} เเจ้งปัญหาได้ 30 นาทีต่อ 1 ครั้งน้าา เเจ้งได้อีกครั้ง <t:{again}:R>"), ephemeral=True)
        wid, cid = self.w_in.value.strip().upper(), self.c_in.value.strip().upper()
        if not get_work(wid):
            return await interaction.response.send_message(embed=emb(f"{E790} ไม่พบผลงาน ID นี้น้า ตรวจ ID ที่ล่างสุดของผลงานอีกที"),
                                                           ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        files, img_name = [], None
        atts = list(getattr(self.f_in, "values", None) or []) if self.f_in else []
        if atts and (atts[0].content_type or "").startswith("image/"):
            data = await atts[0].read()
            if len(data) <= 8_000_000:
                img_name = "report" + (os.path.splitext(atts[0].filename)[1] or ".png")
                files.append(discord.File(io.BytesIO(data), filename=img_name))
        title, detail = self.t_in.value.strip(), self.d_in.value.strip()
        e = discord.Embed(
            description=(f"# มีคนเเจ้งผลงาน\n\n**คนที่เเจ้งมา** {interaction.user.mention} ID: `{uid}`\n\n"
                         f"**หัวข้อเรื่อง** {safe(title)}\n\n**IDผลงาน** `{wid}`\n\n"
                         f"**IDข้อความ** {('`' + cid + '`') if cid else '-'}\n\n"
                         f"**ลายละเอียด**\n```{safe(detail) or '-'}```\n**รูปที่เเนบ** {'' if img_name else 'ไม่มี'}"),
            color=WHITE, timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.set_footer(text="เเจ้งเมื่อ")
        if img_name:
            e.set_image(url=f"attachment://{img_name}")
        try:
            ch = interaction.client.get_channel(REPORT_CHANNEL_ID) or await interaction.client.fetch_channel(REPORT_CHANNEL_ID)
            msg = await ch.send(embed=e, files=files, view=ReportHandleView())
        except discord.HTTPException:
            return await interaction.followup.send(
                embed=emb(f"{E790} ส่งรายงานไม่สำเร็จน้า ลองใหม่อีกที (ยังไม่นับเป็นรอบ)"), ephemeral=True)
        q("INSERT INTO pf_reports (reporter_id, title, work_id, comment_id, detail, created_at, msg_id) VALUES (?,?,?,?,?,?,?)",
          (uid, title, wid, cid, detail, now, msg.id))
        set_cd(uid, "report")
        await interaction.followup.send(embed=emb(
            f"{E606} ส่งเรื่องให้เเอดมินเเล้วน้าา เเจ้งได้อีกครั้ง <t:{now + REPORT_CD}:R>"), ephemeral=True)


class HandleModal(discord.ui.Modal, title="จัดการเรื่องที่ถูกเเจ้ง"):
    fixed = discord.ui.TextInput(label="เเก้ไขอะไรบ้าง (ตอบกลับผู้เเจ้ง)", style=discord.TextStyle.paragraph, max_length=800)
    how = discord.ui.TextInput(label="จัดการยังไง", style=discord.TextStyle.paragraph, max_length=800)

    def __init__(self, report_id: int, reporter_id: int, message: discord.Message):
        super().__init__()
        self.report_id, self.reporter_id, self.message = report_id, reporter_id, message

    async def on_submit(self, interaction: discord.Interaction):
        e = emb(f"# {E767} เรื่องที่ทางเเอดมินได้รับเเจ้ง\n\n"
                f"{E764} ลายละเอียดที่เเอดมินตอบกลับ: {safe(self.fixed.value.strip())}\n\n"
                f"{E764} การจัดการของเเอดมิน: {safe(self.how.value.strip())}\n\n"
                f"{E763} ปัญหาของคุณได้รับการตอบกลับเเล้วน้าาา หากมีข้อสงสัยสามารถรายงานมาอีกได้เลยยย")
        sent = True
        try:
            user = await interaction.client.fetch_user(self.reporter_id)
            await user.send(embed=e)
        except discord.HTTPException:
            sent = False
        q("UPDATE pf_reports SET handled=1 WHERE id=?", (self.report_id,))
        try:
            em = self.message.embeds[0]
            em.description += f"\n\n{E606} จัดการเเล้ว โดย {interaction.user.mention}" + ("" if sent else " (DM ผู้เเจ้งไม่ได้)")
            await self.message.edit(embed=em, view=None)
        except (discord.HTTPException, IndexError):
            pass
        await interaction.response.send_message(
            embed=emb(f"{E606} ส่งคำตอบให้ผู้เเจ้งเเล้ว" if sent else f"{E790} บันทึกเเล้ว เเต่ DM ผู้เเจ้งไม่ได้"), ephemeral=True)


class ReportHandleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="จัดการเเล้ว", style=discord.ButtonStyle.success, custom_id="pf:handled")
    async def handled(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_staff(interaction):
            return await interaction.response.send_message(embed=emb(f"{E790} เฉพาะเเอดมินน้า"), ephemeral=True)
        row = q("SELECT id, reporter_id, handled FROM pf_reports WHERE msg_id=?", (interaction.message.id,), one=True)
        if not row or row[2]:
            return await interaction.response.send_message(embed=emb("เรื่องนี้จัดการไปเเล้ว หรือไม่มีในระบบน้า"), ephemeral=True)
        await interaction.response.send_modal(HandleModal(row[0], row[1], interaction.message))


# ═════════════ แผงในห้อง performance ═════════════
def panel_embed() -> discord.Embed:
    return emb(
        f"# {E874} การลงผลงาน เเละการเยี่ยมชม {E874}\n\n"
        f"{E863} นี่คือระบบที่จะเปิดให้ทุกคนสามารถลงผลงานของตัวเองได้ เเละสามารถเยี่ยมชมผลงานคนอื่น ให้คำเเนะนำ ติผลงาน ได้ตามสบาย "
        "เเละระบบที่คำนึงถึงความลับของผู้ใช้ จะไม่มีใครรู้ตัวตนของผู้ใช้ยกเว้นเจ้าของบอท เผื่อเกิดเหตุการณ์ต่างๆจะสามารถเเก้ไขได้\n\n"
        f"{E790} **ข้อตกลงการใช้บอท**\n\n"
        f"{E803} เมื่อคุณตัดสินใจลงผลงาน ผลงานของคุณจะถูกส่งมาที่เเอดมินบอทก่อน เพื่อรอการอนุมัติ "
        "เพราะกันเหตุการณ์ที่มีคนลงภาพอะไรไม่เหมาะสม เช่น ภาพเหตุความรุนเเรง 18+ เป็นต้น "
        "ถ้าคุณลงผลงานอย่างถูกเงื่อนไข เเอดมินจะอนุมัติผลงานของคุณเเละทุกคนสามารถเห็นผลงานคุณได้ "
        "เเละงดการด้อยค่าผลงานผู้อื่น หรือทำให้เจ้าของผลงานเสียความรู้สึก\n\n"
        f"{E793} **การรายงานปัญหา**\n\n"
        f"{E739} หากในผลงานของคุณ ถูกวิจารณ์ที่เท็จ มีคำหยาบ ไม่สุภาพ หรือทำให้เสียความรู้สึก "
        "คุณสามารถกดลิสคำสั่ง กดรายงานผลงานของคุณ เเล้วเเอดมินจะทำการตรวจสอบ "
        "หากพบการวิจารณ์ที่ไม่เหมาะสม เเอดมินจะทำการลบให้\n\n"
        f"{E803} ถ้าหากขี้เกียจเลื่อนหาหมวดหมู่สิ่งที่ตัวเองตามหา ในการดูผลงานคนอื่น จะมีลิสให้กดเลือกว่าอยากดูงานประเภทไหน "
        "เพราะเเอดมินจะเเยกไว้ตังหาก\n\n"
        f"{E804} ปล.ผลงานในที่นี้ ไม่ได้บังคับว่าต้องเป็นงานภาพวาดอย่างเดียว ลิ้งเพลง ช่องตต. IG เฟส หรือผลงานต่างๆก็สามารถลงได้หมด "
        "เเต่อยากให้ลงอะไรที่มันมีสาระนิดนึงง")


class PerformancePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(custom_id="pf:panel", placeholder="เลือกคำสั่ง", options=[
            discord.SelectOption(label="ลงผลงานของตัวเอง", value="submit", emoji=pe(E866)),
            discord.SelectOption(label="เยี่ยมชมผลงานคนอื่น", value="visit", emoji=pe(E865)),
            discord.SelectOption(label="ดูผลงานของตัวเอง", value="mine", emoji=pe(E804)),
            discord.SelectOption(label="รายงานผลงานหรือคำหยาบคาย", value="report", emoji=pe(E793)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E863)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def reset(self, interaction: discord.Interaction):
        try:
            await interaction.message.edit(view=PerformancePanelView())
        except discord.HTTPException:
            pass

    async def on_select(self, interaction: discord.Interaction):
        v, uid = interaction.data["values"][0], interaction.user.id
        if v == "submit":
            if is_banned(uid):
                await interaction.response.send_message(embed=emb(f"{E790} พี่โดนเเบนไม่ให้ลงผลงานน้า"), ephemeral=True)
            elif cd_left(uid, "submit", SUBMIT_CD):
                again = cd_left(uid, "submit", SUBMIT_CD)
                await interaction.response.send_message(
                    embed=emb(f"{E790} ส่งผลงานได้ 1 ผลงานต่อ 10 นาทีน้า ลงได้อีกครั้ง <t:{again}:R>"), ephemeral=True)
            else:
                await interaction.response.send_modal(WorkModal())
        elif v == "report":
            again = cd_left(uid, "report", REPORT_CD)
            if again:
                await interaction.response.send_message(
                    embed=emb(f"{E790} เเจ้งปัญหาได้ 30 นาทีต่อ 1 ครั้งน้าา เเจ้งได้อีกครั้ง <t:{again}:R>"), ephemeral=True)
            else:
                await interaction.response.send_modal(ReportModal())
        elif v == "visit":
            s = Session(uid, visible_ids("all"))
            embed, files, view = browse_payload(s)
            await interaction.response.send_message(embed=embed, files=files, view=view, ephemeral=True)
            s.origin = interaction
        elif v == "mine":
            s = Session(uid, own_ids(uid), "mine")
            embed, files, view = mine_payload(s)
            kw = {"view": view} if view else {}
            await interaction.response.send_message(embed=embed, files=files, ephemeral=True, **kw)
            s.origin = interaction
        else:
            await interaction.response.send_message(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"), ephemeral=True)
        await self.reset(interaction)


# ═════════════ Cog ═════════════
class PerformanceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()
        self.bot.add_view(PerformancePanelView())
        self.bot.add_view(ReviewView())
        self.bot.add_view(ReportHandleView())

    @app_commands.command(name="performance", description="คำสั่งสำหรับลงผลงานให้คนทั่วโลกเห็น (แอดมินเท่านั้น)")
    @app_commands.guild_only()
    async def performance(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
        guild, me = interaction.guild, interaction.guild.me
        if not me.guild_permissions.manage_channels:
            return await interaction.response.send_message(
                embed=emb(f"{E790} น้องต้องมีสิทธิ์ จัดการช่อง ก่อนน้า"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        row = q("SELECT channel_id, panel_message_id FROM pf_config WHERE guild_id=?", (guild.id,), one=True)
        try:
            ch = guild.get_channel(row[0]) if row else None
            if ch is None:  # ห้ามพิมพ์
                ch = await guild.create_text_channel("performance", overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True, send_messages=False, add_reactions=False,
                        create_public_threads=False, create_private_threads=False, read_message_history=True),
                    me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True)})
            elif row and row[1]:
                try:
                    await (await ch.fetch_message(row[1])).delete()
                except discord.HTTPException:
                    pass
            msg = await ch.send(embed=panel_embed(), view=PerformancePanelView())
        except discord.HTTPException as e:
            return await interaction.followup.send(
                embed=emb(f"{E790} สร้างห้องไม่สำเร็จ ({e.status}) เช็คสิทธิ์บอทเเล้วลองใหม่น้า"), ephemeral=True)
        q("INSERT INTO pf_config VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
          "channel_id=excluded.channel_id, panel_message_id=excluded.panel_message_id", (guild.id, ch.id, msg.id))
        await interaction.followup.send(embed=emb(f"{E606} สร้างห้อง performance เเล้วน้าา {ch.mention}"), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        # ── โหมดสำรอง: รับรูปผลงานทาง DM ──
        if message.guild is None:
            pend = PENDING_IMG.get(message.author.id)
            if pend and pend["expires"] > time.time() and message.attachments:
                att = next((a for a in message.attachments if (a.content_type or "").startswith("image/")), None)
                if att is None:
                    return
                prep = prepare_image(await att.read(), att.content_type, att.filename)
                if prep is None:
                    return await message.channel.send(embed=emb(
                        f"{E790} รูปใหญ่เกิน {MAX_IMG_BYTES // 1_000_000} MB หรือไม่ใช่ไฟล์ภาพน้า ลองส่งใหม่"))
                err = await create_submission(self.bot, message.author, pend["title"], pend["desc"], *prep)
                await message.channel.send(embed=emb(
                    f"{E790} {err}" if err else f"{E606} ส่งผลงานให้เเอดมินตรวจเเล้วน้าา รออนุมัติเเล้วจะเเจ้งทาง DM"))
            return

        # ── คำสั่งเเอดมิน ในห้องตรวจ/ห้องรายงาน ──
        if message.channel.id not in (REVIEW_CHANNEL_ID, REPORT_CHANNEL_ID) or not message.content.startswith("!"):
            return
        perms = message.author.guild_permissions
        if not (perms.administrator or await self.bot.is_owner(message.author)):
            return
        parts = message.content.split()
        cmd, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
        reply = lambda text: message.reply(embed=emb(text), mention_author=False)

        if cmd in ("!ban", "!unban"):
            if not arg.isdigit():
                return await reply(f"{E790} ใช้เเบบนี้: `{cmd} <id คน>`")
            target = int(arg)
            if cmd == "!ban":
                q("INSERT OR REPLACE INTO pf_bans VALUES (?,?,?)", (target, message.author.id, int(time.time())))
                await reply(f"{E606} เเบน <@{target}> ({target}) ไม่ให้ลงผลงานเเล้ว (ยังกดใจ/ให้คำเเนะนำได้)")
            else:
                q("DELETE FROM pf_bans WHERE user_id=?", (target,))
                await reply(f"{E606} ปลดเเบน <@{target}> ({target}) เเล้ว")
        elif cmd == "!de":
            cid = arg.upper()
            row = q("SELECT work_id FROM pf_comments WHERE cid=?", (cid,), one=True)
            if not row:
                return await reply(f"{E790} ไม่พบคำเเนะนำ ID `{cid}`")
            q("DELETE FROM pf_comments WHERE cid=?", (cid,))
            await reply(f"{E606} ลบคำเเนะนำ `{cid}` ออกจากผลงาน `{row[0]}` เเล้ว")
        elif cmd == "!de1":
            wid = arg.upper()
            w = get_work(wid)
            if not w:
                return await reply(f"{E790} ไม่พบผลงาน ID `{wid}`")
            delete_work(wid)
            await reply(f"{E606} ลบผลงาน `{wid}` (ของ <@{w['owner_id']}>) ออกเเล้ว")
        elif cmd == "!check":
            cid = arg.upper()
            row = q("SELECT user_id, work_id FROM pf_comments WHERE cid=?", (cid,), one=True)
            if not row:
                return await reply(f"{E790} ไม่พบคำเเนะนำ ID `{cid}`")
            await reply(f"คำเเนะนำ `{cid}` เป็นของ <@{row[0]}> ID: `{row[0]}` (ผลงาน `{row[1]}`)")
        elif cmd == "!check1":
            wid = arg.upper()
            w = get_work(wid)
            if not w:
                return await reply(f"{E790} ไม่พบผลงาน ID `{wid}`")
            await reply(f"ผลงาน `{wid}` เป็นของ <@{w['owner_id']}> ID: `{w['owner_id']}` "
                        f"(สถานะ {STATUS_TH.get(w['status'], w['status'])})")


async def setup(bot: commands.Bot):
    await bot.add_cog(PerformanceCog(bot))
