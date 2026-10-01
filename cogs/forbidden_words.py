import math
import time
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)
DELETE_AFTER = 3  # วินาที ที่บอทลบข้อความเตือนของตัวเอง

# ───────── อีโมจิ ─────────
E_TITLE = "<a:1000035791:1554977295414988820>"
E793 = "<:1000035793:1554977816431431850>"
E790 = "<:1000035790:1554970748232147004>"
E604 = "<a:1000035604:1554847795524141216>"
E603 = "<a:1000035603:1554845277071089736>"
E727 = "<a:1000035727:1554859928957755393>"
E726 = "<a:1000035726:1554859496894111744>"
E740 = "<a:1000035740:1554874072205107263>"
E762 = "<a:1000035762:1554919569682989166>"
E606 = "<a:1000035606:1554848463320129567>"
E744 = "<a:1000035744:1554884849406451762>"
E767 = "<a:1000035767:1554921960838926417>"
E763 = "<a:1000035763:1554920997382262874>"
E764 = "<a:1000035764:1554920142146904164>"
E757 = "<a:1000035757:1554907672502083694>"
E760 = "<a:1000035760:1554908193174589581>"
E786 = "<a:1000035786:1554968314135191682>"
E729 = "<a:1000035729:1554863632528052315>"
E725 = "<a:1000035725:1554844594175483904>"
E608 = "<a:1000035608:1554844998506123274>"
E741 = "<a:1000035741:1554876169017499658>"
E742 = "<a:1000035742:1554876309790793908>"
E743 = "<a:1000035743:1554882610134524034>"
E607 = "<a:1000035607:1554874918632562788>"
E728 = "<a:1000035728:1554860189125967894>"


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
    q("""CREATE TABLE IF NOT EXISTS fw_words (
        guild_id INTEGER, word TEXT, added_by INTEGER, added_at INTEGER,
        PRIMARY KEY (guild_id, word))""")
    q("""CREATE TABLE IF NOT EXISTS fw_config (
        guild_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0, mode TEXT DEFAULT 'delete',
        limit_n INTEGER DEFAULT 0, timeout_min INTEGER DEFAULT 0, warn_text TEXT DEFAULT '',
        set_by INTEGER, set_at INTEGER)""")
    try:  # เพิ่มคอลัมน์ "ใครเปิด/ปิดล่าสุด" (ฐานข้อมูลเก่าที่ยังไม่มี)
        q("ALTER TABLE fw_config ADD COLUMN status_by INTEGER")
    except Exception:
        pass
    q("""CREATE TABLE IF NOT EXISTS fw_exempt (
        guild_id INTEGER, kind TEXT, target_id INTEGER,
        PRIMARY KEY (guild_id, kind, target_id))""")
    q("""CREATE TABLE IF NOT EXISTS fw_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER,
        kind TEXT, word TEXT, extra INTEGER DEFAULT 0, created_at INTEGER)""")
    q("CREATE INDEX IF NOT EXISTS idx_fw_log ON fw_log (guild_id, kind, created_at)")
    q("""CREATE TABLE IF NOT EXISTS fw_warns (
        guild_id INTEGER, user_id INTEGER, count INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id))""")


CACHE: dict = {}  # guild_id -> state (กันอ่าน DB ทุกข้อความ)


def invalidate(gid: int):
    CACHE.pop(gid, None)


