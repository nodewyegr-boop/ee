import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from database import db

# ------------------------------------------------------------------
# 1. PERSISTENT VIEWS (หน้าต่างรับยศในช่องแชท)
# ------------------------------------------------------------------

# Modal สำหรับกรอกเลข
class NumberInputModal(discord.ui.Modal, title="กรอกเลขรับยศ"):
    number_input = discord.ui.TextInput(
        label="กรอกเลขที่ซ่อนอยู่ (1000-9999)",
        placeholder="เช่น 4582",
        min_length=4,
        max_length=4,
        required=True
    )

    def __init__(self, correct_number: int, role_id: int):
        super().__init__()
        self.correct_number = correct_number
        self.role_id = role_id

    async def on_submit(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message(
                embed=discord.Embed(description="<a:1000035729:1554863632528052315> ไม่พบบทบาทในระบบ", color=0xFFFFFF),
                ephemeral=True
            )
            return

        if self.number_input.value.strip() == str(self.correct_number):
            try:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"<a:1000035606:1554848463320129567> เย้ พี่ๆกรอกถูกต้อง ได้รับยศ {role.mention}",
                        color=0xFFFFFF
                    ),
                    ephemeral=True
                )
            except Exception:
                await interaction.response.send_message(
                    embed=discord.Embed(description="<a:1000035729:1554863632528052315> บอทไม่มีสิทธิ์ให้ยศนี้", color=0xFFFFFF),
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"<a:1000035729:1554863632528052315> พี่ๆกรอกไม่ถูกน้าาา มาลองกันใหม่ เฉลยคือเลขขข {self.correct_number}",
                    color=0xFFFFFF
                ),
                ephemeral=True
            )

# Panel 1: กรอกเลขรับยศ
class NumberVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.user_numbers = {}

    @discord.ui.select(
        placeholder="กดตรงนี้เลยย",
        custom_id="verify_number_select",
        options=[
            discord.SelectOption(label="รับเลขที่ถูกซ่อนไว้", value="get_num", emoji="<a:1000035740:1554874072205107263>"),
            discord.SelectOption(label="กรอกเลข", value="enter_num", emoji="<a:1000035727:1554859928957755393>"),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji="<a:1000035604:1554847795524141216>")
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        panel = db.get_panel(interaction.guild_id, "number")
        if not panel:
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> ระบบยังไม่ได้ตั้งค่า", color=0xFFFFFF), ephemeral=True)
            return
        
        _, role_id = panel

        if val == "get_num":
            num = random.randint(1000, 9999)
            self.user_numbers[interaction.user.id] = num
            await interaction.response.send_message(content=f"||{num}||", ephemeral=True)

        elif val == "enter_num":
            if interaction.user.id not in self.user_numbers:
                await interaction.response.send_message(
                    embed=discord.Embed(description="<a:1000035729:1554863632528052315> พี่ๆต้องกดรับเลขก่อนน้าา", color=0xFFFFFF),
                    ephemeral=True
                )
                return
            modal = NumberInputModal(self.user_numbers[interaction.user.id], role_id)
            await interaction.response.send_modal(modal)

        elif val == "clear":
            if interaction.user.id in self.user_numbers:
                del self.user_numbers[interaction.user.id]
            await interaction.response.send_message(
                embed=discord.Embed(description="<a:1000035606:1554848463320129567> ล้างตัวเลือกสำเร็จ", color=0xFFFFFF),
                ephemeral=True
            )

# View ปุ่มกด 3 สี (สุ่มเขียว 1 แดง 2)
class ButtonGameView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=60)
        self.role_id = role_id

        green_btn = discord.ui.Button(style=discord.ButtonStyle.success, emoji="<a:1000035603:1554845277071089736>", custom_id="green")
        red_btn1 = discord.ui.Button(style=discord.ButtonStyle.danger, emoji="<a:1000035743:1554882610134524034>", custom_id="red1")
        red_btn2 = discord.ui.Button(style=discord.ButtonStyle.danger, emoji="<a:1000035743:1554882610134524034>", custom_id="red2")

        green_btn.callback = self.green_click
        red_btn1.callback = self.red_click
        red_btn2.callback = self.red_click

        buttons = [green_btn, red_btn1, red_btn2]
        random.shuffle(buttons)
        for btn in buttons:
            self.add_item(btn)

    async def green_click(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role:
            try:
                await interaction.user.add_roles(role)
                embed = discord.Embed(
                    description=f"<a:1000035603:1554845277071089736> เย้ๆๆ พี่กดถูกก เก่งมากก น้องให้ยศ {role.mention} ให้พี่เเล้วน้าา",
                    color=0xFFFFFF
                )
            except Exception:
                embed = discord.Embed(description="<a:1000035729:1554863632528052315> บอทไม่มีสิทธิ์ให้ยศนี้", color=0xFFFFFF)
        else:
            embed = discord.Embed(description="<a:1000035729:1554863632528052315> ไม่พบบทบาทในระบบ", color=0xFFFFFF)
        await interaction.response.edit_message(embed=embed, view=None)

    async def red_click(self, interaction: discord.Interaction):
        embed = discord.Embed(
            description="<a:1000035604:1554847795524141216> พี่ๆกดไม่ถูกน้าาา ต้องกดสีเขียว ไว้มาลองอีกทีน้าา",
            color=0xFFFFFF
        )
        await interaction.response.edit_message(embed=embed, view=None)

# Panel 2: กดปุ่มรอ 3 วิ
class Button3SecVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="เริ่ม",
        emoji="<a:1000035739:1554873266987081742>",
        style=discord.ButtonStyle.primary,
        custom_id="verify_button_3sec_start"
    )
    async def start_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        panel = db.get_panel(interaction.guild_id, "button3sec")
        if not panel:
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> ระบบยังไม่ได้ตั้งค่า", color=0xFFFFFF), ephemeral=True)
            return

        _, role_id = panel
        embed_prep = discord.Embed(
            description="<a:1000035744:1554884849406451762> พี่เตรียมตัวนะ น้องจะส่งปุ่มให้พี่ๆกดในอีก นับตั้งเเต่3นะ",
            color=0xFFFFFF
        )
        await interaction.response.send_message(embed=embed_prep, ephemeral=True)
        await asyncio.sleep(3)

        embed_game = discord.Embed(
            title="พี่ๆต้องกดปุ่มให้ถูกเเล้วน้องจะให้ยศพี่ๆ <a:1000035740:1554874072205107263>",
            color=0xFFFFFF
        )
        game_view = ButtonGameView(role_id)
        await interaction.edit_original_response(embed=embed_game, view=game_view)

