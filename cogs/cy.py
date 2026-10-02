# cogs/cy.py  —  !cy : บอกว่าบอทอยู่ในเซิร์ฟเวอร์ไหนบ้าง (ใช้ได้เฉพาะในห้องที่กำหนด)
import asyncio

import discord
from discord.ext import commands

CY_CHANNEL_ID = 1487160190678601811
INVITE_MAX_AGE = 86400   # ลิงก์ที่บอทสร้างให้ใช้ได้ 1 วัน (ถ้ามีลิงก์ถาวรอยู่แล้วจะใช้อันนั้นก่อน)
WHITE = discord.Color.from_rgb(255, 255, 255)


async def get_invite(guild: discord.Guild) -> str:
    me = guild.me
    # 1) ใช้ลิงก์ที่มีอยู่แล้ว (ต้องมีสิทธิ์ Manage Server)
    if me is not None and me.guild_permissions.manage_guild:
        try:
            invites = await guild.invites()
            for inv in invites:  # ลิงก์ถาวรก่อน
                if inv.max_age == 0 and not inv.temporary:
                    return inv.url
            if invites:
                return invites[0].url
        except discord.HTTPException:
            pass
    # 2) ไม่มี → สร้างใหม่ในห้องที่บอทสร้างลิงก์ได้
    channels = [guild.rules_channel, guild.system_channel] + list(guild.text_channels)
    for ch in channels:
        if ch is None or not ch.permissions_for(me).create_instant_invite:
            continue
        try:
            inv = await ch.create_invite(max_age=INVITE_MAX_AGE, max_uses=0, unique=False, reason="!cy")
            return inv.url
        except discord.HTTPException:
            continue
    return "ไม่มีลิงก์ (บอทสร้างลิงก์เชิญไม่ได้)"


class CyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.busy = False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (message.author.bot or message.guild is None or message.channel.id != CY_CHANNEL_ID
                or message.content.strip().lower() != "!cy"):
            return
        if self.busy:
            return await message.reply("กำลังรวบรวมอยู่น้า รอแปปนึง", mention_author=False)
        self.busy = True
        try:
            guilds = list(self.bot.guilds)
            note = await message.reply(f"กำลังรวบรวมเซิร์ฟเวอร์ทั้งหมด {len(guilds)} แห่ง...", mention_author=False)
            lines = []
            for g in guilds:
                name = discord.utils.escape_markdown(g.name)
                lines.append(f"**{name}** (`{g.id}`) ({await get_invite(g)})")
                await asyncio.sleep(0.25)   # กัน rate limit

            # แบ่งเป็นหลาย embed (ลิมิต 4096 ตัวอักษรต่อ embed)
            chunks, cur, size = [], [], 0
            for ln in lines:
                if size + len(ln) + 1 > 3800 and cur:
                    chunks.append("\n".join(cur))
                    cur, size = [], 0
                cur.append(ln)
                size += len(ln) + 1
            if cur:
                chunks.append("\n".join(cur))

            embeds = []
            for i, text in enumerate(chunks):
                head = f"# บอทอยู่ในเซิร์ฟเวอร์ทั้งหมด {len(guilds)} แห่ง\n\n" if i == 0 else ""
                embeds.append(discord.Embed(description=head + text, color=WHITE))
            if not embeds:
                embeds = [discord.Embed(description="ตอนนี้บอทยังไม่ได้อยู่ในเซิร์ฟเวอร์ไหนเลย", color=WHITE)]
            for i in range(0, len(embeds), 10):
                await message.channel.send(embeds=embeds[i:i + 10])
            try:
                await note.delete()
            except discord.HTTPException:
                pass
        finally:
            self.busy = False


async def setup(bot: commands.Bot):
    await bot.add_cog(CyCog(bot))