def load(gid: int) -> dict:
    if gid in CACHE:
        return CACHE[gid]
    row = q("SELECT enabled, mode, limit_n, timeout_min, warn_text, set_by, set_at, status_by "
            "FROM fw_config WHERE guild_id=?", (gid,), one=True)
    st = dict(enabled=0, mode="delete", limit=0, timeout=0, warn_text="", set_by=None, set_at=None, status_by=None)
    if row:
        st.update(enabled=row[0], mode=row[1], limit=row[2], timeout=row[3],
                  warn_text=row[4] or "", set_by=row[5], set_at=row[6], status_by=row[7])
    st["words"] = q("SELECT word, added_by, added_at FROM fw_words WHERE guild_id=? ORDER BY added_at",
                    (gid,), many=True)
    st["wordlist"] = [w[0] for w in st["words"]]
    ex = {"user": set(), "channel": set(), "category": set()}
    for kind, tid in q("SELECT kind, target_id FROM fw_exempt WHERE guild_id=?", (gid,), many=True):
        ex.setdefault(kind, set()).add(tid)
    st["ex"] = ex
    CACHE[gid] = st
    return st


ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))


def norm(s: str) -> str:
    return s.lower().translate(ZW).strip()


def split_words(raw: str) -> list:
    seen, out = set(), []
    for w in raw.split(","):
        w = norm(w)
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def parse_int(s: str, lo: int, hi: int) -> Optional[int]:
    s = (s or "").strip()
    if not s.isdigit():
        return None
    n = int(s)
    return n if lo <= n <= hi else None


def set_mode(gid: int, mode: str, limit: int, timeout: int, warn_text: str, by: int):
    q("""INSERT INTO fw_config (guild_id, mode, limit_n, timeout_min, warn_text, set_by, set_at)
         VALUES (?,?,?,?,?,?,?)
         ON CONFLICT(guild_id) DO UPDATE SET mode=excluded.mode, limit_n=excluded.limit_n,
           timeout_min=excluded.timeout_min, warn_text=excluded.warn_text,
           set_by=excluded.set_by, set_at=excluded.set_at""",
      (gid, mode, limit, timeout, warn_text, by, int(time.time())))
    q("DELETE FROM fw_warns WHERE guild_id=?", (gid,))  # เปลี่ยนระบบ = เริ่มนับเตือนใหม่
    invalidate(gid)


def set_enabled(gid: int, on: bool, by: int):
    q("""INSERT INTO fw_config (guild_id, enabled, status_by) VALUES (?,?,?)
         ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled, status_by=excluded.status_by""",
      (gid, int(on), by))
    invalidate(gid)


def add_warn(gid: int, uid: int) -> int:
    q("""INSERT INTO fw_warns (guild_id, user_id, count) VALUES (?,?,1)
         ON CONFLICT(guild_id, user_id) DO UPDATE SET count=count+1""", (gid, uid))
    return q("SELECT count FROM fw_warns WHERE guild_id=? AND user_id=?", (gid, uid), one=True)[0]


def log_event(gid: int, uid: int, kind: str, word: str, extra: int = 0):
    """บันทึกประวัติ kind = warn / kick / ban / timeout"""
    q("INSERT INTO fw_log (guild_id, user_id, kind, word, extra, created_at) VALUES (?,?,?,?,?,?)",
      (gid, uid, kind, word, extra, int(time.time())))


def reset_warn(gid: int, uid: int):
    q("DELETE FROM fw_warns WHERE guild_id=? AND user_id=?", (gid, uid))


MODE_NAME = {
    "delete": "ลบข้อความ + เตือน (ค่าเริ่มต้น)",
    "warn": "เตือนด้วยคำที่เซ็ตเอง",
    "kick": "เตะ",
    "ban": "เเบน",
    "timeout": "หมดเวลา",
}


# ═════════════ Views / Modals (ฝั่งแอดมิน) ═════════════
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


async def finish_modal(interaction: discord.Interaction, parent: discord.ui.View, embed: discord.Embed,
                       refresh: Optional[discord.Embed] = None):
    """รีเซ็ตเมนูเดิม (และอัปเดตแผงถ้าส่ง refresh มา) แล้วส่งผลลัพธ์แบบเห็นคนเดียว"""
    try:
        if refresh is not None:
            await interaction.response.edit_message(embed=refresh, view=parent)
        else:
            await interaction.response.edit_message(view=parent)
    except discord.HTTPException:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ---- antiคำ / ลบคำ ----