# Panel 3: เดาสัตว์
ANIMAL_CLUES = [
    ("สัตว์ตัวนี้ มีขน บินได้ ทำที่อยู่บนต้นไม้ บางชนิดอยู่ด้วยกันเป็นฝูง พบได้ทั่วโลก เเต่ละชนิดสีอาจเเตกต่างกันไป ชอบทำรังบนหลังคาบ้านคน", "นก"),
    ("สัตว์ตัวนี้ อยู่ด้วยกันเป็นฝูง พบมากในทวีปแอฟริกา มีเเรงกัดที่สูงมากจนสามารถกดเเละเคีัยวกระดูกได้สบาย หากินด้วยกัน ตัวเมียมักใหญ่กว่าตัวผู้", "ไฮยีนาลายจุด"),
    ("สัตว์ตัวนี้ อยู่ด้วยกันเป็นฝูง ตัวสีน้ำตาลๆ ตัวเล็ก มีลักษณะคล้ายๆคน มีหาง ชอบกินกล้วย พบบ่อยในจังหวัดลพบุรี", "ลิง"),
    ("สัตว์ตัวนี้ บางพันธุ์มีขนบางพันธุ์ไม่มีขน คนนิยมเอามาเลี้ยง เเละในประเทศไทยยังมีกฎหมายคุ้มครองสัตว์ตัวนี้ ถ้าเลี้ยงไว้ที่บ้านมักจะไม่มีหนู", "เเมว"),
    ("สัตว์ตัวนี้ คนนิยมเอามาเลี้ยงในบ้าน มีการ์ตูนที่มีสัตว์ตัวนี้อยู่ เเละเด็กๆชอบดู มีกฎหมายคุ้มครองสัตว์ตัวนี้ให้ประเทศไทย ถ้าเลี้ยงสัตว์ตัวนี้ดีๆก็จะไม่ทำร้ายใคร เเต่ถ้าเลี้ยงไม่ดีอาจไปทำร้ายคนอื่นได้", "หมา"),
    ("สัตว์ตัวนี้ มีถุงที่หน้าท้อง ไว้ใช้สำหรับเป็นที่อยู่ให้ลูก เเรกเกิดจะตัวเล็กมาก ประมาณนิ้วคน ตัวผู้โตเต็มไวมักจะมีกล้าม เเละมีขนสีน้ำตาลสั้น", "จิ้งโจ้"),
    ("สัตว์ตัวนี้ ในอดีตหลายล้านปี อาจจะมีขา บางชนิดตัวใหญ่บางชนิดเล็ก มีพิษบ้างไม่มีบ้าง คนบางกลุ่มนิยมเลี้ยง บางคนกลัวบางคนชอบ มีลิ้น2เเฉก หากินได้ทั้งบนบกเเละในน้ำ", "งู"),
    ("สัตว์ตัวนี้ บางชนิดใหญ่บางชนิดเล็ก คนชอบเอามากิน สุกบ้างดิบบ้าง เคลื่อนที่ไวใช้มือเปล่าจับเเทบไม่ได้ บางชนิดโตเต็มไวมีกล้ามที่ใหญ่เเละยาวมาก", "กุ้ง"),
    ("สัตว์ตัวนี้ คนนิยมเอามาเลี้ยงเป็นสัตว์สวยงาม บางชนิดถ้าฝึกดีๆมันสามารถพูดได้ มีหลายสี มีเกมที่มีสัตว์ตัวนี้เป็นตัวหลักของเกม เเละบินได้", "นกเเก้ว"),
    ("สัตว์ตัวนี้ อาจจะเป็นต้นเหตุของโรคโควิด19 บินได้ นอนโดยการห้อยหัวลงมา หากินตอนมืด มักอยู่ในถ้ำหรือที่มืดๆ บินได้", "ค้างคาว")
]

