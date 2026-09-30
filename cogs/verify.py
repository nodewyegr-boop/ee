import asyncio
import random
from typing import Any, Dict, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from database import db

WHITE = discord.Color.from_rgb(255, 255, 255)  # เส้นสีขาวข้าง embed
PANEL_GIF = "https://cdn.discordapp.com/attachments/1489587803393364018/1554940385783189715/63b77fcf355e5479a829edc99252be68.gif?backend=b2&ex=6abeb695&is=6abd6515&hm=ca01cfc7ff4bece39745258b1bb6560f360380cd9adb4a7a1cb910568e3c417c&"

# ───────────── อีโมจิ ─────────────
NO = "<a:1000035729:1554863632528052315>"
OK = "<a:1000035606:1554848463320129567>"
E604 = "<a:1000035604:1554847795524141216>"
E603 = "<a:1000035603:1554845277071089736>"
E608 = "<a:1000035608:1554844998506123274>"
E727 = "<a:1000035727:1554859928957755393>"
E741 = "<a:1000035741:1554876169017499658>"
E740 = "<a:1000035740:1554874072205107263>"
E742 = "<a:1000035742:1554876309790793908>"
E743 = "<a:1000035743:1554882610134524034>"
E744 = "<a:1000035744:1554884849406451762>"
E745 = "<a:1000035745:1554887740028485743>"
E725 = "<a:1000035725:1554844594175483904>"
E726 = "<a:1000035726:1554859496894111744>"
E724 = "<a:1000035724:1554844520674500678>"
E602 = "<a:1000035602:1554844971931275325>"
E607 = "<a:1000035607:1554874918632562788>"
E739 = "<a:1000035739:1554873266987081742>"
E760 = "<a:1000035760:1554908193174589581>"
E757 = "<a:1000035757:1554907672502083694>"
E762 = "<a:1000035762:1554919569682989166>"
E763 = "<a:1000035763:1554920997382262874>"
E764 = "<a:1000035764:1554920142146904164>"
E767 = "<a:1000035767:1554921960838926417>"
E597 = "<a:1000035597:1554848439035240449>"
E728 = "<a:1000035728:1554860189125967894>"


def pe(s: str) -> discord.PartialEmoji:
    return discord.PartialEmoji.from_str(s)


def emb(desc: str) -> discord.Embed:
    return discord.Embed(description=desc, color=WHITE)


# ───────────── state ในหน่วยความจำ ─────────────
STATE: Dict[Tuple, Any] = {}      # เลขที่สุ่ม / คำใบ้ที่ผู้เล่นได้รับ
SETTINGS: Dict[Tuple, Dict] = {}  # ค่าที่แอดมินเลือกไว้ก่อนกดเริ่ม
BUSY: set = set()                 # กันกดปุ่ม 3 วิซ้อน


def is_admin(member) -> bool:
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def can_give(guild: discord.Guild, role: discord.Role) -> bool:
    me = guild.me
    return bool(
        me.guild_permissions.manage_roles
        and not role.managed
        and not role.is_default()
        and role < me.top_role
    )


async def reply(interaction: discord.Interaction, embed: discord.Embed, view=None, edit=False):
    """ส่งข้อความแบบเห็นคนเดียว (ephemeral) ใช้ได้ทั้งตอนยังไม่ตอบ/ตอบแล้ว"""
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    elif edit:
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def reset_menu(interaction: discord.Interaction, view_cls):
    """รีเซ็ตโมดูลบนแผงให้กลับเป็นไม่ได้เลือก จะได้กดตัวเลือกเดิมซ้ำได้"""
    try:
        await interaction.message.edit(view=view_cls())
    except Exception:
        pass


async def grant(interaction: discord.Interaction, system: str, good_text: str, edit=False):
    """ให้ยศตามที่เซ็ตไว้ใน database"""
    panel = db.get_panel(interaction.guild.id, system)
    role = interaction.guild.get_role(panel[1]) if panel else None
    if role is None:
        return await reply(interaction, emb(f"{NO} ระบบนี้ยังไม่ได้เซ็ต หรือยศถูกลบไปแล้วน้า"), edit=edit)
    if role in interaction.user.roles:
        return await reply(interaction, emb(f"{E604} พี่มียศ {role.mention} อยู่แล้วน้าา"), edit=edit)
    try:
        await interaction.user.add_roles(role, reason=f"verify: {system}")
    except discord.Forbidden:
        return await reply(interaction, emb(f"{NO} น้องยศไม่ถึง พี่ๆให้ยศน้องก่อนน"), edit=edit)
    except discord.HTTPException:
        return await reply(interaction, emb(f"{NO} มีบางอย่างผิดพลาด ลองใหม่อีกทีน้า"), edit=edit)
    await reply(interaction, emb(good_text.replace("{role}", role.mention)), edit=edit)


