import asyncio
import glob
import io
import os
import random
import string
import time
import unicodedata
from collections import defaultdict
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, features

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)
REPORT_CHANNEL_ID = 1488557048223240385   # ห้องที่รับรายงาน + ใช้คำสั่ง !id !banid !unban
REPORT_COOLDOWN = 3600                    # แจ้งได้ 1 ครั้งต่อ 1 ชั่วโมง
CONFIRM_SECONDS = 180                     # ต้องกดยืนยันแชทภายใน 3 นาที
MAX_MSG_LEN = 500
BANNED_TEXT = ("โดนเเบนจากระบบนี้เเล้วน้า เเล้วจะเรื้อนทำไมล่ะ "
               "ถ้าคิดว่าโดนเเบนผิด ไปติดต่อเเอดมินขอปลดเเบนได้เลย")  # แก้ข้อความนี้ได้

PANEL_IMG = ("https://cdn.discordapp.com/attachments/1541161566584578090/1555308379482624020/"
             "855e39df58a027b1578ab4e9a0ba2e59.jpg?backend=b2&ex=6ac00d4d&is=6abebbcd&hm="
             "63af6218c656dc00cc6529fa6c22a6e31517791b7da539ecc45916285cae8689&")

# ───────── อีโมจิ ─────────
E804 = "<a:1000035804:1555025773742526615>"
E863 = "<:1000035863:1555305403305295912>"
E767 = "<a:1000035767:1554921960838926417>"
E802 = "<a:1000035802:1555024928133226557>"
E801 = "<a:1000035801:1555024761606639747>"
E800 = "<a:1000035800:1555024595050963005>"
E727 = "<a:1000035727:1554859928957755393>"
E726 = "<a:1000035726:1554859496894111744>"
E608 = "<a:1000035608:1554844998506123274>"
E725 = "<a:1000035725:1554844594175483904>"
E793 = "<:1000035793:1554977816431431850>"
E604 = "<a:1000035604:1554847795524141216>"
E742 = "<a:1000035742:1554876309790793908>"
E866 = "<:1000035866:1555310612341461084>"
E865 = "<:1000035865:1555310615478931616>"
E790 = "<:1000035790:1554970748232147004>"
E607 = "<a:1000035607:1554874918632562788>"
E729 = "<a:1000035729:1554863632528052315>"
E741 = "<a:1000035741:1554876169017499658>"
E606 = "<a:1000035606:1554848463320129567>"
E728 = "<a:1000035728:1554860189125967894>"

ROLE_TH = {"venter": "ผู้ระบาย", "listener": "ผู้รับฟัง"}


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
    q("CREATE TABLE IF NOT EXISTS ac_config (guild_id INTEGER PRIMARY KEY, channel_id INTEGER, panel_message_id INTEGER)")
    q("""CREATE TABLE IF NOT EXISTS ac_chats (
        chat_id TEXT PRIMARY KEY, venter_id INTEGER, listener_id INTEGER, status TEXT,
        created_at INTEGER, ended_at INTEGER)""")
    q("""CREATE TABLE IF NOT EXISTS ac_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, text TEXT, ts INTEGER)""")
    q("CREATE INDEX IF NOT EXISTS idx_ac_msg ON ac_messages (chat_id)")
    q("CREATE TABLE IF NOT EXISTS ac_bans (user_id INTEGER PRIMARY KEY, banned_by INTEGER, created_at INTEGER)")
    q("CREATE TABLE IF NOT EXISTS ac_report_cd (user_id INTEGER PRIMARY KEY, last_at INTEGER)")
    # บอทรีสตาร์ท = แชทที่ค้างอยู่หายจากหน่วยความจำ → ปิดสถานะให้
    q("UPDATE ac_chats SET status='ended', ended_at=? WHERE status IN ('pending','active')", (int(time.time()),))


def is_banned(uid: int) -> bool:
    return q("SELECT 1 FROM ac_bans WHERE user_id=?", (uid,), one=True) is not None


def load_msgs(chat_id: str) -> list:
    return [(r, t, ts) for r, t, ts in q(
        "SELECT role, text, ts FROM ac_messages WHERE chat_id=? ORDER BY id", (chat_id,), many=True)]


def new_chat_id() -> str:
    alphabet = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"
    while True:  # ไม่ซ้ำกับห้องที่เคยมี
        cid = "".join(random.choices(alphabet, k=6))
        if not q("SELECT 1 FROM ac_chats WHERE chat_id=?", (cid,), one=True):
            return cid


# ═════════════ วาดภาพแชท (Pillow) ═════════════
W, H = 720, 1640            # สัดส่วนเดียวกับภาพจอดำ 1080x2460 ที่ส่งมา
MARGIN, TOP, BOTTOM, PAD, GAP = 40, 120, 90, 22, 30
BG = (0, 0, 0)
PINK = (255, 196, 218)      # ตัวหนังสือสีชมพูอ่อน
BOX = (44, 44, 46)          # กรอบสี่เหลี่ยมพื้นเทาเข้มนิดๆ
BOX_LINE = (66, 66, 70)
GRAY = (150, 150, 155)
TEXT_SIZE, TIME_SIZE, ID_SIZE = 30, 20, 26
LINE_H = 42