class AnimalAnswerSelect(discord.ui.Select):
    def __init__(self, correct_answer: str, role_id: int):
        self.correct_answer = correct_answer
        self.role_id = role_id
        options = [
            discord.SelectOption(label="นก", value="นก", emoji="<a:1000035759:1554908021115719791>"),
            discord.SelectOption(label="หมา", value="หมา", emoji="<:1000035758:1554907814894501911>"),
            discord.SelectOption(label="เเมว", value="เเมว", emoji="<a:1000035757:1554907672502083694>"),
            discord.SelectOption(label="ค้างคาว", value="ค้างคาว", emoji="<a:1000035752:1554907270393892986>"),
            discord.SelectOption(label="จิงโจ้", value="จิ้งโจ้", emoji="<a:1000035761:1554908402977742918>"),
            discord.SelectOption(label="งู", value="งู", emoji="<a:1000035750:1554907022657589388>"),
            discord.SelectOption(label="ลิง", value="ลิง", emoji="<a:1000035749:1554906589331329074>"),
            discord.SelectOption(label="กุ้ง", value="กุ้ง", emoji="<a:1000035747:1554906257163559004>"),
            discord.SelectOption(label="นกเเก้ว", value="นกเเก้ว", emoji="<a:1000035748:1554906430233116694>"),
            discord.SelectOption(label="ไฮยีนาลายจุด", value="ไฮยีนาลายจุด", emoji="<a:1000035760:1554908193174589581>")
        ]
        super().__init__(placeholder="เลือกคำตอบสัตว์", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected == self.correct_answer:
            role = interaction.guild.get_role(self.role_id)
            if role:
                try:
                    await interaction.user.add_roles(role)
                    embed = discord.Embed(description="<a:1000035742:1554876309790793908> เย้ๆๆ เก่งมาพี่ที่ทายถูก น้องให้ยศที่เเล้วน้าาา", color=0xFFFFFF)
                except Exception:
                    embed = discord.Embed(description="<a:1000035729:1554863632528052315> บอทไม่มีสิทธิ์ให้ยศนี้", color=0xFFFFFF)
            else:
                embed = discord.Embed(description="<a:1000035729:1554863632528052315> ไม่พบบทบาทในระบบ", color=0xFFFFFF)
        else:
            embed = discord.Embed(description="<a:1000035743:1554882610134524034> โอ๋ๆไม่เป็นไรนะพี่ ไว้มาตอบไว้น้าาา", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class AnimalVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.user_answers = {}

    @discord.ui.select(
        placeholder="คำใบ้เเละตอบ",
        custom_id="verify_animal_select",
        options=[
            discord.SelectOption(label="รับคำใบ้", value="get_clue", emoji="<a:1000035740:1554874072205107263>"),
            discord.SelectOption(label="พร้อมเดาเเล้วว", value="guess", emoji="<a:1000035608:1554844998506123274>"),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji="<a:1000035725:1554844594175483904>")
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        panel = db.get_panel(interaction.guild_id, "animal")
        if not panel:
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> ระบบยังไม่ได้ตั้งค่า", color=0xFFFFFF), ephemeral=True)
            return
        
        _, role_id = panel

        if val == "get_clue":
            clue, ans = random.choice(ANIMAL_CLUES)
            self.user_answers[interaction.user.id] = ans
            embed = discord.Embed(
                title="คำใบ้ทายสัตว์ <a:1000035740:1554874072205107263>",
                description=f"{clue}\n\nสัตว์ตัวนี้คือตัวอะไร",
                color=0xFFFFFF
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif val == "guess":
            if interaction.user.id not in self.user_answers:
                await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> พี่ๆต้องกดรับคำใบ้ก่อนน้าา", color=0xFFFFFF), ephemeral=True)
                return
            view = discord.ui.View()
            view.add_item(AnimalAnswerSelect(self.user_answers[interaction.user.id], role_id))
            await interaction.response.send_message(embed=discord.Embed(description="โปรดเลือกคำตอบสัตว์ที่ถูกต้อง:", color=0xFFFFFF), view=view, ephemeral=True)

        elif val == "clear":
            if interaction.user.id in self.user_answers:
                del self.user_answers[interaction.user.id]
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035606:1554848463320129567> ล้างตัวเลือกสำเร็จ", color=0xFFFFFF), ephemeral=True)

# Panel 4: ทายอายุ
AGE_CLUES = [
    ("อายุของหนูยังเป็นเด็กเล็กอยู่ ยังไม่สามารถทำบัตรประชาชนด้ายยย เเละยังต้องกินนมอยู่ เเละยังเดินเองไม่ได้", "1ขวบ"),
    ("อายุของหนู เกษียณ เเล้วว พึ่งเกษียณเลย เริ่มมีผมหงอก เเต่ยังเดินไหวขับรถไหว ถ้ามีลูก ลูกน่าจะอายุ25-30ได้", "60ปี"),
    ("อายุของหนู บางคนอาจจะยังศึกษาอยู่ที่มหาวิทยาลัย อยู่ บางคนก็ทำงาน บางคนก็มีชีวิตคู่เเล้ว อายุสามารถจดทะเบียนสมรสได้เเล้ว", "22ปี"),
    ("อายุของหนู คนมักบอกว่าอายุเท่านี้เป็นคำสาป เพราะคนมักบอกว่า เบญจเพส จะเกิดตอนอายุเท่านี้ อายุหนูจดทะเบียนสมรสได้เเล้ว", "25ปี"),
    ("อายุของหนู อยู่ในวัยทำงาน อายุประมาณนี้คนก็เริ่มเเต่งงานกันเเล้ว อยู่ในช่วงพีคของร่างกาย เพราะอวัยวะทุกส่วนจะอยู่ในช่วงทอง ทำงานได้เต็มที่ อายุหนูอาจจะมากกว่า22รึเปล่าน้าา", "26ปี"),
    ("อายุของหนู เดินไม่ไหวเเล้ว คนส่วนใหญ่อายุไม่ค่อยจะถึงเพราะจะเสียชีวิตก่อน ผมขาวหมดเเล้ว ผิวหนังเหี่ยวย้น ทำอะไรก็ลำบาก ปัสวะเองไม่ได้", "100ปี"),
    ("อายุของหนู อีกสัก10ปีต้องเกษียณเเล้ว ยังเดินไหวทำอะไรไหว เเต่บางคนโรคต่างๆเริ่มถามหาเเล้ว เเต่ส่วนใหญ่ก็ร่างกายยังไหว ยังทำงานไหว", "50ปี"),
    ("อายุของหนู อยู่ประมาณม.2-3 กำลังเข้าช่วงวัยรุ่น อยู่ในวัยลองผิดลองถูก อายุของหนูมากกว่า13 เเล้วส่วนใหญ่เริ่มจะขับรถได้เเล้ว", "15ปี"),
    ("อายุของหนู ทำบัตรประชาชนได้เเล้ว เข้าโรงเรียนเเล้วบางคนก็ ป.1 ป.2 อายุน้อยกว่า10 อายุหนูเขียนหนังสือได้เเล้ว อยู่ gen Alpha", "7ขวบ"),
    ("อายุของหนู เริ่มมีอายุเเล้ว หลายๆคนมีลูกเเล้ว มีการงานมั้นคง มีชีวิตที่ดี ลูกอาจจะอายุ17-19ถ้ามีลูกไว ทำงานไหวสบายๆ เเต่หลายๆคนสายตาอาจจะเริ่มไม่ดีเหมือนเเต่ก่อน", "46ปี")
]

class AgeAnswerSelect(discord.ui.Select):
    def __init__(self, correct_answer: str, role_id: int):
        self.correct_answer = correct_answer
        self.role_id = role_id
        options = [
            discord.SelectOption(label="1ขวบ", value="1ขวบ", emoji="<a:1000035724:1554844520674500678>"),
            discord.SelectOption(label="7ขวบ", value="7ขวบ", emoji="<a:1000035725:1554844594175483904>"),
            discord.SelectOption(label="15ปี", value="15ปี", emoji="<a:1000035602:1554844971931275325>"),
            discord.SelectOption(label="22ปี", value="22ปี", emoji="<a:1000035608:1554844998506123274>"),
            discord.SelectOption(label="25ปี", value="25ปี", emoji="<a:1000035603:1554845277071089736>"),
            discord.SelectOption(label="26ปี", value="26ปี", emoji="<a:1000035604:1554847795524141216>"),
            discord.SelectOption(label="46ปี", value="46ปี", emoji="<a:1000035597:1554848439035240449>"),
            discord.SelectOption(label="50ปี", value="50ปี", emoji="<a:1000035726:1554859496894111744>"),
            discord.SelectOption(label="60ปี", value="60ปี", emoji="<a:1000035727:1554859928957755393>"),
            discord.SelectOption(label="100ปี", value="100ปี", emoji="<a:1000035728:1554860189125967894>")
        ]
        super().__init__(placeholder="เลือกตอบอายุ", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected == self.correct_answer:
            role = interaction.guild.get_role(self.role_id)
            if role:
                try:
                    await interaction.user.add_roles(role)
                    embed = discord.Embed(description=f"<a:1000035762:1554919569682989166> เย้ๆๆๆๆ พี่เก่งมากกก ทายอายุหนูถูกด้วยย หนูให้ยศ {role.mention} ที่เเล้วน้าา", color=0xFFFFFF)
                except Exception:
                    embed = discord.Embed(description="<a:1000035729:1554863632528052315> บอทไม่มีสิทธิ์ให้ยศนี้", color=0xFFFFFF)
            else:
                embed = discord.Embed(description="<a:1000035729:1554863632528052315> ไม่พบบทบาทในระบบ", color=0xFFFFFF)
        else:
            embed = discord.Embed(description="<a:1000035764:1554920142146904164> โอ๋ๆ ไม่เป็นไรน้าา พี่ เอาใหม่นะพี่ เดียวหนูใบ้ให้ง่ายกว่าเดิมน้าาา", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class AgeVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.user_answers = {}

    @discord.ui.select(
        placeholder="เลือกเเละเดา",
        custom_id="verify_age_select",
        options=[
            discord.SelectOption(label="คำใบ้", value="get_clue", emoji="<a:1000035724:1554844520674500678>"),
            discord.SelectOption(label="เลือกตอบ", value="guess", emoji="<a:1000035726:1554859496894111744>"),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji="<a:1000035757:1554907672502083694>")
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        panel = db.get_panel(interaction.guild_id, "age")
        if not panel:
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> ระบบยังไม่ได้ตั้งค่า", color=0xFFFFFF), ephemeral=True)
            return

        _, role_id = panel

        if val == "get_clue":
            clue, ans = random.choice(AGE_CLUES)
            self.user_answers[interaction.user.id] = ans
            embed = discord.Embed(title="คำใบ้อายุ <a:1000035740:1554874072205107263>", description=clue, color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif val == "guess":
            if interaction.user.id not in self.user_answers:
                await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> พี่ๆต้องกดรับคำใบ้ก่อนน้าา", color=0xFFFFFF), ephemeral=True)
                return
            view = discord.ui.View()
            view.add_item(AgeAnswerSelect(self.user_answers[interaction.user.id], role_id))
            await interaction.response.send_message(embed=discord.Embed(description="เลือกตอบอายุ:", color=0xFFFFFF), view=view, ephemeral=True)

        elif val == "clear":
            if interaction.user.id in self.user_answers:
                del self.user_answers[interaction.user.id]
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035606:1554848463320129567> ล้างตัวเลือกสำเร็จ", color=0xFFFFFF), ephemeral=True)

# Panel 5: เดาเกมรับยศ
GAME_CLUES = [
    ("เกมนี้ เป็นเกมเน้นยิงกัน มีคำศัพท์ต่างๆ เช่น มห มต เป็นเกมโดดล่ม มีหลายโหมด สร้างห้องเล่นกับเพื่อนได้ เป็นเกมที่เกลือมาก", "freefire"),
    ("เกมนี้ มีป้อมให้ตี มีหลายร้อยตัวละคร มีหลายสกินให้ใส่ มีเเรงค์ ยอดดาวโหลดเกิน500M เล่นบ่อยๆจะหัวร้อน", "rov"),
    ("เกมนี้เป็นเกมที่เปิดให้คนมาสร้างเกมได้ เเต่งตัวได้ เด็กๆชอบเล่น ผู้ใหญ่หลายๆคนก็เล่น มีลูกเล่นเยอะมาก อาจจะยิงปืน เเต่งตัว พูดคุย", "roblox"),
    ("เกมนี้ เป็นสี่เหลี่ยม ปกเกมเป็นพื้นหญ้า มีมอนสเตอร์เยอะมาก เลี้ยงสัตว์ได้ สร้างบ้านสร้างเซิฟให้คนมาเล่นได้ สมัยก่อนการเล่นกับเพื่อนในเซิฟส่วนตัวเป็นเรื่องที่ยากมาก", "minecraft"),
    ("เกมนี้ เป็นเกมที่เน้นเตะบอล เปิดการ์ดเอาตัวละคร มีหลายโหมด ผู้ชายเล่นกันเยอะ ขึ้นต้นด้วย เ เล่นกับเพื่อนได้ ลงเเรงค์ได้", "เปส"),
    ("เกมนี้ เน้นยิงกัน มีหลายโหมด เเรงค์ ทั่วไป 22 11 โหมดปกติเล่นนานมาก บางเกมมากกว่า30นาที มีหลายตัวละคร มีสกิลปืนหลายอย่างลูกเล่นเยอะ", "valorant")
]

class GameAnswerSelect(discord.ui.Select):
    def __init__(self, correct_answer: str, role_id: int):
        self.correct_answer = correct_answer
        self.role_id = role_id
        options = [
            discord.SelectOption(label="freefire", value="freefire", emoji="<:1000035768:1554926218451882035>"),
            discord.SelectOption(label="rov", value="rov", emoji="<:1000035774:1554927462742499448>"),
            discord.SelectOption(label="valorant", value="valorant", emoji="<:1000035770:1554926594475171970>"),
            discord.SelectOption(label="roblox", value="roblox", emoji="<:1000035771:1554926800058982440>"),
            discord.SelectOption(label="minecraft", value="minecraft", emoji="<:1000035772:1554926984545439814>"),
            discord.SelectOption(label="เปส", value="เปส", emoji="<:1000035773:1554927297356898445>")
        ]
        super().__init__(placeholder="เลือกตอบเกม", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected == self.correct_answer:
            role = interaction.guild.get_role(self.role_id)
            if role:
                try:
                    await interaction.user.add_roles(role)
                    embed = discord.Embed(description=f"<a:1000035763:1554920997382262874> เย้ๆๆๆ เก่งมากกก หนูให้ยศพี่เเล้วน้าาา {role.mention}", color=0xFFFFFF)
                except Exception:
                    embed = discord.Embed(description="<a:1000035729:1554863632528052315> บอทไม่มีสิทธิ์ให้ยศนี้", color=0xFFFFFF)
            else:
                embed = discord.Embed(description="<a:1000035729:1554863632528052315> ไม่พบบทบาทในระบบ", color=0xFFFFFF)
        else:
            embed = discord.Embed(description="<a:1000035764:1554920142146904164> ไม่เป็นไรน้าาาพี่ เอาใหม่ เดียวดูให้คำใบ้ง่ายกว่าเดิมให้เองง", color=0xFFFFFF)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class GameVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.user_answers = {}

    @discord.ui.select(
        placeholder="เซ็ตระบบ",
        custom_id="verify_game_select",
        options=[
            discord.SelectOption(label="รับคำใบ้", value="get_clue", emoji="<a:1000035767:1554921960838926417>"),
            discord.SelectOption(label="พร้อมตอบบ", value="guess", emoji="<a:1000035762:1554919569682989166>"),
            discord.SelectOption(label="ล้างตัวเลือก", value="clear", emoji="<a:1000035727:1554859928957755393>")
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        val = select.values[0]
        panel = db.get_panel(interaction.guild_id, "game")
        if not panel:
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> ระบบยังไม่ได้ตั้งค่า", color=0xFFFFFF), ephemeral=True)
            return

        _, role_id = panel

        if val == "get_clue":
            clue, ans = random.choice(GAME_CLUES)
            self.user_answers[interaction.user.id] = ans
            embed = discord.Embed(title="คำใบ้เดาเกม <a:1000035763:1554920997382262874>", description=clue, color=0xFFFFFF)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif val == "guess":
            if interaction.user.id not in self.user_answers:
                await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> พี่ๆต้องกดรับคำใบ้ก่อนน้าา", color=0xFFFFFF), ephemeral=True)
                return
            view = discord.ui.View()
            view.add_item(GameAnswerSelect(self.user_answers[interaction.user.id], role_id))
            await interaction.response.send_message(embed=discord.Embed(description="เลือกตอบเกม:", color=0xFFFFFF), view=view, ephemeral=True)

        elif val == "clear":
            if interaction.user.id in self.user_answers:
                del self.user_answers[interaction.user.id]
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035606:1554848463320129567> ล้างตัวเลือกสำเร็จ", color=0xFFFFFF), ephemeral=True)


# ------------------------------------------------------------------
# 2. ADMIN SETUP VIEWS (แก้ไขจุดที่เกิด Error เรียบร้อยแล้ว)
# ------------------------------------------------------------------

class AdminSetupView(discord.ui.View):
    def __init__(self, system_type: str):
        super().__init__(timeout=180)
        self.system_type = system_type
        self.selected_role = None
        self.selected_channel = None

    # แก้ไข syntax การเลือก Role
    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="เลือกยศที่ผู้ใช้จะได้รับ")
    async def select_role_cb(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role = select.values[0]
        await interaction.response.send_message(embed=discord.Embed(description=f"เลือกยศ {self.selected_role.mention} เรียบร้อย", color=0xFFFFFF), ephemeral=True)

    # แก้ไข syntax การเลือก Channel
    @discord.ui.select(cls=discord.ui.ChannelSelect, placeholder="เลือกห้องที่จะส่งระบบไป", channel_types=[discord.ChannelType.text])
    async def select_channel_cb(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.selected_channel = select.values[0]
        await interaction.response.send_message(embed=discord.Embed(description=f"เลือกห้อง {self.selected_channel.mention} เรียบร้อย", color=0xFFFFFF), ephemeral=True)

    @discord.ui.button(label="เริ่มม", style=discord.ButtonStyle.success, emoji="<a:1000035606:1554848463320129567>")
    async def start_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_role or not self.selected_channel:
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> กรุณาเลือกยศและห้องให้ครบก่อนน้าา", color=0xFFFFFF), ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member.guild_permissions.manage_roles or self.selected_role >= bot_member.top_role:
            await interaction.response.send_message(embed=discord.Embed(description="<a:1000035729:1554863632528052315> น้องยศไม่ถึง พี่ๆให้ยศน้องก่อนน", color=0xFFFFFF), ephemeral=True)
            return

        # บันทึกข้อมูลลง Database
        db.save_panel(interaction.guild_id, self.system_type, self.selected_channel.id, self.selected_role.id)

        # ส่ง Panel ไปยังห้องที่เลือก
        if self.system_type == "number":
            embed = discord.Embed(
                title="<a:1000035726:1554859496894111744> กรอกเลขรับยศ <a:1000035726:1554859496894111744>",
                description=(
                    "พี่ๆต้องกดลิสด้านล่างก่อน เเล้วเลือกรับเลข หลังจากพี่ๆกดหนูจะให้เลขที่ถูกซ่อนมา เเล้วพี่ๆก็กดรับเลข ทีนี้พี่ๆก็ใส่เลขที่น้องซ่อนให้พวกพี่หาได้เลย <a:1000035740:1554874072205107263>\n\n"
                    f"<a:1000035742:1554876309790793908> ยศที่พี่ๆจะได้ {self.selected_role.mention}"
                ),
                color=0xFFFFFF
            )
            await self.selected_channel.send(embed=embed, view=NumberVerifyView())
            msg_text = f"<a:1000035606:1554848463320129567> สำเร็จ การรับยศถูกส่งไปที่ห้อง {self.selected_channel.mention}"

        elif self.system_type == "button3sec":
            embed = discord.Embed(
                title="<a:1000035743:1554882610134524034> รับยศแบบปุ่ม",
                description=(
                    "<a:1000035740:1554874072205107263> ให้พี่ๆกดปุ่มเริ่มด้านล่างเเล้วกดปุ่มให้ถูกเดียวน้องจะให้ยศเเก่พี่ๆเองง\n\n"
                    f"ยศที่พี่ๆจะได้ {self.selected_role.mention}"
                ),
                color=0xFFFFFF
            )
            await self.selected_channel.send(embed=embed, view=Button3SecVerifyView())
            msg_text = f"<a:1000035741:1554876169017499658> สำเร็จเเล้วน้าาพี่ๆ ห้องที่รับยศคืออ {self.selected_channel.mention}"

        elif self.system_type == "animal":
            embed = discord.Embed(
                title="<a:1000035745:1554887740028485743> รับยศเดาสัตว์ <a:1000035745:1554887740028485743>",
                description=(
                    "<a:1000035744:1554884849406451762> พี่ๆกดลิสด้านล่างมาก่อน เเล้วพี่ๆกดรับคำใบ้ อ่านคำใบ้เเล้วพี่ๆก็มาเลือกคำตอบ ถ้าถูกเดียวน้องให้รางวัลเป็นยศเเก่พี่เองง\n\n"
                    f"ยศที่จะได้รับ {self.selected_role.mention}"
                ),
                color=0xFFFFFF
            )
            await self.selected_channel.send(embed=embed, view=AnimalVerifyView())
            msg_text = f"หนูส่งข้อความไปที่ห้อง {self.selected_channel.mention} เเล้วน้าา พี่ลองได้ดูด้ายย <a:1000035727:1554859928957755393>"

        elif self.system_type == "age":
            embed = discord.Embed(
                title="<a:1000035740:1554874072205107263> เดาอายุรับยศ <a:1000035740:1554874072205107263>",
                description=(
                    "พี่ๆกดลิสด้านล่างรับคำใบ้อายุหนู เเล้วพี่ๆก็มาเลือกดูว่าหนูอายุเท่าไหร่เอ่ยยย\n\n"
                    f"ถ้าพี่ๆทายถูกหนูจะให้ยศ {self.selected_role.mention} พี่เองง"
                ),
                color=0xFFFFFF
            )
            await self.selected_channel.send(embed=embed, view=AgeVerifyView())
            msg_text = f"หนูสร้างให้พี่เเล้วน้าาา พี่ลองไปดูหน่อยยย {self.selected_channel.mention}"

        elif self.system_type == "game":
            embed = discord.Embed(
                title="<a:1000035763:1554920997382262874> เดาเกมรับยศ <a:1000035763:1554920997382262874>",
                description=(
                    "<a:1000035764:1554920142146904164> พี่ๆกดลิสด้านล่างรับคำใบ้เดาเกมได้เลยยย\n\n"
                    f"ยศที่จะได้รับ {self.selected_role.mention}"
                ),
                color=0xFFFFFF
            )
            await self.selected_channel.send(embed=embed, view=GameVerifyView())
            msg_text = f"หนูสร้างระบบเดาเกมให้พี่เเล้วน้าาา ไปดูที่ห้อง {self.selected_channel.mention} ได้เลยย"

        await interaction.response.send_message(embed=discord.Embed(description=msg_text, color=0xFFFFFF), ephemeral=True)

    @discord.ui.button(label="ล้างตัวเลือก", style=discord.ButtonStyle.secondary, emoji="<a:1000035724:1554844520674500678>")
    async def clear_cb(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.selected_role = None
        self.selected_channel = None
        await interaction.response.send_message(
            embed=discord.Embed(description="<a:1000035606:1554848463320129567> ล้างตัวเลือกสำเร็จ", color=0xFFFFFF),
            ephemeral=True
        )


# ------------------------------------------------------------------
# 3. MAIN COMMAND /VERIFY & MENU SELECT
# ------------------------------------------------------------------

class VerifyMainSystemSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="กรอกเลขรับยศ", value="number", emoji="<a:1000035727:1554859928957755393>"),
            discord.SelectOption(label="กดปุ่มรอ3วิ", value="button3sec", emoji="<a:1000035608:1554844998506123274>"),
            discord.SelectOption(label="เดาสัตว์", value="animal", emoji="<a:1000035741:1554876169017499658>"),
            discord.SelectOption(label="ทายอายุ", value="age", emoji="<a:1000035740:1554874072205107263>"),
            discord.SelectOption(label="เดาเกมรับยศ", value="game", emoji="<a:1000035607:1554874918632562788>")
        ]
        super().__init__(placeholder="เลือกระบบยืนยันตัวตนรับยศ", options=options)

    async def callback(self, interaction: discord.Interaction):
        sys_type = self.values[0]
        setup_view = AdminSetupView(sys_type)

        titles = {
            "number": "<a:1000035725:1554844594175483904> กรอกเลขรับยศ",
            "button3sec": "<a:1000035743:1554882610134524034> กดปุ่มรอ3วิ\n\nพี่ๆเลือกยศที่จะให้ ห้อง เเละกดเริ่มได้เลยยย <a:1000035604:1554847795524141216>",
            "animal": "<a:1000035741:1554876169017499658> รับยศโดยการเดาสัตว์ <a:1000035741:1554876169017499658>\n\nพี่ๆ เลือกยศ เลือกห้อง กดเริ่ม เเล้วก็เริ่มเดาได้เลยย <a:1000035604:1554847795524141216>",
            "age": "เดาอายุรับยศ <a:1000035760:1554908193174589581>\n\n<a:1000035603:1554845277071089736> พี่ๆกรอกยศ ห้อง เเละกดเริ่มให้หนูหน่อยย",
            "game": "<a:1000035763:1554920997382262874> เดาเกมรับยศ <a:1000035763:1554920997382262874>\n\n<a:1000035764:1554920142146904164> พี่ๆเลือกยศ ห้อง กดเริ่มให้หนูด้วยน้าาา"
        }

        embed = discord.Embed(title=titles[sys_type], color=0xFFFFFF)
        await interaction.response.send_message(embed=embed, view=setup_view, ephemeral=True)

class VerifyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="verify", description="คำสั่งสำหรับรับยศ")
    async def verify_command(self, interaction: discord.Interaction):
        # เช็คสิทธิ์ Admin
        if not interaction.user.guild_permissions.administrator:
            embed = discord.Embed(
                description="<a:1000035729:1554863632528052315> คุณไม่มีสิทธิ์ใช้งาน!!",
                color=0xFFFFFF
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="# Verify identity <a:1000035604:1554847795524141216>",
            description="โปรดเลือกระบบการยืนยันตัวตนด้วยค่ะ <a:1000035603:1554845277071089736>",
            color=0xFFFFFF
        )
        view = discord.ui.View()
        view.add_item(VerifyMainSystemSelect())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(VerifyCog(bot))