# ═════════════ 1) กรอกเลขรับยศ ═════════════
class NumberModal(discord.ui.Modal, title="กรอกเลขรับยศ"):
    answer = discord.ui.TextInput(
        label="กรอกเลขที่ถูกซ่อนไว้", placeholder="เช่น 1234",
        min_length=1, max_length=4,
    )

    async def on_submit(self, interaction: discord.Interaction):
        key = ("number", interaction.guild.id, interaction.user.id)
        code = STATE.pop(key, None)
        if code is None:
            return await reply(interaction, emb(f"{NO} พี่ต้องกดรับเลขที่ถูกซ่อนไว้ก่อนน้าา"))
        if self.answer.value.strip() == str(code):
            await grant(interaction, "number", f"{OK} เย้ พี่ๆกรอกถูกต้อง ได้รับยศ {{role}}")
        else:
            await reply(interaction, emb(f"{NO} พี่ๆกรอกไม่ถูกน้าาา มาลองกันใหม่ เฉลยคือเลขขข **{code}**"))


class NumberVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        sel = discord.ui.Select(
            custom_id="verify:number:menu",
            placeholder="กดตรงนี้เลยย",
            options=[
                discord.SelectOption(label="รับเลขที่ถูกซ่อนไว้", value="get", emoji=pe(E740)),
                discord.SelectOption(label="กรอกเลข", value="enter", emoji=pe(E727)),
                discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji=pe(E604)),
            ],
        )
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        key = ("number", interaction.guild.id, interaction.user.id)
        if v == "get":
            code = random.randint(1000, 9999)
            STATE[key] = code
            await reply(interaction, emb(f"{E740} เลขของพี่คือ ||{code}||\nกดที่เลขเพื่อเปิดดู แล้วไปเลือก **กรอกเลข** ได้เลยน้าา"))
        elif v == "enter":
            await interaction.response.send_modal(NumberModal())
        else:
            STATE.pop(key, None)
            await reply(interaction, emb(f"{OK} ล้างตัวเลือกสำเร็จ"))
        await reset_menu(interaction, NumberVerifyView)


# ═════════════ 2) กดปุ่มรอ 3 วิ ═════════════
class ButtonPickView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)
        good = random.randrange(3)  # ตำแหน่งปุ่มเขียว สุ่มซ้าย/กลาง/ขวา
        for i in range(3):
            btn = discord.ui.Button(
                emoji=pe(E742) if i == good else pe(E743),  # เขียว=E742, แดง=E743
                style=discord.ButtonStyle.success if i == good else discord.ButtonStyle.danger,
            )
            btn.callback = self._make_cb(i == good)
            self.add_item(btn)

    def _make_cb(self, correct: bool):
        async def cb(interaction: discord.Interaction):
            self.stop()
            if correct:
                await grant(interaction, "button", f"{E603} เย้ๆๆ พี่กดถูกก เก่งมากก น้องให้ยศ {{role}} ให้พี่แล้วน้าา", edit=True)
            else:
                await reply(interaction, emb(f"{E604} พี่ๆกดไม่ถูกน้าาา ต้องกดสีเขียว ไว้มาลองอีกทีน้าา"), edit=True)
        return cb


class Button3SecVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="เริ่ม", style=discord.ButtonStyle.success,
                       custom_id="verify:button:start", emoji=pe(E739))
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        key = (interaction.guild.id, interaction.user.id)
        if key in BUSY:
            return await reply(interaction, emb(f"{E604} รอแป๊บนึงน้าา กำลังนับอยู่"))
        BUSY.add(key)
        try:
            def cd(n):
                return emb(f"{E744} พี่เตรียมตัวนะ น้องจะส่งปุ่มให้พี่ๆกดในอีก **{n}**")
            await interaction.response.send_message(embed=cd(3), ephemeral=True)
            for n in (2, 1, 0):
                await asyncio.sleep(1)
                await interaction.edit_original_response(embed=cd(n))
            await interaction.edit_original_response(
                embed=emb(f"# พี่ๆต้องกดปุ่มให้ถูกเเล้วน้องจะให้ยศพี่ๆ {E740}"),
                view=ButtonPickView(),
            )
        except discord.HTTPException:
            pass
        finally:
            BUSY.discard(key)


