import os
import time

import discord
from discord import app_commands
from discord.ext import commands

from database import db

# ห้อง (หรือผู้ใช้) ที่รับข้อเสนอ — เปลี่ยนได้ด้วยตัวแปร OFFER_CHANNEL_ID
DEST_ID = int(os.getenv("OFFER_CHANNEL_ID") or 1488612764854390846)
COOLDOWN = 3600  # วินาที (1 ชั่วโมง)
WHITE = discord.Color.from_rgb(255, 255, 255)
E606 = "<a:1000035606:1554848463320129567>"
E790 = "<:1000035790:1554970748232147004>"


def emb(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=WHITE)


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
    q("CREATE TABLE IF NOT EXISTS of_cooldown (user_id INTEGER PRIMARY KEY, last_at INTEGER)")


def wait_until(uid: int) -> int:
    """คืนเวลา (unix) ที่ใช้ได้อีกครั้ง ถ้ายังไม่ถึงเวลา; ถ้าใช้ได้แล้วคืน 0"""
    row = q("SELECT last_at FROM of_cooldown WHERE user_id=?", (uid,), one=True)
    if row and row[0] + COOLDOWN > time.time():
        return int(row[0] + COOLDOWN)
    return 0


class OfferModal(discord.ui.Modal, title="เสนอระบบบอท"):
    text = discord.ui.TextInput(
        label="สิ่งที่ต้องการเสนอ", style=discord.TextStyle.paragraph, max_length=1000,
        placeholder="พิมพ์ระบบหรือสิ่งที่อยากให้เพิ่มได้เลยย")

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        again = wait_until(user.id)  # กันกดค้างฟอร์มไว้แล้วส่งซ้ำ
        if again:
            return await interaction.response.send_message(
                embed=emb(f"{E790} เสนอได้ 1 รอบต่อ 1 ชั่วโมงน้าา ใช้ได้อีกครั้ง <t:{again}:R>"), ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        now = int(time.time())
        e = discord.Embed(
            description=("# มีคนเเจ้งปัญหา\n\n"
                         f"**สิ่งที่เเจ้งมา**\n```{self.text.value.strip().replace('```', chr(39) * 3)}```\n"
                         f"**เวลาที่เเจ้งมา**\n<t:{now}:F> (<t:{now}:R>)\n\n"
                         f"**คนเเจ้งคือใคร**\n{user.mention} ({user.id})"),
            color=WHITE, timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=user.display_avatar.url)
        e.set_footer(text="เเจ้งเมื่อ")

        bot = interaction.client
        try:
            try:
                dest = bot.get_channel(DEST_ID) or await bot.fetch_channel(DEST_ID)
            except discord.HTTPException:
                dest = await bot.fetch_user(DEST_ID)  # ถ้า id นี้เป็นคน ส่งเข้า DM
            await dest.send(embed=e)
        except discord.HTTPException:
            return await interaction.followup.send(
                embed=emb(f"{E790} ส่งข้อเสนอไม่สำเร็จน้า ลองใหม่อีกทีนะ (ยังไม่นับเป็นรอบ)"), ephemeral=True)

        q("INSERT OR REPLACE INTO of_cooldown VALUES (?, ?)", (user.id, now))
        await interaction.followup.send(
            embed=emb(f"{E606} ส่งข้อเสนอให้เเล้วน้าา ขอบคุณที่ช่วยเสนอนะ เสนอรอบหน้าได้ <t:{now + COOLDOWN}:R>"),
            ephemeral=True)


class OfferCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()

    @app_commands.command(name="offer", description="เสนอระบบบอทต่างๆ (ทุกคนใช้ได้)")
    async def offer(self, interaction: discord.Interaction):
        again = wait_until(interaction.user.id)
        if again:
            return await interaction.response.send_message(
                embed=emb(f"{E790} เสนอได้ 1 รอบต่อ 1 ชั่วโมงน้าา ใช้ได้อีกครั้ง <t:{again}:R>"), ephemeral=True)
        await interaction.response.send_modal(OfferModal())


async def setup(bot: commands.Bot):
    await bot.add_cog(OfferCog(bot))
