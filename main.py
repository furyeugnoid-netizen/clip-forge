+import discord
from discord.ext import commands
from discord import app_commands
import asyncpg
import os
import random
import string
import re
from datetime import datetime

CYAN = 0x00FFFF
LIGHT_CYAN = 0x00D4FF
DARK_BLUE = 0x0099FF
GREEN = 0x00D26A
ORANGE = 0xFF8C00
RED = 0xFF4757
PURPLE = 0x7B68EE

DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
db_pool = None

PLATFORM_INFO = {
    "youtube": {"emoji": "📺", "name": "YouTube", "url_pattern": r"(youtube\.com|youtu\.be)"},
    "tiktok": {"emoji": "🎵", "name": "TikTok", "url_pattern": r"(tiktok\.com)"},
    "instagram": {"emoji": "📸", "name": "Instagram", "url_pattern": r"(instagram\.com)"},
    "x": {"emoji": "🐦", "name": "X (Twitter)", "url_pattern": r"(twitter\.com|x\.com)"},
}
COUNTRY_LIST = ["🇮🇳 India","🇺🇸 USA","🇬🇧 UK","🇨🇦 Canada","🇦🇺 Australia","🇧🇷 Brazil","🇩🇪 Germany","🇯🇵 Japan","🇫🇷 France","🇲🇽 Mexico","🇰🇷 South Korea","🇮🇩 Indonesia","🇳🇬 Nigeria","🇿🇦 South Africa","🇦🇪 UAE","🇸🇦 Saudi Arabia","🇵🇰 Pakistan","🇧🇩 Bangladesh","🇵🇭 Philippines","🇹🇷 Turkey","🇪🇬 Egypt","🇹🇭 Thailand","🇻🇳 Vietnam","🌍 Other"]

def gen_code():
    return "CF-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as c:
        await c.execute("CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY,username TEXT,avatar_url TEXT DEFAULT '',country TEXT DEFAULT '',payment_method TEXT DEFAULT '',payment_details TEXT DEFAULT '',setup_complete BOOLEAN DEFAULT FALSE,created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS accounts(id SERIAL PRIMARY KEY,user_id TEXT REFERENCES users(user_id),platform TEXT,platform_username TEXT,platform_url TEXT DEFAULT '',verified BOOLEAN DEFAULT FALSE,verification_code TEXT DEFAULT '',linked_at TIMESTAMP DEFAULT NOW(),UNIQUE(user_id,platform),UNIQUE(platform,platform_username))")
        await c.execute("CREATE TABLE IF NOT EXISTS clips(id SERIAL PRIMARY KEY,user_id TEXT REFERENCES users(user_id),platform TEXT,url TEXT UNIQUE,views INTEGER DEFAULT 0,earnings REAL DEFAULT 0,status TEXT DEFAULT 'pending',campaign_id TEXT DEFAULT '',submitted_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS campaigns(id SERIAL PRIMARY KEY,name TEXT,channel_id TEXT,platform TEXT DEFAULT '',created_by TEXT,active BOOLEAN DEFAULT TRUE,created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)")
        await c.execute("INSERT INTO settings(key,value) VALUES('payment_rate','0.001') ON CONFLICT(key) DO NOTHING")
    print("✅ Database initialized")

async def get_rate():
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT value FROM settings WHERE key='payment_rate'")
        return float(r["value"]) if r else 0.001

async def ensure_user(user):
    av = str(user.display_avatar.url) if user.display_avatar else ""
    async with db_pool.acquire() as c:
        await c.execute("INSERT INTO users(user_id,username,avatar_url) VALUES($1,$2,$3) ON CONFLICT(user_id) DO UPDATE SET username=$2,avatar_url=$3", str(user.id), user.name, av)

async def get_user(uid):
    async with db_pool.acquire() as c:
        return await c.fetchrow("SELECT * FROM users WHERE user_id=$1", str(uid))

async def get_accounts(uid):
    async with db_pool.acquire() as c:
        return await c.fetch("SELECT * FROM accounts WHERE user_id=$1 ORDER BY linked_at", str(uid))

async def get_verified_accounts(uid):
    async with db_pool.acquire() as c:
        return await c.fetch("SELECT * FROM accounts WHERE user_id=$1 AND verified=TRUE", str(uid))

async def get_clips(uid):
    async with db_pool.acquire() as c:
        return await c.fetch("SELECT * FROM clips WHERE user_id=$1 ORDER BY submitted_at DESC", str(uid))

async def get_total_views(uid):
    async with db_pool.acquire() as c:
        r = await c.fetchrow("SELECT COALESCE(SUM(views),0) as t FROM clips WHERE user_id=$1", str(uid))
        return int(r["t"])

async def get_leaderboard():
    rate = await get_rate()
    async with db_pool.acquire() as c:
        rows = await c.fetch("SELECT u.user_id,u.username,COALESCE(SUM(c.views),0) as tv,COALESCE(COUNT(c.id),0) as tc FROM users u LEFT JOIN clips c ON u.user_id=c.user_id GROUP BY u.user_id,u.username ORDER BY tv DESC LIMIT 10")
        return [(r["username"], int(r["tv"])*rate, int(r["tv"]), int(r["tc"])) for r in rows]