# ═════════════ 3-5) เดาสัตว์ / ทายอายุ / เดาเกม (โครงเดียวกัน) ═════════════
QUIZ = {
    "animal": {
        "placeholder": "คำใบ้เเละตอบ",
        "menu": [("รับคำใบ้", "hint", E740), ("พร้อมเดาเเล้วว", "answer", E608), ("ล้างตัวเลือก", "clear", E725)],
        "hint_title": f"{E740} คำใบ้ทายสัตว์",
        "hint_tail": "สัตว์ตัวนี้คือตัวอะไร",
        "answer_placeholder": "เลือกคำตอบเลยย",
        "ok": f"{E742} เย้ๆๆ เก่งมากพี่ที่ทายถูก น้องให้ยศ {{role}} แล้วน้าาา",
        "bad": f"{E743} โอ๋ๆไม่เป็นไรนะพี่ ไว้มาตอบใหม่น้าา",
        "choices": [
            ("นก", "<a:1000035759:1554908021115719791>"),
            ("หมา", "<:1000035758:1554907814894501911>"),
            ("แมว", "<a:1000035757:1554907672502083694>"),
            ("ค้างคาว", "<a:1000035752:1554907270393892986>"),
            ("จิงโจ้", "<a:1000035761:1554908402977742918>"),
            ("งู", "<a:1000035750:1554907022657589388>"),
            ("ลิง", "<a:1000035749:1554906589331329074>"),
            ("กุ้ง", "<a:1000035747:1554906257163559004>"),
            ("นกแก้ว", "<a:1000035748:1554906430233116694>"),
            ("ไฮยีนาลายจุด", "<a:1000035760:1554908193174589581>"),
        ],
        # (คำใบ้, index คำตอบที่ถูกใน choices)  — คำตอบไม่ถูกส่งไปในคำใบ้
        "hints": [
            ("สัตว์ตัวนี้ มีขน บินได้ ทำที่อยู่บนต้นไม้ บางชนิดอยู่ด้วยกันเป็นฝูง พบได้ทั่วโลก แต่ละชนิดสีอาจแตกต่างกันไป ชอบทำรังบนหลังคาบ้านคน", 0),
            ("สัตว์ตัวนี้ อยู่ด้วยกันเป็นฝูง พบมากในทวีปแอฟริกา มีแรงกัดที่สูงมากจนสามารถกดและเคี้ยวกระดูกได้สบาย หากินด้วยกัน ตัวเมียมักใหญ่กว่าตัวผู้", 9),
            ("สัตว์ตัวนี้ อยู่ด้วยกันเป็นฝูง ตัวสีน้ำตาลๆ ตัวเล็ก มีลักษณะคล้ายๆคน มีหาง ชอบกินกล้วย พบบ่อยในจังหวัดลพบุรี (ตอนนี้น่าจะไม่ค่อยมีให้เห็นแล้ว)", 6),
            ("สัตว์ตัวนี้ บางพันธุ์มีขนบางพันธุ์ไม่มีขน คนนิยมเอามาเลี้ยง และในประเทศไทยยังมีกฎหมายคุ้มครองสัตว์ตัวนี้ ถ้าเลี้ยงไว้ที่บ้านมักจะไม่มีหนู", 2),
            ("สัตว์ตัวนี้ คนนิยมเอามาเลี้ยงในบ้าน มีการ์ตูนที่มีสัตว์ตัวนี้อยู่ และเด็กๆชอบดู มีกฎหมายคุ้มครองสัตว์ตัวนี้ในประเทศไทย ถ้าเลี้ยงดีๆก็จะไม่ทำร้ายใคร แต่ถ้าเลี้ยงไม่ดีอาจไปทำร้ายคนอื่นได้", 1),
            ("สัตว์ตัวนี้ มีถุงที่หน้าท้อง ไว้ใช้สำหรับเป็นที่อยู่ให้ลูก แรกเกิดจะตัวเล็กมาก ประมาณนิ้วคน ตัวผู้โตเต็มวัยมักจะมีกล้าม และมีขนสีน้ำตาลสั้น", 4),
            ("สัตว์ตัวนี้ ในอดีตหลายล้านปี อาจจะมีขา บางชนิดตัวใหญ่บางชนิดตัวเล็ก มีพิษบ้างไม่มีบ้าง คนบางกลุ่มนิยมเลี้ยง บางคนกลัวบางคนชอบ มีลิ้น 2 แฉก หากินได้ทั้งบนบกและในน้ำ", 5),
            ("สัตว์ตัวนี้ บางชนิดใหญ่บางชนิดเล็ก คนชอบเอามากิน สุกบ้างดิบบ้าง เคลื่อนที่ไวใช้มือเปล่าจับแทบไม่ได้ บางชนิดโตเต็มวัยมีก้ามที่ใหญ่และยาวมาก", 7),
            ("สัตว์ตัวนี้ คนนิยมเอามาเลี้ยงเป็นสัตว์สวยงาม บางชนิดถ้าฝึกดีๆมันสามารถพูดได้ มีหลายสี มีเกมที่มีสัตว์ตัวนี้เป็นตัวหลักของเกม และบินได้", 8),
            ("สัตว์ตัวนี้ อาจจะเป็นต้นเหตุของโรคโควิด19 บินได้ นอนโดยการห้อยหัวลงมา หากินตอนมืด มักอยู่ในถ้ำหรือที่มืดๆ", 3),
        ],
    },
    "age": {
        "placeholder": "เลือกเเละเดา",
        "menu": [("คำใบ้", "hint", E724), ("เลือกตอบ", "answer", E726), ("ล้างตัวเลือก", "clear", E757)],
        "hint_title": f"{E740} คำใบ้อายุของหนู",
        "hint_tail": "หนูอายุเท่าไหร่เอ่ยยย",
        "answer_placeholder": "เลือกอายุที่คิดว่าใช่เลยย",
        "ok": f"{E762} เย้ๆๆๆๆ พี่เก่งมากกก ทายอายุหนูถูกด้วยย หนูให้ยศแล้วน้าา {{role}}",
        "bad": f"{E764} โอ๋ๆ ไม่เป็นไรน้าา พี่ เอาใหม่นะพี่ เดี๋ยวหนูใบ้ให้ง่ายกว่าเดิมน้าาา",
        "choices": [
            ("1 ขวบ", E724), ("7 ขวบ", E725), ("15 ปี", E602), ("22 ปี", E608), ("25 ปี", E603),
            ("26 ปี", E604), ("46 ปี", E597), ("50 ปี", E726), ("60 ปี", E727), ("100 ปี", E728),
        ],
        "hints": [
            ("อายุของหนูยังเป็นเด็กเล็กอยู่ ยังไม่สามารถทำบัตรประชาชนได้ และยังต้องกินนมอยู่ และยังเดินเองไม่ได้", 0),
            ("อายุของหนู เกษียณแล้ว เพิ่งเกษียณเลย เริ่มมีผมหงอก แต่ยังเดินไหวขับรถไหว ถ้ามีลูก ลูกน่าจะอายุ 25-30 ได้", 8),
            ("อายุของหนู บางคนอาจจะยังศึกษาอยู่ที่มหาวิทยาลัย บางคนก็ทำงาน บางคนก็มีชีวิตคู่แล้ว อายุสามารถจดทะเบียนสมรสได้แล้ว", 3),
            ("อายุของหนู คนมักบอกว่าอายุเท่านี้เป็นคำสาป เพราะคนมักบอกว่า เบญจเพส จะเกิดตอนอายุเท่านี้ อายุหนูจดทะเบียนสมรสได้แล้ว", 4),
            ("อายุของหนู อยู่ในวัยทำงาน อายุประมาณนี้คนก็เริ่มแต่งงานกันแล้ว อยู่ในช่วงพีคของร่างกาย เพราะอวัยวะทุกส่วนจะอยู่ในช่วงทอง ทำงานได้เต็มที่ อายุหนูอาจจะมากกว่า 22 รึเปล่าน้าา", 5),
            ("อายุของหนู เดินไม่ไหวแล้ว คนส่วนใหญ่อายุไม่ค่อยจะถึงเพราะจะเสียชีวิตก่อน ผมขาวหมดแล้ว ผิวหนังเหี่ยวย่น ทำอะไรก็ลำบาก ปัสสาวะเองไม่ได้", 9),
            ("อายุของหนู อีกสัก 10 ปีต้องเกษียณแล้ว ยังเดินไหวทำอะไรไหว แต่บางคนโรคต่างๆเริ่มถามหาแล้ว แต่ส่วนใหญ่ก็ร่างกายยังไหว ยังทำงานไหว", 7),
            ("อายุของหนู อยู่ประมาณ ม.2-3 กำลังเข้าช่วงวัยรุ่น อยู่ในวัยลองผิดลองถูก อายุของหนูมากกว่า 13 แล้วส่วนใหญ่เริ่มจะขับรถได้แล้ว", 2),
            ("อายุของหนู ทำบัตรประชาชนได้แล้ว เข้าโรงเรียนแล้วบางคนก็ ป.1 ป.2 อายุน้อยกว่า 10 อายุหนูเขียนหนังสือได้แล้ว อยู่ gen Alpha", 1),
            ("อายุของหนู เริ่มมีอายุแล้ว หลายๆคนมีลูกแล้ว มีการงานมั่นคง มีชีวิตที่ดี ลูกอาจจะอายุ 17-19 ถ้ามีลูกไว ทำงานไหวสบายๆ แต่หลายๆคนสายตาอาจจะเริ่มไม่ดีเหมือนแต่ก่อน", 6),
        ],
    },
    "game": {
        "placeholder": "เซ็ตระบบ",
        "menu": [("รับคำใบ้", "hint", E767), ("พร้อมตอบบ", "answer", E762), ("ล้างตัวเลือก", "clear", E727)],
        "hint_title": f"{E763} คำใบ้เกม",
        "hint_tail": "เกมนี้คือเกมอะไรเอ่ยยย",
        "answer_placeholder": "เลือกเกมที่คิดว่าใช่เลยย",
        "ok": f"{E763} เย้ๆๆๆ เก่งมากกก หนูให้ยศพี่แล้วน้าาา {{role}}",
        "bad": f"{E764} ไม่เป็นไรน้าาาพี่ เอาใหม่ เดี๋ยวดูให้คำใบ้ง่ายกว่าเดิมให้เองง",
        "choices": [
            ("Free Fire", "<:1000035768:1554926218451882035>"),
            ("ROV", "<:1000035774:1554927462742499448>"),
            ("Valorant", "<:1000035770:1554926594475171970>"),
            ("Roblox", "<:1000035771:1554926800058982440>"),
            ("Minecraft", "<:1000035772:1554926984545439814>"),
            ("เปส", "<:1000035773:1554927297356898445>"),
        ],
        "hints": [
            ("เกมนี้ เป็นเกมเน้นยิงกัน มีคำศัพท์ต่างๆ เช่น มห มต เป็นเกมโดดร่ม มีหลายโหมด สร้างห้องเล่นกับเพื่อนได้ เป็นเกมที่เกลือมาก", 0),
            ("เกมนี้ มีป้อมให้ตี มีหลายร้อยตัวละคร มีหลายสกินให้ใส่ มีแรงค์ ยอดดาวน์โหลดเกิน 500M เล่นบ่อยๆจะหัวร้อน", 1),
            ("เกมนี้เป็นเกมที่เปิดให้คนมาสร้างเกมได้ แต่งตัวได้ เด็กๆชอบเล่น ผู้ใหญ่หลายๆคนก็เล่น มีลูกเล่นเยอะมาก อาจจะยิงปืน แต่งตัว พูดคุย", 3),
            ("เกมนี้ เป็นสี่เหลี่ยม ปกเกมเป็นพื้นหญ้า มีมอนสเตอร์เยอะมาก เลี้ยงสัตว์ได้ สร้างบ้านสร้างเซิฟให้คนมาเล่นได้ สมัยก่อนการเล่นกับเพื่อนในเซิฟส่วนตัวเป็นเรื่องที่ยากมาก", 4),
            ("เกมนี้ เป็นเกมที่เน้นเตะบอล เปิดการ์ดเอาตัวละคร มีหลายโหมด ผู้ชายเล่นกันเยอะ ขึ้นต้นด้วย เ เล่นกับเพื่อนได้ ลงแรงค์ได้", 5),
            ("เกมนี้ เน้นยิงกัน มีหลายโหมด แรงค์ ทั่วไป 2v2 1v1 โหมดปกติเล่นนานมาก บางเกมมากกว่า 30 นาที มีหลายตัวละคร มีสกิลปืนหลายอย่างลูกเล่นเยอะ", 2),
        ],
    },
}


