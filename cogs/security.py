import asyncio
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

WHITE = discord.Color.from_rgb(255, 255, 255)

E_TITLE = "<a:1000035786:1554968314135191682>"
E604 = "<a:1000035604:1554847795524141216>"
E607 = "<a:1000035607:1554874918632562788>"
E725 = "<a:1000035725:1554844594175483904>"
E744 = "<a:1000035744:1554884849406451762>"
E_DENY = "<:1000035790:1554970748232147004>"
E_DONE = "<a:1000035729:1554863632528052315>"

MIN_ACCOUNT_AGE = timedelta(days=7)
RUNNING: set = set()  # กันกดเริ่มซ้อนในเซิร์ฟเวอร์เดียวกัน


def emb(desc: str) -> discord.Embed:
    return discord.Embed(description=desc, color=WHITE)


def intro_embed() -> discord.Embed:
    return emb(
        f"# ระบบป้องกันด่วน {E_TITLE}\n\n"
        f"{E604} ระบบนี้ เมื่อกดปุ่มด้านล่าง น้องจะเตะบอทที่ไม่มีเครื่องหมายยืนยันออก "
        "เตะคนที่ไม่มีโปรไฟล์ เตะบัญชีที่มีอายุไม่ถึง 7 วัน\n\n"
        f"ระบบนี้ใช้ได้เเค่หัวดิสเท่านั้น {E607}"
    )


class StartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    @discord.ui.button(label="เริ่ม", style=discord.ButtonStyle.secondary, emoji=discord.PartialEmoji.from_str(E725))
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild

        # ไม่ใช่หัวดิส (เจ้าของเซิร์ฟเวอร์)
        if interaction.user.id != guild.owner_id:
            return await interaction.response.edit_message(
                embed=emb(f"{E_DENY} ไม่ได้น้าา พี่ไม่ใช่หัวดิสใช้ไม่ด้ายยย"), view=None)

        me = guild.me
        if not me.guild_permissions.kick_members:
            return await interaction.response.edit_message(
                embed=emb(f"{E_DENY} น้องไม่มีสิทธิ์ **เตะสมาชิก** พี่ๆให้สิทธิ์น้องก่อนน"), view=None)
        if guild.id in RUNNING:
            return await interaction.response.edit_message(
                embed=emb(f"{E744} กำลังทำงานอยู่น้าา รอแปปนึง"), view=None)

        RUNNING.add(guild.id)
        await interaction.response.edit_message(
            embed=emb(f"{E744} กำลังเริ่มระบบ..รอแปปน้าาพี่"), view=None)
        try:
            humans, bots = await self.purge(guild)
            result = emb(
                f"{E_DONE} เสร็จเเล้วน้าาพี่ หนูเตะบัญชีเเปลกไปทั้งหมด **{humans}** "
                f"หนูเตะบอทไป **{bots}** (บอทไม่มีเครื่องหมายยืนยัน)")
        except Exception:
            result = emb(f"{E_DENY} มีบางอย่างผิดพลาดระหว่างทำงาน ลองใหม่อีกทีน้าา")
        finally:
            RUNNING.discard(guild.id)

        try:
            await interaction.edit_original_response(embed=result)
        except discord.HTTPException:
            # โทเคนของ interaction หมดอายุ (งานนาน) ส่งผลลัพธ์ไปที่ห้องแทน
            if interaction.channel:
                await interaction.channel.send(content=interaction.user.mention, embed=result)

    async def purge(self, guild: discord.Guild):
        me = guild.me
        now = discord.utils.utcnow()
        humans = bots = 0

        async for m in guild.fetch_members(limit=None):
            # ข้ามตัวบอทเอง / หัวดิส / คนที่ยศสูงกว่าหรือเท่าบอท / แอดมิน
            if m.id == me.id or m.id == guild.owner_id or m.top_role >= me.top_role:
                continue
            if m.guild_permissions.administrator:
                continue

            if m.bot:
                if m.public_flags.verified_bot:
                    continue
                reason, is_bot = "security_system: บอทไม่มีเครื่องหมายยืนยัน", True
            elif m.avatar is None:
                reason, is_bot = "security_system: ไม่มีโปรไฟล์", False
            elif now - m.created_at < MIN_ACCOUNT_AGE:
                reason, is_bot = "security_system: บัญชีอายุไม่ถึง 7 วัน", False
            else:
                continue

            try:
                await m.kick(reason=reason)
            except discord.HTTPException:
                continue
            if is_bot:
                bots += 1
            else:
                humans += 1
            await asyncio.sleep(0.6)  # กัน rate limit

        return humans, bots


class SecurityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="security_system", description="ระบบป้องกันด่วน (หัวดิสเท่านั้น)")
    @app_commands.guild_only()
    async def security_system(self, interaction: discord.Interaction):
        # ทุกคนใช้คำสั่งได้ แต่กดเริ่มได้เฉพาะหัวดิส (เห็นคนเดียว เพื่อให้ embed เปลี่ยนเฉพาะของคนกด)
        await interaction.response.send_message(embed=intro_embed(), view=StartView(), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SecurityCog(bot))