class AddWordsModal(discord.ui.Modal, title="antiคำ"):
    words = discord.ui.TextInput(
        label="คำที่ต้องการห้าม (คั่นด้วย , )", style=discord.TextStyle.paragraph,
        placeholder="เช่น ควย,หี,เย็ด,เงี่ยน", max_length=3000)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        added = []
        for w in split_words(self.words.value):
            if len(w) > 100:
                continue
            exists = q("SELECT 1 FROM fw_words WHERE guild_id=? AND word=?", (gid, w), one=True)
            if not exists:
                q("INSERT INTO fw_words VALUES (?,?,?,?)", (gid, w, interaction.user.id, int(time.time())))
                added.append(w)
        invalidate(gid)
        if added:
            e = emb(f"{E767} สำเร็จเเล้วน้าาพี่ เพิ่มคำต้องห้ามไป **{len(added)}** คำ\n({', '.join(added)})")
        else:
            e = emb(f"{E790} ไม่มีคำใหม่ให้เพิ่มน้าา (อาจมีอยู่แล้วหรือเว้นว่าง)")
        await finish_modal(interaction, self.parent, e)


class RemoveWordsModal(discord.ui.Modal, title="ลบคำที่anti"):
    words = discord.ui.TextInput(
        label="คำที่เคยห้าม (คั่นด้วย , )", style=discord.TextStyle.paragraph,
        placeholder="เช่น หี,ควย,เเตด", max_length=3000)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        removed, missing = [], []
        for w in split_words(self.words.value):
            if q("SELECT 1 FROM fw_words WHERE guild_id=? AND word=?", (gid, w), one=True):
                q("DELETE FROM fw_words WHERE guild_id=? AND word=?", (gid, w))
                removed.append(w)
            else:
                missing.append(w)
        invalidate(gid)
        text = f"{E763} หนูลบคำต้องห้ามให้พี่เเล้วน้าา มีคำว่า ({', '.join(removed) or 'ไม่มี'})"
        if missing:
            text += f"\nคำที่ไม่มีอยู่เเล้ว ({', '.join(missing)})"
        await finish_modal(interaction, self.parent, emb(text))


# ---- ตั้งระบบ เตะ/แบน/เตือน/หมดเวลา ----
class KickBanModal(discord.ui.Modal):
    limit = discord.ui.TextInput(label="เตือนกี่ครั้งก่อนเตะ/แบน (สูงสุด 10)", required=False,
                                 placeholder="เว้นว่าง = ลงโทษเลย", max_length=2)

    def __init__(self, kind: str, parent):
        super().__init__(title="ตั้งระบบเตะ" if kind == "kick" else "ตั้งระบบเเบน")
        self.kind, self.parent = kind, parent

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.limit.value.strip()
        n = 0 if raw == "" else parse_int(raw, 0, 10)
        if n is None:
            return await finish_modal(interaction, self.parent,
                                      emb(f"{E790} กรอกเป็นตัวเลข 0-10 เท่านั้นน้าา"))
        set_mode(interaction.guild.id, self.kind, n, 0, "", interaction.user.id)
        name = MODE_NAME[self.kind]
        tail = f"เตือน **{n}** ครั้งก่อน{name}" if n else f"{name}ทันทีเมื่อพิมพ์คำต้องห้าม"
        await finish_modal(interaction, self.parent, emb(f"{E725} พี่เซ็ตระบบ{name}เเล้วน้าา {tail}"),
                           refresh=mode_embed(interaction.guild))


