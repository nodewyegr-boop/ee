import asyncio
import io
import random
import time
import traceback
from collections import Counter, defaultdict
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)

# ───────── อีโมจิ ─────────
E803 = "<a:1000035803:1555025202482516100>"
E847 = "<:1000035847:1555194968770084924>"
E804 = "<a:1000035804:1555025773742526615>"
E739 = "<a:1000035739:1554873266987081742>"
E607 = "<a:1000035607:1554874918632562788>"
E597 = "<a:1000035597:1554848439035240449>"
E767 = "<a:1000035767:1554921960838926417>"
E604 = "<a:1000035604:1554847795524141216>"
E790 = "<:1000035790:1554970748232147004>"
E818 = "<:1000035818:1555201028633268245>"
E836 = "<:1000035836:1555201010903949384>"
E606 = "<a:1000035606:1554848463320129567>"
E728 = "<a:1000035728:1554860189125967894>"
E729 = "<a:1000035729:1554863632528052315>"

PANEL_GIF = ("https://cdn.discordapp.com/attachments/1555167748865392701/1555201529596878858/"
             "6ee6b21d3366affb96b64e9bbd5ae923.gif?backend=b2&ex=6abfa9ca&is=6abe584a&hm="
             "7ee0b49a34275552eae4a4730bf497df205a18b57e1a672b72824580bfefb43c&")

CATEGORY_NAME = "𝐖𝐞𝐫𝐞𝐰𝐨𝐥𝐟"
CREATE_NAME = "╭• สร้างห้องเกมหมาป่า"
LOG_NAME = "╰• Log Game Werewolf"

# ───────── ค่าเวลา/กติกา ─────────
MIN_PLAYERS = 5
LOBBY_SECONDS = 300      # รอคนกดเข้าร่วม 5 นาที
NIGHT0_SECONDS = 30      # คืนแรก (เตรียมตัว ไม่มีอะไร)
NIGHT_SECONDS = 30       # ตอนมืดปกติ
VOTE_SECONDS = 60        # เวลาโหวต
GAME_LIMIT = 3600        # ห้องเล่นได้ 1 ชั่วโมง
CLOSE_AFTER = 300        # หลังจบเกมอยู่ในห้องต่ออีก 5 นาที
IMG_STRIKES = 3          # ส่งรูปครบกี่ครั้งถึงโดนลบออกจากเกม
MAX_LOOKS = 3            # เซียร์/ออร่า ดูได้กี่คนต่อทั้งเกม


def day_seconds(n: int) -> int:
    if n <= 10: return 150   # 2:30
    if n <= 20: return 185   # 3:05
    if n <= 30: return 305   # 5:05
    if n <= 40: return 425   # 7:05
    return 545               # 9:05


def skip_needed(n: int) -> int:
    if n <= 10: return 3
    if n <= 20: return 5
    if n <= 30: return 10
    return 15


def wolves_for(n: int) -> int:
    if n <= 8: return 1
    if n <= 15: return 2
    if n <= 20: return 3
    if n <= 27: return 4
    if n == 28: return 5
    if n <= 35: return 6
    if n <= 40: return 7
    return 8


# บทบาทพิเศษฝั่งมนุษย์ที่สุ่มเข้าเกม (ไม่ซ้ำก่อน ถ้าคนเยอะจนบทบาทไม่พอค่อยสุ่มซ้ำจากกลุ่ม EXTRA)
SPECIAL_POOL = ["seer", "bodyguard", "mage", "cupid", "mayor", "prince", "half_wolf", "infected",
                "aura", "hag", "cowboy"]
EXTRA_POOL = ["seer", "bodyguard", "mage", "half_wolf"]


def compose(n: int) -> list:
    """สุ่มบทบาทตามจำนวนผู้เล่น (มีหมาป่าเเละชาวบ้านอย่างน้อย 2 เสมอ, เเม่มดเริ่มมีตั้งเเต่ 14 คน)"""
    w = max(1, wolves_for(n))
    witch = 1 if n >= 14 else 0
    humans = n - w - witch
    specials = max(0, min(len(SPECIAL_POOL) + len(EXTRA_POOL), humans - 2))
    pool = random.sample(SPECIAL_POOL, min(specials, len(SPECIAL_POOL)))
    if specials > len(SPECIAL_POOL):
        pool += random.sample(EXTRA_POOL, specials - len(SPECIAL_POOL))
    roles = ["wolf"] * w + ["witch"] * witch + pool
    roles += ["villager"] * (n - len(roles))
    random.shuffle(roles)
    return roles


IMG = "https://cdn.discordapp.com/attachments/1555167748865392701/"
ROLES = {
    "wolf": ("หมาป่า", "wolf",
             "คุณได้บทบาทหมาป่า ในทุกคืนคุณต้องฆ่าคนให้หมดเพื่อชนะ อย่าถูกจับได้เด็ดขาด คุณอยู่ฝ่ายหมาป่า",
             IMG + "1555204501240029234/89dc3bf64eeaf97989182154ff859b38.jpg?backend=b2&ex=6abfac8f&is=6abe5b0f&hm=2a032954820f15b6ead660d6dcc1c52bd90bd55c129edc225c88fd656faba688&"),
    "villager": ("ชาวบ้าน", "human",
                 "คุณเป็นคนดี โปรดอยู่ให้รอดถึงจบเกมเพื่อชนะ คุณอยู่ฝ่ายมนุษย์",
                 IMG + "1555204809131429888/c0474b3c6d1998e89eaf9df24aed8ae1.jpg?backend=b2&ex=6abfacd8&is=6abe5b58&hm=573096804d5819f247bcf57040739cf4ba3c901c656ff375a0b98891b4605b51&"),
    "bodyguard": ("บอดี้การ์ด", "human",
                  "โปรดปกป้องคนอื่นไม่ให้หมาป่ากำจัด เมื่อคุณปกป้องคนอื่น เมื่อหมาป่าโจมตีคนนั้น หมาป่าจะไม่สามารถทำร้ายได้ โปรดปกป้องผู้บริสุทธิ์ให้ได้ คุณอยู่ฝ่ายมนุษย์",
                  IMG + "1555204974127091763/ede2f277bba31b5a081f95134b7728cc.jpg?backend=b2&ex=6abfad00&is=6abe5b80&hm=73b1b269d1da5b4060ad0998012c10071c0bd6c4558be95d40223ed5dd15c32c&"),
    "mage": ("นักเวท", "human",
             "สั่งให้คนเงียบ ห้ามพูด เมื่อคุณร่ายเวทใส่ใคร คนนั้นจะไม่สามารถพิมพ์ได้ในวันถัดไป คุณอยู่ฝ่ายมนุษย์",
             IMG + "1555205373235961966/e96ab3a38f7406ef64aa097c84a8ec17.jpg?backend=b2&ex=6abfad5f&is=6abe5bdf&hm=8225bff5bc62c9bce471c358317c5350b4da6d5d6cce9558ffe479af0baec94e&"),
    "cupid": ("คิวปิด", "human",
              "ทำให้คนรักกัน เมื่อคุณเลือก 2 คนให้รักกัน (เลือกได้แค่ 1 คู่ต่อเกม) เมื่อหนึ่งใน 2 คนนั้นตาย อีกคนจะตายตามไปด้วย คุณอยู่ฝ่ายมนุษย์",
              IMG + "1555205644599042089/887f6fada68caf4489e4469899b928f1.jpg?backend=b2&ex=6abfad9f&is=6abe5c1f&hm=34ebc45eed627fdfe7e64e6e821925a232e6ee4c8ae52687dfad9b4414041d81&"),
    "witch": ("แม่มด", "wolf",
              "คุณจะอยู่ฝ่ายหมาป่า แต่จะสามารถฆ่าคนได้แค่ 1 ครั้งต่อเกม",
              IMG + "1555206969818615880/4efec2f8fdb593681e0fbcd166fe06c6.jpg?backend=b2&ex=6abfaedb&is=6abe5d5b&hm=3942fce79db29c8ee443e283f997d8f3f8f8cd23e403c3867926f9e5e8ff47bc&"),
    "seer": ("เซียร์", "human",
             "ในทุกคืน คุณสามารถดูได้ว่าคนนั้นอยู่ฝ่ายหมาป่าหรือมนุษย์ คุณอยู่ฝ่ายมนุษย์",
             IMG + "1555207627913306242/f29e14d96e5ebe472f54ead622a37668.jpg?backend=b2&ex=6abfaf78&is=6abe5df8&hm=4e5e6e331feb146cb17997d8f05a63b560cc77a0f3b9b70206a9f6fbd8a3bb0a&"),
    "half_wolf": ("ลูกครึ่งหมาป่า", "human",
                  "คุณอยู่ฝ่ายมนุษย์และจะไม่สามารถถูกหมาป่าฆ่าได้ แต่เซียร์จะเห็นคุณเป็นหมาป่า",
                  IMG + "1555207901155692574/0484e8347a943ee1f923dc0a703c80f7.jpg?backend=b2&ex=6abfafba&is=6abe5e3a&hm=9adb9568b86a17b62e82c005b155e2a103560fc50f27bd30771fea98a05195ff&"),
    "mayor": ("นายกเทศมนตรี", "human",
              "โหวตของคุณจะนับเป็น 2 คุณอยู่ฝ่ายมนุษย์",
              IMG + "1555208573204561960/3ae9459dcadfbf6ad0a8ec87b541fe08.jpg?backend=b2&ex=6abfb05a&is=6abe5eda&hm=f8f4b7199bb0a1f8a50dd55a13a58cf922bbc059b191bb4d5b75566d6c1a47af&"),
    "aura": ("ออร่า เซียร์", "human",
             "ในทุกคืนคุณสามารถดูได้ว่าคนนี้เป็นชาวบ้านหรือไม่ เช่น คนนี้ไม่ใช่ชาวบ้าน แสดงว่าคนนั้นอาจเป็นหมาป่า คุณอยู่ฝ่ายมนุษย์",
             IMG + "1555208805405556787/e489d3a09c98e4a115c26c68d008c65e.jpg?backend=b2&ex=6abfb091&is=6abe5f11&hm=0909f79eb3a86b4fde86b39b9c6f9e5a134778bf560eada5e7ebbf008fa50caa&"),
    "cowboy": ("คาวบอย", "human",
               "ตอนเริ่มเกม คุณเป็นชาวบ้าน แต่เมื่อโดนฆ่าตอนกลางคืน คุณจะกลายเป็นฝ่ายหมาป่าและสามารถฆ่าคนได้",
               IMG + "1555209780803674216/1f8d835ea5d423d2e3d773c81ee8b990.jpg?backend=b2&ex=6abfb17a&is=6abe5ffa&hm=c3c3418ca02d1e3ed3e2c2fd42ddf47d9f6fafb54b63d930bc9bec9f306febf4&"),
    "prince": ("เจ้าชาย", "human",
               "เมื่อคุณถูกโหวตออก คุณจะถูกเปิดเผยบทบาท แล้วจะยังมีชีวิตอยู่ คุณอยู่ฝ่ายมนุษย์",
               IMG + "1555210598180986990/30d8ec52bc752e70a018abeeb6f0734f.jpg?backend=b2&ex=6abfb23d&is=6abe60bd&hm=403bbbf206b0848cf85704cc439f9adc83ed885d33fd9ee2fa19e317690c7827&"),
    "infected": ("ผู้ติดเชื้อ", "human",
                 "ถ้าคุณถูกกำจัดโดยหมาป่า พวกมันจะไม่สามารถกำจัดใครได้ในคืนถัดไป คุณอยู่ฝ่ายมนุษย์",
                 IMG + "1555211502288502845/cdc054ebea39e5e56a95670a0cf05f77.jpg?backend=b2&ex=6abfb314&is=6abe6194&hm=0e78788f6bc220759bd168331b4c93395847691979cf02db26c8a7af20bbdea0&"),
    "hag": ("อีเเก่", "human",
            "ทุกคืนให้เลือกผู้เล่นหนึ่งคนเพื่อออกจากหมู่บ้านในวันถัดไป เขาจะไม่ถูกฆ่าหรือโดนอะไรเลยเพราะออกจากหมู่บ้าน แต่จะพูดและโหวตในวันถัดไปไม่ได้ คุณอยู่ฝ่ายมนุษย์",
            IMG + "1555214187700035594/9171058e29616474903b9f8499d22f0c.jpg?backend=b2&ex=6abfb594&is=6abe6414&hm=2d75add3187f8ed66fbd974f84da2fc125b767b70dca6e27f99faf03cad41212&"),
}
ROLE_ORDER = ["wolf", "witch", "villager", "bodyguard", "mage", "cupid", "seer", "half_wolf", "mayor",
              "aura", "cowboy", "prince", "infected", "hag"]