# ═══════════════ CONNECT SOCIALS PANEL ═══════════════

class ConnectSocialsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Link Account", emoji="🔗", style=discord.ButtonStyle.success, custom_id="p_link", row=0)
    async def link(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ensure_user(interaction.user)
        embed = discord.Embed(title="🔗 Link Your Social Account", description="**Select a platform** to connect.\n\n📌 **How it works:**\n1️⃣ Choose platform\n2️⃣ Enter username & profile URL\n3️⃣ Get a **verification code**\n4️⃣ Add code to your **bio**\n5️⃣ Click **Verify** ✅", color=GREEN)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await interaction.response.send_message(embed=embed, view=ChoosePlatformView(interaction.user.id), ephemeral=True)

    @discord.ui.button(label="View Accounts", emoji="👥", style=discord.ButtonStyle.primary, custom_id="p_view", row=0)
    async def view(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ensure_user(interaction.user)
        embed = await build_profile_card(interaction.user)
        await interaction.response.send_message(embed=embed, view=ViewAccountsView(interaction.user.id), ephemeral=True)

async def build_profile_card(user):
    uid = str(user.id)
    accounts = await get_accounts(uid)
    tv = await get_total_views(uid)
    rate = await get_rate()
    embed = discord.Embed(title="👤 Your Profile", color=CYAN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="👁 All-Time Views", value=f"**{tv:,}**", inline=True)
    embed.add_field(name="💵 Earnings", value=f"**${tv*rate:.2f}**", inline=True)
    if accounts:
        t = ""
        for a in accounts:
            e = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
            s = "✅" if a["verified"] else "⏳ Unverified"
            t += f"{e} **{a['platform'].title()}**: `@{a['platform_username']}` {s}\n"
        embed.add_field(name="🔗 Connected Accounts", value=t, inline=False)
    else:
        embed.add_field(name="🔗 Connected Accounts", value="No accounts linked yet.\nClick **Link Account** to start!", inline=False)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    return embed

class ViewAccountsView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="🔗 Link New", style=discord.ButtonStyle.success)
    async def link(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🔗 Link Account", description="Select a platform.", color=GREEN)
        await interaction.response.edit_message(embed=embed, view=ChoosePlatformView(interaction.user.id))

    @discord.ui.button(label="🗑️ Unlink", style=discord.ButtonStyle.danger)
    async def unlink(self, interaction: discord.Interaction, button: discord.ui.Button):
        accs = await get_accounts(str(interaction.user.id))
        if not accs:
            await interaction.response.send_message("❌ No accounts to unlink!", ephemeral=True)
            return
        embed = discord.Embed(title="🗑️ Unlink Account", description="Select to remove.", color=RED)
        await interaction.response.edit_message(embed=embed, view=UnlinkView(interaction.user.id, accs))

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_profile_card(interaction.user)
        await interaction.response.edit_message(embed=embed, view=ViewAccountsView(interaction.user.id))

# ═══════════════ LINK FLOW ═══════════════

class ChoosePlatformView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="YouTube", emoji="📺", style=discord.ButtonStyle.danger)
    async def yt(self, i: discord.Interaction, b): await i.response.send_modal(LinkModal(self.uid, "youtube"))
    @discord.ui.button(label="TikTok", emoji="🎵", style=discord.ButtonStyle.danger)
    async def tt(self, i: discord.Interaction, b): await i.response.send_modal(LinkModal(self.uid, "tiktok"))
    @discord.ui.button(label="Instagram", emoji="📸", style=discord.ButtonStyle.primary)
    async def ig(self, i: discord.Interaction, b): await i.response.send_modal(LinkModal(self.uid, "instagram"))
    @discord.ui.button(label="X (Twitter)", emoji="🐦", style=discord.ButtonStyle.secondary)
    async def tw(self, i: discord.Interaction, b): await i.response.send_modal(LinkModal(self.uid, "x"))

class LinkModal(discord.ui.Modal):
    def __init__(self, uid, platform):
        pn = PLATFORM_INFO[platform]["name"]
        super().__init__(title=f"Link {pn}")
        self.uid = uid
        self.platform = platform
        self.uname = discord.ui.TextInput(label=f"{pn} Username", placeholder="YourUsername (no @)", required=True, max_length=100)
        self.purl = discord.ui.TextInput(label=f"{pn} Profile URL", placeholder=f"https://www.{platform if platform != 'x' else 'x'}.com/...", required=True, max_length=300)
        self.add_item(self.uname)
        self.add_item(self.purl)

    async def on_submit(self, interaction: discord.Interaction):
        username = self.uname.value.strip().lstrip("@")
        url = self.purl.value.strip()
        pi = PLATFORM_INFO[self.platform]
        if not re.search(pi["url_pattern"], url, re.IGNORECASE):
            await interaction.response.send_message(f"❌ That URL doesn't look like a **{pi['name']}** link!", ephemeral=True)
            return
        async with db_pool.acquire() as c:
            ex = await c.fetchrow("SELECT user_id FROM accounts WHERE platform=$1 AND platform_username=$2 AND user_id!=$3", self.platform, username, str(self.uid))
            if ex:
                await interaction.response.send_message(f"❌ `@{username}` on **{pi['name']}** is already linked by another user!", ephemeral=True)
                return
            own = await c.fetchrow("SELECT * FROM accounts WHERE platform=$1 AND user_id=$2", self.platform, str(self.uid))
            if own and own["verified"]:
                await interaction.response.send_message(f"✅ You already have verified **{pi['name']}**: `@{own['platform_username']}`\nUnlink it first to change.", ephemeral=True)
                return
            code = gen_code()
            await c.execute("INSERT INTO accounts(user_id,platform,platform_username,platform_url,verified,verification_code) VALUES($1,$2,$3,$4,FALSE,$5) ON CONFLICT(user_id,platform) DO UPDATE SET platform_username=$3,platform_url=$4,verified=FALSE,verification_code=$5,linked_at=NOW()", str(self.uid), self.platform, username, url, code)
        embed = discord.Embed(title=f"{pi['emoji']} Verify Your {pi['name']}", description=f"**Account:** `@{username}`\n**URL:** {url}\n\n━━━━━━━━━━━━━━━━━━━━━\n\n📋 **Your Verification Code:**\n```\n{code}\n```\n\n**Steps:**\n1️⃣ Copy the code above\n2️⃣ Go to your **{pi['name']}** profile\n3️⃣ Add code to your **bio**\n4️⃣ Click **✅ Verify Now**\n\n⚠️ *Remove code from bio after verification*", color=ORANGE)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await interaction.response.edit_message(embed=embed, view=VerifyView(self.uid, self.platform, username, code))

class VerifyView(discord.ui.View):
    def __init__(self, uid, platform, username, code):
        super().__init__(timeout=300)
        self.uid = uid
        self.platform = platform
        self.username = username
        self.code = code

    @discord.ui.button(label="✅ Verify Now", style=discord.ButtonStyle.success)
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        pi = PLATFORM_INFO[self.platform]
        async with db_pool.acquire() as c:
            await c.execute("UPDATE accounts SET verified=TRUE WHERE user_id=$1 AND platform=$2 AND verification_code=$3", str(self.uid), self.platform, self.code)
        accs = await get_accounts(str(self.uid))
        vc = sum(1 for a in accs if a["verified"])
        embed = discord.Embed(title=f"✅ {pi['name']} Verified!", description=f"{pi['emoji']} **@{self.username}** connected!\n\nYou have **{vc}** verified account(s).\nYou can remove the code from your bio.\n\n🎉 Start submitting clips!", color=GREEN)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await interaction.response.edit_message(embed=embed, view=AfterVerifyView(self.uid))

    @discord.ui.button(label="📋 Copy Code", style=discord.ButtonStyle.secondary)
    async def copy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"```\n{self.code}\n```", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM accounts WHERE user_id=$1 AND platform=$2 AND verified=FALSE", str(self.uid), self.platform)
        await interaction.response.edit_message(embed=discord.Embed(title="❌ Cancelled", color=RED), view=None)

class AfterVerifyView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="🔗 Link Another", style=discord.ButtonStyle.success)
    async def another(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🔗 Link Another", description="Select platform.", color=GREEN)
        await interaction.response.edit_message(embed=embed, view=ChoosePlatformView(interaction.user.id))

    @discord.ui.button(label="👤 View Profile", style=discord.ButtonStyle.primary)
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_profile_card(interaction.user)
        await interaction.response.edit_message(embed=embed, view=ViewAccountsView(interaction.user.id))

class UnlinkSelect(discord.ui.Select):
    def __init__(self, uid, accs):
        self.uid = uid
        opts = [discord.SelectOption(label=f"{a['platform'].title()} — @{a['platform_username']}", value=a["platform"], emoji=PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")) for a in accs]
        super().__init__(placeholder="Select to unlink...", options=opts, row=1)

    async def callback(self, interaction: discord.Interaction):
        async with db_pool.acquire() as c:
            await c.execute("DELETE FROM accounts WHERE user_id=$1 AND platform=$2", str(self.uid), self.values[0])
        await interaction.response.edit_message(embed=discord.Embed(title=f"✅ {self.values[0].title()} Unlinked", color=GREEN), view=AfterVerifyView(self.uid))

class UnlinkView(discord.ui.View):
    def __init__(self, uid, accs):
        super().__init__(timeout=120)
        self.add_item(UnlinkSelect(uid, accs))

    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_profile_card(interaction.user)
        await interaction.response.edit_message(embed=embed, view=ViewAccountsView(interaction.user.id))

# ═══════════════ SETUP ═══════════════

class SetupStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🚀 Start Setup", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ensure_user(interaction.user)
        embed = discord.Embed(title="🌍 Step 1/2 — Country", description="Select your country.", color=GREEN)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await interaction.response.edit_message(embed=embed, view=SetupCountryView(interaction.user.id))

class SetupCountryView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.add_item(CountrySelect(uid))

class CountrySelect(discord.ui.Select):
    def __init__(self, uid):
        self.uid = uid
        super().__init__(placeholder="▼ Select country...", options=[discord.SelectOption(label=c, value=c) for c in COUNTRY_LIST], row=1)

    async def callback(self, interaction: discord.Interaction):
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET country=$1 WHERE user_id=$2", self.values[0], str(self.uid))
        embed = discord.Embed(title="💵 Step 2/2 — Payment", description=f"✅ Country: **{self.values[0]}**\n\nSelect payment method:", color=ORANGE)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await interaction.response.edit_message(embed=embed, view=SetupPaymentView(self.uid))

class SetupPaymentView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid

    @discord.ui.button(label="🅿️ PayPal", style=discord.ButtonStyle.primary)
    async def pp(self, i: discord.Interaction, b): await i.response.send_modal(PayModal(self.uid, "PayPal", "PayPal Email"))
    @discord.ui.button(label="📱 UPI", style=discord.ButtonStyle.success)
    async def upi(self, i: discord.Interaction, b): await i.response.send_modal(PayModal(self.uid, "UPI", "UPI ID"))
    @discord.ui.button(label="🏦 Bank", style=discord.ButtonStyle.secondary)
    async def bank(self, i: discord.Interaction, b): await i.response.send_modal(PayModal(self.uid, "Bank Transfer", "Bank Details"))
    @discord.ui.button(label="₿ Crypto", style=discord.ButtonStyle.secondary)
    async def crypto(self, i: discord.Interaction, b): await i.response.send_modal(PayModal(self.uid, "Crypto", "Wallet Address"))

class PayModal(discord.ui.Modal):
    def __init__(self, uid, method, label):
        super().__init__(title=f"{method} Details")
        self.uid = uid
        self.method = method
        self.det = discord.ui.TextInput(label=label, placeholder=f"Enter {method}...", required=True)
        self.add_item(self.det)

    async def on_submit(self, interaction: discord.Interaction):
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET payment_method=$1,payment_details=$2,setup_complete=TRUE WHERE user_id=$3", self.method, self.det.value.strip(), str(self.uid))
        u = await get_user(self.uid)
        accs = await get_accounts(str(self.uid))
        d = "🎉 Account ready!\n\n"
        if accs:
            d += "**🔗 Socials:**\n"
            for a in accs:
                e = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
                d += f"{e} `@{a['platform_username']}` {'✅' if a['verified'] else '⏳'}\n"
        d += f"\n🌍 **Country:** {u['country']}\n💵 **Payment:** {self.method}"
        embed = discord.Embed(title="🎉 Setup Complete!", description=d, color=GREEN)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await interaction.response.edit_message(embed=embed, view=HomeButtonView())

class HomeButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.success)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_home(interaction.user)
        await interaction.response.edit_message(embed=embed, view=HomeView(interaction.user.id))

# ═══════════════ HOME ═══════════════

def build_home(user):
    embed = discord.Embed(title="🔥 Clip Forge Hub", description=f"Welcome, **{user.display_name}**!\nMonetize your content. Track earnings. Get paid.", color=CYAN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    return embed

class HomeView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid

    @discord.ui.button(label="⚡ Setup", style=discord.ButtonStyle.success)
    async def setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ensure_user(interaction.user)
        u = await get_user(str(interaction.user.id))
        if u and u["setup_complete"]:
            await interaction.response.send_message("✅ Already set up!", ephemeral=True)
            return
        embed = discord.Embed(title="⚡ Account Setup", description="🌍 Step 1 — Country\n💵 Step 2 — Payment\n\n*Link socials in #connect-socials!*", color=CYAN)
        await interaction.response.edit_message(embed=embed, view=SetupStartView())

    @discord.ui.button(label="👤 Profile", style=discord.ButtonStyle.primary)
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_full_profile(interaction.user)
        await interaction.response.edit_message(embed=embed, view=ProfileView(interaction.user.id))

    @discord.ui.button(label="💰 Earnings", style=discord.ButtonStyle.success)
    async def earnings(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_earnings(interaction.user)
        await interaction.response.edit_message(embed=embed, view=EarningsView(interaction.user.id))

    @discord.ui.button(label="📤 Submit", style=discord.ButtonStyle.primary, row=2)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        v = await get_verified_accounts(str(interaction.user.id))
        if not v:
            await interaction.response.send_message("❌ Verify a social account in #connect-socials first!", ephemeral=True)
            return
        embed = discord.Embed(title="📤 Submit Clip", description="Select platform.", color=PURPLE)
        await interaction.response.edit_message(embed=embed, view=SubmitView(interaction.user.id))

    @discord.ui.button(label="🏆 Leaderboard", style=discord.ButtonStyle.secondary, row=2)
    async def lb(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_lb()
        await interaction.response.edit_message(embed=embed, view=LBView(interaction.user.id))

    @discord.ui.button(label="📚 Help", style=discord.ButtonStyle.secondary, row=2)
    async def help(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_help()
        await interaction.response.edit_message(embed=embed, view=HelpView(interaction.user.id))

# ═══════════════ PROFILE ═══════════════

async def build_full_profile(user):
    uid = str(user.id)
    await ensure_user(user)
    u = await get_user(uid)
    accs = await get_accounts(uid)
    clips = await get_clips(uid)
    rate = await get_rate()
    tv = sum(c["views"] for c in clips)
    embed = discord.Embed(title=f"👤 {user.display_name}", color=CYAN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="Status", value="✅ Verified" if u and u["setup_complete"] else "⚠️ Incomplete", inline=True)
    embed.add_field(name="📹 Clips", value=str(len(clips)), inline=True)
    embed.add_field(name="👁 Views", value=f"{tv:,}", inline=True)
    embed.add_field(name="💵 Earnings", value=f"${tv*rate:.2f}", inline=True)
    if u and u["country"]: embed.add_field(name="🌍", value=u["country"], inline=True)
    if u and u["payment_method"]: embed.add_field(name="💳", value=u["payment_method"], inline=True)
    if accs:
        t = "\n".join(f"{PLATFORM_INFO.get(a['platform'],{}).get('emoji','🔗')} **{a['platform'].title()}**: `@{a['platform_username']}` {'✅' if a['verified'] else '⏳'}" for a in accs)
        embed.add_field(name="🔗 Socials", value=t, inline=False)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    return embed

class ProfileView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary)
    async def home(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=build_home(i.user), view=HomeView(i.user.id))

    @discord.ui.button(label="💰 Earnings", style=discord.ButtonStyle.success)
    async def earn(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=await build_earnings(i.user), view=EarningsView(i.user.id))

    @discord.ui.button(label="✏️ Edit", style=discord.ButtonStyle.primary)
    async def edit(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=discord.Embed(title="✏️ Edit Account", color=ORANGE), view=EditView(i.user.id))

class EditView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid

    @discord.ui.button(label="🌍 Country", style=discord.ButtonStyle.success)
    async def country(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=discord.Embed(title="🌍 Change Country", color=GREEN), view=EditCountryView(i.user.id))

    @discord.ui.button(label="💵 Payment", style=discord.ButtonStyle.primary)
    async def pay(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=discord.Embed(title="💵 Change Payment", color=ORANGE), view=EditPayView(i.user.id))

    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.secondary)
    async def back(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=await build_full_profile(i.user), view=ProfileView(i.user.id))

class EditCountryView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.add_item(EditCountrySel(uid))

class EditCountrySel(discord.ui.Select):
    def __init__(self, uid):
        self.uid = uid
        super().__init__(placeholder="▼ Country...", options=[discord.SelectOption(label=c, value=c) for c in COUNTRY_LIST], row=1)

    async def callback(self, i: discord.Interaction):
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET country=$1 WHERE user_id=$2", self.values[0], str(self.uid))
        await i.response.send_message(f"✅ Country → **{self.values[0]}**", ephemeral=True)

class EditPayView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid

    @discord.ui.button(label="🅿️ PayPal", style=discord.ButtonStyle.primary)
    async def pp(self, i: discord.Interaction, b): await i.response.send_modal(EditPayModal(self.uid, "PayPal", "Email"))
    @discord.ui.button(label="📱 UPI", style=discord.ButtonStyle.success)
    async def upi(self, i: discord.Interaction, b): await i.response.send_modal(EditPayModal(self.uid, "UPI", "UPI ID"))
    @discord.ui.button(label="🏦 Bank", style=discord.ButtonStyle.secondary)
    async def bank(self, i: discord.Interaction, b): await i.response.send_modal(EditPayModal(self.uid, "Bank Transfer", "Details"))
    @discord.ui.button(label="₿ Crypto", style=discord.ButtonStyle.secondary)
    async def crypto(self, i: discord.Interaction, b): await i.response.send_modal(EditPayModal(self.uid, "Crypto", "Wallet"))
    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.danger, row=2)
    async def back(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=await build_full_profile(i.user), view=ProfileView(i.user.id))

class EditPayModal(discord.ui.Modal):
    def __init__(self, uid, method, label):
        super().__init__(title=f"Update {method}")
        self.uid = uid
        self.method = method
        self.det = discord.ui.TextInput(label=label, required=True)
        self.add_item(self.det)

    async def on_submit(self, i: discord.Interaction):
        async with db_pool.acquire() as c:
            await c.execute("UPDATE users SET payment_method=$1,payment_details=$2 WHERE user_id=$3", self.method, self.det.value.strip(), str(self.uid))
        await i.response.send_message(f"✅ Payment → **{self.method}**", ephemeral=True)

# ═══════════════ EARNINGS ═══════════════

async def build_earnings(user):
    clips = await get_clips(str(user.id))
    rate = await get_rate()
    tv = sum(c["views"] for c in clips)
    te = tv * rate
    pe = sum(c["views"] for c in clips if c["status"]=="pending") * rate
    pa = sum(c["views"] for c in clips if c["status"]=="paid") * rate
    embed = discord.Embed(title="💰 Earnings", color=GREEN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="💵 Total", value=f"**${te:.2f}**", inline=True)
    embed.add_field(name="⏳ Pending", value=f"${pe:.2f}", inline=True)
    embed.add_field(name="✅ Paid", value=f"${pa:.2f}", inline=True)
    embed.add_field(name="👁 Views", value=f"{tv:,}", inline=True)
    embed.add_field(name="📹 Clips", value=str(len(clips)), inline=True)
    embed.add_field(name="💲 Rate", value=f"${rate}/view", inline=True)
    if clips:
        r = ""
        for cl in clips[:5]:
            e = PLATFORM_INFO.get(cl["platform"],{}).get("emoji","🔗")
            s = "✅" if cl["status"]=="paid" else "⏳"
            r += f"{s} {e} {cl['views']:,} views — ${cl['views']*rate:.2f}\n"
        embed.add_field(name="📋 Recent", value=r, inline=False)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    return embed

class EarningsView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary)
    async def home(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=build_home(i.user), view=HomeView(i.user.id))

    @discord.ui.button(label="📤 Submit", style=discord.ButtonStyle.primary)
    async def sub(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=discord.Embed(title="📤 Submit Clip", color=PURPLE), view=SubmitView(i.user.id))

    @discord.ui.button(label="🏆 Leaderboard", style=discord.ButtonStyle.success)
    async def lb(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=await build_lb(), view=LBView(i.user.id))

# ═══════════════ SUBMIT ═══════════════

class SubmitView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid
        self.add_item(SubmitSel(uid))

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=build_home(i.user), view=HomeView(i.user.id))

class SubmitSel(discord.ui.Select):
    def __init__(self, uid):
        self.uid = uid
        opts = [discord.SelectOption(label=v["name"], emoji=v["emoji"], value=k) for k, v in PLATFORM_INFO.items()]
        super().__init__(placeholder="▼ Platform...", options=opts, row=1)

    async def callback(self, i: discord.Interaction):
        await i.response.send_modal(SubmitModal(self.uid, self.values[0]))

class SubmitModal(discord.ui.Modal):
    def __init__(self, uid, platform):
        super().__init__(title=f"Submit {PLATFORM_INFO[platform]['name']} Clip")
        self.uid = uid
        self.platform = platform
        self.url = discord.ui.TextInput(label="Clip URL", placeholder="https://...", required=True)
        self.views = discord.ui.TextInput(label="View Count", placeholder="50000", required=True)
        self.add_item(self.url)
        self.add_item(self.views)

    async def on_submit(self, i: discord.Interaction):
        url = self.url.value.strip()
        pi = PLATFORM_INFO[self.platform]
        if not re.search(pi["url_pattern"], url, re.IGNORECASE):
            await i.response.send_message(f"❌ Not a valid **{pi['name']}** URL!", ephemeral=True)
            return
        try:
            vc = int(self.views.value.strip().replace(",","").replace("k","000").replace("K","000"))
        except:
            await i.response.send_message("❌ Invalid views!", ephemeral=True)
            return
        rate = await get_rate()
        async with db_pool.acquire() as c:
            ex = await c.fetchrow("SELECT id FROM clips WHERE url=$1", url)
            if ex:
                await i.response.send_message("❌ Already submitted!", ephemeral=True)
                return
            await c.execute("INSERT INTO clips(user_id,platform,url,views,earnings,status) VALUES($1,$2,$3,$4,$5,'pending')", str(self.uid), self.platform, url, vc, vc*rate)
        embed = discord.Embed(title="✅ Clip Submitted!", description=f"{pi['emoji']} **{pi['name']}**\n👁 **{vc:,}** views\n💵 **${vc*rate:.2f}**\n🔗 {url}\n\n⏳ Pending Review", color=GREEN)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await i.response.edit_message(embed=embed, view=AfterSubmitView(self.uid))

class AfterSubmitView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="📤 Another", style=discord.ButtonStyle.primary)
    async def another(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=discord.Embed(title="📤 Submit", color=PURPLE), view=SubmitView(i.user.id))

    @discord.ui.button(label="💰 Earnings", style=discord.ButtonStyle.success)
    async def earn(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=await build_earnings(i.user), view=EarningsView(i.user.id))

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary)
    async def home(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=build_home(i.user), view=HomeView(i.user.id))