class AnswerView(discord.ui.View):
    """เมนูเลือกคำตอบ (เห็นคนเดียว)"""
    def __init__(self, system: str):
        super().__init__(timeout=180)
        self.system = system
        cfg = QUIZ[system]
        sel = discord.ui.Select(
            placeholder=cfg["answer_placeholder"],
            options=[discord.SelectOption(label=l, value=str(i), emoji=pe(e))
                     for i, (l, e) in enumerate(cfg["choices"])],
        )
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        cfg = QUIZ[self.system]
        key = (self.system, interaction.guild.id, interaction.user.id)
        correct = STATE.pop(key, None)
        if correct is None:
            return await reply(interaction, emb(f"{NO} ต้องกดรับคำใบ้ก่อนน้าาพี่"), edit=True)
        self.stop()
        if int(interaction.data["values"][0]) == correct:
            await grant(interaction, self.system, cfg["ok"], edit=True)
        else:
            await reply(interaction, emb(cfg["bad"]), edit=True)


class QuizPanelView(discord.ui.View):
    system = ""

    def __init__(self):
        super().__init__(timeout=None)
        cfg = QUIZ[self.system]
        sel = discord.ui.Select(
            custom_id=f"verify:{self.system}:menu",
            placeholder=cfg["placeholder"],
            options=[discord.SelectOption(label=l, value=v, emoji=pe(e)) for l, v, e in cfg["menu"]],
        )
        sel.callback = self.on_select
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        cfg = QUIZ[self.system]
        v = interaction.data["values"][0]
        key = (self.system, interaction.guild.id, interaction.user.id)
        if v == "hint":
            idx = random.randrange(len(cfg["hints"]))
            STATE[key] = cfg["hints"][idx][1]
            text = f"# {cfg['hint_title']}\n\n{cfg['hints'][idx][0]}\n\n**{cfg['hint_tail']}**"
            await reply(interaction, emb(text))
        elif v == "answer":
            if key not in STATE:
                await reply(interaction, emb(f"{NO} ต้องกดรับคำใบ้ก่อนน้าาพี่"))
            else:
                await reply(interaction, emb(f"{E740} เลือกคำตอบได้เลยย"), view=AnswerView(self.system))
        else:
            STATE.pop(key, None)
            await reply(interaction, emb(f"{OK} ล้างตัวเลือกสำเร็จ"))
        await reset_menu(interaction, type(self))