def emb(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=WHITE)


def pe(s: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(s)


# ═════════════ ฐานข้อมูล ═════════════
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
    q("""CREATE TABLE IF NOT EXISTS ww_config (
        guild_id INTEGER PRIMARY KEY, category_id INTEGER, create_channel_id INTEGER,
        log_channel_id INTEGER, panel_message_id INTEGER, counter INTEGER DEFAULT 0)""")


def get_cfg(gid: int) -> Optional[dict]:
    row = q("SELECT category_id, create_channel_id, log_channel_id, panel_message_id, counter "
            "FROM ww_config WHERE guild_id=?", (gid,), one=True)
    if not row:
        return None
    return dict(zip(("category_id", "create_channel_id", "log_channel_id", "panel_message_id", "counter"), row))


def next_number(gid: int) -> int:
    q("INSERT INTO ww_config (guild_id, counter) VALUES (?, 1) ON CONFLICT(guild_id) "
      "DO UPDATE SET counter=counter+1", (gid,))
    return q("SELECT counter FROM ww_config WHERE guild_id=?", (gid,), one=True)[0]


# ═════════════ ตัวเกม ═════════════
GAMES: dict = {}   # channel_id -> Game
HOSTS: dict = {}   # (guild_id, host_id) -> channel_id


class Player:
    __slots__ = ("uid", "role", "alive", "strikes", "converted", "revealed", "protected", "looks")

    def __init__(self, uid: int, role: str):
        self.uid, self.role = uid, role
        self.alive, self.strikes, self.converted, self.revealed = True, 0, False, False
        self.protected: set = set()   # บอดี้การ์ด: คนที่เคยปกป้องในรอบนี้ (ครบทุกคนแล้วรีเซ็ต)
        self.looks = 0                # เซียร์/ออร่า: จำนวนครั้งที่ดูไปแล้วทั้งเกม


def team_of(role: str) -> str:
    return ROLES[role][1]


class Game:
    def __init__(self, guild, channel, role, host_id, invited, bracket, number, log_channel_id):
        self.guild, self.channel, self.role = guild, channel, role
        self.host_id, self.invited, self.bracket, self.number = host_id, set(invited), bracket, number
        self.log_channel_id = log_channel_id
        self.joined = [host_id]
        self.players: dict = {}
        self.state = "lobby"   # lobby / night / day / vote / ended
        self.start_event = asyncio.Event()
        self.skip_event = asyncio.Event()
        self.vote_event = asyncio.Event()
        self.lobby_msg = None
        self.lobby_end = int(time.time()) + LOBBY_SECONDS
        self.deadline = 0
        self.day_no = 0
        self.night_no = 0
        self.actions_open = False
        self.night_actions: dict = {}
        self.votes: dict = {}
        self.skip_votes: set = set()
        self.silenced: set = set()
        self.away: set = set()
        self.lovers: Optional[tuple] = None
        self.cupid_done = False
        self.witch_used = False
        self.wolves_blocked = False
        self.report: list = []
        self.events: list = []
        self.winner: Optional[str] = None
        self.timed_out = False
        self.task: Optional[asyncio.Task] = None

    # ── helpers ──
    def name(self, uid: int) -> str:
        m = self.guild.get_member(uid)
        return m.display_name if m else f"ผู้เล่น {uid}"

    def alive_ids(self) -> list:
        return [u for u, p in self.players.items() if p.alive]

    def skip_need(self) -> int:
        """จำนวนโหวตข้ามที่ต้องใช้ ลดลงตามจำนวนคนที่เหลือ (คนที่เหลือกดครบก็ข้ามได้เสมอ)"""
        alive = len(self.alive_ids())
        if alive <= 0:
            return 1
        return max(1, min(skip_needed(alive), alive))

    def skip_count(self) -> int:
        """จำนวนโหวตข้ามที่นับได้ตอนนี้ (นับเฉพาะคนที่ยังมีชีวิต)"""
        return len(self.skip_votes & set(self.alive_ids()))

    def check_skip(self):
        """เช็คว่าครบเกณฑ์ข้ามเวลาคุยหรือยัง (เรียกทุกครั้งที่มีคนกด หรือมีคนตาย)"""
        if self.state != "day":
            return
        have = self.skip_count()
        if have > 0 and have >= self.skip_need():
            self.skip_event.set()

    def wolf_team_alive(self) -> list:
        return [u for u, p in self.players.items() if p.alive and team_of(p.role) == "wolf"]

    def log(self, text: str):
        self.events.append(f"[{time.strftime('%H:%M:%S', time.gmtime(time.time() + 7 * 3600))}] {text}")

    async def send(self, embed=None, view=None, content=None):
        try:
            return await self.channel.send(content=content, embed=embed, view=view,
                                           allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            return None

    async def set_talk(self, allow: bool):
        try:
            await self.channel.set_permissions(self.role, overwrite=discord.PermissionOverwrite(
                view_channel=True, send_messages=allow, read_message_history=True,
                attach_files=False, embed_links=False, add_reactions=False))
        except discord.HTTPException:
            pass

    async def remove_role(self, uid: int):
        m = self.guild.get_member(uid)
        if m:
            try:
                await m.remove_roles(self.role, reason="werewolf: ออกจากเกม")
            except discord.HTTPException:
                pass

    async def wait(self, seconds: float, event: Optional[asyncio.Event] = None):
        seconds = max(0, min(seconds, self.deadline - time.time()))
        try:
            if event is not None:
                await asyncio.wait_for(event.wait(), timeout=seconds)
            else:
                await asyncio.sleep(seconds)
        except asyncio.TimeoutError:
            pass
        if time.time() >= self.deadline:
            self.timed_out = True

    def check_end(self) -> bool:
        alive = self.alive_ids()
        wolves = [u for u in alive if team_of(self.players[u].role) == "wolf"]
        humans = [u for u in alive if team_of(self.players[u].role) != "wolf"]
        if not wolves:
            self.winner = "human"
        elif len(wolves) >= len(humans):   # หมาป่าเท่ากับหรือมากกว่ามนุษย์ → หมาป่าชนะ
            self.winner = "wolf"
        else:
            self.winner = None
        return self.winner is not None

    async def kill(self, uid: int) -> list:
        """ฆ่าผู้เล่น (คนรักตายตามด้วย) คืนรายชื่อคนที่ตายทั้งหมด"""
        dead, queue = [], [uid]
        while queue:
            u = queue.pop(0)
            p = self.players.get(u)
            if not p or not p.alive:
                continue
            p.alive = False
            dead.append(u)
            await self.remove_role(u)
            if self.lovers and u in self.lovers:
                queue.append(self.lovers[1] if self.lovers[0] == u else self.lovers[0])
        self.check_skip()                  # คนลดลง → เกณฑ์ข้ามลดลงด้วย
        if self.check_end():               # เกมควรจบแล้ว → ตัดช่วงคุย/โหวตที่ค้างอยู่ทันที
            self.skip_event.set()
            self.vote_event.set()
        return dead

    # ── การ์ด ──
    def card_embed(self, uid: int) -> discord.Embed:
        p = self.players[uid]
        name, team, desc, img = ROLES[p.role]
        text = f"**{name}**\n{desc}"
        if team == "wolf":
            mates = [u for u, x in self.players.items() if u != uid and team_of(x.role) == "wolf"]
            if mates:
                text += "\n\n**เพื่อนฝ่ายหมาป่า:** " + " ".join(f"<@{u}>" for u in mates)
        if self.lovers and uid in self.lovers:
            other = self.lovers[1] if self.lovers[0] == uid else self.lovers[0]
            text += f"\n\n{E804} **คนรักของคุณคือ** <@{other}> (ตายตามกัน)"
        if p.converted:
            text += "\n\nคุณกลายเป็นฝ่ายหมาป่าเเล้ว!"
        if not p.alive:
            text += f"\n\n{E790} พี่ตายเเล้ว ดูเกมต่อได้เเต่พิมพ์ไม่ได้"
        e = emb(text)
        e.set_image(url=img)
        return e

    # ── ความสามารถกลางคืน ──
    def bodyguard_cands(self, uid: int) -> list:
        """คนที่บอดี้การ์ดปกป้องได้คืนนี้ = คนเป็นที่ยังไม่เคยปกป้องในรอบนี้ (ถ้าครบทุกคนเเล้ว เริ่มรอบใหม่)"""
        p = self.players[uid]
        alive = self.alive_ids()
        left = [u for u in alive if u not in p.protected]
        return left if left else alive

    def action_for(self, uid: int):
        """คืน (kind, ผู้เล่นที่เลือกได้, จำนวนที่ต้องเลือก, ข้อความ) หรือ (None, ..., ข้อความอธิบาย)"""
        p = self.players[uid]
        others = [u for u in self.alive_ids() if u != uid]
        if p.role == "wolf":
            if self.wolves_blocked:
                return None, [], 0, "ฆ่าไม่ได้ เพราะเมื่อคืนฆ่าผู้ติดเชื้อ คืนนี้หมาป่าทำอะไรไม่ได้"
            c = [u for u in others if team_of(self.players[u].role) != "wolf"]
            return "wolf", c, 1, "ต้องการให้หมาป่าฆ่าใคร (ถ้าหมาป่าหลายตัวเลือกไม่ตรงกัน จะนับเสียงข้างมาก)"
        if p.role == "witch":
            if self.witch_used:
                return None, [], 0, "คุณใช้ความสามารถฆ่าไปเเล้ว (ได้ 1 ครั้งต่อเกม)"
            return "witch", others, 1, "ต้องการฆ่าใคร (ใช้ได้ครั้งเดียวทั้งเกม ถ้าไม่เลือกคืนนี้ก็ยังเก็บไว้ได้)"
        if p.role == "bodyguard":
            return "bodyguard", self.bodyguard_cands(uid), 1, (
                "ต้องการปกป้องใคร (ปกป้องคนเดิมซ้ำไม่ได้ จนกว่าจะปกป้องครบทุกคน เเล้วค่อยเริ่มรอบใหม่)")
        if p.role == "mage":
            return "mage", others, 1, "ต้องการร่ายเวทใบ้ใส่ใคร"
        if p.role == "cupid":
            if self.cupid_done:
                return None, [], 0, "คุณใช้ความสามารถคิวปิดไปเเล้ว (ได้ 1 คู่ต่อเกม)"
            if self.night_no != 1:
                return None, [], 0, "คุณใช้ความสามารถได้ในคืนที่ 1 เท่านั้น"
            return "cupid", self.alive_ids(), 2, "เลือก 2 คนให้รักกัน"
        if p.role in ("seer", "aura"):
            left = MAX_LOOKS - p.looks
            if left <= 0:
                return None, [], 0, f"พี่ดูครบ {MAX_LOOKS} คนเเล้ว (ดูได้ {MAX_LOOKS} คนต่อทั้งเกม)"
            what = ("ต้องการดูว่าใครอยู่ฝ่ายหมาป่าหรือมนุษย์" if p.role == "seer"
                    else "ต้องการดูว่าใครเป็นชาวบ้านหรือไม่")
            return p.role, others, 1, f"{what} (เหลือสิทธิ์ดูอีก {left}/{MAX_LOOKS} คน)"
        if p.role == "hag":
            return "hag", others, 1, "ต้องการให้ใครออกจากหมู่บ้าน"
        return None, [], 0, "คืนนี้คุณไม่มีความสามารถที่ต้องใช้ พักผ่อนรอเช้าได้เลย"

    async def record_action(self, interaction: discord.Interaction, uid: int, kind: str, targets: list):
        p = self.players.get(uid)
        if self.state != "night" or not self.actions_open or not p or not p.alive:
            return await interaction.response.edit_message(
                embed=emb(f"{E790} หมดเวลาใช้ความสามารถเเล้วน้าา"), view=None)
        if kind in ("seer", "aura"):
            if uid in self.night_actions:
                return await interaction.response.edit_message(
                    embed=emb(f"{E790} คืนนี้คุณดูไปเเล้วน้าา"), view=None)
            if p.looks >= MAX_LOOKS:
                return await interaction.response.edit_message(
                    embed=emb(f"{E790} คุณดูครบ {MAX_LOOKS} คนเเล้วน้าา (ดูได้ {MAX_LOOKS} คนต่อทั้งเกม)"), view=None)
        if kind == "bodyguard" and targets[0] not in self.bodyguard_cands(uid):
            return await interaction.response.edit_message(
                embed=emb(f"{E790} ปกป้องคนเดิมซ้ำไม่ได้น้าา ต้องปกป้องให้ครบทุกคนก่อน"), view=None)
        self.night_actions[uid] = (kind, targets)
        if kind in ("seer", "aura"):
            p.looks += 1
        t = targets[0]
        if kind == "seer":
            r = "หมาป่า" if (team_of(self.players[t].role) == "wolf" or self.players[t].role == "half_wolf") else "มนุษย์"
            text = f"{E606} ผลการดู: <@{t}> อยู่ฝ่าย **{r}**"
        elif kind == "aura":
            r = "เป็นชาวบ้าน" if self.players[t].role == "villager" else "ไม่ใช่ชาวบ้าน"
            text = f"{E606} ผลการดู: <@{t}> **{r}**"
        elif kind == "cupid":
            text = f"{E606} เลือก <@{targets[0]}> กับ <@{targets[1]}> ให้รักกันเเล้ว"
        else:
            text = f"{E606} เลือก <@{t}> เเล้ว (เปลี่ยนใจได้จนกว่าตอนกลางคืนจะจบ)"
        await interaction.response.edit_message(embed=emb(text), view=None)
        self.log(f"{self.name(uid)} ({ROLES[p.role][0]}) ใช้ความสามารถ {kind}")

    async def resolve_night(self):
        acts = self.night_actions
        away, protect, silence, wolf_votes, witch_t = set(), set(), set(), Counter(), None
        for uid, (kind, targets) in acts.items():
            p = self.players.get(uid)
            if not p or not p.alive:
                continue
            if kind == "cupid" and not self.cupid_done and len(targets) == 2:
                self.lovers, self.cupid_done = (targets[0], targets[1]), True
            elif kind == "hag":
                away.add(targets[0])
            elif kind == "bodyguard":
                protect.add(targets[0])
                if not [u for u in self.alive_ids() if u not in p.protected]:
                    p.protected = set()          # ปกป้องครบทุกคนเเล้ว เริ่มรอบใหม่
                p.protected.add(targets[0])
            elif kind == "mage":
                silence.add(targets[0])
            elif kind == "wolf":
                wolf_votes[targets[0]] += 1
            elif kind == "witch":
                witch_t = targets[0]

        attempts = []
        if self.wolves_blocked:
            self.wolves_blocked = False
        elif wolf_votes:
            top = max(wolf_votes.values())
            attempts.append((random.choice([t for t, c in wolf_votes.items() if c == top]), "wolf"))
        if witch_t is not None and not self.witch_used:
            attempts.append((witch_t, "witch"))
            self.witch_used = True

        deaths, infected_hit = [], False
        for tgt, src in attempts:
            p = self.players.get(tgt)
            if not p or not p.alive:
                continue
            if tgt in away or tgt in protect or p.role == "half_wolf":
                continue
            if p.role == "cowboy":      # คาวบอยโดนฆ่า → เปลี่ยนเป็นฝ่ายหมาป่า (ไม่ตาย)
                p.role, p.converted = "wolf", True
                self.log(f"{self.name(tgt)} (คาวบอย) กลายเป็นหมาป่า")
                continue
            if p.role == "infected" and src == "wolf":
                infected_hit = True
            deaths += await self.kill(tgt)
        if infected_hit:
            self.wolves_blocked = True

        self.silenced = {t for t in silence if self.players[t].alive}
        self.away = {t for t in away if self.players[t].alive}
        rep = []
        for u in deaths:
            rep.append(f"{E790} <@{u}> ถูกฆ่าตายเมื่อคืนนี้")
            self.log(f"{self.name(u)} ({ROLES[self.players[u].role][0]}) ตายตอนกลางคืน")
        if not deaths:
            rep.append("เมื่อคืนไม่มีใครตาย")
        for u in self.silenced:
            rep.append(f"{E604} <@{u}> โดนใบ้ พิมพ์ไม่ได้ตลอดวันนี้")
        for u in self.away:
            rep.append(f"{E597} <@{u}> ออกจากหมู่บ้านไปในวันนี้ (พูดเเละโหวตไม่ได้)")
        self.report = rep

    # ── วงจรเกม ──
    async def lobby_wait(self):
        try:
            await asyncio.wait_for(self.start_event.wait(), timeout=LOBBY_SECONDS)
        except asyncio.TimeoutError:
            pass
        if len(self.joined) >= MIN_PLAYERS:
            await self.run()
        else:
            await self.cancel(f"มีคนเข้าร่วมไม่ถึง {MIN_PLAYERS} คน ห้องนี้ถูกยกเลิก")

    async def cancel(self, reason: str):
        self.state = "ended"
        await self.send(emb(f"{E790} {reason}"))
        await asyncio.sleep(8)
        await self.cleanup()

    async def cleanup(self):
        GAMES.pop(self.channel.id, None)
        HOSTS.pop((self.guild.id, self.host_id), None)
        for obj in (self.channel, self.role):
            try:
                await obj.delete(reason="werewolf: ปิดห้อง")
            except discord.HTTPException:
                pass

    async def run(self):
        try:
            await self.start_game()
            await self.night(first=True)
            while not self.timed_out:
                if self.check_end():
                    break
                await self.day()
                if self.check_end() or self.timed_out:
                    break
                await self.vote()
                if self.check_end() or self.timed_out:
                    break
                await self.night()
                if self.check_end():
                    break
            await self.finish()
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
            try:
                await self.send(emb(f"{E790} เกมมีข้อผิดพลาด เลยต้องปิดห้องนี้น้า"))
                await asyncio.sleep(5)
            finally:
                await self.cleanup()

    async def start_game(self):
        self.state = "night"
        if self.lobby_msg:
            try:
                await self.lobby_msg.edit(view=None)
            except discord.HTTPException:
                pass
        keys = compose(len(self.joined))
        random.shuffle(keys)
        self.players = {uid: Player(uid, keys[i]) for i, uid in enumerate(self.joined)}
        self.deadline = time.time() + GAME_LIMIT
        counts = Counter(keys)
        lines = [f"• {ROLES[k][0]}" + (f" × {counts[k]}" if counts[k] > 1 else "")
                 for k in ROLE_ORDER if counts.get(k)]
        n = len(self.joined)
        self.log(f"เริ่มเกม {n} คน: " + ", ".join(f"{ROLES[k][0]}x{c}" for k, c in counts.items()))
        await self.send(emb(
            f"# {E804} เกมหมาป่าเริ่มเเล้ว! {E804}\n\n"
            f"{E803} ในเกมนี้มีบทบาท\n\n" + "\n".join(lines) +
            f"\n\nผู้เล่น **{n}** คน เป็นหมาป่า **{counts.get('wolf', 0)}** คน"
            f"\nเวลาคุยตอนเช้า: **{day_seconds(n) // 60} นาที {day_seconds(n) % 60} วิ**"
            f"\nกดปุ่มด้านล่าง หรือพิมพ์ `!check` เพื่อดูการ์ดของคุณ (ห้ามบอกบทบาทตัวเองนะ!)"),
            view=CardView(self))

    async def night(self, first: bool = False):
        self.state = "night"
        if not first:
            self.night_no += 1
        self.silenced, self.away = set(), set()
        self.night_actions = {}
        self.actions_open = not first
        await self.set_talk(False)
        dur = NIGHT0_SECONDS if first else NIGHT_SECONDS
        end = int(time.time() + dur)
        if first:
            text = (f"# {E739} ตอนมืด {E739}\n\nกำลังอยู่ในระหว่างตอนกลางคืน ห้ามพิมพ์!\n"
                    f"คืนแรกเป็นช่วงเตรียมตัวเท่านั้น **ไม่มีการฆ่าเเละไม่มีการโหวต** ใช้ความสามารถไม่ได้ ให้พี่ๆดูการ์ดเเล้วเตรียมตัวไว้ ตอนเช้าจะเริ่ม <t:{end}:R>")
        else:
            text = (f"# {E739} คืนที่ {self.night_no} {E739}\n\n"
                    "กำลังอยู่ในระหว่างตอนกลางคืน ห้ามพิมพ์! ตอนเช้าทุกคนจะกลับมาพิมพ์ได้\n"
                    f"เหลือเวลาในห้องนี้อีก <t:{int(self.deadline)}:R>\n"
                    f"ตอนกลางคืนจบ <t:{end}:R>\n\n"
                    "ใครมีความสามารถ กดปุ่มด้านล่างเพื่อเลือกใช้ได้เลย (ถ้าเลือกไม่ใช้ จะเก็บไว้ใช้ตอนเช้าไม่ได้)")
        await self.send(emb(text), view=CardView(self))
        await self.wait(dur)
        if not first:
            self.actions_open = False
            await self.resolve_night()
            self.check_end()

    async def day(self):
        self.state = "day"
        self.day_no += 1
        await self.set_talk(True)
        n = len(self.alive_ids())
        dur = day_seconds(len(self.players))
        end = int(time.time() + dur)
        rep = "\n".join(self.report) if self.report else ""
        self.log(f"เช้าวันที่ {self.day_no}: " + (" | ".join(r.replace(E790, '').strip() for r in self.report) or "-"))
        self.skip_event, self.skip_votes = asyncio.Event(), set()
        await self.send(emb(
            f"# {E803} ตอนเช้า วันที่ {self.day_no} {E803}\n\n"
            + (rep + "\n\n" if rep else "") +
            f"เหลือผู้เล่น **{n}** คน ให้ทุกคนคุยกันได้เลย หมดเวลาคุย <t:{end}:R>\n"
            f"ถ้าคุยเสร็จเเล้วขี้เกียจรอ พิมพ์ `!time` เพื่อโหวตข้ามไปช่วงโหวต"))
        self.report = []
        await self.wait(dur, self.skip_event)
        if self.skip_event.is_set() and not self.timed_out and not self.check_end():
            await self.send(emb(f"{E803} ผู้เล่นที่เหลือโหวตข้ามเวลาคุยครบเเล้ว เข้าสู่ช่วงโหวตเลย!"))

    async def vote(self):
        self.state = "vote"
        self.votes = {}
        self.vote_event = asyncio.Event()
        end = int(time.time() + VOTE_SECONDS)
        await self.send(emb(
            f"# {E804} เลือกโหวต {E804}\n\nกดปุ่มด้านล่างเพื่อเลือกว่าจะโหวตใคร หรือโหวตข้าม "
            f"(เปลี่ยนใจได้จนกว่าจะหมดเวลา)\nหมดเวลาโหวต <t:{end}:R>"), view=VoteView(self))
        await self.wait(VOTE_SECONDS, self.vote_event)
        # นับคะแนน
        counts, skip = Counter(), 0
        for uid, tgt in self.votes.items():
            w = 2 if self.players[uid].role == "mayor" else 1
            if tgt == 0:
                skip += w
            else:
                counts[tgt] += w
        lines = [f"<@{u}> : **{c}** โหวต" for u, c in counts.most_common()]
        lines.append(f"โหวตข้าม : **{skip}**")
        out = emb(f"# {E804} ผลโหวต {E804}\n\n" + "\n".join(lines) + "\n\n(ไม่เปิดเผยว่าใครโหวตอะไร)")
        await self.send(out)
        self.log("ผลโหวต: " + ", ".join(f"{self.name(u)}={c}" for u, c in counts.items()) + f", ข้าม={skip}")
        if counts:
            top = max(counts.values())
            tops = [u for u, c in counts.items() if c == top]
            if top > skip and len(tops) == 1:
                await self.eliminate(tops[0])
                return
        await self.send(emb("ไม่มีใครถูกโหวตออกในวันนี้"))

    async def eliminate(self, uid: int):
        p = self.players[uid]
        if p.role == "prince":
            p.revealed = True
            e = emb(f"{E803} <@{uid}> ถูกโหวตออก เเต่เขาคือ **เจ้าชาย**! บทบาทถูกเปิดเผยเเต่ **ยังมีชีวิตอยู่**")
            e.set_image(url=ROLES["prince"][3])
            self.log(f"{self.name(uid)} (เจ้าชาย) ถูกโหวตออกเเต่รอด")
            return await self.send(e)
        dead = await self.kill(uid)
        text = f"{E790} <@{uid}> ถูกโหวตออก"
        extra = [d for d in dead if d != uid]
        if extra:
            text += "\n" + "\n".join(f"{E790} <@{d}> ตายตามคนรักไป" for d in extra)
        self.log(f"{self.name(uid)} ({ROLES[p.role][0]}) ถูกโหวตออก")
        await self.send(emb(text))

    async def finish(self):
        self.state = "ended"
        self.check_end()
        await self.set_talk(True)
        for uid in self.players:       # คืนยศให้ทุกคนคุยกันต่อได้ 5 นาที
            m = self.guild.get_member(uid)
            if m and self.role not in m.roles:
                try:
                    await m.add_roles(self.role)
                except discord.HTTPException:
                    pass
        if self.winner == "human":
            res = f"{E606} **ฝ่ายมนุษย์ชนะ!** หมาป่าถูกกำจัดหมดเเล้ว"
        elif self.winner == "wolf":
            res = f"{E729} **ฝ่ายหมาป่าชนะ!** หมาป่ามีจำนวนเท่ากับหรือมากกว่ามนุษย์เเล้ว"
        else:
            res = f"{E597} **หมดเวลา 1 ชั่วโมง** เกมจบเเบบไม่มีผู้ชนะ"
        roles_text = "\n".join(
            f"{'' if p.alive else '💀 '}<@{u}> — **{ROLES[p.role][0]}**" for u, p in self.players.items())
        end = int(time.time()) + CLOSE_AFTER
        self.log(f"จบเกม: {res.replace('**', '')}")
        await self.send(emb(f"# {E804} จบเกมเเล้ว {E804}\n\n{res}\n\n**บทบาทของทุกคน**\n{roles_text}\n\n"
                            f"ห้องนี้จะถูกลบ <t:{end}:R> (คุยกันต่อได้เลย)"))
        await asyncio.sleep(CLOSE_AFTER)
        await self.save_log(res)
        await self.cleanup()

    async def save_log(self, res: str):
        log_ch = self.guild.get_channel(self.log_channel_id or 0)
        if log_ch is None:
            return
        try:
            chat = [m async for m in self.channel.history(limit=None, oldest_first=True)]
        except discord.HTTPException:
            chat = []
        lines = [f"WEREWOLF GAME #{self.number}", f"Server: {self.guild.name} ({self.guild.id})",
                 f"Host: {self.name(self.host_id)} ({self.host_id})", f"Result: {res.replace('**', '')}",
                 "", "[Players]"]
        lines += [f"{self.name(u)} ({u}): {ROLES[p.role][0]}{'' if p.alive else ' (ตาย)'}"
                  for u, p in self.players.items()]
        lines += ["", "[Timeline]"] + self.events + ["", "[Chat]"]
        for m in chat:
            ts = time.strftime("%H:%M:%S", time.gmtime(m.created_at.timestamp() + 7 * 3600))
            lines.append(f"[{ts}] {m.author} ({m.author.id}): {m.content or ''}".rstrip())
            for e in m.embeds:
                if e.description:
                    lines.append("  [Embed] " + e.description.replace("\n", " | ")[:500])
        e = discord.Embed(
            description=(f"# {E767} บันทึกเกมหมาป่า {E767}\n\n**ห้อง** Werewolf-{self.number}\n"
                         f"**คนสร้างห้อง** <@{self.host_id}>\n**ผู้เล่น** {len(self.players)} คน\n"
                         f"**ผลการเล่น** {res}\n\n"
                         + "\n".join(f"<@{u}> — {ROLES[p.role][0]}" for u, p in self.players.items())),
            color=WHITE, timestamp=discord.utils.utcnow())
        e.set_footer(text="จบเกมเมื่อ")
        try:
            await log_ch.send(embed=e, file=discord.File(
                io.BytesIO("\n".join(lines).encode("utf-8")), filename=f"werewolf-{self.number}.txt"))
        except discord.HTTPException:
            pass


# ═════════════ Views ในเกม ═════════════
def chunked_options(game: Game, uids: list):
    opts = [discord.SelectOption(label=game.name(u)[:90] or str(u), value=str(u)) for u in uids]
    return [opts[i:i + 25] for i in range(0, len(opts), 25)][:4]


class PickView(discord.ui.View):
    """เลือกเป้าหมาย (เห็นคนเดียว) need=1 เลือกเสร็จบันทึกทันที, need=2 ต้องกดยืนยัน (คิวปิด)"""
    def __init__(self, game: Game, uid: int, kind: str, cands: list, need: int):
        super().__init__(timeout=120)
        self.game, self.uid, self.kind, self.need = game, uid, kind, need
        self.per: dict = {}
        for i, opts in enumerate(chunked_options(game, cands)):
            sel = discord.ui.Select(placeholder="เลือกคน" + (f" (กลุ่ม {i + 1})" if len(cands) > 25 else ""),
                                    options=opts, min_values=1 if need == 1 else 0, max_values=need, row=i)
            sel.callback = self._cb(i, sel)
            self.add_item(sel)
        if need == 2:
            btn = discord.ui.Button(label="ยืนยัน", style=discord.ButtonStyle.success, row=4)
            btn.callback = self.confirm
            self.add_item(btn)

    def _cb(self, idx: int, sel: discord.ui.Select):
        async def cb(interaction: discord.Interaction):
            vals = [int(v) for v in sel.values]
            if self.need == 1:
                return await self.game.record_action(interaction, self.uid, self.kind, vals)
            self.per[idx] = set(vals)
            chosen = set().union(*self.per.values())
            await interaction.response.edit_message(
                embed=emb(f"เลือกอยู่: " + (" ".join(f"<@{u}>" for u in chosen) or "ยังไม่ได้เลือก")
                          + "\nต้องเลือกให้ครบ 2 คนเเล้วกดยืนยัน"), view=self)
        return cb

    async def confirm(self, interaction: discord.Interaction):
        chosen = list(set().union(*self.per.values())) if self.per else []
        if len(chosen) != 2:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ต้องเลือกให้ครบ 2 คนน้าา"), ephemeral=True)
        await self.game.record_action(interaction, self.uid, self.kind, chosen)


class CardView(discord.ui.View):
    """ปุ่ม 'ดูการ์ด / ใช้ความสามารถ' (กดแล้วเห็นคนเดียว)"""
    def __init__(self, game: Game):
        super().__init__(timeout=GAME_LIMIT + 600)
        self.game = game

    @discord.ui.button(label="ดูการ์ด / ใช้ความสามารถ", style=discord.ButtonStyle.primary, emoji=pe(E836))
    async def card(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = self.game
        p = g.players.get(interaction.user.id)
        if not p:
            return await interaction.response.send_message(
                embed=emb(f"{E790} คุณไม่ได้อยู่ในเกมนี้น้า"), ephemeral=True)
        embed, view = g.card_embed(interaction.user.id), None
        if g.state == "night" and g.actions_open and p.alive:
            kind, cands, need, note = g.action_for(interaction.user.id)
            embed.description += f"\n\n{E739} {note}"
            if kind and cands:
                view = PickView(g, interaction.user.id, kind, cands, need)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class VoteView(discord.ui.View):
    def __init__(self, game: Game):
        super().__init__(timeout=VOTE_SECONDS + 30)
        self.game = game

    @discord.ui.button(label="เลือกโหวต", style=discord.ButtonStyle.primary, emoji=pe(E804))
    async def open(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = self.game
        p = g.players.get(interaction.user.id)
        if g.state != "vote" or not p or not p.alive or interaction.user.id in g.away:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ตอนนี้พี่โหวตไม่ได้น้า (ตายเเล้ว/ไม่ได้เล่น/ออกจากหมู่บ้าน/หมดเวลา)"), ephemeral=True)
        cands = [u for u in g.alive_ids() if u != interaction.user.id]
        view = discord.ui.View(timeout=VOTE_SECONDS + 30)
        for i, opts in enumerate(chunked_options(g, cands)):
            sel = discord.ui.Select(placeholder="โหวตคนที่จะให้ออก", options=opts, row=i)

            async def cb(inter: discord.Interaction, sel=sel):
                await self._cast(inter, int(sel.values[0]))
            sel.callback = cb
            view.add_item(sel)
        skip = discord.ui.Button(label="โหวตข้าม", style=discord.ButtonStyle.secondary, row=4)

        async def skip_cb(inter: discord.Interaction):
            await self._cast(inter, 0)
        skip.callback = skip_cb
        view.add_item(skip)
        await interaction.response.send_message(embed=emb(f"{E804} เลือกคนที่จะโหวต หรือกดโหวตข้าม"),
                                                view=view, ephemeral=True)

    async def _cast(self, interaction: discord.Interaction, target: int):
        g = self.game
        if g.state != "vote":
            return await interaction.response.edit_message(embed=emb(f"{E790} หมดเวลาโหวตเเล้วน้าา"), view=None)
        g.votes[interaction.user.id] = target
        txt = "โหวตข้ามเเล้ว" if target == 0 else f"โหวต <@{target}> เเล้ว"
        await interaction.response.edit_message(embed=emb(f"{E606} {txt} (เปลี่ยนใจได้จนกว่าจะหมดเวลา)"), view=None)
        eligible = [u for u in g.alive_ids() if u not in g.away]
        if all(u in g.votes for u in eligible):
            g.vote_event.set()


class SkipView(discord.ui.View):
    def __init__(self, game: Game):
        super().__init__(timeout=120)
        self.game = game

    @discord.ui.button(label="โหวตข้ามเวลาคุย", style=discord.ButtonStyle.success, emoji=pe(E803))
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        g = self.game
        p = g.players.get(interaction.user.id)
        if g.state != "day" or not p or not p.alive:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ตอนนี้โหวตข้ามไม่ได้น้า"), ephemeral=True)
        g.skip_votes.add(interaction.user.id)
        need = g.skip_need()
        await interaction.response.send_message(
            embed=emb(f"{E606} โหวตข้ามเเล้ว ({g.skip_count()}/{need})"), ephemeral=True)
        g.check_skip()


class OwnCardView(discord.ui.View):
    """ตอบ !check / !check1 : กดได้เฉพาะคนที่พิมพ์ แล้วเห็นการ์ดคนเดียว"""
    def __init__(self, game: Game, owner_id: int, abilities: bool):
        super().__init__(timeout=30)
        self.game, self.owner_id, self.abilities = game, owner_id, abilities

    @discord.ui.button(label="กดดู (เห็นคนเดียว)", style=discord.ButtonStyle.primary, emoji=pe(E836))
    async def show(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(embed=emb(f"{E790} ปุ่มนี้ของคนอื่นน้า"), ephemeral=True)
        g = self.game
        if interaction.user.id not in g.players:
            return await interaction.response.send_message(embed=emb(f"{E790} คุณไม่ได้อยู่ในเกมนี้น้า"), ephemeral=True)
        if self.abilities:
            role = g.players[interaction.user.id].role
            name, _, desc, img = ROLES[role]
            e = emb(f"**{name}**\n{desc}")
            e.set_image(url=img)
        else:
            e = g.card_embed(interaction.user.id)
        await interaction.response.send_message(embed=e, ephemeral=True)


# ═════════════ ล็อบบี้ ═════════════
class LobbyView(discord.ui.View):
    def __init__(self, game: Game):
        super().__init__(timeout=LOBBY_SECONDS + 60)
        self.game = game
        j = discord.ui.Button(label="เข้าร่วมห้อง", style=discord.ButtonStyle.success, emoji=pe(E604))
        l = discord.ui.Button(label="ออกจากห้อง", style=discord.ButtonStyle.danger, emoji=pe(E790))
        j.callback, l.callback = self.join, self.leave
        self.add_item(j)
        self.add_item(l)
        if len(game.joined) >= MIN_PLAYERS:
            s = discord.ui.Button(label="เริ่ม", style=discord.ButtonStyle.primary, emoji=pe(E803))
            s.callback = self.start
            self.add_item(s)

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=lobby_embed(self.game), view=LobbyView(self.game))

    async def join(self, interaction: discord.Interaction):
        g, uid = self.game, interaction.user.id
        if g.state != "lobby":
            return await interaction.response.send_message(embed=emb(f"{E790} เกมเริ่มไปเเล้วน้า"), ephemeral=True)
        if uid != g.host_id and uid not in g.invited:
            return await interaction.response.send_message(embed=emb(f"{E790} คุณไม่ได้ถูกชวนเข้าห้องนี้น้า"), ephemeral=True)
        if uid in g.joined:
            return await interaction.response.send_message(embed=emb("คุณเข้าร่วมเเล้วน้าา รอเกมเริ่มได้เลย"), ephemeral=True)
        member = g.guild.get_member(uid)
        try:
            await member.add_roles(g.role, reason="werewolf: เข้าร่วม")
        except discord.HTTPException:
            return await interaction.response.send_message(embed=emb(f"{E790} ให้ยศเข้าห้องไม่ได้ (ยศบอทไม่ถึง)"), ephemeral=True)
        g.joined.append(uid)
        await self.refresh(interaction)
        await interaction.followup.send(embed=emb(
            f"{E606} เข้าร่วมเเล้วน้าา น้องจะสุ่มบทบาทให้ตอนเกมเริ่ม เเล้วดูการ์ดได้ที่ปุ่ม **ดูการ์ด** หรือพิมพ์ `!check`"),
            ephemeral=True)
        if len(g.joined) == len(g.invited) + 1:   # ครบทุกคนที่ชวน → เริ่มเลย
            g.start_event.set()

    async def leave(self, interaction: discord.Interaction):
        g, uid = self.game, interaction.user.id
        if uid == g.host_id:
            return await interaction.response.send_message(
                embed=emb(f"{E790} เจ้าของห้องออกไม่ได้น้า (ถ้าไม่เล่นแล้วรอให้ห้องหมดเวลายกเลิก)"), ephemeral=True)
        if uid not in g.joined or g.state != "lobby":
            return await interaction.response.send_message(embed=emb(f"{E790} พี่ไม่ได้อยู่ในห้องนี้น้า"), ephemeral=True)
        g.joined.remove(uid)
        await g.remove_role(uid)
        await self.refresh(interaction)

    async def start(self, interaction: discord.Interaction):
        g = self.game
        if interaction.user.id != g.host_id:
            return await interaction.response.send_message(embed=emb(f"{E790} เเค่เจ้าของห้องที่กดเริ่มได้น้า"), ephemeral=True)
        if len(g.joined) < MIN_PLAYERS:
            return await interaction.response.send_message(embed=emb(f"{E790} ต้องมีอย่างน้อย {MIN_PLAYERS} คนน้า"), ephemeral=True)
        await interaction.response.edit_message(view=None)
        g.start_event.set()


def lobby_embed(g: Game) -> discord.Embed:
    return emb(f"# {E804} เกมหมาป่า {E804}\n\n"
               f"**ตอนนี้กำลังอยู่ในช่วงรอผู้เล่น** ตอนนี้มีคนเข้าร่วมเเล้ว {len(g.joined)}/{len(g.invited) + 1}\n\n"
               f"ห้อง {g.bracket[0]}-{g.bracket[1]} คน (ต้องมีอย่างน้อย {MIN_PLAYERS} คน)\n"
               f"รอผู้เล่นอีก <t:{g.lobby_end}:R> ถ้าครบ/ถึงเวลาเเละมีคนพอ เกมจะเริ่มเอง\n"
               f"ผู้เล่นที่เข้าร่วมเเล้ว: " + " ".join(f"<@{u}>" for u in g.joined))


# ═════════════ แผงหลัก + สร้างห้อง ═════════════
BRACKETS = [(5, 10), (11, 20), (21, 30), (31, 40), (41, 50)]


def panel_embed() -> discord.Embed:
    e = emb(
        f"# {E803} Werewolf room {E847}\n\n"
        f"{E804} ให้พี่ๆสร้างห้องมา เเล้วพี่ๆก็เลือกเพื่อนที่จะเล่นด้วย สูงสุด 50 คน ขั้นต่ำ 5 คน "
        "ให้พี่ๆที่ถูกชวน กดยอมรับ เเล้วน้องจะสุ่มการ์ดให้พี่\n\n"
        "`!check` จะเป็นการดูการ์ดตัวเอง\n`!check1` ดูว่าบทบาทตัวเองทำอะไรได้\n\n"
        "ทุกคืนน้องจะให้พี่ๆใช้ความสามารถของการ์ดได้ เเล้วตอนเช้าจะมีเวลาให้พี่ๆคุยกัน ถ้า\n"
        "5-10 คน มีเวลา 2 นาที 30 วิ\n11-20 คน มีเวลา 3 นาที 5 วิ\n21-30 คน มีเวลา 5 นาที 5 วิ\n"
        "31-40 คน มีเวลา 7 นาที 5 วิ\n41-50 คน มีเวลา 9 นาที 5 วิ\n\n"
        f"{E739} เเล้วถ้าพี่ๆคุยกันเสร็จเเล้วขี้เกียจรอ ให้พี่ๆ `!time` เเล้วน้องจะให้พี่ๆโหวตกันว่าจะข้ามไปเลยมั้ย\n"
        "5-10 คน กด 3 คนจะข้าม\n11-20 คน กด 5 ข้าม\n21-30 คน กด 10 ข้าม\n31-40 คน กด 15 ข้าม\n41-50 คน กด 15 ข้าม\n\n"
        "ถ้าพี่ๆสงสัยว่าบทบาททั้งหมดมีเท่าไหร่เเล้วทำอะไรได้บ้าง ให้พี่ๆกดเลือก **ดูบทบาททั้งหมด** ในลิสด้านล่างได้เลยย "
        "หลังจากเล่นจบจะมีเวลาให้พี่ๆ 5 นาทีในห้องนั้นก่อนจะลบห้อง เเล้วจะเก็บการเล่นของพี่ๆไว้ที่ werewolf log\n\n"
        f"{E607} **วิธีเล่นเเบบละเอียด**\n\n"
        "พอพี่ๆถูกชวนให้เข้าร่วม หลังจากกดเข้า น้องจะสุ่มบทบาทให้เมื่อเกมเริ่ม หลังจากคนกดครบเกมจะเริ่ม "
        "เกมจะเริ่มไปตอนมืดทันที มีเวลาตอนมืด 30 วิ ให้พี่ๆเตรียมตัว คืนเเรกจะไม่มีอะไร หลังจากเช้า ให้พี่ๆคุยกันได้ "
        "พอตอนมืด น้องจะให้พี่ๆใช้ความสามารถได้ เเละจะมีหมาป่ามาออกล่าพวกพี่ ให้หาหมาป่าตัวนั้นให้เจอไม่งั้นทุกคนจะตายเเละเเพ้ "
        "หลังจากตอนเช้า น้องจะให้พี่ๆกดโหวต ว่าจะโหวตคนหรือข้าม หลังจากจบเกมน้องก็จะเเสดงบทบาทของทุกคนที่เล่น\n\n"
        f"{E803} **เงื่อนไข**\n\n"
        "ถ้าเลือกห้อง 5-10 คน เเต่คนกดเล่นไม่ถึง 5 ห้องจะถูกยกเลิก มีเวลาให้ทุกคนกดเข้าร่วมห้อง 5 นาทีก่อนเกมจะเริ่ม "
        "เเต่ถ้าคนกดถึง 5 เกมก็จะเริ่มได้ เเล้วห้องนึงจะมีเวลาให้เล่น 1 ชั่วโมงก่อนห้องจะถูกลบ เเละเมื่อคุณตายจะไม่สามารถพิมพ์ได้\n\n"
        f"{E597} **กฎการเล่น**\n\n"
        "โปรดอย่าบอกบทบาทของตนเอง เเล้วจะไม่สามารถส่งรูปภาพได้ "
        "จะจบเกมได้ต่อเมื่อหมาป่าหมดหรือชาวบ้านโดนกำจัดหมด")
    e.set_image(url=PANEL_GIF)
    return e


class CreateView(discord.ui.View):
    def __init__(self, host_id: int):
        super().__init__(timeout=600)
        self.host_id = host_id
        self.bracket: Optional[tuple] = None
        self.invites: set = set()
        b = discord.ui.Select(placeholder="เลือกจำนวนคนในห้อง", row=0, options=[
            discord.SelectOption(label=f"{a}-{z}", value=f"{a}-{z}") for a, z in BRACKETS])
        u = discord.ui.UserSelect(placeholder="เลือกเพื่อนที่จะเล่นด้วย (เลือกเพิ่มได้หลายรอบ)",
                                  min_values=1, max_values=25, row=1)
        b.callback, u.callback = self.on_bracket, self.on_users
        self.b, self.u = b, u
        self.add_item(b)
        self.add_item(u)
        go = discord.ui.Button(label="เริ่มสร้าง", style=discord.ButtonStyle.success, emoji=pe(E606), row=2)
        clr = discord.ui.Button(label="ล้างตัวเลือก", style=discord.ButtonStyle.secondary, emoji=pe(E728), row=2)
        go.callback, clr.callback = self.create, self.clear
        self.add_item(go)
        self.add_item(clr)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.host_id:
            await interaction.response.send_message(embed=emb(f"{E790} เมนูนี้ของคนอื่นน้า"), ephemeral=True)
            return False
        return True

    def state_embed(self, note: str = "") -> discord.Embed:
        mx = self.bracket[1] if self.bracket else 50
        inv = " ".join(f"<@{u}>" for u in self.invites) or "ยังไม่ได้เลือก"
        return emb(f"# {E767} เลือกจำนวนคนในห้องเเละคนที่จะเล่นด้วยกัน {E767}\n\n"
                   f"ห้อง: **{f'{self.bracket[0]}-{self.bracket[1]} คน' if self.bracket else 'ยังไม่ได้เลือก'}**\n"
                   f"คนที่ชวน ({len(self.invites)}/{mx - 1}) ตัวพี่เองนับเป็นผู้เล่นอยู่เเล้ว: {inv}\n"
                   f"ต้องชวนอย่างน้อย {MIN_PLAYERS - 1} คน" + (f"\n\n{note}" if note else ""))

    async def on_bracket(self, interaction: discord.Interaction):
        a, z = self.b.values[0].split("-")
        self.bracket = (int(a), int(z))
        note = ""
        if len(self.invites) > self.bracket[1] - 1:
            self.invites = set(list(self.invites)[: self.bracket[1] - 1])
            note = "คนที่ชวนเกินจำนวนห้อง เลยตัดออกบางส่วนน้า"
        await interaction.response.edit_message(embed=self.state_embed(note), view=self)

    async def on_users(self, interaction: discord.Interaction):
        mx = self.bracket[1] if self.bracket else 50
        note = ""
        for m in self.u.values:
            if m.bot or m.id == self.host_id:
                continue
            if len(self.invites) >= mx - 1 and m.id not in self.invites:
                note = f"ชวนได้ไม่เกิน {mx - 1} คนน้า (ห้อง {self.bracket[0]}-{mx} คน)" if self.bracket else ""
                break
            self.invites.add(m.id)
        await interaction.response.edit_message(embed=self.state_embed(note), view=self)

    async def clear(self, interaction: discord.Interaction):
        self.bracket, self.invites = None, set()
        await interaction.response.edit_message(embed=self.state_embed(f"{E728} ล้างตัวเลือกสำเร็จจ"), view=self)

    async def create(self, interaction: discord.Interaction):
        if not self.bracket:
            return await interaction.response.send_message(embed=emb(f"{E790} เลือกจำนวนคนในห้องก่อนน้าา"), ephemeral=True)
        if len(self.invites) < MIN_PLAYERS - 1:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ต้องชวนอย่างน้อย {MIN_PLAYERS - 1} คน (รวมตัวพี่เป็น {MIN_PLAYERS} คน) น้าา"), ephemeral=True)
        await interaction.response.edit_message(embed=emb(f"{E804} กำลังสร้างห้อง..."), view=None)
        res = await create_game(interaction, self.host_id, self.invites, self.bracket)
        await interaction.edit_original_response(embed=res)


async def create_game(interaction: discord.Interaction, host_id: int, invites: set, bracket: tuple) -> discord.Embed:
    guild = interaction.guild
    cfg = get_cfg(guild.id)
    category = guild.get_channel(cfg["category_id"]) if cfg and cfg["category_id"] else None
    create_ch = guild.get_channel(cfg["create_channel_id"]) if cfg and cfg["create_channel_id"] else None
    if category is None or create_ch is None:
        return emb(f"{E790} ระบบยังไม่ได้ตั้งค่า ให้เเอดมินใช้ /werewolf ก่อนน้า")
    if (guild.id, host_id) in HOSTS:
        return emb(f"{E790} พี่มีห้องที่กำลังเล่นอยู่เเล้วน้า รอให้จบก่อน")
    me = guild.me
    if not (me.guild_permissions.manage_channels and me.guild_permissions.manage_roles
            and me.guild_permissions.manage_messages):
        return emb(f"{E790} น้องต้องมีสิทธิ์ จัดการช่อง / จัดการยศ / จัดการข้อความ ก่อนน้า")

    n = next_number(guild.id)
    try:
        role = await guild.create_role(name=f"Werewolf-{n}", reason="werewolf: ห้องเกม")
        bot_ow = discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                             attach_files=True, manage_messages=True, read_message_history=True)
        channel = await guild.create_text_channel(
            f"Werewolf-{n}", category=category, reason="werewolf: ห้องเกม",
            overwrites={
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=False, attach_files=False, embed_links=False,
                    add_reactions=False, read_message_history=True),
                role: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, attach_files=False, embed_links=False,
                    add_reactions=False, read_message_history=True),
                me: bot_ow})
        try:  # ให้ห้องเกมอยู่ต่อจากห้องสร้างเกม (ก่อนห้อง log)
            await channel.move(after=create_ch, category=category, sync_permissions=False)
        except discord.HTTPException:
            pass
        host = guild.get_member(host_id)
        await host.add_roles(role, reason="werewolf: เจ้าของห้อง")
    except discord.HTTPException as e:
        return emb(f"{E790} สร้างห้องไม่สำเร็จ ({e.status}) เช็คสิทธิ์/ลำดับยศของบอทเเล้วลองใหม่น้า")

    game = Game(guild, channel, role, host_id, invites, bracket, n, cfg["log_channel_id"])
    GAMES[channel.id] = game
    HOSTS[(guild.id, host_id)] = channel.id
    game.lobby_msg = await game.send(
        lobby_embed(game), LobbyView(game),
        content=f"<@{host_id}> " + " ".join(f"<@{u}>" for u in invites) + "\nเปิด DM จากบอทไว้ด้วยน้า (ไม่บังคับ)")
    game.task = asyncio.create_task(game.lobby_wait())
    return emb(f"{E606} สร้างห้องเเล้วน้าา {channel.mention} น้องเเท็กคนที่ชวนไว้ในห้องเเล้ว")


class RolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        sel = discord.ui.Select(placeholder="เลือกบทบาทที่อยากรู้", options=[
            discord.SelectOption(label=ROLES[k][0], value=k,
                                 description=("ฝ่ายหมาป่า" if ROLES[k][1] == "wolf" else "ฝ่ายมนุษย์"))
            for k in ROLE_ORDER])
        sel.callback = self.on_select
        self.sel = sel
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        k = self.sel.values[0]
        name, team, desc, img = ROLES[k]
        e = emb(f"**{name}**\n{desc}")
        e.set_image(url=img)
        await interaction.response.edit_message(embed=e, view=RolesView())


class WerewolfPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(custom_id="werewolf:panel", placeholder="ลิสระบบต่างๆ", options=[
            discord.SelectOption(label="สร้างห้อง", value="create", emoji=pe(E818)),
            discord.SelectOption(label="ดูบทบาททั้งหมด", value="roles", emoji=pe(E836)),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E803)),
        ])
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        try:
            await interaction.message.edit(view=WerewolfPanelView())  # รีเซ็ตเมนู
        except discord.HTTPException:
            pass
        if v == "create":
            view = CreateView(interaction.user.id)
            await interaction.response.send_message(embed=view.state_embed(), view=view, ephemeral=True)
        elif v == "roles":
            names = "\n".join(f"• {ROLES[k][0]} ({'ฝ่ายหมาป่า' if ROLES[k][1] == 'wolf' else 'ฝ่ายมนุษย์'})"
                              for k in ROLE_ORDER)
            await interaction.response.send_message(
                embed=emb(f"# {E836} บทบาททั้งหมด\n\n{names}\n\nเลือกบทบาทที่อยากรู้ในลิสด้านล่างได้เลย"),
                view=RolesView(), ephemeral=True)
        else:
            await interaction.response.send_message(embed=emb(f"{E728} ล้างตัวเลือกสำเร็จจ"), ephemeral=True)