# ═══════════════ LEADERBOARD ═══════════════

async def build_lb():
    data = await get_leaderboard()
    embed = discord.Embed(title="🏆 Leaderboard", color=ORANGE)
    if not data:
        embed.description = "No earnings yet!"
    else:
        m = ["🥇","🥈","🥉"]
        t = ""
        for idx,(name,earn,views,clips) in enumerate(data):
            r = m[idx] if idx < 3 else f"**{idx+1}.**"
            t += f"{r} **{name}** — ${earn:.2f} ({views:,} views)\n"
        embed.description = t
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    return embed

class LBView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary)
    async def home(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=build_home(i.user), view=HomeView(i.user.id))

    @discord.ui.button(label="👤 Profile", style=discord.ButtonStyle.primary)
    async def prof(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=await build_full_profile(i.user), view=ProfileView(i.user.id))

# ═══════════════ HELP ═══════════════

def build_help():
    embed = discord.Embed(title="📚 Commands", color=LIGHT_CYAN)
    embed.add_field(name="⚡ User", value="`/home` `/setup` `/profile` `/earnings` `/submit` `/leaderboard` `/connect` `/help`", inline=False)
    embed.add_field(name="🔧 Admin", value="`/setrate` `/allusers` `/userinfo` `/approveclip` `/postpanel` `/createcampaign`", inline=False)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    return embed