class AnimalVerifyView(QuizPanelView):
    system = "animal"


class AgeVerifyView(QuizPanelView):
    system = "age"


class GameVerifyView(QuizPanelView):
    system = "game"


# ═════════════ ข้อความแผง (embed) ที่บอทส่งไปห้อง ═════════════
def build_panel(system: str, role: discord.Role):
    if system == "number":
        desc = (
            f"# {E726} กรอกเลขรับยศ {E726}\n\n"
            "พี่ๆต้องกดลิสด้านล่างก่อน เเล้วเลือกรับเลข หลังจากพี่ๆกดหนูจะให้เลขที่ถูกซ่อนมา "
            "เเล้วพี่ๆก็กดรับเลข ทีนี้พี่ๆก็ใส่เลขที่น้องซ่อนให้พวกพี่หาได้เลย "
            f"{E740}\n\n{E742} ยศที่พี่ๆจะได้ {role.mention}"
        )
        view = NumberVerifyView()
    elif system == "button":
        desc = (
            f"# {E743} รับยศแบบปุ่ม\n\n"
            f"{E740} ให้พี่ๆกดปุ่มเริ่มด้านล่างเเล้วกดปุ่มให้ถูกเดียวน้องจะให้ยศเเก่พี่ๆเองง\n\n"
            f"ยศที่พี่ๆจะได้ {role.mention}"
        )
        view = Button3SecVerifyView()
    elif system == "animal":
        desc = (
            f"# {E745} รับยศเดาสัตว์ {E745}\n\n"
            f"{E744} พี่ๆกดลิสด้านล่างมาก่อน เเล้วพี่ๆกดรับคำใบ้ อ่านคำใบ้เเล้วพี่ๆก็มาเลือกคำตอบ "
            f"ถ้าถูกเดียวน้องให้รางวัลเป็นยศเเก่พี่เองง\n\nยศที่จะได้รับ {role.mention}"
        )
        view = AnimalVerifyView()
    elif system == "age":
        desc = (
            f"# {E740} เดาอายุรับยศ {E740}\n\n"
            "พี่ๆกดลิสด้านล่างรับคำใบ้อายุหนู เเล้วพี่ๆก็มาเลือกดูว่าหนูอายุเท่าไหร่เอ่ยยย\n\n"
            f"ถ้าพี่ๆทายถูกหนูจะให้ยศ {role.mention} พี่เองง"
        )
        view = AgeVerifyView()
    else:  # game
        desc = (
            f"# {E763} เดาเกมรับยศ {E763}\n\n"
            f"{E764} พี่ๆกดลิสด้านล่างรับคำใบ้ เเล้วเลือกเกมที่คิดว่าใช่ ถ้าทายถูกหนูให้ยศ {role.mention} เองน้าา"
        )
        view = GameVerifyView()
    embed = emb(desc)
    embed.set_image(url=PANEL_GIF)  # gif ใต้แผงรับยศทุกแบบ
    return embed, view