# ═════════════ Cog ═════════════
class WerewolfCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()
        self.bot.add_view(WerewolfPanelView())

    @app_commands.command(name="werewolf", description="เซ็ตระบบเกมหมาป่า (แอดมินเท่านั้น)")
    @app_commands.guild_only()
    async def werewolf(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                embed=emb(f"{E790} ไม่ได้น้าา พี่ไม่ใช่แอดมิน"), ephemeral=True)
        guild, me = interaction.guild, interaction.guild.me
        if not (me.guild_permissions.manage_channels and me.guild_permissions.manage_roles
                and me.guild_permissions.manage_messages):
            return await interaction.response.send_message(
                embed=emb(f"{E790} น้องต้องมีสิทธิ์ จัดการช่อง / จัดการยศ / จัดการข้อความ ก่อนน้า"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        cfg = get_cfg(guild.id) or {}
        bot_ow = discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                             attach_files=True, manage_messages=True, manage_channels=True,
                                             read_message_history=True)
        try:
            category = guild.get_channel(cfg.get("category_id") or 0)
            if category is None:
                category = await guild.create_category(CATEGORY_NAME, overwrites={me: bot_ow})
            create_ch = guild.get_channel(cfg.get("create_channel_id") or 0)
            if create_ch is None:
                create_ch = await guild.create_text_channel(CREATE_NAME, category=category, overwrites={
                    guild.default_role: discord.PermissionOverwrite(
                        view_channel=True, send_messages=False, read_message_history=True), me: bot_ow})
            log_ch = guild.get_channel(cfg.get("log_channel_id") or 0)
            if log_ch is None:
                log_ch = await guild.create_text_channel(LOG_NAME, category=category, overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False), me: bot_ow})
            if cfg.get("panel_message_id"):
                try:
                    await (await create_ch.fetch_message(cfg["panel_message_id"])).delete()
                except discord.HTTPException:
                    pass
            msg = await create_ch.send(embed=panel_embed(), view=WerewolfPanelView())
        except discord.HTTPException as e:
            return await interaction.followup.send(
                embed=emb(f"{E790} ตั้งค่าไม่สำเร็จ ({e.status}) เช็คสิทธิ์บอทเเล้วลองใหม่น้า"), ephemeral=True)

        q("""INSERT INTO ww_config (guild_id, category_id, create_channel_id, log_channel_id, panel_message_id)
             VALUES (?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET category_id=excluded.category_id,
             create_channel_id=excluded.create_channel_id, log_channel_id=excluded.log_channel_id,
             panel_message_id=excluded.panel_message_id""",
          (guild.id, category.id, create_ch.id, log_ch.id, msg.id))
        await interaction.followup.send(embed=emb(
            f"{E606} ตั้งค่าระบบเกมหมาป่าเเล้วน้าา\n{E767} ห้องสร้างเกม: {create_ch.mention}\n"
            f"{E767} ห้อง log: {log_ch.mention}"), ephemeral=True)

    # ───────── ควบคุมข้อความในห้องเกม ─────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        g = GAMES.get(message.channel.id)
        if g is None or message.author.bot or message.guild is None:
            return
        uid = message.author.id
        p = g.players.get(uid)
        cmd = message.content.strip().lower()

        async def warn(text: str):
            try:
                await message.channel.send(f"{message.author.mention} {E790} {text}", delete_after=4,
                                           allowed_mentions=discord.AllowedMentions(users=[message.author]))
            except discord.HTTPException:
                pass

        async def delete():
            try:
                await message.delete()
            except discord.HTTPException:
                pass

        # คำสั่งในห้อง (ไม่ใช้ตอนกลางคืน)
        if cmd in ("!check", "!check1", "!time") and g.state != "night":
            await delete()
            if g.state == "lobby":
                return await warn("เกมยังไม่เริ่มน้า")
            if cmd == "!time":
                if g.state != "day" or not p or not p.alive:
                    return await warn("!time ใช้ได้ตอนเช้า เเละต้องเป็นผู้เล่นที่ยังไม่ตายน้า")
                need = g.skip_need()
                try:
                    await message.channel.send(
                        embed=emb(f"{E739} ให้พี่ๆโหวตว่าจะข้ามเวลาคุยเลยมั้ย ต้องมีคนกด **{need}** คนถึงจะข้าม (ถ้าคนเหลือน้อย เกณฑ์จะลดลงตามจำนวนคนที่เหลือ)"),
                        view=SkipView(g), delete_after=120)
                except discord.HTTPException:
                    pass
                return
            try:
                await message.channel.send(
                    f"{message.author.mention} กดปุ่มด้านล่างเพื่อดู{'ความสามารถของบทบาท' if cmd == '!check1' else 'การ์ดของพี่'} "
                    "(เห็นคนเดียว)", view=OwnCardView(g, uid, cmd == "!check1"), delete_after=30,
                    allowed_mentions=discord.AllowedMentions(users=[message.author]))
            except discord.HTTPException:
                pass
            return

        # ตอนกลางคืน: ลบทุกข้อความ
        if g.state == "night":
            await delete()
            return await warn("ห้ามพิมพ์ข้อความในระหว่างตอนกลางคืน")

        # ห้ามส่งรูป/ไฟล์/สติกเกอร์ (คนที่มียศส่งได้ บอทลบ+เตือน ครบ 3 รอบลบออกจากเกม)
        if message.attachments or message.stickers or any(e.type in ("image", "gifv") for e in message.embeds):
            await delete()
            if p and p.alive and g.state in ("day", "vote"):
                p.strikes += 1
                if p.strikes >= IMG_STRIKES:
                    dead = await g.kill(uid)
                    g.log(f"{g.name(uid)} ถูกลบออกจากเกมเพราะส่งรูปครบ {IMG_STRIKES} ครั้ง")
                    await g.send(emb(f"{E790} <@{uid}> ส่งรูปครบ {IMG_STRIKES} ครั้ง ถูกลบออกจากเกมเเล้ว"
                                     + "".join(f"\n<@{d}> ตายตามคนรักไป" for d in dead if d != uid)))
                else:
                    await warn(f"ห้ามส่งรูปในเกมน้า ({p.strikes}/{IMG_STRIKES}) ครบเเล้วจะโดนลบออกจากเกม")
            else:
                await warn("ห้ามส่งรูปในห้องเกมน้า")
            return

        # ข้อความของผู้เล่นที่ตายเเล้ว / โดนใบ้ / ออกจากหมู่บ้าน → ลบ
        if p and g.state in ("day", "vote"):
            if not p.alive:
                await delete()
                return await warn("พี่ตายเเล้ว พิมพ์ไม่ได้น้า")
            if uid in g.silenced:
                await delete()
                return await warn("พี่โดนใบ้ พิมพ์ไม่ได้ตลอดวันนี้")
            if uid in g.away:
                await delete()
                return await warn("พี่ออกจากหมู่บ้านอยู่ พิมพ์ไม่ได้ในวันนี้")


async def setup(bot: commands.Bot):
    await bot.add_cog(WerewolfCog(bot))