SYSTEM_FONTS = [
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/truetype/tlwg/Loma.ttf", "/usr/share/fonts/opentype/tlwg/Loma.otf",
    "/usr/share/fonts/truetype/tlwg/Garuda.ttf", "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
]
_font_path: Optional[str] = None
_font_cache: dict = {}
_font_checked = False


def find_font() -> Optional[str]:
    global _font_path, _font_checked
    if _font_checked:
        return _font_path
    _font_checked = True
    env = os.getenv("FONT_PATH")
    if env and os.path.exists(env):
        _font_path = env
        return _font_path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found = []
    for pat in ("fonts/*.ttf", "fonts/*.otf", "*.ttf", "*.otf"):
        found += sorted(glob.glob(os.path.join(root, pat)))
    for f in found:  # ให้ความสำคัญกับฟอนต์ที่ชื่อบอกว่าเป็นไทย
        if any(k in os.path.basename(f).lower() for k in ("thai", "sarabun", "prompt", "kanit", "noto")):
            _font_path = f
            return f
    if found:
        _font_path = found[0]
        return _font_path
    for f in SYSTEM_FONTS:
        if os.path.exists(f):
            _font_path = f
            return f
    print("[anonymous_chat] ไม่พบฟอนต์ไทย! วางไฟล์ .ttf ไว้ที่ fonts/ หรือตั้ง FONT_PATH")
    return None


def get_font(size: int):
    if size in _font_cache:
        return _font_cache[size]
    path = find_font()
    font = None
    if path:
        try:
            engine = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
            font = ImageFont.truetype(path, size, layout_engine=engine)
        except Exception:
            try:
                font = ImageFont.truetype(path, size)
            except Exception:
                font = None
    if font is None:
        try:
            font = ImageFont.load_default(size)
        except TypeError:
            font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def wrap(text: str, font, max_w: int) -> list:
    lines = []
    for para in text.split("\n"):
        cur, last_space = "", -1
        for ch in para:
            if unicodedata.category(ch) == "Mn" or ch == "\u200b":  # สระ/วรรณยุกต์ติดตัวอักษรก่อนหน้า
                cur += ch
                continue
            if cur and font.getlength(cur + ch) > max_w:
                if last_space > 0 and len(cur) - last_space < 18:   # ตัดที่ช่องว่างถ้าอยู่ใกล้ๆ
                    lines.append(cur[:last_space].rstrip())
                    cur = cur[last_space:].lstrip()
                else:
                    lines.append(cur)
                    cur = ""
                last_space = -1
            if ch == " ":
                last_space = len(cur)
            cur += ch
        lines.append(cur)
    return lines


def hhmm(ts: int) -> str:
    return time.strftime("%H:%M", time.gmtime(ts + 7 * 3600))  # เวลาไทย


def render(chat_id: str, msgs: list, page: int):
    """วาดหน้าแชท คืน (BytesIO png, จำนวนหน้าทั้งหมด, หน้าที่วาดจริง)"""
    f_text, f_time, f_id = get_font(TEXT_SIZE), get_font(TIME_SIZE), get_font(ID_SIZE)
    inner_w = W - 2 * MARGIN - 2 * PAD
    blocks = []
    for role, text, ts in msgs:
        lines = wrap(f"[{ROLE_TH[role]}] {text}", f_text, inner_w)
        h = PAD + len(lines) * LINE_H + 6 + TIME_SIZE + 10 + PAD // 2
        blocks.append((lines, hhmm(ts), h))
    pages, y = [[]], TOP
    for b in blocks:
        if pages[-1] and y + b[2] > H - BOTTOM:
            pages.append([])
            y = TOP
        pages[-1].append(b)
        y += b[2] + GAP
    page = max(0, min(page, len(pages) - 1))

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    id_text = f"ID: {chat_id}"           # ไอดีห้องขวาบน
    d.text((W - MARGIN - f_id.getlength(id_text), 46), id_text, font=f_id, fill=PINK)
    y = TOP
    for lines, t, h in pages[page]:
        d.rounded_rectangle((MARGIN, y, W - MARGIN, y + h), radius=22, fill=BOX, outline=BOX_LINE, width=2)
        ty = y + PAD
        for ln in lines:
            d.text((MARGIN + PAD, ty), ln, font=f_text, fill=PINK)
            ty += LINE_H
        d.text((W - MARGIN - PAD - f_time.getlength(t), ty + 2), t, font=f_time, fill=GRAY)
        y += h + GAP                      # เว้น 1 บรรทัดก่อนข้อความถัดไป
    footer = f"หน้า {page + 1}/{len(pages)}"
    d.text(((W - f_time.getlength(footer)) / 2, H - 56), footer, font=f_time, fill=GRAY)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf, len(pages), page