# ═════════════ เซ็ตระบบ (ฝั่งแอดมิน) ═════════════
SETUP = {
    "number": dict(
        desc=f"# {E725} กรอกเลขรับยศ\n\nเลือกห้องเเละยศ เเล้วกดเริ่มได้เลยย",
        placeholder="เลือกห้องเเละยศ",
        labels=("เลือกยศ", "เลือกห้องที่จะให้รับ", "เริ่มม", "ล้างตัวเลือก"),
        done=lambda ch: f"{OK} สำเร็จ การรับยศถูกส่งไปที่ห้อง {ch}",
    ),
    "button": dict(
        desc=f"# {E743} กดปุ่มรอ3วิ\n\nพี่ๆเลือกยศที่จะให้ ห้อง เเละกดเริ่มได้เลยยย {E604}",
        placeholder="เซ็ตระบบ",
        labels=("เลือกยศ", "เลือกห้อง", "เริ่ม", "ล้างตัวเลือก"),
        done=lambda ch: f"{E741} สำเร็จเเล้วน้าาพี่ๆ ห้องที่รับยศคืออ {ch}",
    ),
    "animal": dict(
        desc=f"# {E741} รับยศโดยการเดาสัตว์ {E741}\n\nพี่ๆ เลือกยศ เลือกห้อง กดเริ่ม เเล้วก็เริ่มเดาได้เลยย {E604}",
        placeholder="เซ็ตระบบ",
        labels=("เลือกยศ", "เลือกห้อง", "เริ่มม", "ล้างตัวเลือก"),
        done=lambda ch: f"{E727} หนูส่งข้อความไปที่ห้อง {ch} เเล้วน้าา พี่ลองได้ดูด้ายย",
    ),
    "age": dict(
        desc=f"# เดาอายุรับยศ {E760}\n\n{E603} พี่ๆกรอกยศ ห้อง เเละกดเริ่มให้หนูหน่อยย",
        placeholder="กรอกข้อมูล",
        labels=("เลือกยศ", "เลือกช่อง", "เริ่ม", "ล้างตัวเลือก"),
        done=lambda ch: f"หนูสร้างให้พี่เเล้วน้าาา พี่ลองไปดูหน่อยยย {ch}",
    ),
    "game": dict(
        desc=f"# {E763} เดาเกมรับยศ {E763}\n\n{E764} พี่ๆเลือกยศ ห้อง กดเริ่มให้หนูด้วยน้าาา",
        placeholder="เซ็ตระบบ",
        labels=("เลือกยศ", "เลือกห้อง", "เริ่ม", "ล้างตัวเลือก"),
        done=lambda ch: f"{E763} หนูส่งข้อความไปที่ห้อง {ch} เเล้วน้าา พี่ลองได้ดูด้ายย",
    ),
}


