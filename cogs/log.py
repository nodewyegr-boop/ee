# cogs/log.py  —  ไฟล์เดียวจบ ระบบ /log (log all)
# เก็บห้อง log ใน database.py เดิม (ใช้ตาราง verify_panels, system_type="log") ไม่ต้องแก้ไฟล์อื่น
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)
LOG_CHANNEL_NAME = "ȴⰙƓ"

NO = "<a:1000035743:1554882610134524034>"
OK = "<a:1000035763:1554920997382262874>"
E_TITLE = "<a:1000035608:1554844998506123274>"
E_A = "<a:1000035767:1554921960838926417>"   # บรรทัดที่ 1
E_B = "<a:1000035762:1554919569682989166>"   # บรรทัดที่ 2
E_C = "<a:1000035760:1554908193174589581>"   # บรรทัดที่ 3
E_D = "<a:1000035604:1554847795524141216>"   # บรรทัดที่ 4

A = discord.AuditLogAction


def log_embed(title: str, lines: list, thumb: Optional[str] = None, footer: str = "เมื่อ", image: Optional[str] = None) -> discord.Embed:
    e = discord.Embed(
        description=f"# {E_TITLE} {title} {E_TITLE}\n\n" + "\n\n".join(lines),
        color=WHITE,
        timestamp=discord.utils.utcnow(),  # แสดงเวลาเล็กๆ ใต้ embed
    )
    if thumb:
        e.set_thumbnail(url=thumb)  # โปรไฟล์เล็กๆ ขวาบน
    if image:
        e.set_image(url=image)
    e.set_footer(text=footer)
    return e


def mention(obj) -> str:
    if obj is None:
        return "ไม่ทราบ"
    return getattr(obj, "mention", None) or f"<@{obj.id}>"


def avatar(obj) -> Optional[str]:
    a = getattr(obj, "display_avatar", None)
    return a.url if a else None


def dv(entry: discord.AuditLogEntry, name: str):
    """ดึงค่าจาก audit log (before ก่อน ถ้าไม่มีค่อย after)"""
    for side in (entry.before, entry.after):
        try:
            v = getattr(side, name)
            if v is not None:
                return v
        except AttributeError:
            pass
    return None


_NA = object()


def pair(entry: discord.AuditLogEntry, name: str):
    """คืน (ค่าเดิม, ค่าใหม่) ถ้าฟิลด์นี้ถูกเปลี่ยนใน audit log ไม่งั้นคืน None"""
    b = getattr(entry.before, name, _NA)
    a = getattr(entry.after, name, _NA)
    if b is _NA and a is _NA:
        return None
    return (None if b is _NA else b, None if a is _NA else a)


def roles_text(roles) -> str:
    return " ".join(f"<@&{r.id}>" for r in roles) or "ไม่ทราบ"


def trunc(s: str, n: int = 900) -> str:
    return s if len(s) <= n else s[:n] + "…"


class LogCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ───────── helpers ─────────
    def log_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        row = db.get_panel(guild.id, "log")
        return guild.get_channel(row[0]) if row else None

    async def send(self, guild: discord.Guild, embed: discord.Embed):
        ch = self.log_channel(guild)
        if ch is None:
            return
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    # ───────── /log ─────────
    @app_commands.command(name="log", description="ระบบlog all (แอดมินเท่านั้น)")
    @app_commands.guild_only()
    async def log(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            e = discord.Embed(description=f"{NO} ไม่ได้น้าา พี่ไม่ใช่แอดมิน", color=WHITE)
            return await interaction.response.send_message(embed=e, ephemeral=True)

        guild = interaction.guild
        existing = self.log_channel(guild)
        if existing:
            e = discord.Embed(description=f"{OK} หนูสร้างlogให้พี่เเล้วน้าาา {existing.mention}", color=WHITE)
            return await interaction.response.send_message(embed=e, ephemeral=True)

        me = guild.me
        if not (me.guild_permissions.manage_channels and me.guild_permissions.view_audit_log):
            e = discord.Embed(
                description=f"{NO} น้องต้องมีสิทธิ์ **จัดการช่อง** กับ **ดูบันทึกกิจกรรม** ก่อนน้าา",
                color=WHITE)
            return await interaction.response.send_message(embed=e, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
        }
        # วางไว้ล่างสุด: ท้ายหมวดหมู่สุดท้าย (ถ้าไม่มีหมวดหมู่ ก็ท้ายสุดของเซิร์ฟเวอร์)
        category = guild.categories[-1] if guild.categories else None
        try:
            channel = await guild.create_text_channel(
                LOG_CHANNEL_NAME, category=category, overwrites=overwrites,
                reason=f"/log โดย {interaction.user}")
            await channel.edit(position=len(category.channels) if category else len(guild.channels))
        except discord.HTTPException:
            e = discord.Embed(description=f"{NO} สร้างห้องไม่สำเร็จน้า ลองใหม่อีกทีนะ", color=WHITE)
            return await interaction.followup.send(embed=e, ephemeral=True)

        db.save_panel(guild.id, "log", channel.id, 0)
        e = discord.Embed(description=f"{OK} หนูสร้างlogให้พี่เเล้วน้าาา {channel.mention}", color=WHITE)
        await interaction.followup.send(embed=e, ephemeral=True)

    # ───────── ข้อความถูกลบ ─────────
    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        log_ch = self.log_channel(guild)
        if log_ch is None or payload.channel_id == log_ch.id:
            return

        msg = payload.cached_message
        if msg is not None and msg.author.bot:
            return

        if msg is not None:
            content = msg.content or ""
            if msg.attachments:
                content += ("\n" if content else "") + "\n".join(f"📎 {a.filename}" for a in msg.attachments)
            if content:
                content = trunc(content)
            elif not self.bot.intents.message_content:
                content = "*(อ่านเนื้อหาไม่ได้ ยังไม่ได้เปิด message_content ใน main.py)*"
            else:
                content = "*(ไม่มีข้อความ เช่น ส่งเป็นสติกเกอร์/embed อย่างเดียว)*"
            owner = msg.author
            # หาคนลบจาก audit log (ถ้าไม่มี = เจ้าของลบเอง)
            await asyncio.sleep(1.5)
            deleter = await self.find_deleter(guild, payload.channel_id, owner.id) or owner
        else:
            content = "*(ข้อความเก่ากว่าที่บอทเห็น เลยไม่ทราบเนื้อหา)*"
            owner = deleter = None

        e = log_embed("มีคนลบข้อความ", [
            f"{E_A} ข้อความที่ลบ: {content}",
            f"{E_B} ข้อความเป็นของ: {mention(owner)}",
            f"{E_C} คนที่ลบ: {mention(deleter)}",
            f"{E_D} ห้องที่ลบ: <#{payload.channel_id}>",
        ], thumb=avatar(deleter), footer="ถูกลบเมื่อ")
        await self.send(guild, e)

    async def find_deleter(self, guild, channel_id: int, author_id: int):
        if not guild.me.guild_permissions.view_audit_log:
            return None
        try:
            async for en in guild.audit_logs(limit=5, action=A.message_delete):
                if (discord.utils.utcnow() - en.created_at).total_seconds() > 10:
                    break
                ch = getattr(en.extra, "channel", None)
                if en.target.id == author_id and ch is not None and ch.id == channel_id:
                    return en.user
        except discord.HTTPException:
            pass
        return None

    # ───────── คนออก VC ─────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or before.channel is None or after.channel is not None:
            return
        e = log_embed("มีคนออกVC", [
            f"{E_A} คนที่ออก: {member.mention}",
            f"{E_C} ห้องที่ออก: {before.channel.mention}",
        ], thumb=avatar(member), footer="ออกเมื่อ")
        await self.send(member.guild, e)

    # ───────── ทุกอย่างที่ผ่าน Audit Log ─────────
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        guild = entry.guild
        if self.log_channel(guild) is None:
            return
        a, ex, reason = entry.action, entry.user, entry.reason
        tgt = entry.target
        by = lambda label: f"{E_B} {label}: {mention(ex)}"
        why = f"{E_D} เหตุผล: {reason or 'ไม่ได้ระบุ'}"
        thumb = avatar(ex)
        e = None

        if a is A.bot_add:
            e = log_embed("มีการเพิ่มบอทเข้าเซิร์ฟเวอร์", [
                f"{E_A} บอทที่เพิ่ม: {mention(tgt)}", by("คนที่เพิ่ม")],
                avatar(tgt) or thumb, "เพิ่มเมื่อ")
        elif a is A.kick and getattr(tgt, "bot", False):
            e = log_embed("มีการลบบอท", [
                f"{E_A} บอทที่โดนลบ: {mention(tgt)}", by("คนที่ลบ"), why],
                avatar(tgt) or thumb, "ลบเมื่อ")
        elif a is A.kick:
            e = log_embed("มีคนโดนเตะ", [f"{E_A} คนที่โดนเตะ: {mention(tgt)}", by("คนที่เตะ"), why],
                          avatar(tgt) or thumb, "เตะเมื่อ")
        elif a is A.ban:
            e = log_embed("มีคนโดนแบน", [f"{E_A} คนที่โดนแบน: {mention(tgt)}", by("คนที่แบน"), why],
                          avatar(tgt) or thumb, "แบนเมื่อ")
        elif a is A.unban:
            e = log_embed("มีคนโดนปลดแบน", [f"{E_A} คนที่โดนปลดแบน: {mention(tgt)}", by("คนที่ปลด"), why],
                          avatar(tgt) or thumb, "ปลดแบนเมื่อ")
        elif a is A.member_update:
            before = getattr(entry.before, "timed_out_until", None)
            after = getattr(entry.after, "timed_out_until", None)
            if after is not None:
                e = log_embed("มีคนโดนหมดเวลา", [
                    f"{E_A} คนที่โดน: {mention(tgt)}", by("คนที่ให้หมดเวลา"),
                    f"{E_C} หมดเวลาถึง: {discord.utils.format_dt(after, 'F')} ({discord.utils.format_dt(after, 'R')})",
                    why], avatar(tgt) or thumb, "หมดเวลาเมื่อ")
            elif before is not None:
                e = log_embed("มีคนโดนปลดหมดเวลา", [
                    f"{E_A} คนที่โดนปลด: {mention(tgt)}", by("คนที่ปลด"), why],
                    avatar(tgt) or thumb, "ปลดหมดเวลาเมื่อ")
            else:
                nk = pair(entry, "nick")
                if nk is not None and ex is not None and tgt is not None and tgt.id != ex.id:
                    e = log_embed("มีการเปลี่ยนชื่อคนอื่น", [
                        f"{E_A} คนที่โดนเปลี่ยน: {mention(tgt)}", by("คนที่เปลี่ยน"),
                        f"{E_C} ชื่อเดิม: {nk[0] or 'ชื่อบัญชีเดิม'}",
                        f"{E_D} ชื่อใหม่: {nk[1] or 'ชื่อบัญชีเดิม'}"],
                        avatar(tgt) or thumb, "เปลี่ยนเมื่อ")
        elif a is A.member_role_update:
            if ex is not None and ex.id == self.bot.user.id:
                return  # ไม่ log ตอนบอทเราให้ยศเอง (เช่นระบบ verify)
            added_roles = list(entry.after.roles) if hasattr(entry.after, "roles") else []
            removed_roles = list(entry.before.roles) if hasattr(entry.before, "roles") else []
            selfact = ex is not None and tgt is not None and ex.id == tgt.id
            if added_roles:
                if selfact:
                    e = log_embed("มีการให้ยศตัวเอง", [
                        f"{E_A} คนที่ให้ตัวเอง: {mention(ex)}",
                        f"{E_C} ยศที่ได้: {roles_text(added_roles)}"], thumb, "ให้ยศเมื่อ")
                else:
                    e = log_embed("มีการให้ยศคนอื่น", [
                        f"{E_A} คนที่ได้รับยศ: {mention(tgt)}", by("คนที่ให้"),
                        f"{E_C} ยศที่ให้: {roles_text(added_roles)}"], avatar(tgt) or thumb, "ให้ยศเมื่อ")
            elif removed_roles:
                if selfact:
                    e = log_embed("มีการลบยศตัวเอง", [
                        f"{E_A} คนที่ลบ: {mention(ex)}",
                        f"{E_C} ยศที่ลบ: {roles_text(removed_roles)}"], thumb, "ลบยศเมื่อ")
                else:
                    e = log_embed("มีการลบยศคนอื่น", [
                        f"{E_A} คนที่โดนลบยศ: {mention(tgt)}", by("คนที่ลบ"),
                        f"{E_C} ยศที่ลบ: {roles_text(removed_roles)}"], avatar(tgt) or thumb, "ลบยศเมื่อ")
        elif a is A.guild_update:
            titles, lines, image = [], [by("คนที่เปลี่ยน")], None
            nm = pair(entry, "name")
            if nm is not None:
                titles.append("ชื่อเซิร์ฟเวอร์")
                lines += [f"{E_C} ชื่อเดิม: {nm[0]}", f"{E_D} ชื่อใหม่: {nm[1]}"]
            ic = pair(entry, "icon")
            if ic is not None:
                titles.append("โปรไฟล์เซิร์ฟเวอร์")
                lines.append(f"{E_C} เปลี่ยนรูปโปรไฟล์(ไอคอน)เซิร์ฟเวอร์")
                image = ic[1].url if ic[1] else image
            bn = pair(entry, "banner")
            sp = pair(entry, "splash")
            if bn is not None or sp is not None:
                titles.append("ปกเซิร์ฟเวอร์")
                lines.append(f"{E_D} เปลี่ยนปก/แบนเนอร์เซิร์ฟเวอร์")
                new = (bn[1] if bn is not None else None) or (sp[1] if sp is not None else None)
                image = new.url if new else image
            if titles:
                e = log_embed("มีการเปลี่ยน" + " และ".join(titles), lines, thumb, "เปลี่ยนเมื่อ", image)
        elif a is A.webhook_create:
            ch = dv(entry, "channel")
            e = log_embed("มีการสร้างWebhook", [
                f"{E_A} ชื่อ Webhook: {dv(entry, 'name') or 'ไม่ทราบ'}", by("คนที่สร้าง"),
                f"{E_D} ห้อง: {mention(ch) if ch else 'ไม่ทราบ'}"], thumb, "สร้างเมื่อ")
        elif a is A.webhook_delete:
            ch = dv(entry, "channel")
            e = log_embed("มีการลบWebhook", [
                f"{E_A} ชื่อ Webhook: {dv(entry, 'name') or 'ไม่ทราบ'}", by("คนที่ลบ"),
                f"{E_D} ห้อง: {mention(ch) if ch else 'ไม่ทราบ'}"], thumb, "ลบเมื่อ")
        elif a is A.channel_delete:
            is_cat = dv(entry, "type") == discord.ChannelType.category
            e = log_embed("มีการลบหมวดหมู่" if is_cat else "มีการลบห้อง", [
                f"{E_A} {'หมวดหมู่' if is_cat else 'ห้อง'}ที่ลบ: {dv(entry, 'name') or 'ไม่ทราบ'}",
                by("คนที่ลบ")], thumb, "ลบเมื่อ")
        elif a is A.thread_delete:
            e = log_embed("มีการลบเธรด/กระทู้", [
                f"{E_A} เธรดที่ลบ: {dv(entry, 'name') or 'ไม่ทราบ'}", by("คนที่ลบ")], thumb, "ลบเมื่อ")
        elif a is A.role_delete:
            e = log_embed("มีการลบยศ", [
                f"{E_A} ยศที่ลบ: {dv(entry, 'name') or 'ไม่ทราบ'}", by("คนที่ลบ")], thumb, "ลบเมื่อ")
        elif a is A.emoji_delete:
            e = log_embed("มีการลบอีโมจิ", [
                f"{E_A} อีโมจิที่ลบ: {dv(entry, 'name') or 'ไม่ทราบ'}", by("คนที่ลบ")], thumb, "ลบเมื่อ")
        elif a is A.sticker_delete:
            e = log_embed("มีการลบสติกเกอร์", [
                f"{E_A} สติกเกอร์ที่ลบ: {dv(entry, 'name') or 'ไม่ทราบ'}", by("คนที่ลบ")], thumb, "ลบเมื่อ")
        elif a is A.invite_delete:
            e = log_embed("มีการลบลิงก์เชิญ", [
                f"{E_A} โค้ดเชิญที่ลบ: {dv(entry, 'code') or 'ไม่ทราบ'}", by("คนที่ลบ")], thumb, "ลบเมื่อ")
        elif a is A.scheduled_event_delete:
            e = log_embed("มีการลบอีเวนต์", [
                f"{E_A} อีเวนต์ที่ลบ: {dv(entry, 'name') or 'ไม่ทราบ'}", by("คนที่ลบ")], thumb, "ลบเมื่อ")
        elif a is A.message_bulk_delete:
            e = log_embed("มีการลบข้อความหลายข้อความ", [
                f"{E_A} จำนวน: {getattr(entry.extra, 'count', '?')} ข้อความ", by("คนที่ลบ"),
                f"{E_D} ห้องที่ลบ: <#{tgt.id}>"], thumb, "ลบเมื่อ")

        if e is not None:
            await self.send(guild, e)


async def setup(bot: commands.Bot):
    await bot.add_cog(LogCog(bot))