class WarnModal(discord.ui.Modal, title="ตั้งระบบเตือน"):
    text = discord.ui.TextInput(
        label="ข้อความเตือน (ว่าง = ข้อความเดิมของบอท)", style=discord.TextStyle.paragraph,
        required=False, max_length=300,
        placeholder="เช่น ไม่ควรพูดเเบบนี้นะคะ  (ใช้ {user} {word} ได้)")

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        t = self.text.value.strip()
        set_mode(interaction.guild.id, "warn", 0, 0, t, interaction.user.id)
        shown = f"\nคำเตือน: {t}" if t else "\nใช้ข้อความเดิมของบอท"
        await finish_modal(interaction, self.parent,
                           emb(f"{E725} พี่เซ็ตระบบเตือนเเล้วน้าา (ลบข้อความ + เตือนเฉยๆ ไม่เตะไม่เเบน){shown}"),
                           refresh=mode_embed(interaction.guild))


class TimeoutModal(discord.ui.Modal, title="ตั้งระบบหมดเวลา"):
    minutes = discord.ui.TextInput(label="หมดเวลากี่นาที (สูงสุด 10080)", placeholder="เช่น 60", max_length=5)
    limit = discord.ui.TextInput(label="เตือนกี่ครั้งก่อนหมดเวลา (สูงสุด 10)", required=False,
                                 placeholder="เว้นว่าง = หมดเวลาเลย", max_length=2)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        m = parse_int(self.minutes.value, 1, 10080)
        raw = self.limit.value.strip()
        n = 0 if raw == "" else parse_int(raw, 0, 10)
        if m is None or n is None:
            return await finish_modal(interaction, self.parent,
                                      emb(f"{E790} กรอกนาทีเป็นเลข 1-10080 และเตือนเป็นเลข 0-10 เท่านั้นน้าา"))
        set_mode(interaction.guild.id, "timeout", n, m, "", interaction.user.id)
        await finish_modal(interaction, self.parent, emb(
            f"{E725} พี่เซ็ตระบบหมดเวลาเเล้วน้าา หมดเวลาไป **{m}** นาที\n"
            f"ถ้าเป็นชั่วโมงจะเท่ากับ: {round(m / 60, 2):g}\n"
            f"ถ้าเป็นวัน: {round(m / 1440, 2):g}"
            + (f"\nเตือนก่อน **{n}** ครั้ง" if n else "")),
            refresh=mode_embed(interaction.guild))


def info_lines(st: dict):
    """บล็อก 'ระบบเดิมตอนนี้' + 'สถานะตอนนี้' ใช้ซ้ำทั้งแผงหลักและหน้าเซ็ตระบบ"""
    who = f"<@{st['set_by']}>" if st["set_by"] else "ไม่มี"
    info = f"{E760} ระบบเดิมตอนนี้คือ : **{MODE_NAME[st['mode']]}**\nเซ็ตโดย : {who}"
    if st["mode"] in ("kick", "ban", "timeout"):
        info += f"\nเตือนทั้งหมด: {st['limit']} ครั้ง"
    if st["mode"] == "timeout":
        info += f"\nหมดเวลา: {st['timeout']} นาที"
    by = f" ({'เปิด' if st['enabled'] else 'ปิด'}โดย <@{st['status_by']}>)" if st["status_by"] else ""
    status = f"{E741} สถานะตอนนี้: " + (f"เปิด {E742}" if st["enabled"] else f"ปิด {E743}") + by
    return info, status


def mode_embed(guild: discord.Guild) -> discord.Embed:
    info, status = info_lines(load(guild.id))
    return emb("\n\n".join([
        f"# เลือกระบบเตะ เเบน เตือน {E767}",
        f"{E757} ให้พี่ๆเลือกระบบ ว่าจะให้น้อง เตือน/หมดเวลา หรือ เตะ หรือ เเบนคนเลยเมื่อมีคนพิมพ์คำต้องห้าม",
        info, status]))


