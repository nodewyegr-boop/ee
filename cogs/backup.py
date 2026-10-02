import base64
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import db

PREFIX = "bot_backup_"        # bot_backup_<ชุด>_<ลำดับ>.json  และ bot_backup_<ชุด>_done.json
LEGACY_NAME = "bot_backup.json"
PART_LIMIT = 6 * 1024 * 1024  # ขนาด JSON ต่อไฟล์ (ต่ำกว่าลิมิตอัปโหลดของ Discord)
INTERVAL_MIN = 2              # เช็คทุกกี่นาที
KEEP_SETS = 2                 # เก็บชุดสำรองล่าสุดกี่ชุด


def enc(v):
    return {"__b64__": base64.b64encode(bytes(v)).decode()} if isinstance(v, (bytes, bytearray, memoryview)) else v


def dec(v):
    return base64.b64decode(v["__b64__"]) if isinstance(v, dict) and "__b64__" in v else v


def table_list(conn):
    cur = conn.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return cur.fetchall()


def count_rows() -> int:
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        total = 0
        for name, _ in table_list(conn):
            cur.execute(f'SELECT COUNT(*) FROM "{name}"')
            total += cur.fetchone()[0]
        return total
    finally:
        conn.close()


def iter_parts():
    """อ่านฐานข้อมูลทีละแถว แล้วแบ่งเป็นก้อน JSON ไม่เกิน PART_LIMIT (ไม่โหลดทั้งก้อนเข้าหน่วยความจำ)"""
    conn = db.get_connection()
    try:
        part, size = {}, 0
        for name, sql in table_list(conn):
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM "{name}"')
            cols = [d[0] for d in cur.description]
            for row in cur:
                r = [enc(v) for v in row]
                est = len(json.dumps(r, ensure_ascii=False)) + 2
                if size + est > PART_LIMIT and size > 0:
                    yield {"v": 2, "tables": part}
                    part, size = {}, 0
                t = part.setdefault(name, {"sql": sql, "cols": cols, "rows": []})
                t["rows"].append(r)
                size += est
        if part:
            yield {"v": 2, "tables": part}
    finally:
        conn.close()


def apply_data(data: dict):
    """กู้คืนจากข้อมูล 1 ก้อน (รองรับรูปแบบเก่า v1 และใหม่ v2)"""
    tables = data["tables"] if data.get("v") == 2 else data
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        for name, t in tables.items():
            sql = t["sql"]
            if sql and "IF NOT EXISTS" not in sql[:60].upper():
                sql = sql.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
            cur.execute(sql)
            if t["rows"]:
                cols = ", ".join(f'"{c}"' for c in t["cols"])
                ph = ", ".join("?" * len(t["cols"]))
                cur.executemany(f'INSERT OR REPLACE INTO "{name}" ({cols}) VALUES ({ph})',
                                [[dec(v) for v in row] for row in t["rows"]])
        conn.commit()
    finally:
        conn.close()


def db_signature():
    path = getattr(db, "db_name", None)
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except Exception:
        return None


def db_size_mb() -> float:
    sig = db_signature()
    return (sig[1] / 1_048_576) if sig else 0.0


def clear_caches():
    """ล้างแคชของ cog อื่น เพื่อให้อ่านข้อมูลที่เพิ่งกู้คืนมาใหม่"""
    for mod in ("cogs.anti_system", "cogs.forbidden_words"):
        m = sys.modules.get(mod)
        if m is not None and hasattr(m, "CACHE"):
            m.CACHE.clear()


def emb(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=discord.Color.from_rgb(255, 255, 255))


class BackupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_sig = None
        self.last_save = 0.0
        self.started = False

    async def target(self):
        cid = os.getenv("BACKUP_CHANNEL_ID", "").strip()
        if cid.isdigit():
            return self.bot.get_channel(int(cid)) or await self.bot.fetch_channel(int(cid))
        info = await self.bot.application_info()
        owner = info.team.owner if info.team else info.owner
        return await owner.create_dm()

    async def scan(self, ch):
        """คืน {ชุด: {"parts": {i: attachment}, "done": attachment|None, "msgs": [message]}} และไฟล์เก่า (v1)"""
        sets, legacy = {}, []
        async for m in ch.history(limit=1000):
            if m.author.id != self.bot.user.id:
                continue
            for a in m.attachments:
                n = a.filename
                if n == LEGACY_NAME:
                    legacy.append(a)
                elif n.startswith(PREFIX) and n.endswith(".json"):
                    body = n[len(PREFIX):-5]            # <ชุด>_<ลำดับ|done>
                    sid, _, tail = body.rpartition("_")
                    s = sets.setdefault(sid, {"parts": {}, "done": None, "msgs": []})
                    s["msgs"].append(m)
                    if tail == "done":
                        s["done"] = a
                    elif tail.isdigit():
                        s["parts"][int(tail)] = a
        return sets, legacy

    @commands.Cog.listener()
    async def on_ready(self):
        if self.started:
            return
        self.started = True
        try:
            await self.try_restore()
        except Exception as e:
            print(f"[backup] กู้คืนไม่สำเร็จ: {e}")
        if not self.loop.is_running():
            self.loop.start()

    async def try_restore(self):
        rows = count_rows()
        if rows > 0:  # มีข้อมูลอยู่แล้ว ไม่ทับ
            self.last_sig = db_signature()
            print(f"[backup] มีข้อมูลในไฟล์อยู่แล้ว ({rows} แถว) ไม่ต้องกู้คืน")
            return
        ch = await self.target()
        sets, legacy = await self.scan(ch)
        # ชุดใหม่สุดที่ครบทุกไฟล์ (ชื่อชุด = เวลา จึงเรียงตามตัวเลขได้)
        for sid in sorted(sets, reverse=True):
            s = sets[sid]
            if not s["done"]:
                continue
            n = json.loads((await s["done"].read()).decode("utf-8"))["parts"]
            if all(i in s["parts"] for i in range(1, n + 1)):
                total = 0
                for i in range(1, n + 1):
                    data = json.loads((await s["parts"][i].read()).decode("utf-8"))
                    apply_data(data)
                    total += sum(len(t["rows"]) for t in data["tables"].values())
                clear_caches()
                self.last_sig = db_signature()
                print(f"[backup] กู้คืนข้อมูลสำเร็จ ({total} แถว จาก {n} ไฟล์)")
                return
        if legacy:  # ไฟล์สำรองรูปแบบเก่า
            data = json.loads((await legacy[0].read()).decode("utf-8"))
            apply_data(data)
            clear_caches()
            self.last_sig = db_signature()
            print("[backup] กู้คืนข้อมูลสำเร็จ (ไฟล์สำรองรูปแบบเก่า)")
            return
        print("[backup] ไฟล์ข้อมูลว่าง และยังไม่มีไฟล์สำรองให้กู้คืน")

    async def save(self, force: bool = False):
        if count_rows() == 0:  # ห้ามส่งไฟล์ว่างไปทับของดี
            return "empty"
        sig = db_signature()
        if not force:
            if sig is not None and sig == self.last_sig:
                return "same"
            # ฐานข้อมูลยิ่งใหญ่ ยิ่งสำรองห่างขึ้น (กันส่งไฟล์ใหญ่ถี่ๆ)
            if time.time() - self.last_save < min(6 * 3600, 120 + db_size_mb() * 60):
                return "wait"
        ch = await self.target()
        sid = str(int(time.time()))
        n = 0
        for part in iter_parts():
            n += 1
            raw = json.dumps(part, ensure_ascii=False).encode("utf-8")
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            await ch.send(f"สำรองข้อมูล {stamp} (ไฟล์ {n})",
                          file=discord.File(io.BytesIO(raw), filename=f"{PREFIX}{sid}_{n}.json"))
        await ch.send(f"สำรองข้อมูลครบ {n} ไฟล์",
                      file=discord.File(io.BytesIO(json.dumps({"parts": n}).encode()), filename=f"{PREFIX}{sid}_done.json"))
        self.last_sig, self.last_save = sig, time.time()

        # ลบชุดเก่าเกินที่เก็บ (รวมไฟล์รูปแบบเก่า)
        sets, legacy = await self.scan(ch)
        for old_sid in sorted(sets, reverse=True)[KEEP_SETS:]:
            for m in sets[old_sid]["msgs"]:
                try:
                    await m.delete()
                except discord.HTTPException:
                    pass
        return "saved"

    @tasks.loop(minutes=INTERVAL_MIN)
    async def loop(self):
        try:
            await self.save()
        except Exception as e:
            print(f"[backup] สำรองไม่สำเร็จ: {e}")

    @app_commands.command(name="backup_now", description="สำรองข้อมูลทันที (เจ้าของบอทเท่านั้น)")
    async def backup_now(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message(embed=emb("ไม่ได้น้าา เฉพาะเจ้าของบอทเท่านั้น"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            r = await self.save(force=True)
        except Exception as e:
            return await interaction.followup.send(embed=emb(f"สำรองไม่สำเร็จ: {e}"), ephemeral=True)
        msg = {"saved": "สำรองข้อมูลเรียบร้อยเเล้วน้าา", "empty": "ตอนนี้ยังไม่มีข้อมูลให้สำรองน้าา"}.get(r, "ok")
        await interaction.followup.send(embed=emb(msg), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
