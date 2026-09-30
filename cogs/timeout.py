import discord
from discord import app_commands
from discord.ext import commands
import datetime

class TimeoutCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="timeout", description="สั่งหมดเวลาสมาชิกชั่วคราว (ชั่วโมง)")
    @app_commands.describe(
        target="คนที่ต้องการให้หมดเวลา",
        hours="ระยะเวลาที่โดนหมดเวลา (ชั่วโมง สูงสุด 330)",
        reason="เหตุผลที่หมดเวลา"
    )
    # จำกัดระยะเวลา 1 ถึง 330 ชั่วโมง
    @app_commands.rename(target="target", hours="time", reason="reason")
    async def timeout_command(
        self, 
        interaction: discord.Interaction, 
        target: discord.Member, 
        hours: app_commands.Range[int, 1, 330], 
        reason: str
    ):
        GIF_URL = "https://cdn.discordapp.com/attachments/1502986327367487539/1554860892531728484/092fe20671b454b981794766ce0c4f4c.gif?backend=b2&ex=6abe6c8c&is=6abd1b0c&hm=c76c92856690af7d59fa2617ee641452939b296aa000587cc88267dddbb00e77&"

        # 1. เช็คสิทธิ์ของผู้ใช้คำสั่ง (ต้องเป็น Admin เท่านั้น)
        if not interaction.user.guild_permissions.administrator:
            embed_no_permission = discord.Embed(
                description="<a:1000035604:1554847795524141216> คุณไม่มีสิทธิ์ใช้คำสั่งนี้นะ!!",
                color=0xFFFFFF
            )
            # ส่งแบบ ephemeral (เห็นเฉพาะคนใช้ 2ต่อ2)
            await interaction.response.send_message(embed=embed_no_permission, ephemeral=True)
            return

        # 2. เช็คว่าบอทมีสิทธิ์ระงับผู้ใช้คนนี้หรือไม่ (ยศสูงกว่าบอท หรือบอทไม่มีสิทธิ์)
        bot_member = interaction.guild.me
        if not bot_member.guild_permissions.moderate_members or target.top_role >= bot_member.top_role or target.id == interaction.guild.owner_id:
            embed_bot_no_perm = discord.Embed(
                description="<a:1000035729:1554863632528052315> บอทไม่มีสิทธิ์แบนคนนี้",
                color=0xFFFFFF
            )
            # ส่งแบบ ephemeral (เห็นเฉพาะคนใช้ 2ต่อ2)
            await interaction.response.send_message(embed=embed_bot_no_perm, ephemeral=True)
            return

        # คำนวณเวลา
        now = datetime.datetime.now(datetime.timezone.utc)
        duration_delta = datetime.timedelta(hours=hours)
        until_time = now + duration_delta

        try:
            # ดำเนินการ Timeout
            await target.timeout(duration_delta, reason=reason)
            
            # คำนวณ Timestamp สำหรับ Discord
            until_timestamp = int(until_time.timestamp())

            # สร้าง Embed ผลลัพธ์สำหรับส่งให้ทุกคนเห็น
            embed = discord.Embed(
                title="<a:1000035725:1554844594175483904> Timeout",
                color=0xFFFFFF
            )
            embed.set_thumbnail(url=GIF_URL)
            
            description_text = (
                f"<a:1000035726:1554859496894111744> timeout by : {interaction.user.mention}\n\n"
                f"<a:1000035727:1554859928957755393> target : {target.mention}\n\n"
                f"<a:1000035728:1554860189125967894> time : ({hours} hour)\n\n"
                f"<a:1000035608:1554844998506123274> reason : {reason}\n\n"
                f"⏱️ **สิ้นสุดเมื่อ:** <t:{until_timestamp}:F> (<t:{until_timestamp}:R>)"
            )
            
            embed.description = description_text

            # ส่งให้ทุกคนในช่องเห็น
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            embed_error = discord.Embed(
                description=f"<a:1000035729:1554863632528052315> เกิดข้อผิดพลาด: {str(e)}",
                color=0xFFFFFF
            )
            await interaction.response.send_message(embed=embed_error, ephemeral=True)

async def setup(bot):
    await bot.add_cog(TimeoutCog(bot))
