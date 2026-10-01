import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import db

FILE_NAME = "bot_backup.json"
INTERVAL_MIN = 2   # เช็คทุกกี่นาที (ส่งไฟล์ใหม่เฉพาะตอนข้อมูลเปลี่ยน)
KEEP = 5           # เก็บไฟล์สำรองล่าสุดกี่ไฟล์


def dump() -> dict:
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        out = {}
        for name, sql in cur.fetchall():
            cur.execute(f'SELECT * FROM "{name}"')
            cols = [d[0] for d in cur.description]
            out[name] = {"sql": sql, "cols": cols, "rows": [list(r) for r in cur.fetchall()]}
        return out
    finally:
        conn.close()


def total_rows(data: dict) -> int:
    return sum(len(t["rows"]) for t in data.values())


def digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def restore(data: dict):
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        for name, t in data.items():
            sql = t["sql"]
            if sql and "IF NOT EXISTS" not in sql[:60].upper():
                sql = sql.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
            cur.execute(sql)
            if not t["rows"]:
                continue
            cols = ", ".join(f'"{c}"' for c in t["cols"])
            ph = ", ".join("?" * len(t["cols"]))
            cur.executemany(f'INSERT OR REPLACE INTO "{name}" ({cols}) VALUES ({ph})', t["rows"])
        conn.commit()
    finally:
        conn.close()


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
        self.last_hash = None
        self.started = False

    async def target(self):
        cid = os.getenv("BACKUP_CHANNEL_ID", "").strip()
        if cid.isdigit():
            return self.bot.get_channel(int(cid)) or await self.bot.fetch_channel(int(cid))
        info = await self.bot.application_info()
        owner = info.team.owner if info.team else info.owner
        return await owner.create_dm()

    async def backups(self, ch):
        """ข้อความสำรองของบอท เรียงใหม่ → เก่า"""
        out = []
        async for m in ch.history(limit=200):
            if m.author.id == self.bot.user.id and any(a.filename == FILE_NAME for a in m.attachments):
                out.append(m)
        return out

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
        local = dump()
        if total_rows(local) > 0:  # มีข้อมูลอยู่แล้ว ไม่ทับ
            self.last_hash = digest(local)
            print(f"[backup] มีข้อมูลในไฟล์อยู่แล้ว ({total_rows(local)} แถว) ไม่ต้องกู้คืน")
            return
        ch = await self.target()
        msgs = await self.backups(ch)
        if not msgs:
            print("[backup] ไฟล์ข้อมูลว่าง และยังไม่มีไฟล์สำรองให้กู้คืน")
            return
        att = next(a for a in msgs[0].attachments if a.filename == FILE_NAME)
        data = json.loads((await att.read()).decode("utf-8"))
        restore(data)
        clear_caches()
        self.last_hash = digest(dump())
        print(f"[backup] กู้คืนข้อมูลสำเร็จ ({total_rows(data)} แถว)")

    async def save(self, force: bool = False):
        data = dump()
        if total_rows(data) == 0:  # ห้ามส่งไฟล์ว่างไปทับของดี
            return "empty"
        h = digest(data)
        if not force and h == self.last_hash:
            return "same"
        ch = await self.target()
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        await ch.send(f"สำรองข้อมูล {stamp} ({total_rows(data)} แถว)",
                      file=discord.File(io.BytesIO(raw), filename=FILE_NAME))
        self.last_hash = h
        for old in (await self.backups(ch))[KEEP:]:  # ลบไฟล์เก่าเกินที่เก็บ
            try:
                await old.delete()
            except discord.HTTPException:
                pass
        return "saved"

    @tasks.loop(minutes=INTERVAL_MIN)
    async def loop(self):
        try:
            await self.save()
        except Exception as e:
            print(f"[backup] สำรองไม่สำเร็จ: {e}")

    @app_commands.command(name="backup", description="สำรองข้อมูลทันที (เจ้าของบอทเท่านั้น)")
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
