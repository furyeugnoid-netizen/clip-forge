import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncpg
import asyncio
import os
import random
import string
import re
import traceback
from datetime import datetime, timedelta

# ═══════════════════════════════════════════
#  CLIP FORGE BOT v4.0
# ═══════════════════════════════════════════

CYAN = 0x00FFFF
LIGHT_CYAN = 0x00D4FF
DARK_BLUE = 0x0099FF
GREEN = 0x00D26A
ORANGE = 0xFF8C00
RED = 0xFF4757
PURPLE = 0x7B68EE
GOLD = 0xFFD700

DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("DISCORD_TOKEN")
FOOTER = "Clip Forge • clip.tech"

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

def footer(embed):
    embed.set_footer(text=FOOTER, icon_url="https://cdn.discordapp.com/embed/avatars/0.png")
    return embed

# ═══════════════ DATABASE ═══════════════

async def get_db():
    global db_pool
    if db_pool is None or db_pool._closed:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return db_pool

async def init_db():
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY,username TEXT,avatar_url TEXT DEFAULT '',country TEXT DEFAULT '',payment_method TEXT DEFAULT '',payment_details TEXT DEFAULT '',setup_complete BOOLEAN DEFAULT FALSE,created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS accounts(id SERIAL PRIMARY KEY,user_id TEXT REFERENCES users(user_id),platform TEXT,platform_username TEXT,platform_url TEXT DEFAULT '',verified BOOLEAN DEFAULT FALSE,verification_code TEXT DEFAULT '',linked_at TIMESTAMP DEFAULT NOW(),UNIQUE(user_id,platform),UNIQUE(platform,platform_username))")
        await c.execute("CREATE TABLE IF NOT EXISTS clips(id SERIAL PRIMARY KEY,user_id TEXT REFERENCES users(user_id),platform TEXT,url TEXT UNIQUE,views INTEGER DEFAULT 0,last_views INTEGER DEFAULT 0,earnings REAL DEFAULT 0,status TEXT DEFAULT 'pending',campaign_id TEXT DEFAULT '',submitted_at TIMESTAMP DEFAULT NOW(),last_checked TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS campaigns(id SERIAL PRIMARY KEY,name TEXT,channel_id TEXT,platform TEXT DEFAULT '',created_by TEXT,active BOOLEAN DEFAULT TRUE,deadline TIMESTAMP DEFAULT NULL,daily_limit INTEGER DEFAULT 50,created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)")
        await c.execute("INSERT INTO settings(key,value) VALUES('payment_rate','0.001') ON CONFLICT(key) DO NOTHING")
        await c.execute("CREATE TABLE IF NOT EXISTS tickets(id SERIAL PRIMARY KEY,user_id TEXT,channel_id TEXT,status TEXT DEFAULT 'open',subject TEXT DEFAULT '',created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS payouts(id SERIAL PRIMARY KEY,user_id TEXT,amount REAL,status TEXT DEFAULT 'pending',admin_id TEXT DEFAULT '',note TEXT DEFAULT '',created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS bans(id SERIAL PRIMARY KEY,user_id TEXT,reason TEXT DEFAULT '',banned_by TEXT,created_at TIMESTAMP DEFAULT NOW(),UNIQUE(user_id))")
        try:
            await c.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS deadline TIMESTAMP DEFAULT NULL")
            await c.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS daily_limit INTEGER DEFAULT 50")
            await c.execute("ALTER TABLE clips ADD COLUMN IF NOT EXISTS last_views INTEGER DEFAULT 0")
            await c.execute("ALTER TABLE clips ADD COLUMN IF NOT EXISTS last_checked TIMESTAMP DEFAULT NOW()")
        except:
            pass
    print("✅ Database initialized")

async def get_rate():
    pool = await get_db()
    async with pool.acquire() as c:
        r = await c.fetchrow("SELECT value FROM settings WHERE key='payment_rate'")
        return float(r["value"]) if r else 0.001

async def ensure_user(user):
    av = str(user.display_avatar.url) if user.display_avatar else ""
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO users(user_id,username,avatar_url) VALUES($1,$2,$3) ON CONFLICT(user_id) DO UPDATE SET username=$2,avatar_url=$3", str(user.id), user.name, av)

async def get_user(uid):
    pool = await get_db()
    async with pool.acquire() as c:
        return await c.fetchrow("SELECT * FROM users WHERE user_id=$1", str(uid))

async def get_accounts(uid):
    pool = await get_db()
    async with pool.acquire() as c:
        return await c.fetch("SELECT * FROM accounts WHERE user_id=$1 ORDER BY linked_at", str(uid))

async def get_verified_accounts(uid):
    pool = await get_db()
    async with pool.acquire() as c:
        return await c.fetch("SELECT * FROM accounts WHERE user_id=$1 AND verified=TRUE", str(uid))

async def get_clips(uid):
    pool = await get_db()
    async with pool.acquire() as c:
        return await c.fetch("SELECT * FROM clips WHERE user_id=$1 ORDER BY submitted_at DESC", str(uid))

async def get_total_views(uid):
    pool = await get_db()
    async with pool.acquire() as c:
        r = await c.fetchrow("SELECT COALESCE(SUM(views),0) as t FROM clips WHERE user_id=$1", str(uid))
        return int(r["t"])

async def get_leaderboard():
    rate = await get_rate()
    pool = await get_db()
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT u.user_id,u.username,COALESCE(SUM(c.views),0) as tv,COALESCE(COUNT(c.id),0) as tc FROM users u LEFT JOIN clips c ON u.user_id=c.user_id GROUP BY u.user_id,u.username ORDER BY tv DESC LIMIT 15")
        return [(r["username"], int(r["tv"])*rate, int(r["tv"]), int(r["tc"])) for r in rows]

# ═══════════════ ERROR HANDLER ═══════════════

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ Admin only!", ephemeral=True)
    else:
        print(f"Error: {error}")
        traceback.print_exc()
        try:
            await interaction.response.send_message("❌ Something went wrong. Try again.", ephemeral=True)
        except:
            pass

# ═══════════════ CONNECT SOCIALS PANEL ═══════════════

class ConnectSocialsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Link Account", emoji="🔗", style=discord.ButtonStyle.success, custom_id="p_link")
    async def link(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            embed = discord.Embed(title="🔗 Link Your Social Account", description="**Select a platform** to connect.\n\n📌 **How it works:**\n1️⃣ Choose platform\n2️⃣ Enter username & profile URL\n3️⃣ Get a **verification code**\n4️⃣ Add code to your **bio**\n5️⃣ Click **Verify** ✅", color=GREEN)
            footer(embed)
            await interaction.response.send_message(embed=embed, view=ChoosePlatformView(interaction.user.id), ephemeral=True)
        except Exception as e:
            print(f"Link error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="View Accounts", emoji="👥", style=discord.ButtonStyle.primary, custom_id="p_view")
    async def view(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            embed = await build_profile_card(interaction.user)
            await interaction.response.send_message(embed=embed, view=ViewAccountsView(interaction.user.id), ephemeral=True)
        except Exception as e:
            print(f"View error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

async def build_profile_card(user):
    uid = str(user.id)
    accounts = await get_accounts(uid)
    tv = await get_total_views(uid)
    rate = await get_rate()
    clips = await get_clips(uid)
    embed = discord.Embed(title="👤 Your Profile", color=CYAN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="👁 All-Time Views", value=f"**{tv:,}**", inline=True)
    embed.add_field(name="💵 Earnings", value=f"**${tv*rate:.2f}**", inline=True)
    embed.add_field(name="📹 Total Posts", value=f"**{len(clips)}**", inline=True)
    if accounts:
        t = ""
        for a in accounts:
            e = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
            s = "✅" if a["verified"] else "⏳ Unverified"
            t += f"{e} **{a['platform'].title()}**: `@{a['platform_username']}` {s}\n"
        embed.add_field(name="🔗 Connected Accounts", value=t, inline=False)
    else:
        embed.add_field(name="🔗 Connected Accounts", value="No accounts linked yet.\nClick **Link Account** to start!", inline=False)
    footer(embed)
    return embed

class ViewAccountsView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="🔗 Link New", style=discord.ButtonStyle.success)
    async def link(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🔗 Link Account", description="Select a platform.", color=GREEN)
        footer(embed)
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
        pool = await get_db()
        async with pool.acquire() as c:
            ex = await c.fetchrow("SELECT user_id FROM accounts WHERE platform=$1 AND platform_username=$2 AND user_id!=$3", self.platform, username, str(self.uid))
            if ex:
                await interaction.response.send_message(f"❌ `@{username}` on **{pi['name']}** is already linked by another user!\nEach account can only be connected to **one** Discord account.", ephemeral=True)
                return
            own = await c.fetchrow("SELECT * FROM accounts WHERE platform=$1 AND user_id=$2", self.platform, str(self.uid))
            if own and own["verified"]:
                await interaction.response.send_message(f"✅ You already have verified **{pi['name']}**: `@{own['platform_username']}`\nUnlink first to change.", ephemeral=True)
                return
            code = gen_code()
            await c.execute("INSERT INTO accounts(user_id,platform,platform_username,platform_url,verified,verification_code) VALUES($1,$2,$3,$4,FALSE,$5) ON CONFLICT(user_id,platform) DO UPDATE SET platform_username=$3,platform_url=$4,verified=FALSE,verification_code=$5,linked_at=NOW()", str(self.uid), self.platform, username, url, code)
        embed = discord.Embed(title=f"{pi['emoji']} Verify Your {pi['name']}", description=f"**Account:** `@{username}`\n**URL:** {url}\n\n━━━━━━━━━━━━━━━━━━━━━\n\n📋 **Your Verification Code:**\n```\n{code}\n```\n\n**Steps:**\n1️⃣ Copy the code above\n2️⃣ Go to your **{pi['name']}** profile\n3️⃣ Add code to your **bio**\n4️⃣ Click **✅ Verify Now**\n\n⚠️ *Remove code from bio after verification*", color=ORANGE)
        footer(embed)
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
        pool = await get_db()
        async with pool.acquire() as c:
            await c.execute("UPDATE accounts SET verified=TRUE WHERE user_id=$1 AND platform=$2 AND verification_code=$3", str(self.uid), self.platform, self.code)
        accs = await get_accounts(str(self.uid))
        vc = sum(1 for a in accs if a["verified"])
        embed = discord.Embed(title=f"✅ {pi['name']} Verified!", description=f"{pi['emoji']} **@{self.username}** connected!\n\nYou have **{vc}** verified account(s).\nRemove the code from your bio now.\n\n🎉 You can now submit posts in campaigns!", color=GREEN)
        footer(embed)
        await interaction.response.edit_message(embed=embed, view=AfterVerifyView(self.uid))

    @discord.ui.button(label="📋 Copy Code", style=discord.ButtonStyle.secondary)
    async def copy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"```\n{self.code}\n```", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        pool = await get_db()
        async with pool.acquire() as c:
            await c.execute("DELETE FROM accounts WHERE user_id=$1 AND platform=$2 AND verified=FALSE", str(self.uid), self.platform)
        await interaction.response.edit_message(embed=discord.Embed(title="❌ Cancelled", color=RED), view=None)

class AfterVerifyView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="🔗 Link Another", style=discord.ButtonStyle.success)
    async def another(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="🔗 Link Another", description="Select platform.", color=GREEN)
        footer(embed)
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
        pool = await get_db()
        async with pool.acquire() as c:
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

# ═══════════════ CAMPAIGN PANEL ═══════════════
# This is the main panel users see in campaign channels
# Like the SuperClip screenshot with: Submissions, Accounts, Payouts, Stats, Submit post

class CampaignView(discord.ui.View):
    def __init__(self, campaign_name):
        super().__init__(timeout=None)
        self.campaign_name = campaign_name

    @discord.ui.button(label="Submissions", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="p_subs")
    async def submissions(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            clips = await get_clips(str(interaction.user.id))
            if not clips:
                await interaction.response.send_message("📋 You have **0** submissions.\nClick **Submit post** to get started!", ephemeral=True)
                return
            desc = ""
            rate = await get_rate()
            for i, cl in enumerate(clips[:10], 1):
                e = PLATFORM_INFO.get(cl["platform"],{}).get("emoji","🔗")
                s = "✅" if cl["status"] == "paid" else "⏳" if cl["status"] == "pending" else "🔍"
                desc += f"{i}. {e} {s} **{cl['views']:,}** views — ${cl['views']*rate:.2f}\n"
            embed = discord.Embed(title="📋 Your Submissions", description=desc, color=DARK_BLUE)
            footer(embed)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Subs error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="Accounts", emoji="🔗", style=discord.ButtonStyle.secondary, custom_id="p_camp_accs")
    async def accounts(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            embed = await build_profile_card(interaction.user)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Accs error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="Payouts", emoji="💸", style=discord.ButtonStyle.secondary, custom_id="p_payouts")
    async def payouts(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            clips = await get_clips(str(interaction.user.id))
            rate = await get_rate()
            tv = sum(c["views"] for c in clips)
            te = tv * rate
            pe = sum(c["views"] for c in clips if c["status"] in ("pending","under_review","tracking")) * rate
            pa = sum(c["views"] for c in clips if c["status"] == "paid") * rate
            embed = discord.Embed(title="💸 Your Payouts", color=GREEN)
            embed.add_field(name="💵 Total Earned", value=f"**${te:.2f}**", inline=True)
            embed.add_field(name="⏳ Pending", value=f"${pe:.2f}", inline=True)
            embed.add_field(name="✅ Paid", value=f"${pa:.2f}", inline=True)
            u = await get_user(str(interaction.user.id))
            if u and u["payment_method"]:
                embed.add_field(name="💳 Payment Method", value=u["payment_method"], inline=False)
            footer(embed)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Payouts error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="Stats", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="p_stats")
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            clips = await get_clips(str(interaction.user.id))
            rate = await get_rate()
            tv = sum(c["views"] for c in clips)
            accs = await get_verified_accounts(str(interaction.user.id))

            # Tier
            tier = "⚪ Unranked"
            if tv >= 100000: tier = "💎 Diamond"
            elif tv >= 50000: tier = "🥇 Gold"
            elif tv >= 10000: tier = "🥈 Silver"
            elif tv >= 1000: tier = "🥉 Bronze"

            embed = discord.Embed(title=f"📊 {interaction.user.display_name}'s Stats", color=PURPLE)
            embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            embed.add_field(name="🎖️ Tier", value=tier, inline=True)
            embed.add_field(name="👁 Views", value=f"{tv:,}", inline=True)
            embed.add_field(name="📹 Posts", value=str(len(clips)), inline=True)
            embed.add_field(name="💵 Earnings", value=f"${tv*rate:.2f}", inline=True)
            embed.add_field(name="🔗 Accounts", value=str(len(accs)), inline=True)

            # Platform breakdown
            if clips:
                platforms = {}
                for cl in clips:
                    p = cl["platform"]
                    if p not in platforms:
                        platforms[p] = {"views": 0, "count": 0}
                    platforms[p]["views"] += cl["views"]
                    platforms[p]["count"] += 1
                bd = ""
                for p, d in platforms.items():
                    e = PLATFORM_INFO.get(p,{}).get("emoji","🔗")
                    bd += f"{e} **{p.title()}**: {d['views']:,} views ({d['count']} posts)\n"
                embed.add_field(name="📊 Breakdown", value=bd, inline=False)

            footer(embed)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Stats error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="Submit post", emoji="➕", style=discord.ButtonStyle.success, custom_id="p_submit_post", row=2)
    async def submit_post(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            uid = str(interaction.user.id)
            pool = await get_db()

            # Check if banned
            async with pool.acquire() as c:
                ban = await c.fetchrow("SELECT * FROM bans WHERE user_id=$1", uid)
            if ban:
                await interaction.response.send_message(f"🚫 You are **banned** from campaigns.\nReason: {ban['reason'] or 'No reason given'}", ephemeral=True)
                return

            # Check verified accounts
            accs = await get_verified_accounts(uid)
            if not accs:
                await interaction.response.send_message("❌ You need a **verified** social account!\nGo to #connect-socials first.", ephemeral=True)
                return

            # Check campaign deadline
            async with pool.acquire() as c:
                camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(interaction.channel.id))
            if camp:
                if camp["deadline"] and datetime.utcnow() > camp["deadline"]:
                    await interaction.response.send_message("⏰ This campaign has **expired**! Submissions are closed.", ephemeral=True)
                    return

                # Check daily limit
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                async with pool.acquire() as c:
                    today_count = await c.fetchrow(
                        "SELECT COUNT(*) as cnt FROM clips WHERE user_id=$1 AND campaign_id=$2 AND submitted_at >= $3",
                        uid, str(camp["id"]), today_start
                    )
                if today_count and int(today_count["cnt"]) >= camp["daily_limit"]:
                    await interaction.response.send_message(f"📛 Daily limit reached! Max **{camp['daily_limit']}** posts per day.", ephemeral=True)
                    return

            desc = "Select which account you're submitting from:\n\n"
            for a in accs:
                e = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
                desc += f"{e} **{a['platform'].title()}**: `@{a['platform_username']}` ✅\n"
            embed = discord.Embed(title="➕ Submit Post", description=desc, color=GREEN)
            footer(embed)
            await interaction.response.send_message(embed=embed, view=SubmitPlatformView(interaction.user.id, accs), ephemeral=True)
        except Exception as e:
            print(f"Submit error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)


class SubmitPlatformView(discord.ui.View):
    def __init__(self, uid, accs):
        super().__init__(timeout=120)
        self.add_item(SubmitPlatformSelect(uid, accs))


class SubmitPlatformSelect(discord.ui.Select):
    def __init__(self, uid, accs):
        self.uid = uid
        opts = []
        for a in accs:
            e = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
            opts.append(discord.SelectOption(label=f"{a['platform'].title()} — @{a['platform_username']}", value=a["platform"], emoji=e))
        super().__init__(placeholder="▼ Select account...", options=opts)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SubmitPostModal(self.uid, self.values[0]))


class SubmitPostModal(discord.ui.Modal):
    def __init__(self, uid, platform):
        pn = PLATFORM_INFO[platform]["name"]
        super().__init__(title=f"Submit {pn} Post")
        self.uid = uid
        self.platform = platform
        self.url = discord.ui.TextInput(label="Post / Video URL", placeholder="https://...", required=True)
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url.value.strip()
        pi = PLATFORM_INFO[self.platform]

        if not re.search(pi["url_pattern"], url, re.IGNORECASE):
            await interaction.response.send_message(f"❌ Not a valid **{pi['name']}** URL!", ephemeral=True)
            return

        pool = await get_db()
        async with pool.acquire() as c:
            ex = await c.fetchrow("SELECT id FROM clips WHERE url=$1", url)
            if ex:
                await interaction.response.send_message("❌ This URL was already submitted!", ephemeral=True)
                return
            await c.execute(
                "INSERT INTO clips(user_id,platform,url,views,earnings,status) VALUES($1,$2,$3,0,0,'tracking')",
                str(self.uid), self.platform, url
            )

        embed = discord.Embed(
            title="✅ Post Submitted!",
            description=(
                f"{pi['emoji']} **Platform:** {pi['name']}\n"
                f"🔗 **URL:** {url}\n\n"
                f"📊 Views will be tracked automatically.\n"
                f"⏳ Staff will review within **48 hours**.\n\n"
                f"⚠️ Submit right after publishing to ensure all views count!"
            ),
            color=GREEN
        )
        footer(embed)
        await interaction.response.edit_message(embed=embed, view=None)


# ═══════════════ SETUP ═══════════════

class SetupStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🚀 Start Setup", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            embed = discord.Embed(title="🌍 Step 1/2 — Country", description="Select your country.", color=GREEN)
            footer(embed)
            await interaction.response.edit_message(embed=embed, view=SetupCountryView(interaction.user.id))
        except Exception as e:
            print(f"Setup error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

class SetupCountryView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.add_item(CountrySelect(uid))

class CountrySelect(discord.ui.Select):
    def __init__(self, uid):
        self.uid = uid
        super().__init__(placeholder="▼ Select country...", options=[discord.SelectOption(label=c, value=c) for c in COUNTRY_LIST], row=1)

    async def callback(self, interaction: discord.Interaction):
        pool = await get_db()
        async with pool.acquire() as c:
            await c.execute("UPDATE users SET country=$1 WHERE user_id=$2", self.values[0], str(self.uid))
        embed = discord.Embed(title="💵 Step 2/2 — Payment", description=f"✅ Country: **{self.values[0]}**\n\nSelect payment method:", color=ORANGE)
        footer(embed)
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
        pool = await get_db()
        async with pool.acquire() as c:
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
        footer(embed)
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
    footer(embed)
    return embed

class HomeView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid

    @discord.ui.button(label="⚡ Setup", style=discord.ButtonStyle.success)
    async def setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            u = await get_user(str(interaction.user.id))
            if u and u["setup_complete"]:
                await interaction.response.send_message("✅ Already set up!", ephemeral=True)
                return
            embed = discord.Embed(title="⚡ Account Setup", description="🌍 Step 1 — Country\n💵 Step 2 — Payment\n\n*Link socials in #connect-socials!*", color=CYAN)
            footer(embed)
            await interaction.response.edit_message(embed=embed, view=SetupStartView())
        except Exception as e:
            print(f"Setup error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="👤 Profile", style=discord.ButtonStyle.primary)
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = await build_full_profile(interaction.user)
            await interaction.response.edit_message(embed=embed, view=ProfileView(interaction.user.id))
        except Exception as e:
            print(f"Profile error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="💰 Earnings", style=discord.ButtonStyle.success)
    async def earnings(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = await build_earnings(interaction.user)
            await interaction.response.edit_message(embed=embed, view=EarningsView(interaction.user.id))
        except Exception as e:
            print(f"Earnings error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="🏆 Leaderboard", style=discord.ButtonStyle.secondary, row=2)
    async def lb(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = await build_lb()
            await interaction.response.edit_message(embed=embed, view=LBView(interaction.user.id))
        except Exception as e:
            print(f"LB error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

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

    tier = "⚪ Unranked"
    if tv >= 100000: tier = "💎 Diamond"
    elif tv >= 50000: tier = "🥇 Gold"
    elif tv >= 10000: tier = "🥈 Silver"
    elif tv >= 1000: tier = "🥉 Bronze"

    embed = discord.Embed(title=f"👤 {user.display_name}", color=CYAN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="Status", value="✅ Verified" if u and u["setup_complete"] else "⚠️ Incomplete", inline=True)
    embed.add_field(name="🎖️ Tier", value=tier, inline=True)
    embed.add_field(name="📹 Posts", value=str(len(clips)), inline=True)
    embed.add_field(name="👁 Views", value=f"{tv:,}", inline=True)
    embed.add_field(name="💵 Earnings", value=f"${tv*rate:.2f}", inline=True)
    if u and u["country"]: embed.add_field(name="🌍", value=u["country"], inline=True)
    if accs:
        t = "\n".join(f"{PLATFORM_INFO.get(a['platform'],{}).get('emoji','🔗')} **{a['platform'].title()}**: `@{a['platform_username']}` {'✅' if a['verified'] else '⏳'}" for a in accs)
        embed.add_field(name="🔗 Socials", value=t, inline=False)
    footer(embed)
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
        embed = discord.Embed(title="✏️ Edit Account", description="What would you like to change?", color=ORANGE)
        footer(embed)
        await i.response.edit_message(embed=embed, view=EditView(i.user.id))

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
        pool = await get_db()
        async with pool.acquire() as c:
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
        pool = await get_db()
        async with pool.acquire() as c:
            await c.execute("UPDATE users SET payment_method=$1,payment_details=$2 WHERE user_id=$3", self.method, self.det.value.strip(), str(self.uid))
        await i.response.send_message(f"✅ Payment → **{self.method}**", ephemeral=True)

# ═══════════════ EARNINGS ═══════════════

async def build_earnings(user):
    clips = await get_clips(str(user.id))
    rate = await get_rate()
    tv = sum(c["views"] for c in clips)
    te = tv * rate
    pe = sum(c["views"] for c in clips if c["status"] in ("pending","tracking","under_review")) * rate
    pa = sum(c["views"] for c in clips if c["status"] == "paid") * rate
    embed = discord.Embed(title="💰 Earnings", color=GREEN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="💵 Total", value=f"**${te:.2f}**", inline=True)
    embed.add_field(name="⏳ Pending", value=f"${pe:.2f}", inline=True)
    embed.add_field(name="✅ Paid", value=f"${pa:.2f}", inline=True)
    embed.add_field(name="👁 Views", value=f"{tv:,}", inline=True)
    embed.add_field(name="📹 Posts", value=str(len(clips)), inline=True)
    embed.add_field(name="💲 Rate", value=f"${rate}/view", inline=True)
    if clips:
        r = ""
        for cl in clips[:5]:
            e = PLATFORM_INFO.get(cl["platform"],{}).get("emoji","🔗")
            s = "✅" if cl["status"]=="paid" else "⏳"
            r += f"{s} {e} {cl['views']:,} views — ${cl['views']*rate:.2f}\n"
        embed.add_field(name="📋 Recent", value=r, inline=False)
    footer(embed)
    return embed

class EarningsView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)

    @discord.ui.button(label="🏠 Home", style=discord.ButtonStyle.secondary)
    async def home(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=build_home(i.user), view=HomeView(i.user.id))

    @discord.ui.button(label="🏆 Leaderboard", style=discord.ButtonStyle.success)
    async def lb(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=await build_lb(), view=LBView(i.user.id))

# ═══════════════ LEADERBOARD ═══════════════

async def build_lb():
    data = await get_leaderboard()
    embed = discord.Embed(title="🏆 Leaderboard", color=GOLD)
    if not data or all(d[2] == 0 for d in data):
        embed.description = "No submissions yet! Be the first."
    else:
        m = ["🥇","🥈","🥉"]
        t = ""
        for idx,(name,earn,views,clips) in enumerate(data):
            if views == 0: continue
            r = m[idx] if idx < 3 else f"**{idx+1}.**"
            t += f"{r} **{name}** — {views:,} views (${earn:.2f})\n"
        embed.description = t or "No submissions yet!"
    footer(embed)
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

# ═══════════════ TIER VERIFICATION ═══════════════

class TierVerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎖️ Verify My Tier", style=discord.ButtonStyle.success, custom_id="p_tier")
    async def verify_tier(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            accs = await get_verified_accounts(str(interaction.user.id))
            if not accs:
                await interaction.response.send_message("❌ Verify a social account in #connect-socials first!", ephemeral=True)
                return
            desc = "**Your verified accounts:**\n\n"
            for a in accs:
                e = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
                desc += f"{e} **{a['platform'].title()}**: `@{a['platform_username']}` ✅\n"
            desc += "\n**Select a platform** to submit for tier review."
            embed = discord.Embed(title="🎖️ Tier Verification", description=desc, color=ORANGE)
            embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            footer(embed)
            await interaction.response.send_message(embed=embed, view=TierPlatformView(interaction.user.id, accs), ephemeral=True)
        except Exception as e:
            print(f"Tier error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="📋 My Tier Status", style=discord.ButtonStyle.primary, custom_id="p_tier_status")
    async def tier_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            tv = await get_total_views(str(interaction.user.id))
            u = await get_user(str(interaction.user.id))
            accs = await get_verified_accounts(str(interaction.user.id))
            tier = "⚪ Unranked"
            if tv >= 100000: tier = "💎 Diamond"
            elif tv >= 50000: tier = "🥇 Gold"
            elif tv >= 10000: tier = "🥈 Silver"
            elif tv >= 1000: tier = "🥉 Bronze"

            desc = f"**Current Tier:** {tier}\n**Total Views:** {tv:,}\n**Country:** {u['country'] if u else '—'}\n**Accounts:** {len(accs)}\n\n"
            if tv < 1000: desc += "📈 Next: 🥉 Bronze at 1,000 views"
            elif tv < 10000: desc += f"📈 Next: 🥈 Silver at 10K ({10000-tv:,} to go)"
            elif tv < 50000: desc += f"📈 Next: 🥇 Gold at 50K ({50000-tv:,} to go)"
            elif tv < 100000: desc += f"📈 Next: 💎 Diamond at 100K ({100000-tv:,} to go)"
            else: desc += "👑 Highest tier reached!"

            embed = discord.Embed(title=f"🎖️ {interaction.user.display_name}'s Tier", description=desc, color=ORANGE)
            embed.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            footer(embed)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Tier status error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

class TierPlatformView(discord.ui.View):
    def __init__(self, uid, accs):
        super().__init__(timeout=120)
        self.add_item(TierPlatformSelect(uid, accs))

class TierPlatformSelect(discord.ui.Select):
    def __init__(self, uid, accs):
        self.uid = uid
        opts = [discord.SelectOption(label=f"{a['platform'].title()} — @{a['platform_username']}", value=a["platform"], emoji=PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")) for a in accs]
        super().__init__(placeholder="▼ Select platform...", options=opts)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TierSubmitModal(self.uid, self.values[0]))

class TierSubmitModal(discord.ui.Modal):
    def __init__(self, uid, platform):
        super().__init__(title=f"Submit {PLATFORM_INFO[platform]['name']} for Review")
        self.uid = uid
        self.platform = platform
        self.url = discord.ui.TextInput(label="Video / Post URL", placeholder="https://...", required=True)
        self.add_item(self.url)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url.value.strip()
        pi = PLATFORM_INFO[self.platform]
        if not re.search(pi["url_pattern"], url, re.IGNORECASE):
            await interaction.response.send_message(f"❌ Not a valid **{pi['name']}** URL!", ephemeral=True)
            return
        pool = await get_db()
        async with pool.acquire() as c:
            ex = await c.fetchrow("SELECT id FROM clips WHERE url=$1", url)
            if ex:
                await interaction.response.send_message("❌ Already submitted!", ephemeral=True)
                return
            await c.execute("INSERT INTO clips(user_id,platform,url,views,earnings,status) VALUES($1,$2,$3,0,0,'under_review')", str(self.uid), self.platform, url)

        embed = discord.Embed(title="📩 Submitted for Review!", description=f"{pi['emoji']} **{pi['name']}**\n🔗 {url}\n\n━━━━━━━━━━━━━━━━━━━━━\n\n⏳ **Under review by staff.**\nYou'll be updated within **48 hours**.\n\nViews will be tracked automatically once approved.", color=ORANGE)
        footer(embed)
        await interaction.response.edit_message(embed=embed, view=None)

# ═══════════════ HELP ═══════════════

def build_help():
    embed = discord.Embed(title="📚 Admin Commands", color=LIGHT_CYAN)
    embed.add_field(name="📌 Post Panels", value=(
        "`/postpanel` — #connect-socials\n"
        "`/postprofile` — #your-profile\n"
        "`/postcampaign` — Campaign channel\n"
        "`/posttier` — #tier-verification\n"
        "`/postticket` — #support"
    ), inline=False)
    embed.add_field(name="🎯 Campaign", value=(
        "`/campaignlb` `/endcampaign` `/setlimit`"
    ), inline=False)
    embed.add_field(name="💸 Payouts", value=(
        "`/sendpayout` `/pendingpayouts` `/payouthistory`"
    ), inline=False)
    embed.add_field(name="🚫 Moderation", value=(
        "`/ban` `/unban` `/banlist`"
    ), inline=False)
    embed.add_field(name="🔧 Tools", value=(
        "`/embed` `/colors` `/announce` `/dmuser`\n"
        "`/setrate` `/allusers` `/userinfo` `/approveclip`"
    ), inline=False)
    footer(embed)
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
        try:
            pool = await get_db()
            async with pool.acquire() as c:
                camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(message.channel.id))
            if camp:
                urls = re.findall(r'https?://\S+', message.content)
                if urls:
                    uid = str(message.author.id)

                    # Check ban
                    async with pool.acquire() as c:
                        ban = await c.fetchrow("SELECT * FROM bans WHERE user_id=$1", uid)
                    if ban:
                        await message.reply("🚫 You are banned from campaigns.", delete_after=10)
                        return

                    # Check deadline
                    if camp["deadline"] and datetime.utcnow() > camp["deadline"]:
                        await message.reply("⏰ Campaign expired!", delete_after=10)
                        return

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

                    # Check daily limit
                    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                    async with pool.acquire() as c:
                        today_count = await c.fetchrow(
                            "SELECT COUNT(*) as cnt FROM clips WHERE user_id=$1 AND campaign_id=$2 AND submitted_at >= $3",
                            uid, str(camp["id"]), today_start
                        )
                    if today_count and int(today_count["cnt"]) >= camp["daily_limit"]:
                        await message.reply(f"📛 Daily limit reached! Max {camp['daily_limit']} posts/day.", delete_after=10)
                        return

                    async with pool.acquire() as c:
                        ex = await c.fetchrow("SELECT id FROM clips WHERE url=$1", url)
                        if ex:
                            await message.reply("⚠️ Already submitted!", delete_after=10)
                            return
                        await c.execute("INSERT INTO clips(user_id,platform,url,views,earnings,status,campaign_id) VALUES($1,$2,$3,0,0,'tracking',$4)", uid, camp["platform"] or "unknown", url, str(camp["id"]))
                    await message.add_reaction("✅")
                    await message.reply(f"✅ Tracked for **{camp['name']}**!", delete_after=15)
        except Exception as e:
            print(f"Message tracking error: {e}")
    await bot.process_commands(message)

# ═══════════════ PROFILE PANEL (for #your-profile) ═══════════════

class ProfilePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="👤 My Profile", style=discord.ButtonStyle.primary, custom_id="p_my_profile")
    async def my_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            embed = await build_full_profile(interaction.user)
            await interaction.response.send_message(embed=embed, view=ProfileActionView(interaction.user.id), ephemeral=True)
        except Exception as e:
            print(f"Profile error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="💰 Earnings", style=discord.ButtonStyle.success, custom_id="p_my_earnings")
    async def my_earnings(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            embed = await build_earnings(interaction.user)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Earnings error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="🏆 Leaderboard", style=discord.ButtonStyle.secondary, custom_id="p_my_lb")
    async def my_lb(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = await build_lb()
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"LB error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="⚡ Setup Account", style=discord.ButtonStyle.success, custom_id="p_my_setup", row=2)
    async def my_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            u = await get_user(str(interaction.user.id))
            if u and u["setup_complete"]:
                await interaction.response.send_message("✅ Your account is already set up! Click **👤 My Profile** to view.", ephemeral=True)
                return
            embed = discord.Embed(title="⚡ Account Setup", description="Complete 2 steps to start earning!\n\n🌍 **Step 1** — Select Country\n💵 **Step 2** — Payment Method\n\n*Link socials in #connect-socials!*", color=CYAN)
            footer(embed)
            await interaction.response.send_message(embed=embed, view=SetupStartView(), ephemeral=True)
        except Exception as e:
            print(f"Setup error: {e}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)


class ProfileActionView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="💰 Earnings", style=discord.ButtonStyle.success)
    async def earn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_earnings(interaction.user)
        await interaction.response.edit_message(embed=embed, view=EarningsBackView(interaction.user.id))

    @discord.ui.button(label="✏️ Edit Account", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="✏️ Edit Account", description="What would you like to change?", color=ORANGE)
        footer(embed)
        await interaction.response.edit_message(embed=embed, view=EditView(interaction.user.id))

    @discord.ui.button(label="🏆 Leaderboard", style=discord.ButtonStyle.secondary)
    async def lb(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_lb()
        await interaction.response.edit_message(embed=embed, view=LBBackView(interaction.user.id))


class EarningsBackView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="👤 Profile", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_full_profile(interaction.user)
        await interaction.response.edit_message(embed=embed, view=ProfileActionView(interaction.user.id))


class LBBackView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="👤 Profile", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_full_profile(interaction.user)
        await interaction.response.edit_message(embed=embed, view=ProfileActionView(interaction.user.id))


# ═══════════════ SLASH COMMANDS (on_ready) ═══════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(ConnectSocialsView())
    bot.add_view(TierVerifyView())
    bot.add_view(CampaignView("default"))
    bot.add_view(TicketView())
    bot.add_view(TicketControlView())
    bot.add_view(ProfilePanelView())
    try:
        s = await bot.tree.sync()
        print(f"✅ Synced {len(s)} commands")
    except Exception as e:
        print(f"❌ Sync: {e}")
    print(f"✅ {bot.user} is live!")

# ═══════════════ ADMIN COMMANDS ═══════════════

@bot.tree.command(name="postpanel", description="[Admin] Post connect-socials panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_panel(i: discord.Interaction):
    embed = discord.Embed(title="🔗 Manage Your Social Accounts", description="Use the buttons below to manage your account.\n\n**🔗 Link Account**\nConnect your social media page.\n\n**👥 View Accounts**\nView your connected accounts, views & earnings.", color=GREEN)
    footer(embed)
    await i.channel.send(embed=embed, view=ConnectSocialsView())
    await i.response.send_message("✅ Panel posted!", ephemeral=True)

@bot.tree.command(name="postprofile", description="[Admin] Post profile panel for #your-profile")
@app_commands.checks.has_permissions(administrator=True)
async def s_postprofile(i: discord.Interaction):
    embed = discord.Embed(
        title="👤 Your Account",
        description=(
            "Manage your Clip Forge account here!\n\n"
            "**👤 My Profile**\n"
            "View your stats, connected accounts, tier & earnings.\n\n"
            "**💰 Earnings**\n"
            "See total, pending & paid earnings breakdown.\n\n"
            "**🏆 Leaderboard**\n"
            "See where you rank among all clippers.\n\n"
            "**⚡ Setup Account**\n"
            "First time? Set up your country & payment method."
        ),
        color=CYAN
    )
    footer(embed)
    await i.channel.send(embed=embed, view=ProfilePanelView())
    await i.response.send_message("✅ Profile panel posted!", ephemeral=True)

@bot.tree.command(name="postcampaign", description="[Admin] Post campaign panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_postcampaign(i: discord.Interaction, name: str, platform: str = "", daily_limit: int = 50, deadline_hours: int = 0):
    if platform and platform.lower() not in PLATFORM_INFO:
        await i.response.send_message(f"❌ Use: {', '.join(PLATFORM_INFO.keys())}", ephemeral=True)
        return
    dl = None
    if deadline_hours > 0:
        dl = datetime.utcnow() + timedelta(hours=deadline_hours)
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO campaigns(name,channel_id,platform,created_by,daily_limit,deadline) VALUES($1,$2,$3,$4,$5,$6)", name, str(i.channel.id), platform.lower() if platform else "", str(i.user.id), daily_limit, dl)

    pt = f" ({PLATFORM_INFO[platform.lower()]['name']} only)" if platform else ""
    dl_text = f"\n⏰ **Deadline:** <t:{int(dl.timestamp())}:R>" if dl else ""
    embed = discord.Embed(
        title=f"🚀 {name} is now live!",
        description=(
            f"Submissions are open{pt}. Start posting your content!\n"
            f"📛 **Daily limit:** {daily_limit} posts per user{dl_text}\n\n"
            f"**👉 Submit your posts**\n"
            f"Click **Submit post** below to start clipping!\n\n"
            f"⚠️ Submit right after publishing to ensure all views count!\n\n"
            f"*By clicking Submit post, you accept the campaign terms.*"
        ),
        color=RED
    )
    footer(embed)
    await i.channel.send(embed=embed, view=CampaignView(name))
    await i.response.send_message("✅ Campaign posted!", ephemeral=True)

# ═══════════════ CAMPAIGN LEADERBOARD ═══════════════

@bot.tree.command(name="campaignlb", description="[Admin] Show campaign leaderboard")
@app_commands.checks.has_permissions(administrator=True)
async def s_campaignlb(i: discord.Interaction):
    pool = await get_db()
    async with pool.acquire() as c:
        camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(i.channel.id))
    if not camp:
        await i.response.send_message("❌ No active campaign in this channel!", ephemeral=True)
        return

    rate = await get_rate()
    async with pool.acquire() as c:
        rows = await c.fetch("""
            SELECT u.username, COALESCE(SUM(c.views),0) as tv, COUNT(c.id) as tc
            FROM clips c JOIN users u ON c.user_id = u.user_id
            WHERE c.campaign_id = $1
            GROUP BY u.username ORDER BY tv DESC LIMIT 15
        """, str(camp["id"]))

    if not rows or all(r["tv"] == 0 for r in rows):
        await i.response.send_message("📊 No submissions yet for this campaign!", ephemeral=True)
        return

    medals = ["🥇","🥈","🥉"]
    t = ""
    for idx, r in enumerate(rows):
        rank = medals[idx] if idx < 3 else f"**{idx+1}.**"
        t += f"{rank} **{r['username']}** — {int(r['tv']):,} views ({int(r['tc'])} posts)\n"

    embed = discord.Embed(title=f"🏆 {camp['name']} — Leaderboard", description=t, color=GOLD)
    footer(embed)
    await i.response.send_message(embed=embed)

# ═══════════════ BAN SYSTEM ═══════════════

@bot.tree.command(name="ban", description="[Admin] Ban user from campaigns")
@app_commands.checks.has_permissions(administrator=True)
async def s_ban(i: discord.Interaction, user: discord.User, reason: str = "No reason given"):
    pool = await get_db()
    async with pool.acquire() as c:
        try:
            await c.execute("INSERT INTO bans(user_id,reason,banned_by) VALUES($1,$2,$3)", str(user.id), reason, str(i.user.id))
        except:
            await i.response.send_message(f"⚠️ {user.mention} is already banned!", ephemeral=True)
            return
    embed = discord.Embed(title="🚫 User Banned", description=f"**User:** {user.mention}\n**Reason:** {reason}\n**By:** {i.user.mention}", color=RED)
    footer(embed)
    await i.response.send_message(embed=embed)

    # DM the banned user
    try:
        dm_embed = discord.Embed(title="🚫 You have been banned", description=f"You've been banned from Clip Forge campaigns.\n**Reason:** {reason}\n\nContact support if you believe this is a mistake.", color=RED)
        footer(dm_embed)
        await user.send(embed=dm_embed)
    except:
        pass

@bot.tree.command(name="unban", description="[Admin] Unban user")
@app_commands.checks.has_permissions(administrator=True)
async def s_unban(i: discord.Interaction, user: discord.User):
    pool = await get_db()
    async with pool.acquire() as c:
        result = await c.execute("DELETE FROM bans WHERE user_id=$1", str(user.id))
    await i.response.send_message(embed=discord.Embed(title="✅ User Unbanned", description=f"{user.mention} can now submit again.", color=GREEN))

@bot.tree.command(name="banlist", description="[Admin] Show banned users")
@app_commands.checks.has_permissions(administrator=True)
async def s_banlist(i: discord.Interaction):
    pool = await get_db()
    async with pool.acquire() as c:
        bans = await c.fetch("SELECT * FROM bans ORDER BY created_at DESC")
    if not bans:
        await i.response.send_message("✅ No banned users!", ephemeral=True)
        return
    t = ""
    for b in bans:
        t += f"• <@{b['user_id']}> — {b['reason']}\n"
    embed = discord.Embed(title="🚫 Banned Users", description=t, color=RED)
    footer(embed)
    await i.response.send_message(embed=embed)

# ═══════════════ PAYOUT SYSTEM ═══════════════

@bot.tree.command(name="sendpayout", description="[Admin] Send payout to user")
@app_commands.checks.has_permissions(administrator=True)
async def s_sendpayout(i: discord.Interaction, user: discord.User, amount: float, note: str = ""):
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO payouts(user_id,amount,status,admin_id,note) VALUES($1,$2,'paid',$3,$4)", str(user.id), amount, str(i.user.id), note)
        # Mark user's pending clips as paid
        await c.execute("UPDATE clips SET status='paid' WHERE user_id=$1 AND status IN ('pending','tracking','under_review')", str(user.id))

    embed = discord.Embed(title="💸 Payout Sent!", description=f"**User:** {user.mention}\n**Amount:** ${amount:.2f}\n**Note:** {note or '—'}\n**By:** {i.user.mention}\n\nAll pending clips marked as paid.", color=GREEN)
    footer(embed)
    await i.response.send_message(embed=embed)

    # DM the user
    try:
        dm_embed = discord.Embed(title="💸 You've been paid!", description=f"**Amount:** ${amount:.2f}\n**Note:** {note or '—'}\n\nCheck your payment method for the funds. Keep clipping! 🎉", color=GREEN)
        footer(dm_embed)
        await user.send(embed=dm_embed)
    except:
        pass

@bot.tree.command(name="payouthistory", description="[Admin] View payout history")
@app_commands.checks.has_permissions(administrator=True)
async def s_payouthistory(i: discord.Interaction, user: discord.User = None):
    pool = await get_db()
    async with pool.acquire() as c:
        if user:
            payouts = await c.fetch("SELECT * FROM payouts WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20", str(user.id))
        else:
            payouts = await c.fetch("SELECT * FROM payouts ORDER BY created_at DESC LIMIT 20")
    if not payouts:
        await i.response.send_message("📋 No payouts yet!", ephemeral=True)
        return
    t = ""
    total = 0
    for p in payouts:
        t += f"• <@{p['user_id']}> — **${p['amount']:.2f}** ({p['status']}) {p['note'] or ''}\n"
        total += p["amount"]
    embed = discord.Embed(title="💸 Payout History", description=t, color=GREEN)
    embed.add_field(name="💰 Total Paid", value=f"**${total:.2f}**", inline=False)
    footer(embed)
    await i.response.send_message(embed=embed)

@bot.tree.command(name="pendingpayouts", description="[Admin] Show users with pending earnings")
@app_commands.checks.has_permissions(administrator=True)
async def s_pendingpayouts(i: discord.Interaction):
    rate = await get_rate()
    pool = await get_db()
    async with pool.acquire() as c:
        rows = await c.fetch("""
            SELECT u.user_id, u.username, u.payment_method,
                   COALESCE(SUM(c.views),0) as tv, COUNT(c.id) as tc
            FROM users u JOIN clips c ON u.user_id = c.user_id
            WHERE c.status IN ('pending','tracking','under_review')
            GROUP BY u.user_id, u.username, u.payment_method
            HAVING SUM(c.views) > 0
            ORDER BY tv DESC
        """)
    if not rows:
        await i.response.send_message("✅ No pending payouts!", ephemeral=True)
        return
    t = ""
    total = 0
    for r in rows:
        amt = int(r["tv"]) * rate
        total += amt
        t += f"• **{r['username']}** — ${amt:.2f} ({int(r['tv']):,} views) [{r['payment_method'] or '—'}]\n"
    embed = discord.Embed(title="⏳ Pending Payouts", description=t, color=ORANGE)
    embed.add_field(name="💰 Total Pending", value=f"**${total:.2f}**", inline=False)
    footer(embed)
    await i.response.send_message(embed=embed)

# ═══════════════ TICKET SYSTEM ═══════════════

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Create Ticket", style=discord.ButtonStyle.success, custom_id="p_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal())

class TicketModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Create Support Ticket")
        self.subject = discord.ui.TextInput(label="Subject", placeholder="Brief description of your issue", required=True, max_length=100)
        self.details = discord.ui.TextInput(label="Details", placeholder="Explain your issue in detail...", style=discord.TextStyle.paragraph, required=True, max_length=2000)
        self.add_item(self.subject)
        self.add_item(self.details)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        uid = str(interaction.user.id)

        # Check if user already has an open ticket
        pool = await get_db()
        async with pool.acquire() as c:
            existing = await c.fetchrow("SELECT * FROM tickets WHERE user_id=$1 AND status='open'", uid)
        if existing:
            await interaction.response.send_message(f"❌ You already have an open ticket! <#{existing['channel_id']}>", ephemeral=True)
            return

        # Create ticket channel
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        # Find or create ticket category
        category = discord.utils.get(guild.categories, name="TICKETS")
        if not category:
            category = await guild.create_category("TICKETS")

        channel = await guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )

        # Save to database
        async with pool.acquire() as c:
            await c.execute("INSERT INTO tickets(user_id,channel_id,subject) VALUES($1,$2,$3)", uid, str(channel.id), self.subject.value)

        # Send ticket embed in channel
        embed = discord.Embed(
            title=f"🎫 Ticket — {self.subject.value}",
            description=(
                f"**Created by:** {interaction.user.mention}\n"
                f"**Subject:** {self.subject.value}\n\n"
                f"**Details:**\n{self.details.value}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"A staff member will respond shortly.\n"
                f"Click **🔒 Close Ticket** when resolved."
            ),
            color=CYAN
        )
        footer(embed)
        await channel.send(embed=embed, view=TicketControlView())
        await channel.send(f"{interaction.user.mention} your ticket has been created!")

        await interaction.response.send_message(f"✅ Ticket created! Go to {channel.mention}", ephemeral=True)

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="p_close_ticket")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        pool = await get_db()
        async with pool.acquire() as c:
            await c.execute("UPDATE tickets SET status='closed' WHERE channel_id=$1", str(interaction.channel.id))

        embed = discord.Embed(title="🔒 Ticket Closed", description=f"Closed by {interaction.user.mention}\nThis channel will be deleted in 10 seconds.", color=RED)
        footer(embed)
        await interaction.response.send_message(embed=embed)

        await asyncio.sleep(10)
        try:
            await interaction.channel.delete()
        except:
            pass

@bot.tree.command(name="postticket", description="[Admin] Post ticket creation panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_postticket(i: discord.Interaction):
    embed = discord.Embed(
        title="🎫 Support Tickets",
        description=(
            "Need help? Create a support ticket!\n\n"
            "**🎫 Create Ticket**\n"
            "A private channel will be created for you and staff.\n"
            "Describe your issue and we'll help ASAP.\n\n"
            "**Common issues:**\n"
            "• Payment not received\n"
            "• Account verification problems\n"
            "• Campaign questions\n"
            "• Bug reports"
        ),
        color=CYAN
    )
    footer(embed)
    await i.channel.send(embed=embed, view=TicketView())
    await i.response.send_message("✅ Ticket panel posted!", ephemeral=True)

# ═══════════════ CAMPAIGN MANAGEMENT ═══════════════

@bot.tree.command(name="endcampaign", description="[Admin] End campaign in this channel")
@app_commands.checks.has_permissions(administrator=True)
async def s_endcampaign(i: discord.Interaction):
    pool = await get_db()
    async with pool.acquire() as c:
        camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(i.channel.id))
        if not camp:
            await i.response.send_message("❌ No active campaign here!", ephemeral=True)
            return
        await c.execute("UPDATE campaigns SET active=FALSE WHERE id=$1", camp["id"])
    embed = discord.Embed(title=f"🛑 {camp['name']} — Campaign Ended", description="Submissions are now **closed**.\nNo more posts will be accepted.", color=RED)
    footer(embed)
    await i.response.send_message(embed=embed)

@bot.tree.command(name="setlimit", description="[Admin] Set daily post limit for campaign")
@app_commands.checks.has_permissions(administrator=True)
async def s_setlimit(i: discord.Interaction, limit: int):
    pool = await get_db()
    async with pool.acquire() as c:
        camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(i.channel.id))
        if not camp:
            await i.response.send_message("❌ No active campaign here!", ephemeral=True)
            return
        await c.execute("UPDATE campaigns SET daily_limit=$1 WHERE id=$2", limit, camp["id"])
    await i.response.send_message(embed=discord.Embed(title="✅ Limit Updated", description=f"Daily limit set to **{limit}** posts per user.", color=GREEN))

@bot.tree.command(name="posttier", description="[Admin] Post tier verification panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_posttier(i: discord.Interaction):
    embed = discord.Embed(
        title="🎖️ Tier Verification",
        description=(
            "Verify your tier to unlock rewards!\n\n"
            "**🎖️ Verify My Tier**\nSubmit a video for staff review.\n\n"
            "**📋 My Tier Status**\nCheck your current tier & progress.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🥉 **Bronze** — 1,000+ views\n"
            "🥈 **Silver** — 10,000+ views\n"
            "🥇 **Gold** — 50,000+ views\n"
            "💎 **Diamond** — 100,000+ views"
        ),
        color=ORANGE
    )
    footer(embed)
    await i.channel.send(embed=embed, view=TierVerifyView())
    await i.response.send_message("✅ Tier panel posted!", ephemeral=True)

@bot.tree.command(name="announce", description="[Admin] DM all users with announcement")
@app_commands.checks.has_permissions(administrator=True)
async def s_announce(i: discord.Interaction, title: str, message: str):
    await i.response.defer(ephemeral=True)
    pool = await get_db()
    async with pool.acquire() as c:
        users = await c.fetch("SELECT user_id FROM users")

    sent = 0
    failed = 0
    for row in users:
        try:
            user = await bot.fetch_user(int(row["user_id"]))
            embed = discord.Embed(title=f"📢 {title}", description=message, color=CYAN)
            embed.set_author(name="Clip Forge", icon_url=bot.user.display_avatar.url if bot.user.display_avatar else None)
            footer(embed)
            await user.send(embed=embed)
            sent += 1
        except:
            failed += 1

    await i.followup.send(f"✅ Announcement sent!\n📨 **Sent:** {sent}\n❌ **Failed:** {failed}", ephemeral=True)

@bot.tree.command(name="dmuser", description="[Admin] DM a specific user")
@app_commands.checks.has_permissions(administrator=True)
async def s_dmuser(i: discord.Interaction, user: discord.User, message: str):
    try:
        embed = discord.Embed(title="📬 Message from Clip Forge", description=message, color=CYAN)
        embed.set_author(name="Clip Forge", icon_url=bot.user.display_avatar.url if bot.user.display_avatar else None)
        footer(embed)
        await user.send(embed=embed)
        await i.response.send_message(f"✅ DM sent to {user.mention}!", ephemeral=True)
    except:
        await i.response.send_message(f"❌ Could not DM {user.mention}. They may have DMs closed.", ephemeral=True)

@bot.tree.command(name="setrate", description="[Admin] Set rate")
@app_commands.checks.has_permissions(administrator=True)
async def s_rate(i: discord.Interaction, rate: float):
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("UPDATE settings SET value=$1 WHERE key='payment_rate'", str(rate))
    await i.response.send_message(embed=discord.Embed(title="✅ Rate Updated", description=f"${rate}/view", color=GREEN))

@bot.tree.command(name="allusers", description="[Admin] All users")
@app_commands.checks.has_permissions(administrator=True)
async def s_all(i: discord.Interaction):
    d = await get_leaderboard()
    if not d:
        await i.response.send_message("❌ None!", ephemeral=True)
        return
    t = "\n".join(f"• **{n}** — ${e:.2f} ({v:,} views, {cl} posts)" for n,e,v,cl in d)
    await i.response.send_message(embed=discord.Embed(title="👥 Users", description=t, color=DARK_BLUE))

@bot.tree.command(name="userinfo", description="[Admin] User info")
@app_commands.checks.has_permissions(administrator=True)
async def s_uinfo(i: discord.Interaction, user: discord.User):
    uid = str(user.id)
    u = await get_user(uid)
    if not u:
        await i.response.send_message("❌ Not found!", ephemeral=True)
        return
    accs = await get_accounts(uid)
    clips = await get_clips(uid)
    rate = await get_rate()
    tv = sum(c["views"] for c in clips)
    embed = discord.Embed(title=f"👤 {user.name}", color=LIGHT_CYAN)
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="Status", value="✅" if u["setup_complete"] else "⚠️", inline=True)
    embed.add_field(name="Posts", value=str(len(clips)), inline=True)
    embed.add_field(name="Views", value=f"{tv:,}", inline=True)
    embed.add_field(name="Earnings", value=f"${tv*rate:.2f}", inline=True)
    embed.add_field(name="Country", value=u["country"] or "—", inline=True)
    embed.add_field(name="Payment", value=u["payment_method"] or "—", inline=True)
    if u["payment_details"]:
        embed.add_field(name="Details", value=f"`{u['payment_details']}`", inline=False)
    if accs:
        embed.add_field(name="Socials", value="\n".join(f"{PLATFORM_INFO.get(a['platform'],{}).get('emoji','🔗')} `@{a['platform_username']}` {'✅' if a['verified'] else '⏳'}" for a in accs), inline=False)
    await i.response.send_message(embed=embed)

@bot.tree.command(name="approveclip", description="[Admin] Approve clip")
@app_commands.checks.has_permissions(administrator=True)
async def s_approve(i: discord.Interaction, clip_id: int):
    pool = await get_db()
    async with pool.acquire() as c:
        cl = await c.fetchrow("SELECT * FROM clips WHERE id=$1", clip_id)
        if not cl:
            await i.response.send_message("❌ Not found!", ephemeral=True)
            return
        await c.execute("UPDATE clips SET status='paid' WHERE id=$1", clip_id)
    await i.response.send_message(embed=discord.Embed(title=f"✅ Clip #{clip_id} Approved", color=GREEN))

# ═══════════════ EMBED CREATOR ═══════════════

@bot.tree.command(name="embed", description="[Admin] Create a custom embed")
@app_commands.checks.has_permissions(administrator=True)
async def s_embed(i: discord.Interaction):
    await i.response.send_modal(EmbedCreatorModal())

class EmbedCreatorModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Create Custom Embed")
        self.embed_title = discord.ui.TextInput(
            label="Title",
            placeholder="Your embed title...",
            required=False,
            max_length=256
        )
        self.embed_desc = discord.ui.TextInput(
            label="Description (supports Discord markdown)",
            placeholder="**Bold** *italic* `code` [link](url)\n\nUse \\n for new lines",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000
        )
        self.embed_color = discord.ui.TextInput(
            label="Color (hex code)",
            placeholder="e.g. FF0000 (red), 00FF00 (green), 00FFFF (cyan)",
            required=False,
            max_length=7,
            default="00FFFF"
        )
        self.embed_image = discord.ui.TextInput(
            label="Image URL (optional)",
            placeholder="https://i.imgur.com/example.png",
            required=False,
            max_length=500
        )
        self.embed_footer_text = discord.ui.TextInput(
            label="Footer text (optional)",
            placeholder="Leave empty for default footer",
            required=False,
            max_length=200
        )
        self.add_item(self.embed_title)
        self.add_item(self.embed_desc)
        self.add_item(self.embed_color)
        self.add_item(self.embed_image)
        self.add_item(self.embed_footer_text)

    async def on_submit(self, interaction: discord.Interaction):
        # Parse color
        color_str = self.embed_color.value.strip().lstrip("#")
        try:
            color = int(color_str, 16) if color_str else CYAN
        except:
            color = CYAN

        # Replace \n with actual newlines
        desc = self.embed_desc.value.replace("\\n", "\n")
        title = self.embed_title.value or None

        embed = discord.Embed(title=title, description=desc, color=color)

        # Image
        img = self.embed_image.value.strip()
        if img and img.startswith("http"):
            embed.set_image(url=img)

        # Footer
        ft = self.embed_footer_text.value.strip()
        if ft:
            embed.set_footer(text=ft)
        else:
            embed.set_footer(text=FOOTER)

        # Show preview first
        await interaction.response.send_message("**Preview:**", embed=embed, view=EmbedPreviewView(embed), ephemeral=True)


class EmbedPreviewView(discord.ui.View):
    def __init__(self, embed):
        super().__init__(timeout=300)
        self.embed = embed

    @discord.ui.button(label="✅ Post Here", style=discord.ButtonStyle.success)
    async def post(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send(embed=self.embed)
        await interaction.response.edit_message(content="✅ Embed posted!", view=None)

    @discord.ui.button(label="✏️ Edit & Retry", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedCreatorModal())

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Cancelled.", view=None)


# Quick color reference command
@bot.tree.command(name="colors", description="[Admin] Show color codes for embeds")
@app_commands.checks.has_permissions(administrator=True)
async def s_colors(i: discord.Interaction):
    embed = discord.Embed(title="🎨 Color Codes for /embed", description=(
        "**Common Colors:**\n"
        "`FF0000` — 🔴 Red\n"
        "`FF4757` — 🔴 Soft Red\n"
        "`FF6B35` — 🟠 Orange\n"
        "`FF8C00` — 🟠 Dark Orange\n"
        "`FFD700` — 🟡 Gold\n"
        "`FFFF00` — 🟡 Yellow\n"
        "`00D26A` — 🟢 Green\n"
        "`00FF00` — 🟢 Lime\n"
        "`00FFFF` — 🔵 Cyan\n"
        "`00D4FF` — 🔵 Light Blue\n"
        "`0099FF` — 🔵 Blue\n"
        "`0000FF` — 🔵 Dark Blue\n"
        "`7B68EE` — 🟣 Purple\n"
        "`9B59B6` — 🟣 Dark Purple\n"
        "`FF69B4` — 🩷 Pink\n"
        "`FFFFFF` — ⚪ White\n"
        "`2B2D31` — ⚫ Discord Dark\n"
        "`000000` — ⚫ Black\n\n"
        "**Usage:** `/embed` → paste color code in the Color field"
    ), color=CYAN)
    await i.response.send_message(embed=embed, ephemeral=True)


# ═══════════════ LEGACY COMMANDS ═══════════════

# ═══════════════ ADMIN HELP ═══════════════

@bot.tree.command(name="help", description="[Admin] Show all admin commands")
@app_commands.checks.has_permissions(administrator=True)
async def s_help(i: discord.Interaction):
    await i.response.send_message(embed=build_help(), ephemeral=True)

# ═══════════════ LEGACY COMMANDS (admin only) ═══════════════

@bot.command(name="help")
@commands.has_permissions(administrator=True)
async def c_help(ctx):
    await ctx.send(embed=build_help())

# ═══════════════ START ═══════════════

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN not found!")