class ModeView(AdminView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        sel = discord.ui.Select(placeholder="เลือกระบบ", options=[
            discord.SelectOption(label="เตะ", value="kick", emoji=pe(E790)),
            discord.SelectOption(label="เเบน", value="ban", emoji=pe(E786)),
            discord.SelectOption(label="เตือน", value="warn", emoji=pe(E793)),
            discord.SelectOption(label="หมดเวลา", value="timeout", emoji=pe(E727)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E729)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        if v in ("kick", "ban"):
            await interaction.response.send_modal(KickBanModal(v, self))
        elif v == "warn":
            await interaction.response.send_modal(WarnModal(self))
        elif v == "timeout":
            await interaction.response.send_modal(TimeoutModal(self))
        else:
            await interaction.response.edit_message(view=self)
            await interaction.followup.send(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"), ephemeral=True)


# ---- prevent คน/ช่อง/หมวดหมู่ (ยกเว้นไม่โดน anti) ----
def prevent_embed(gid: int) -> discord.Embed:
    ex = load(gid)["ex"]
    u = " ".join(f"<@{i}>" for i in ex["user"]) or "ไม่มี"
    c = " ".join(f"<#{i}>" for i in ex["channel"]) or "ไม่มี"
    g = " ".join(f"<#{i}>" for i in ex["category"]) or "ไม่มี"
    return emb(
        f"# prevent คน/ช่อง/หมวดหมู่ {E793}\n\n"
        "เลือกคน ช่อง หรือหมวดหมู่ ที่ **ไม่ต้องโดน anti** ได้เลยน้าา (เลือกซ้ำ = เอาออก)\n\n"
        f"{E740} คน: {u}\n{E740} ช่อง: {c}\n{E740} หมวดหมู่: {g}")


def toggle_exempt(gid: int, kind: str, tid: int):
    if q("SELECT 1 FROM fw_exempt WHERE guild_id=? AND kind=? AND target_id=?", (gid, kind, tid), one=True):
        q("DELETE FROM fw_exempt WHERE guild_id=? AND kind=? AND target_id=?", (gid, kind, tid))
    else:
        q("INSERT INTO fw_exempt VALUES (?,?,?)", (gid, kind, tid))


class PreventView(AdminView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        us = discord.ui.UserSelect(placeholder="เลือกคน", min_values=1, max_values=10, row=0)
        cs = discord.ui.ChannelSelect(
            placeholder="เลือกช่อง/หมวดหมู่", min_values=1, max_values=10, row=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.voice,
                           discord.ChannelType.forum, discord.ChannelType.category])
        us.callback = self.on_users
        cs.callback = self.on_channels
        self.us, self.cs = us, cs
        self.add_item(us)
        self.add_item(cs)

    async def on_users(self, interaction: discord.Interaction):
        for u in self.us.values:
            toggle_exempt(interaction.guild.id, "user", u.id)
        invalidate(interaction.guild.id)
        await interaction.response.edit_message(embed=prevent_embed(interaction.guild.id), view=self)

    async def on_channels(self, interaction: discord.Interaction):
        for c in self.cs.values:
            kind = "category" if c.type == discord.ChannelType.category else "channel"
            toggle_exempt(interaction.guild.id, kind, c.id)
        invalidate(interaction.guild.id)
        await interaction.response.edit_message(embed=prevent_embed(interaction.guild.id), view=self)


# ---- เมนูหลัก ----
def _main_text() -> str:
    return (
        f"# anti คำต้องห้าม {E_TITLE}\n\n"
        f"{E793} คำสั่งนี้ จะantiคำที่แอดมินเซ็ตไว้ เช่น พ่อมึงตาย ถึงจะไม่ได้พิมพ์พ่อมึงตายโดยตรง "
        "เเต่ถ้าในประโยคมีคำนั้นเช่น ไอ้หน้าหีพ่อมึงตาย เเค่มีคำนั้นในประโยคก็สามารถโดนได้ "
        "เเล้วพี่ๆสามารถเซ็ตให้น้อง เตะ แบน เตือนด้วยคำพูด ได้ เตือนด้วยคำพูดพี่ๆสามารถเซ็ตคำเองได้ "
        "เช่นให้น้องตอบกลับไปว่า ไม่ควรพูดเเบบนี้นะคะ เเล้วลบคำนั้น หรือจะเตะจะเเบนก็ด้ายยย "
        f"พี่ๆสามารถเซ็ตได้โดยการกดลิสด้านล่าง {E604}\n\n"
        f"{E603} พี่ๆไม่ต้องเสียเวลามาพิมพ์ทีละคำ พี่ๆสามารถเซ็ตเเบบนี้ได้ ควย,หี,เย็ด,เงี่ยน "
        "โดยใช้เครื่องหมาย , ในการคั้นได้เลยย รวมถึงการลบคำก็ด้วยย")


def main_embed(gid: int) -> discord.Embed:
    info, status = info_lines(load(gid))
    return emb(_main_text() + "\n\n" + info + "\n\n" + status)


# ---- ประวัติการโดนเตือน/เตะ/เเบน/หมดเวลา ----
KINDS = ["warn", "ban", "kick", "timeout"]
KIND_TITLE = {"warn": "รายชื่อผู้ถูกบอทเตือน", "ban": "รายชื่อผู้ถูกเเบน",
              "kick": "รายชื่อผู้ถูกเตะ", "timeout": "รายชื่อผู้ถูกหมดเวลา"}
KIND_SHORT = {"warn": "เตือน", "ban": "เเบน", "kick": "เตะ", "timeout": "หมดเวลา"}
PAGE_SIZE = 50


def log_embeds(guild_id: int, kind: str, page: int, avatar_url: str):
    total = q("SELECT COUNT(*) FROM fw_log WHERE guild_id=? AND kind=?", (guild_id, kind), one=True)[0]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    rows = q("SELECT user_id, word, extra, created_at FROM fw_log WHERE guild_id=? AND kind=? "
             "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
             (guild_id, kind, PAGE_SIZE, page * PAGE_SIZE), many=True)
    head = (f"# {KIND_TITLE[kind]} {E608}\n\n"
            f"{E603} หากต้องการดูรายชื่อผู้ถูกเเบน เตะ หมดเวลา โปรดกดปุ่มด้านล่าง\n\n")
    if total == 0:
        chunks = [f"ยังไม่มีคนโดน{KIND_SHORT[kind]}เยยย"]
    elif not rows:
        chunks = ["ยังไม่ถึงหน้านี้น้าา"]
    else:
        lines = []
        for uid, word, extra, ts in rows:
            w = word if len(word) <= 20 else word[:20] + "…"
            w = w.replace("`", "'")
            line = f"<@{uid}> เนื่องจากพิมพ์คำว่า `{w}` เมื่อเวลา <t:{ts}:f>"
            if kind == "timeout" and extra:
                line += f" ({extra} นาที)"
            lines.append(line)
        # แบ่ง 2 embed ต่อหน้า (ลิมิตตัวอักษรของ embed)
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


class MainView(AdminView):
    def __init__(self, owner_id: int, enabled: bool = False):
        super().__init__(owner_id)
        sel = discord.ui.Select(placeholder="เซ็ตระบบ", options=[
            discord.SelectOption(label="antiคำ", value="add", emoji=pe(E727)),
            discord.SelectOption(label="ลบคำที่anti", value="remove", emoji=pe(E726)),
            discord.SelectOption(label="เช็คคำต้องห้าม", value="list", emoji=pe(E740)),
            discord.SelectOption(label="เช็คการโดนตักเตือน เตะ เเบน หมดเวลา", value="history", emoji=pe(E603)),
            discord.SelectOption(label="เซ็ต เตะ/เเบน/เตือน/หมดเวลา", value="mode", emoji=pe(E762)),
            discord.SelectOption(label="prevent คน/ช่อง/หมวดหมู่", value="prevent", emoji=pe(E793)),
            discord.SelectOption(label="ปิด" if enabled else "เปิด", value="toggle",
                                 emoji=pe(E743 if enabled else E742)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E744)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        guild = interaction.guild
        if v == "add":
            return await interaction.response.send_modal(AddWordsModal(self))
        if v == "remove":
            return await interaction.response.send_modal(RemoveWordsModal(self))

        if v == "toggle":
            on = not load(guild.id)["enabled"]
            set_enabled(guild.id, on, interaction.user.id)
            # สร้างเมนูใหม่ ให้ตัวเลือกสลับเป็น เปิด <-> ปิด
            await interaction.response.edit_message(embed=main_embed(guild.id), view=MainView(self.owner_id, on))
            if on:
                st = load(guild.id)
                n = (str(st["limit"]) if st["limit"] else "0 (ลงโทษทันที)") \
                    if st["mode"] in ("kick", "ban", "timeout") else "ไม่มี"
                e = emb(f"{E742} เปิดระบบสำเร็จ\nระบบที่เปิด: **{MODE_NAME[st['mode']]}**\nจำนวนครั้งที่เตือน: **{n}**")
            else:
                e = emb(f"{E743} ปิดระบบเเล้วน้าาพี่")
            return await interaction.followup.send(embed=e, ephemeral=True)

        await interaction.response.edit_message(view=self)  # รีเซ็ตเมนู
        send = lambda **kw: interaction.followup.send(ephemeral=True, **kw)

        if v == "list":
            words = load(guild.id)["words"]
            if not words:
                e = emb(f"# {E764} คำต้องห้ามทั้งหมด\n\nไม่มีคำต้องห้ามเยยย")
            else:
                parts, size = [], 0
                for i, (w, by, at) in enumerate(words):
                    line = f"`{w}` เพิ่มโดย: <@{by}> เมื่อ: <t:{at}:R>"
                    if size + len(line) > 3500:
                        parts.append(f"…และอีก {len(words) - i} คำ")
                        break
                    parts.append(line)
                    size += len(line) + 2
                e = emb(f"# {E764} คำต้องห้ามทั้งหมด\n\n" + "\n\n".join(parts))
            e.set_thumbnail(url=interaction.client.user.display_avatar.url)
            await send(embed=e)
        elif v == "history":
            await send(embeds=log_embeds(guild.id, "warn", 0, interaction.client.user.display_avatar.url),
                       view=LogView(interaction.user.id))
        elif v == "mode":
            await send(embed=mode_embed(guild), view=ModeView(interaction.user.id))
        elif v == "prevent":
            await send(embed=prevent_embed(guild.id), view=PreventView(interaction.user.id))
        else:
            await send(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"))


# ═════════════ ตัวตรวจข้อความ ═════════════
class ForbiddenWordsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()

    @app_commands.command(name="forbidden_words", description="antiคำบางคำ (แอดมินเท่านั้น)")
    @app_commands.guild_only()
    async def forbidden_words(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
        await interaction.response.send_message(
            embed=main_embed(interaction.guild.id), view=MainView(interaction.user.id, bool(load(interaction.guild.id)["enabled"])),
            ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or not message.content:
            return
        st = load(message.guild.id)
        if not st["enabled"] or not st["wordlist"]:
            return

        ex, ch = st["ex"], message.channel
        if message.author.id in ex["user"] or ch.id in ex["channel"]:
            return
        if getattr(ch, "category_id", None) in ex["category"]:
            return
        if isinstance(ch, discord.Thread) and (ch.parent_id in ex["channel"]):
            return

        text = norm(message.content)
        hit = next((w for w in st["wordlist"] if w in text), None)  # มีคำนั้นอยู่ส่วนไหนของประโยคก็โดน
        if hit:
            await self.handle(message, st, hit)

    async def handle(self, message: discord.Message, st: dict, hit: str):
        guild, member, ch = message.guild, message.author, message.channel
        mentions = discord.AllowedMentions(users=[member])

        async def say(text: str):
            try:
                await ch.send(text, delete_after=DELETE_AFTER, allowed_mentions=mentions)
            except discord.HTTPException:
                pass

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        mode = st["mode"]
        if mode in ("kick", "ban", "timeout"):
            limit = st["limit"]
            if limit > 0:
                n = add_warn(guild.id, member.id)
                if n <= limit:
                    log_event(guild.id, member.id, "warn", hit)
                    return await say(
                        f"{E790} {member.mention} พี่พิมพ์คำนี้ไม่ได้น้าาา ({hit}) พี่เหลือโอกาสอีก {limit - n} ครั้ง")
            if await self.punish(member, mode, st, hit):
                reset_warn(guild.id, member.id)
                log_event(guild.id, member.id, mode, hit, st["timeout"] if mode == "timeout" else 0)
                return
            # ลงโทษไม่ได้ (ยศบอทไม่ถึง/ไม่มีสิทธิ์) → เตือนธรรมดา
        elif mode == "warn" and st["warn_text"]:
            t = st["warn_text"]
            if "{user}" not in t:
                t = "{user} " + t
            log_event(guild.id, member.id, "warn", hit)
            return await say(t.replace("{user}", member.mention).replace("{word}", hit))

        log_event(guild.id, member.id, "warn", hit)
        await say(f"{E790} {member.mention} พี่พิมพ์คำนี้ไม่ได้น้าาา ({hit})")

    async def punish(self, member: discord.Member, mode: str, st: dict, hit: str) -> bool:
        guild, me = member.guild, member.guild.me
        perms = me.guild_permissions
        ok_perm = {"kick": perms.kick_members, "ban": perms.ban_members,
                   "timeout": perms.moderate_members}[mode]
        if (not ok_perm or member.id == guild.owner_id or member.top_role >= me.top_role
                or member.guild_permissions.administrator):
            return False

        if mode == "timeout":
            m = st["timeout"]
            until = discord.utils.utcnow() + timedelta(minutes=m)
            fmt = "f" if m >= 1440 else "t"  # เกิน 1 วันโชว์วันที่ด้วย
            footer = "โดนหมดเวลาเมื่อ"
            desc = (f"# {E607} เเจ้งการโดนหมดเวลา\n\n"
                    f"พี่โดนหมดเวลาจากดิส **{guild.name}** เนื่องจากพี่พิมพ์คำต้องห้ามเยอะเกินกำหนดน้าา "
                    f"พี่โดนไป **{m}** นาที เดี๋ยวตอน {discord.utils.format_dt(until, fmt)} ปลด")
        else:
            action, footer = ("ถูกเตะจาก", "ถูกเตะเมื่อ") if mode == "kick" else ("ถูกเเบนจาก", "ถูกเเบนเมื่อ")
            desc = (f"พี่{action}ดิส **{guild.name}** (`{guild.id}`) เนื่องจากพิมพ์คำต้องห้ามเกินข้อกำหนด "
                    f"คำที่พี่พิมพ์ไป **{hit}** ไว้มีโอกาสเราค่อยเจอกันใหม่นะคะพี่ {E729}")

        dm = discord.Embed(description=desc, color=WHITE, timestamp=discord.utils.utcnow())
        dm.set_thumbnail(url=member.display_avatar.url)
        dm.set_footer(text=footer)
        try:
            await member.send(embed=dm)
        except discord.HTTPException:
            pass  # ปิด DM ไว้ ก็ลงโทษต่อ

        reason = f"forbidden_words: {hit}"
        try:
            if mode == "kick":
                await member.kick(reason=reason)
            elif mode == "ban":
                await guild.ban(member, reason=reason, delete_message_days=0)
            else:
                await member.timeout(timedelta(minutes=st["timeout"]), reason=reason)
        except discord.HTTPException:
            return False
        return True


async def setup(bot: commands.Bot):
    await bot.add_cog(ForbiddenWordsCog(bot))