# ═════════════ สถานะแชท (หน่วยความจำ) ═════════════
QUEUES = {"venter": [], "listener": []}
SEARCHING: dict = {}      # uid -> {"role", "msg", "user"}
ROLE_PICK: dict = {}      # uid -> role ที่เลือกไว้
USER_CHAT: dict = {}      # uid -> Chat
LAST_SENT: dict = defaultdict(float)


class Chat:
    def __init__(self, cid: str, venter, listener):
        self.id = cid
        self.users = {venter.id: venter, listener.id: listener}
        self.role = {venter.id: "venter", listener.id: "listener"}
        self.state = "pending"            # pending / active / ended
        self.confirmed: set = set()
        self.msgs: list = []
        self.dm: dict = {}                # uid -> ข้อความ DM ปัจจุบัน
        self.page: dict = {venter.id: 0, listener.id: 0}
        self.follow: dict = {venter.id: True, listener.id: True}
        self.task: Optional[asyncio.Task] = None
        self.refresh_task: Optional[asyncio.Task] = None

    def other(self, uid: int) -> int:
        return next(u for u in self.users if u != uid)


def chat_embed(footer: str = "") -> discord.Embed:
    e = discord.Embed(color=WHITE)
    e.set_image(url="attachment://chat.png")
    if footer:
        e.set_footer(text=footer)
    return e


async def push(chat: Chat, uid: int, final: bool = False):
    """ส่งภาพแชทล่าสุดเป็นข้อความใหม่ใน DM (ให้มีแจ้งเตือน) แล้วลบข้อความเก่า"""
    total_before = render(chat.id, chat.msgs, 10 ** 6)[1]
    if chat.follow.get(uid, True):
        chat.page[uid] = total_before - 1
    buf, total, page = render(chat.id, chat.msgs, chat.page.get(uid, 0))
    chat.page[uid] = page
    view = None if final else ChatView(chat, uid, page, total)
    footer = f"แชทจบเเล้ว • ID {chat.id} (ใช้ ID นี้ดูประวัติ/รายงานได้)" if final else ""
    old = chat.dm.get(uid)
    try:
        chat.dm[uid] = await chat.users[uid].send(
            embed=chat_embed(footer), file=discord.File(buf, "chat.png"), view=view)
    except discord.HTTPException:
        return
    if old:
        try:
            await old.delete()
        except discord.HTTPException:
            pass


async def push_all(chat: Chat, final: bool = False):
    for uid in chat.users:
        await push(chat, uid, final)


def schedule_refresh(chat: Chat):
    """รวมข้อความที่พิมพ์ถี่ๆ ให้อัปเดตภาพครั้งเดียว (กัน rate limit)"""
    async def run():
        await asyncio.sleep(1.2)
        if chat.state == "active":
            await push_all(chat)
    if chat.refresh_task is None or chat.refresh_task.done():
        chat.refresh_task = asyncio.create_task(run())


def add_message(chat: Chat, uid: int, text: str):
    role, ts = chat.role[uid], int(time.time())
    chat.msgs.append((role, text, ts))
    q("INSERT INTO ac_messages (chat_id, role, text, ts) VALUES (?,?,?,?)", (chat.id, role, text, ts))


async def end_chat(chat: Chat, by: Optional[int], status: str = "ended", reason: str = ""):
    if chat.state == "ended":
        return
    was_active = chat.state == "active"
    chat.state = "ended"
    if chat.task and not chat.task.done():
        chat.task.cancel()
    q("UPDATE ac_chats SET status=?, ended_at=? WHERE chat_id=?", (status, int(time.time()), chat.id))
    for uid in chat.users:
        USER_CHAT.pop(uid, None)
    if was_active:
        if by is not None:
            try:
                await chat.users[chat.other(by)].send(embed=emb(f"{E790} คู่สนทนาออกจากเเชทเเล้วน้า เเชทนี้จบเเล้ว"))
            except discord.HTTPException:
                pass
        await push_all(chat, final=True)
    else:
        for uid, msg in chat.dm.items():
            try:
                await msg.edit(embed=emb(f"{E790} {reason or 'ยกเลิกเเชทเเล้ว'}"), view=None)
            except discord.HTTPException:
                pass


# ═════════════ Views ใน DM ═════════════
class TypeModal(discord.ui.Modal, title="เริ่มพิมพ์"):
    text = discord.ui.TextInput(label="ข้อความที่จะส่ง", style=discord.TextStyle.paragraph,
                                max_length=MAX_MSG_LEN, placeholder="พิมพ์ข้อความได้เลยย")

    def __init__(self, chat: Chat):
        super().__init__()
        self.chat = chat

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await relay(self.chat, interaction.user.id, self.text.value)


async def relay(chat: Chat, uid: int, text: str):
    text = text.strip()
    if chat.state != "active" or not text or uid not in chat.users:
        return
    if time.time() - LAST_SENT[uid] < 0.8:
        return
    LAST_SENT[uid] = time.time()
    add_message(chat, uid, text[:MAX_MSG_LEN])
    schedule_refresh(chat)