class HelpView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.success)
    async def home(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=build_home(i.user), view=HomeView(i.user.id))

# ═══════════════ CAMPAIGN AUTO-TRACK ═══════════════

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if db_pool:
        async with db_pool.acquire() as c:
            camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(message.channel.id))
        if camp:
            urls = re.findall(r'https?://\S+', message.content)
            if urls:
                uid = str(message.author.id)
                v = await get_verified_accounts(uid)
                if not v:
                    await message.reply("❌ Verify a social account in #connect-socials first!", delete_after=10)
                    return
                url = urls[0]
                if camp["platform"]:
                    pi = PLATFORM_INFO.get(camp["platform"],{})
                    if pi and not re.search(pi.get("url_pattern",""), url, re.IGNORECASE):
                        await message.reply(f"❌ Only **{pi.get('name','')}** links allowed!", delete_after=10)
                        return
                async with db_pool.acquire() as c:
                    ex = await c.fetchrow("SELECT id FROM clips WHERE url=$1", url)
                    if ex:
                        await message.reply("⚠️ Already submitted!", delete_after=10)
                        return
                    await c.execute("INSERT INTO clips(user_id,platform,url,views,earnings,status,campaign_id) VALUES($1,$2,$3,0,0,'tracking',$4)", uid, camp["platform"] or "unknown", url, str(camp["id"]))
                await message.add_reaction("✅")
                await message.reply(f"✅ Tracked for **{camp['name']}**!", delete_after=15)
    await bot.process_commands(message)