class RolePickView(discord.ui.View):
    def __init__(self, key):
        super().__init__(timeout=180)
        self.key = key
        sel = discord.ui.RoleSelect(placeholder="เลือกยศที่จะให้", min_values=1, max_values=1)
        sel.callback = self.on_select
        self.sel = sel
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        role = self.sel.values[0]
        SETTINGS.setdefault(self.key, {})["role"] = role.id
        await interaction.response.edit_message(embed=emb(f"{OK} เลือกยศ {role.mention} เเล้วน้าา"), view=None)


class ChannelPickView(discord.ui.View):
    def __init__(self, key):
        super().__init__(timeout=180)
        self.key = key
        sel = discord.ui.ChannelSelect(
            placeholder="เลือกห้องที่จะส่งแผง",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=1,
        )
        sel.callback = self.on_select
        self.sel = sel
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        ch = self.sel.values[0]
        SETTINGS.setdefault(self.key, {})["channel"] = ch.id
        await interaction.response.edit_message(embed=emb(f"{OK} เลือกห้อง <#{ch.id}> เเล้วน้าา"), view=None)


class SetupView(discord.ui.View):
    def __init__(self, system: str, owner_id: int):
        super().__init__(timeout=600)
        self.system, self.owner_id = system, owner_id
        cfg = SETUP[system]
        lr, lc, ls, lx = cfg["labels"]
        sel = discord.ui.Select(
            placeholder=cfg["placeholder"],
            options=[
                discord.SelectOption(label=lr, value="role", emoji=pe(E741)),
                discord.SelectOption(label=lc, value="channel", emoji=pe(E742)),
                discord.SelectOption(label=ls, value="start", emoji=pe(E608)),
                discord.SelectOption(label=lx, value="clear", emoji=pe(E724)),
            ],
        )
        sel.callback = self.on_select
        self.add_item(sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not is_admin(interaction.user):
            await reply(interaction, emb(f"{NO} คุณไม่มีสิทธิ์ใช้งาน!!"))
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        v = interaction.data["values"][0]
        key = (interaction.guild.id, interaction.user.id, self.system)
        await interaction.response.edit_message(view=self)  # รีเซ็ตเมนู
        if v == "role":
            await interaction.followup.send(embed=emb(f"{E741} เลือกยศที่จะให้รับ"), view=RolePickView(key), ephemeral=True)
        elif v == "channel":
            await interaction.followup.send(embed=emb(f"{E742} เลือกห้องที่จะให้ส่ง"), view=ChannelPickView(key), ephemeral=True)
        elif v == "clear":
            SETTINGS.pop(key, None)
            await interaction.followup.send(embed=emb(f"{OK} ล้างตัวเลือกสำเร็จ"), ephemeral=True)
        else:
            await self.start(interaction, key)

    async def start(self, interaction: discord.Interaction, key):
        guild = interaction.guild
        cfg = SETTINGS.get(key, {})
        role = guild.get_role(cfg.get("role", 0))
        channel = guild.get_channel(cfg.get("channel", 0))

        async def err(text):
            await interaction.followup.send(embed=emb(f"{NO} {text}"), ephemeral=True)

        if role is None or channel is None:
            return await err("เลือกยศกับห้องให้ครบก่อนน้าาพี่ๆ")
        if not can_give(guild, role):
            return await err("น้องยศไม่ถึง พี่ๆให้ยศน้องก่อนน")
        p = channel.permissions_for(guild.me)
        if not (p.view_channel and p.send_messages and p.embed_links):
            return await err("น้องส่งข้อความในห้องนั้นไม่ได้น้า ช่วยเปิดสิทธิ์ให้น้องหน่อยย")

        embed, view = build_panel(self.system, role)
        try:
            await channel.send(embed=embed, view=view)
        except discord.HTTPException:
            return await err("ส่งแผงไปที่ห้องไม่สำเร็จ ลองใหม่อีกทีน้า")
        db.save_panel(guild.id, self.system, channel.id, role.id)
        await interaction.followup.send(embed=emb(SETUP[self.system]["done"](channel.mention)), ephemeral=True)


# ═════════════ /verify ═════════════
class VerifyMenuView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        sel = discord.ui.Select(
            placeholder="เลือกระบบยืนยันตัวตนรับยศ",
            options=[
                discord.SelectOption(label="กรอกเลขรับยศ", value="number", emoji=pe(E727)),
                discord.SelectOption(label="กดปุ่มรอ3วิ", value="button", emoji=pe(E608)),
                discord.SelectOption(label="เดาสัตว์", value="animal", emoji=pe(E741)),
                discord.SelectOption(label="ทายอายุ", value="age", emoji=pe(E740)),
                discord.SelectOption(label="เดาเกมรับยศ", value="game", emoji=pe(E607)),
            ],
        )
        sel.callback = self.on_select
        self.add_item(sel)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id or not is_admin(interaction.user):
            await reply(interaction, emb(f"{NO} คุณไม่มีสิทธิ์ใช้งาน!!"))
            return False
        return True

    async def on_select(self, interaction: discord.Interaction):
        system = interaction.data["values"][0]
        await interaction.response.edit_message(view=self)  # รีเซ็ตเมนู
        await interaction.followup.send(
            embed=emb(SETUP[system]["desc"]),
            view=SetupView(system, interaction.user.id),
            ephemeral=True,
        )


class VerifyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="verify", description="คำสั่งสำหรับรับยศ")
    @app_commands.guild_only()
    async def verify(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                embed=emb(f"{NO} คุณไม่มีสิทธิ์ใช้งาน!!"), ephemeral=True)
        await interaction.response.send_message(
            embed=emb(f"# Verify identity {E604}\n\nโปรดเลือกระบบการยืนยันตัวตนด้วยค่ะ {E603}"),
            view=VerifyMenuView(interaction.user.id),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(VerifyCog(bot))