class ChatView(discord.ui.View):
    def __init__(self, chat: Chat, uid: int, page: int, total: int):
        super().__init__(timeout=None)
        self.chat, self.uid = chat, uid
        t = discord.ui.Button(label="เริ่มพิมพ์", style=discord.ButtonStyle.primary, emoji=pe(E725), row=0)
        lv = discord.ui.Button(label="ออกจากเเชท", style=discord.ButtonStyle.danger, emoji=pe(E790), row=0)
        pv = discord.ui.Button(label="กลับไปหน้าที่ผ่านมา", style=discord.ButtonStyle.secondary,
                               emoji="◀️", row=1, disabled=page <= 0)
        nx = discord.ui.Button(label="ไปหน้าถัดไป", style=discord.ButtonStyle.secondary,
                               emoji="▶️", row=1, disabled=page >= total - 1)
        t.callback, lv.callback, pv.callback, nx.callback = self.type, self.leave, self.prev, self.next
        for b in (t, lv, pv, nx):
            self.add_item(b)

    async def type(self, interaction: discord.Interaction):
        if self.chat.state != "active":
            return await interaction.response.send_message(embed=emb(f"{E790} เเชทจบเเล้วน้า"), ephemeral=True)
        await interaction.response.send_modal(TypeModal(self.chat))

    async def leave(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await end_chat(self.chat, by=self.uid)

    async def _go(self, interaction: discord.Interaction, delta: int):
        c = self.chat
        buf, total, page = render(c.id, c.msgs, c.page[self.uid] + delta)
        c.page[self.uid], c.follow[self.uid] = page, page == total - 1
        await interaction.response.edit_message(
            embed=chat_embed(), attachments=[discord.File(buf, "chat.png")], view=ChatView(c, self.uid, page, total))

    async def prev(self, interaction: discord.Interaction):
        await self._go(interaction, -1)

    async def next(self, interaction: discord.Interaction):
        await self._go(interaction, 1)


class ConfirmView(discord.ui.View):
    def __init__(self, chat: Chat, uid: int):
        super().__init__(timeout=None)
        self.chat, self.uid = chat, uid
        ok = discord.ui.Button(label="ยืนยันเเชท", style=discord.ButtonStyle.success, emoji=pe(E606))
        no = discord.ui.Button(label="ยกเลิกเเชท", style=discord.ButtonStyle.danger, emoji=pe(E790))
        ok.callback, no.callback = self.confirm, self.cancel
        self.add_item(ok)
        self.add_item(no)

    async def confirm(self, interaction: discord.Interaction):
        c = self.chat
        if c.state != "pending":
            return await interaction.response.send_message(embed=emb(f"{E790} เเชทนี้หมดอายุเเล้วน้า"), ephemeral=True)
        c.confirmed.add(self.uid)
        if len(c.confirmed) < 2:
            e = interaction.message.embeds[0]
            e.description += f"\n\n{E606} พี่ยืนยันเเล้ว รออีกฝั่งกดยืนยัน..."
            return await interaction.response.edit_message(embed=e, view=None)
        await interaction.response.defer()
        c.state = "active"
        if c.task and not c.task.done():
            c.task.cancel()
        q("UPDATE ac_chats SET status='active' WHERE chat_id=?", (c.id,))
        old = dict(c.dm)
        await push_all(c)
        for m in old.values():
            try:
                await m.delete()
            except discord.HTTPException:
                pass

    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await end_chat(self.chat, by=self.uid, status="cancelled", reason="ยกเลิกเเชทเเล้ว")
        try:
            await self.chat.users[self.chat.other(self.uid)].send(
                embed=emb(f"{E790} อีกฝั่งยกเลิกเเชทเเล้วน้า"))
        except discord.HTTPException:
            pass


class WaitView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=None)
        self.uid = uid
        b = discord.ui.Button(label="ยกเลิกการค้นหา", style=discord.ButtonStyle.secondary, emoji=pe(E790))
        b.callback = self.cancel
        self.add_item(b)

    async def cancel(self, interaction: discord.Interaction):
        stop_search(self.uid)
        await interaction.response.edit_message(embed=emb(f"{E790} ยกเลิกการค้นหาเเล้วน้า"), view=None)


def stop_search(uid: int):
    SEARCHING.pop(uid, None)
    for lst in QUEUES.values():
        if uid in lst:
            lst.remove(uid)


