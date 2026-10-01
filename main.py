import os
import asyncio
import traceback
import discord
from discord.ext import commands, tasks
from keep_alive import keep_alive
from cogs.verify import NumberVerifyView, Button3SecVerifyView, AnimalVerifyView, AgeVerifyView, GameVerifyView

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True  # ให้ระบบ log / anti / เกม อ่านเนื้อหาข้อความได้ (ต้องเปิดใน Developer Portal ด้วย)

bot = commands.Bot(command_prefix="!", intents=intents)


@tasks.loop(minutes=1)
async def update_status():
    await bot.wait_until_ready()
    total_members = sum(guild.member_count for guild in bot.guilds)
    total_guilds = len(bot.guilds)
    activity = discord.Game(name=f"สมาชิก {total_members} คน | {total_guilds} เซิร์ฟเวอร์")
    await bot.change_presence(activity=activity)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # ลงทะเบียน Persistent Views เพื่อรองรับ Data Persistence เวลารีสตาร์ท
    bot.add_view(NumberVerifyView())
    bot.add_view(Button3SecVerifyView())
    bot.add_view(AnimalVerifyView())
    bot.add_view(AgeVerifyView())
    bot.add_view(GameVerifyView())

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    if not update_status.is_running():
        update_status.start()


async def main():
    # โหลดทุก cog โดยถ้าไฟล์ไหนพัง (เช่นขาดไลบรารี) จะข้ามไฟล์นั้น บอทตัวอื่นยังทำงานต่อ
    for filename in sorted(os.listdir('./cogs')):
        if filename.endswith('.py') and not filename.startswith('_'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f"Loaded Cog: {filename[:-3]}")
            except Exception:
                print(f"!!! โหลด cog '{filename[:-3]}' ไม่สำเร็จ (ข้ามไป):")
                traceback.print_exc()

    keep_alive()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN is missing!")
        return
    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
