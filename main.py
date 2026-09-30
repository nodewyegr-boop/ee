import os
import asyncio
import discord
from discord.ext import commands, tasks
from keep_alive import keep_alive

# ตั้งค่า Intent
intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# อัปเดตสถานะบอทแบบเรียลไทม์
@tasks.loop(minutes=1)
async def update_status():
    await bot.wait_until_ready()
    total_members = sum(guild.member_count for guild in bot.guilds)
    total_guilds = len(bot.guilds)
    
    # ขึ้นว่า "กำลังเล่น ..."
    activity = discord.Game(name=f"มีสมาชิก {total_members} คน | {total_guilds} เซิร์ฟเวอร์")
    await bot.change_presence(activity=activity)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    
    # ซิงค์ Slash Commands
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")
        
    if not update_status.is_running():
        update_status.start()

async def main():
    # โหลดไฟล์ระบบต่างๆ ในโฟลเดอร์ cogs
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')
            print(f"Loaded Cog: {filename[:-3]}")
            
    # เรียกใช้ keep_alive สำหรับ Render
    keep_alive()
    
    # ดึง Token จาก Environment Variable ใน Render
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN is missing in Environment Variables!")
        return
        
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