# ═════════════ จับคู่ ═════════════
def pending_embed(role: str, chat: Chat) -> discord.Embed:
    if role == "listener":
        text = (f"# {E607} เจอผู้ที่จะมาให้คุณรับฟังเเล้ว {E607}\n\n"
                f"{E726} อย่าลืมกฎการใช้งานระบบนี้ ขอให้โชคดีกับการเเชทครั้งนี้ กดปุ่มด้านล่างเพื่อเริ่มเเชท")
    else:
        text = (f"# {E729} มีผู้ยินดีรับฟังคุณเเล้ว {E729}\n\n"
                f"{E741} กดปุ่มด้านล่างเพื่อเริ่มเเชท อย่าลืมกฎการใช้ คุณมีอะไรค้างคาในใจสามารถระบายออกมาได้เต็มที่")
    return emb(text + f"\n\nต้องกดยืนยันภายใน {CONFIRM_SECONDS // 60} นาที (เเชท ID: {chat.id})")


async def try_match(uid: int, role: str):
    opposite = "listener" if role == "venter" else "venter"
    queue = QUEUES[opposite]
    while queue:
        other = queue.pop(0)
        if other == uid or other not in SEARCHING or is_banned(other):
            continue
        a, b = SEARCHING[uid], SEARCHING[other]
        venter, listener = (a["user"], b["user"]) if role == "venter" else (b["user"], a["user"])
        chat = Chat(new_chat_id(), venter, listener)
        sent = {}
        try:
            for u in (venter, listener):
                sent[u.id] = await u.send(embed=pending_embed(chat.role[u.id], chat), view=ConfirmView(chat, u.id))
        except discord.HTTPException:
            for m in sent.values():
                try:
                    await m.delete()
                except discord.HTTPException:
                    pass
            bad = next((u.id for u in (venter, listener) if u.id not in sent), None)
            if bad is not None:      # คนที่ DM ไม่ได้ออกจากคิว อีกคนค้นหาต่อ
                stop_search(bad)
            if bad == other:
                continue
            return
        for u in (uid, other):
            m = SEARCHING.pop(u, {}).get("msg")
            if m:
                try:
                    await m.edit(embed=emb(f"{E606} เจอเเชทเเล้ว! ดูข้อความใหม่ใน DM ได้เลยน้า"), view=None)
                except discord.HTTPException:
                    pass
        chat.dm = sent
        for u in chat.users:
            USER_CHAT[u] = chat
        q("INSERT INTO ac_chats VALUES (?,?,?,?,?,NULL)",
          (chat.id, venter.id, listener.id, "pending", int(time.time())))

        async def timeout():
            await asyncio.sleep(CONFIRM_SECONDS)
            if chat.state == "pending":
                await end_chat(chat, by=None, status="cancelled",
                               reason=f"ยกเลิกเเชทเพราะมีคนไม่กดรับเเชทภายใน {CONFIRM_SECONDS // 60} นาที")
        chat.task = asyncio.create_task(timeout())
        return
    QUEUES[role].append(uid)


# ═════════════ แผงในห้อง + เมนู ═════════════
def panel_embed() -> discord.Embed:
    e = emb(
        f"# {E804} Anonymous Chat {E863}\n\n"
        "ได้เเรงบัลดานใจมาจากเว็บ: blissiam.com\n\n"
        f"{E767} ก่อนจะเริ่มหาเเชท โปรดทักDmไปหาบอทก่อน 1 ครั้งเพื่อเป็นการเปิดDmให้บอทสามารถส่งเเชทได้\n\n"
        f"{E802} ระบบนี้เป็นระบบคุยกันให้คำปรึกษากันแบบ Anonymous คือการคุยกันแบบไม่ระบุตัวตน "
        "สามารถเลือกได้ว่าจะเป็นผู้รับฟังหรือผู้ระบาย ถ้าหากพบเจอคนที่พูดไม่เพราะเรื้อน สามารถเลือกลิสรายงานได้ "
        "ส่งคำอธิบาย + เเนบID เเชทที่คุยกัน สามารถกู้เเชทได้โดยการเลือกลิสประวัติเเชท\n\n"
        f"{E801} **วิธีใช้**\n\n"
        f"{E800} กดเริ่มเเชทด้านล่าง เลือกว่าจะเป็นผู้ระบายหรือรับฟัง เเล้วบอทจะส่งข้อความไปในเเชทDm ของคุณ "
        "เมื่อหาเเชทเจอบอทจะเเจ้งให้คุณกดยืนยันเเชท เเล้วก็จะสามารถเริ่มคุยกันได้ "
        "หลังจากคุยเสร็จบอทจะบันทึกการคุยของคุณไว้เพื่อความปลอดภัยของท่าน\n\n"
        f"{E727} **เงื่อนไขการใช้**\n\n"
        f"{E726} ห้ามToxic เรื้อน ด่า หรือใช้คำพูดที่ไม่เหมาะสม ซ้ำเติม หรืออะไรต่างๆ "
        "ไม่ว่าจะเป็นบทผู้ระบายหรือผู้รับฟัง\n\n"
        "ถ้ารู้สึกหนักเกินจะรับไหว โทรสายด่วนสุขภาพจิต **1323** ได้ตลอด 24 ชั่วโมงนะ")
    e.set_image(url=PANEL_IMG)
    return e