# ═══════════════ SLASH COMMANDS ═══════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(ConnectSocialsView())
    try:
        s = await bot.tree.sync()
        print(f"✅ Synced {len(s)} commands")
    except Exception as e:
        print(f"❌ Sync: {e}")
    print(f"✅ {bot.user} is live!")

@bot.tree.command(name="home", description="Main menu")
async def s_home(i: discord.Interaction):
    await ensure_user(i.user); await i.response.send_message(embed=build_home(i.user), view=HomeView(i.user.id))

@bot.tree.command(name="setup", description="Account setup")
async def s_setup(i: discord.Interaction):
    await ensure_user(i.user)
    u = await get_user(str(i.user.id))
    if u and u["setup_complete"]: await i.response.send_message("✅ Done! Use `/profile`.", ephemeral=True); return
    await i.response.send_message(embed=discord.Embed(title="⚡ Setup", description="🌍 Country → 💵 Payment", color=CYAN), view=SetupStartView())

@bot.tree.command(name="profile", description="Your profile")
async def s_profile(i: discord.Interaction):
    await ensure_user(i.user); await i.response.send_message(embed=await build_full_profile(i.user), view=ProfileView(i.user.id))

@bot.tree.command(name="earnings", description="Earnings dashboard")
async def s_earnings(i: discord.Interaction):
    await ensure_user(i.user); await i.response.send_message(embed=await build_earnings(i.user), view=EarningsView(i.user.id))