class RolePickView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        sel = discord.ui.Select(placeholder="เลือกบทบาท", options=[
            discord.SelectOption(label="ผู้ระบาย", value="venter", emoji=pe(E866)),
            discord.SelectOption(label="ผู้รับฟัง", value="listener", emoji=pe(E865)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        role = interaction.data["values"][0]
        ROLE_PICK[interaction.user.id] = role
        await interaction.response.edit_message(
            embed=emb(f"{E606} เลือกบทบาทเป็น **{ROLE_TH[role]}** เเล้วน้า กด **เริ่มค้นหาเเชท** ได้เลย"), view=None)


class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        sel = discord.ui.Select(placeholder="เลือกระบบ", options=[
            discord.SelectOption(label="เลือกบทบาท", value="role", emoji=pe(E866)),
            discord.SelectOption(label="เริ่มค้นหาเเชท", value="search", emoji=pe(E865)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E790)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v, uid = interaction.data["values"][0], interaction.user.id
        await interaction.response.edit_message(view=self)  # รีเซ็ตเมนู
        send = lambda **kw: interaction.followup.send(ephemeral=True, **kw)
        if v == "role":
            return await send(embed=emb(f"{E742} เลือกว่าจะเป็นผู้ระบายหรือผู้รับฟัง"), view=RolePickView())
        if v == "clear":
            ROLE_PICK.pop(uid, None)
            if uid in SEARCHING:
                stop_search(uid)
            return await send(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"))

        # เริ่มค้นหา
        if is_banned(uid):
            return await send(embed=emb(f"{E790} {BANNED_TEXT}"))
        role = ROLE_PICK.get(uid)
        if not role:
            return await send(embed=emb(f"{E790} ต้องเลือกบทบาทก่อนถึงจะค้นหาได้น้าา"))
        if uid in SEARCHING or uid in USER_CHAT:
            return await send(embed=emb(f"{E790} พี่กำลังค้นหาหรืออยู่ในเเชทอยู่เเล้วน้า"))
        try:
            msg = await interaction.user.send(
                embed=emb(f"{E742} ตอนนี้คุณกำลังอยู่ในบทบาท **{ROLE_TH[role]}** โปรดรอเเชท\n"
                          "เมื่อเจอเเล้วบอทจะส่งเเชทมาที่ DM นี้ (ยกเลิกการค้นหาได้ที่ปุ่มด้านล่าง)"),
                view=WaitView(uid))
        except discord.HTTPException:
            return await send(embed=emb(f"{E790} บอทส่ง DM หาพี่ไม่ได้ ช่วยเปิดรับ DM เเละทักบอทก่อน 1 ครั้งน้า"))
        SEARCHING[uid] = {"role": role, "msg": msg, "user": interaction.user}
        await send(embed=emb(f"{E606} ตอนนี้คุณกำลังอยู่ในบทบาท **{ROLE_TH[role]}** โปรดรอเเชท "
                             "(ดูความคืบหน้าใน DM ได้เลย)"))
        await try_match(uid, role)


class HistoryPage(discord.ui.View):
    def __init__(self, chat_id: str, page: int, total: int):
        super().__init__(timeout=900)
        self.chat_id = chat_id
        pv = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary, disabled=page <= 0)
        nx = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary, disabled=page >= total - 1)
        pv.callback = lambda i: self.go(i, page - 1)
        nx.callback = lambda i: self.go(i, page + 1)
        self.add_item(pv)
        self.add_item(nx)

    async def go(self, interaction: discord.Interaction, page: int):
        buf, total, page = render(self.chat_id, load_msgs(self.chat_id), page)
        await interaction.response.edit_message(
            embed=chat_embed(), attachments=[discord.File(buf, "chat.png")], view=HistoryPage(self.chat_id, page, total))


class HistoryView(discord.ui.View):
    def __init__(self, rows: list, uid: int):
        super().__init__(timeout=600)
        opts = []
        for cid, vid, created, n in rows:
            role = ROLE_TH["venter" if vid == uid else "listener"]
            opts.append(discord.SelectOption(
                label=f"ID {cid} • {role}", value=cid,
                description=f"{time.strftime('%d/%m/%Y %H:%M', time.gmtime(created + 25200))} • {n} ข้อความ"))
        sel = discord.ui.Select(placeholder="เลือกเเชทที่อยากดู", options=opts)
        sel.callback = self.on_select
        self.sel, self.uid = sel, uid
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        cid = self.sel.values[0]
        ok = q("SELECT 1 FROM ac_chats WHERE chat_id=? AND (venter_id=? OR listener_id=?)",
               (cid, self.uid, self.uid), one=True)
        if not ok:
            return await interaction.response.send_message(embed=emb(f"{E790} ไม่พบเเชทนี้ในประวัติของพี่น้า"), ephemeral=True)
        buf, total, page = render(cid, load_msgs(cid), 0)
        await interaction.response.send_message(
            embed=chat_embed(), file=discord.File(buf, "chat.png"), view=HistoryPage(cid, page, total), ephemeral=True)


class ReportModal(discord.ui.Modal, title="รายงานเเชท"):
    chat_id = discord.ui.TextInput(label="ID เเชท (ดูได้จากมุมขวาบนของภาพเเชท)", max_length=12, placeholder="เช่น 7KQ2MX")
    reason = discord.ui.TextInput(label="รายงานเเชทนี้เพราะอะไร", style=discord.TextStyle.paragraph,
                                  max_length=900, placeholder="อธิบายสิ่งที่เกิดขึ้น")

    async def on_submit(self, interaction: discord.Interaction):
        uid, now = interaction.user.id, int(time.time())
        row = q("SELECT last_at FROM ac_report_cd WHERE user_id=?", (uid,), one=True)
        if row and row[0] + REPORT_COOLDOWN > now:
            return await interaction.response.send_message(
                embed=emb(f"{E790} เเจ้งได้ 1 ครั้งต่อ 1 ชั่วโมงน้าา เเจ้งได้อีกครั้ง <t:{row[0] + REPORT_COOLDOWN}:R>"),
                ephemeral=True)
        cid = self.chat_id.value.strip().upper()
        chat = q("SELECT venter_id, listener_id FROM ac_chats WHERE chat_id=?", (cid,), one=True)
        if not chat or uid not in chat:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ไม่พบเเชท ID นี้ในประวัติของพี่น้า (ต้องเป็นเเชทที่พี่เคยคุยเท่านั้น)"), ephemeral=True)
        role = "venter" if chat[0] == uid else "listener"
        await interaction.response.defer(ephemeral=True)
        e = discord.Embed(
            description=(f"# มีคนเเจ้งเเชท\n\n{interaction.user.mention} id({uid})\n\n"
                         f"คนที่เเจ้งเป็นบทบาท **{ROLE_TH[role]}**\n\nidเเชท({cid})\n\n"
                         f"**สิ่งที่เเจ้งมา**\n```{self.reason.value.strip().replace('```', chr(39) * 3)}```"),
            color=WHITE, timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.set_footer(text="เเจ้งเมื่อ")
        try:
            ch = interaction.client.get_channel(REPORT_CHANNEL_ID) or await interaction.client.fetch_channel(REPORT_CHANNEL_ID)
            await ch.send(embed=e)
        except discord.HTTPException:
            return await interaction.followup.send(
                embed=emb(f"{E790} ส่งรายงานไม่สำเร็จน้า ลองใหม่อีกที (ยังไม่นับเป็นรอบ)"), ephemeral=True)
        q("INSERT OR REPLACE INTO ac_report_cd VALUES (?,?)", (uid, now))
        await interaction.followup.send(
            embed=emb(f"{E606} ส่งรายงานให้เเอดมินเเล้วน้าา เเจ้งได้อีกครั้ง <t:{now + REPORT_COOLDOWN}:R>"), ephemeral=True)


class AnonPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(custom_id="anon:panel", placeholder="ลิสระบบ", options=[
            discord.SelectOption(label="เริ่มการเเชท", value="start", emoji=pe(E608)),
            discord.SelectOption(label="ประวัติเเชท", value="history", emoji=pe(E725)),
            discord.SelectOption(label="รายงาน", value="report", emoji=pe(E793)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E604)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v, uid = interaction.data["values"][0], interaction.user.id
        try:
            await interaction.message.edit(view=AnonPanelView())  # รีเซ็ตเมนู
        except discord.HTTPException:
            pass
        if v == "report":
            return await interaction.response.send_modal(ReportModal())
        if v == "start":
            return await interaction.response.send_message(
                embed=emb(f"# {E742} เลือกบทบาทเเละการค้นหาเเชท {E742}\n\n"
                          "ให้กดลิสด้านล่าง เลือกบทบาท ว่าจะเป็น ผู้ระบาย ผู้รับฟัง เเล้วกดค้นหาเเชท "
                          "(ตอนนี้บอทยังเป็นบอทใหม่อาจจะยังไม่มีคนมาใช้งานระบบมากนัก ต้องขออภัยด้วยค่ะ)"),
                view=StartView(), ephemeral=True)
        if v == "history":
            rows = q("""SELECT c.chat_id, c.venter_id, c.created_at,
                               (SELECT COUNT(*) FROM ac_messages m WHERE m.chat_id=c.chat_id) n
                        FROM ac_chats c WHERE (c.venter_id=? OR c.listener_id=?) AND c.status='ended'
                        ORDER BY c.created_at DESC LIMIT 25""", (uid, uid), many=True)
            rows = [r for r in rows if r[3] > 0]
            if not rows:
                return await interaction.response.send_message(
                    embed=emb(f"{E725} ยังไม่มีประวัติเเชทของพี่เลยน้า"), ephemeral=True)
            return await interaction.response.send_message(
                embed=emb(f"# {E725} ประวัติเเชท\n\nเลือกเเชทที่อยากดูในลิสด้านล่างได้เลย (เห็นเฉพาะเเชทของพี่เอง)"),
                view=HistoryView(rows, uid), ephemeral=True)
        await interaction.response.send_message(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"), ephemeral=True)


# ═════════════ Cog ═════════════
class AnonymousChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()
        find_font()
        self.bot.add_view(AnonPanelView())

    @app_commands.command(name="anonymous_chat", description="ระบบคุยกันแบบไม่ระบุตัวตน (แอดมินเท่านั้น)")
    @app_commands.guild_only()
    async def anonymous_chat(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
        guild, me = interaction.guild, interaction.guild.me
        if not me.guild_permissions.manage_channels:
            return await interaction.response.send_message(
                embed=emb(f"{E790} น้องต้องมีสิทธิ์ จัดการช่อง ก่อนน้า"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        row = q("SELECT channel_id, panel_message_id FROM ac_config WHERE guild_id=?", (guild.id,), one=True)
        try:
            ch = guild.get_channel(row[0]) if row else None
            if ch is None:
                ch = await guild.create_text_channel("Anonymous Chat", overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True, send_messages=False, read_message_history=True),
                    me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                                    manage_messages=True)})
            elif row and row[1]:
                try:
                    await (await ch.fetch_message(row[1])).delete()
                except discord.HTTPException:
                    pass
            msg = await ch.send(embed=panel_embed(), view=AnonPanelView())
        except discord.HTTPException as e:
            return await interaction.followup.send(
                embed=emb(f"{E790} สร้างห้องไม่สำเร็จ ({e.status}) เช็คสิทธิ์บอทเเล้วลองใหม่น้า"), ephemeral=True)
        q("INSERT INTO ac_config VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
          "channel_id=excluded.channel_id, panel_message_id=excluded.panel_message_id", (guild.id, ch.id, msg.id))
        await interaction.followup.send(embed=emb(f"{E606} สร้างห้อง Anonymous Chat เเล้วน้าา {ch.mention}"), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        # ── พิมพ์ใน DM ตรงๆ ก็ส่งต่อให้คู่สนทนาได้ ──
        if message.guild is None:
            chat = USER_CHAT.get(message.author.id)
            if chat and chat.state == "active":
                if message.attachments or message.stickers:
                    return await message.channel.send(embed=emb(f"{E790} ส่งได้เฉพาะข้อความตัวอักษรน้า"), delete_after=8)
                await relay(chat, message.author.id, message.content)
            return

        # ── คำสั่งของเเอดมิน ในห้องรายงาน ──
        if message.channel.id != REPORT_CHANNEL_ID or not message.content.startswith("!"):
            return
        perms = message.author.guild_permissions
        if not (perms.administrator or await self.bot.is_owner(message.author)):
            return
        parts = message.content.split()
        cmd, arg = parts[0].lower(), (parts[1] if len(parts) > 1 else "")

        if cmd == "!id":
            cid = arg.upper()
            row = q("SELECT venter_id, listener_id, status, created_at FROM ac_chats WHERE chat_id=?", (cid,), one=True)
            if not row:
                return await message.reply(embed=emb(f"{E790} ไม่พบเเชท ID `{cid}`"), mention_author=False)
            msgs = load_msgs(cid)
            info = emb(f"# เเชท {cid}\n\n**ผู้ระบาย** <@{row[0]}> id({row[0]})\n**ผู้รับฟัง** <@{row[1]}> id({row[1]})\n"
                       f"**สถานะ** {row[2]} • **ข้อความ** {len(msgs)}\n\n"
                       "เเบนได้ด้วย `!banid <id คน>` ปลดเเบนด้วย `!unban <id คน>`")
            files, page, total = [], 0, 1
            while page < total:
                buf, total, _ = render(cid, msgs, page)
                files.append(discord.File(buf, f"chat-{cid}-{page + 1}.png"))
                page += 1
            await message.reply(embed=info, mention_author=False)
            for i in range(0, len(files), 10):
                await message.channel.send(files=files[i:i + 10])
        elif cmd in ("!banid", "!unban"):
            if not arg.isdigit():
                return await message.reply(embed=emb(f"{E790} ใช้เเบบนี้: `{cmd} <id คน>`"), mention_author=False)
            target = int(arg)
            if cmd == "!banid":
                q("INSERT OR REPLACE INTO ac_bans VALUES (?,?,?)", (target, message.author.id, int(time.time())))
                stop_search(target)
                chat = USER_CHAT.get(target)
                if chat:
                    await end_chat(chat, by=target, status="ended")
                await message.reply(embed=emb(f"{E606} เเบน <@{target}> ({target}) ไม่ให้ใช้ระบบเเชทเเล้ว"),
                                    mention_author=False)
            else:
                q("DELETE FROM ac_bans WHERE user_id=?", (target,))
                await message.reply(embed=emb(f"{E606} ปลดเเบน <@{target}> ({target}) เเล้ว"), mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(AnonymousChatCog(bot))