@bot.tree.command(name="submit", description="Submit a clip")
async def s_submit(i: discord.Interaction):
    v = await get_verified_accounts(str(i.user.id))
    if not v: await i.response.send_message("❌ Verify account first!", ephemeral=True); return
    await i.response.send_message(embed=discord.Embed(title="📤 Submit", color=PURPLE), view=SubmitView(i.user.id))

@bot.tree.command(name="leaderboard", description="Top earners")
async def s_lb(i: discord.Interaction):
    await i.response.send_message(embed=await build_lb(), view=LBView(i.user.id))

@bot.tree.command(name="connect", description="Link social account")
async def s_connect(i: discord.Interaction):
    await ensure_user(i.user); await i.response.send_message(embed=discord.Embed(title="🔗 Link Account", color=GREEN), view=ChoosePlatformView(i.user.id), ephemeral=True)

@bot.tree.command(name="help", description="All commands")
async def s_help(i: discord.Interaction):
    await i.response.send_message(embed=build_help(), view=HelpView(i.user.id))

# Admin
@bot.tree.command(name="postpanel", description="[Admin] Post connect-socials panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_panel(i: discord.Interaction):
    embed = discord.Embed(title="🔗 Manage Your Social Accounts", description="Use the buttons below to manage your account.\n\n**🔗 Link Account**\nConnect your social media page.\n\n**👥 View Accounts**\nView your connected accounts, views & earnings.", color=GREEN)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    await i.channel.send(embed=embed, view=ConnectSocialsView())
    await i.response.send_message("✅ Panel posted!", ephemeral=True)

@bot.tree.command(name="createcampaign", description="[Admin] Create campaign in this channel")
@app_commands.checks.has_permissions(administrator=True)
async def s_campaign(i: discord.Interaction, name: str, platform: str = ""):
    if platform and platform.lower() not in PLATFORM_INFO:
        await i.response.send_message(f"❌ Use: {', '.join(PLATFORM_INFO.keys())}", ephemeral=True); return
    async with db_pool.acquire() as c:
        await c.execute("INSERT INTO campaigns(name,channel_id,platform,created_by) VALUES($1,$2,$3,$4)", name, str(i.channel.id), platform.lower() if platform else "", str(i.user.id))
    pt = f" ({PLATFORM_INFO[platform.lower()]['name']})" if platform else ""
    await i.response.send_message(embed=discord.Embed(title=f"🎯 Campaign: {name}{pt}", description="Users can now paste links here!\nBot auto-tracks submissions.", color=PURPLE))

@bot.tree.command(name="setrate", description="[Admin] Set rate")
@app_commands.checks.has_permissions(administrator=True)
async def s_rate(i: discord.Interaction, rate: float):
    async with db_pool.acquire() as c:
        await c.execute("UPDATE settings SET value=$1 WHERE key='payment_rate'", str(rate))
    await i.response.send_message(embed=discord.Embed(title="✅ Rate Updated", description=f"${rate}/view", color=GREEN))

@bot.tree.command(name="allusers", description="[Admin] All users")
@app_commands.checks.has_permissions(administrator=True)
async def s_all(i: discord.Interaction):
    d = await get_leaderboard()
    if not d: await i.response.send_message("❌ None!", ephemeral=True); return
    t = "\n".join(f"• **{n}** — ${e:.2f} ({v:,} views)" for n,e,v,cl in d)
    await i.response.send_message(embed=discord.Embed(title="👥 Users", description=t, color=DARK_BLUE))

@bot.tree.command(name="userinfo", description="[Admin] User info")
@app_commands.checks.has_permissions(administrator=True)
async def s_uinfo(i: discord.Interaction, user: discord.User):
    uid = str(user.id)
    u = await get_user(uid)
    if not u: await i.response.send_message("❌ Not found!", ephemeral=True); return
    accs = await get_accounts(uid)
    clips = await get_clips(uid)
    rate = await get_rate()
    tv = sum(c["views"] for c in clips)
    embed = discord.Embed(title=f"👤 {user.name}", color=LIGHT_CYAN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="Status", value="✅" if u["setup_complete"] else "⚠️", inline=True)
    embed.add_field(name="Clips", value=str(len(clips)), inline=True)
    embed.add_field(name="Views", value=f"{tv:,}", inline=True)
    embed.add_field(name="Earnings", value=f"${tv*rate:.2f}", inline=True)
    embed.add_field(name="Country", value=u["country"] or "—", inline=True)
    embed.add_field(name="Payment", value=u["payment_method"] or "—", inline=True)
    if u["payment_details"]: embed.add_field(name="Details", value=f"`{u['payment_details']}`", inline=False)
    if accs:
        embed.add_field(name="Socials", value="\n".join(f"{PLATFORM_INFO.get(a['platform'],{}).get('emoji','🔗')} `@{a['platform_username']}` {'✅' if a['verified'] else '⏳'}" for a in accs), inline=False)
    await i.response.send_message(embed=embed)

@bot.tree.command(name="approveclip", description="[Admin] Approve clip")
@app_commands.checks.has_permissions(administrator=True)
async def s_approve(i: discord.Interaction, clip_id: int):
    async with db_pool.acquire() as c:
        cl = await c.fetchrow("SELECT * FROM clips WHERE id=$1", clip_id)
        if not cl: await i.response.send_message("❌ Not found!", ephemeral=True); return
        await c.execute("UPDATE clips SET status='paid' WHERE id=$1", clip_id)
    await i.response.send_message(embed=discord.Embed(title=f"✅ Clip #{clip_id} Approved", color=GREEN))

# Legacy
@bot.command(name="home")
async def c_home(ctx):
    await ensure_user(ctx.author); await ctx.send(embed=build_home(ctx.author), view=HomeView(ctx.author.id))

@bot.command(name="help")
async def c_help(ctx):
    await ctx.send(embed=build_help(), view=HelpView(ctx.author.id))

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN not found!")
