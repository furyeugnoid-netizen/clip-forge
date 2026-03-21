+import discord
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
#  CLIP FORGE BOT v5.0
# ═══════════════════════════════════════════

MAIN_COLOR = 0x2C3E6B  # Navy Blue — used everywhere
DATABASE_URL = os.getenv("DATABASE_URL")
TOKEN = os.getenv("DISCORD_TOKEN")
FOOTER = "Clip Forge • clip.tech"
CLIPPER_ROLE_NAME = "clipper"

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
TIER_NAMES = {0: "⚪ Unranked", 1: "🥉 Tier 1", 2: "🥈 Tier 2", 3: "🥇 Tier 3"}

def gen_code():
    return "CF-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def ft(embed):
    embed.set_footer(text=FOOTER)
    return embed

def emb(title=None, desc=None):
    e = discord.Embed(title=title, description=desc, color=MAIN_COLOR)
    ft(e)
    return e

# ═══════════════ DATABASE ═══════════════

async def get_db():
    global db_pool
    if db_pool is None or db_pool._closed:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return db_pool

async def init_db():
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY,username TEXT,avatar_url TEXT DEFAULT '',country TEXT DEFAULT '',payment_method TEXT DEFAULT '',payment_details TEXT DEFAULT '',setup_complete BOOLEAN DEFAULT FALSE,tier INTEGER DEFAULT 0,created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS accounts(id SERIAL PRIMARY KEY,user_id TEXT REFERENCES users(user_id),platform TEXT,platform_username TEXT,platform_url TEXT DEFAULT '',verified BOOLEAN DEFAULT FALSE,verification_code TEXT DEFAULT '',linked_at TIMESTAMP DEFAULT NOW(),UNIQUE(user_id,platform),UNIQUE(platform,platform_username))")
        await c.execute("CREATE TABLE IF NOT EXISTS clips(id SERIAL PRIMARY KEY,user_id TEXT REFERENCES users(user_id),platform TEXT,url TEXT UNIQUE,views INTEGER DEFAULT 0,earnings REAL DEFAULT 0,status TEXT DEFAULT 'pending',campaign_id TEXT DEFAULT '',submitted_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS campaigns(id SERIAL PRIMARY KEY,name TEXT,channel_id TEXT,platform TEXT DEFAULT '',created_by TEXT,active BOOLEAN DEFAULT TRUE,deadline TIMESTAMP DEFAULT NULL,daily_limit INTEGER DEFAULT 50,media_only BOOLEAN DEFAULT TRUE,created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)")
        await c.execute("INSERT INTO settings(key,value) VALUES('payment_rate','0.001') ON CONFLICT(key) DO NOTHING")
        await c.execute("CREATE TABLE IF NOT EXISTS tickets(id SERIAL PRIMARY KEY,user_id TEXT,channel_id TEXT,category TEXT DEFAULT '',status TEXT DEFAULT 'open',created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS payouts(id SERIAL PRIMARY KEY,user_id TEXT,amount REAL,status TEXT DEFAULT 'pending',admin_id TEXT DEFAULT '',note TEXT DEFAULT '',created_at TIMESTAMP DEFAULT NOW())")
        await c.execute("CREATE TABLE IF NOT EXISTS bans(id SERIAL PRIMARY KEY,user_id TEXT,reason TEXT DEFAULT '',banned_by TEXT,created_at TIMESTAMP DEFAULT NOW(),UNIQUE(user_id))")
        try:
            await c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tier INTEGER DEFAULT 0")
            await c.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS media_only BOOLEAN DEFAULT TRUE")
            await c.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS deadline TIMESTAMP DEFAULT NULL")
            await c.execute("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS daily_limit INTEGER DEFAULT 50")
            await c.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS category TEXT DEFAULT ''")
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

async def assign_clipper_role(interaction):
    try:
        role = discord.utils.get(interaction.guild.roles, name=CLIPPER_ROLE_NAME)
        if role and role not in interaction.user.roles:
            await interaction.user.add_roles(role)
    except:
        pass

# ═══════════════ ERROR HANDLER ═══════════════

@bot.tree.error
async def on_app_command_error(interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ Admin only!", ephemeral=True)
    else:
        print(f"Error: {error}")
        traceback.print_exc()
        try:
            await interaction.response.send_message("❌ Something went wrong.", ephemeral=True)
        except:
            pass

# ═══════════════ WELCOME DM ═══════════════

@bot.event
async def on_member_join(member):
    try:
        e = emb("👋 Welcome to Clip Forge!", f"Hey **{member.name}**!\n\nWelcome to the community. Here's how to get started:\n\n1️⃣ Go to **#connect-socials** and link your accounts\n2️⃣ Set up your profile in **#your-profile**\n3️⃣ Join active campaigns and start earning!\n\nNeed help? Open a ticket in **#create-ticket**\n\nLet's get clipping! 🎬")
        e.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        await member.send(embed=e)
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
            e = emb("🔗 Link Your Social Account", "**Select a platform** to connect.\n\n📌 **How it works:**\n1️⃣ Choose platform\n2️⃣ Enter username & profile URL\n3️⃣ Get a **verification code**\n4️⃣ Add code to your **bio**\n5️⃣ Click **Verify** ✅")
            await interaction.response.send_message(embed=e, view=ChoosePlatformView(interaction.user.id), ephemeral=True)
        except Exception as ex:
            print(f"Link error: {ex}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="View Accounts", emoji="👥", style=discord.ButtonStyle.primary, custom_id="p_view")
    async def view(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            e = await build_profile_card(interaction.user)
            await interaction.response.send_message(embed=e, view=ViewAccountsView(interaction.user.id), ephemeral=True)
        except Exception as ex:
            print(f"View error: {ex}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

async def build_profile_card(user):
    uid = str(user.id)
    accounts = await get_accounts(uid)
    tv = await get_total_views(uid)
    rate = await get_rate()
    clips = await get_clips(uid)
    u = await get_user(uid)
    tier = TIER_NAMES.get(u["tier"] if u else 0, "⚪ Unranked")
    e = discord.Embed(title="👤 Your Profile", color=MAIN_COLOR)
    e.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    e.add_field(name="🎖️ Tier", value=tier, inline=True)
    e.add_field(name="👁 All-Time Views", value=f"**{tv:,}**", inline=True)
    e.add_field(name="💵 Earnings", value=f"**${tv*rate:.2f}**", inline=True)
    e.add_field(name="📹 Total Posts", value=f"**{len(clips)}**", inline=True)
    if accounts:
        t = ""
        for a in accounts:
            em = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
            s = "✅" if a["verified"] else "⏳"
            t += f"{em} **{a['platform'].title()}**: `@{a['platform_username']}` {s}\n"
        e.add_field(name="🔗 Connected Accounts", value=t, inline=False)
    else:
        e.add_field(name="🔗 Connected Accounts", value="No accounts linked yet.", inline=False)
    ft(e)
    return e

class ViewAccountsView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="🔗 Link New", style=discord.ButtonStyle.success)
    async def link(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = emb("🔗 Link Account", "Select a platform.")
        await interaction.response.edit_message(embed=e, view=ChoosePlatformView(interaction.user.id))

    @discord.ui.button(label="🗑️ Unlink", style=discord.ButtonStyle.danger)
    async def unlink(self, interaction: discord.Interaction, button: discord.ui.Button):
        accs = await get_accounts(str(interaction.user.id))
        if not accs:
            await interaction.response.send_message("❌ No accounts to unlink!", ephemeral=True)
            return
        e = emb("🗑️ Unlink Account", "Select to remove.")
        await interaction.response.edit_message(embed=e, view=UnlinkView(interaction.user.id, accs))

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = await build_profile_card(interaction.user)
        await interaction.response.edit_message(embed=e, view=ViewAccountsView(interaction.user.id))

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
            await interaction.response.send_message(f"❌ Not a valid **{pi['name']}** URL!", ephemeral=True)
            return
        pool = await get_db()
        async with pool.acquire() as c:
            ex = await c.fetchrow("SELECT user_id FROM accounts WHERE platform=$1 AND platform_username=$2 AND user_id!=$3", self.platform, username, str(self.uid))
            if ex:
                await interaction.response.send_message(f"❌ `@{username}` on **{pi['name']}** is already linked by another user!", ephemeral=True)
                return
            own = await c.fetchrow("SELECT * FROM accounts WHERE platform=$1 AND user_id=$2", self.platform, str(self.uid))
            if own and own["verified"]:
                await interaction.response.send_message(f"✅ You already have verified **{pi['name']}**: `@{own['platform_username']}`\nUnlink first to change.", ephemeral=True)
                return
            code = gen_code()
            await c.execute("INSERT INTO accounts(user_id,platform,platform_username,platform_url,verified,verification_code) VALUES($1,$2,$3,$4,FALSE,$5) ON CONFLICT(user_id,platform) DO UPDATE SET platform_username=$3,platform_url=$4,verified=FALSE,verification_code=$5,linked_at=NOW()", str(self.uid), self.platform, username, url, code)
        e = emb(f"{pi['emoji']} Verify Your {pi['name']}", f"**Account:** `@{username}`\n**URL:** {url}\n\n━━━━━━━━━━━━━━━━━━━━━\n\n📋 **Your Verification Code:**\n```\n{code}\n```\n\n**Steps:**\n1️⃣ Copy the code above\n2️⃣ Go to your **{pi['name']}** profile\n3️⃣ Add code to your **bio**\n4️⃣ Click **✅ Verify Now**\n\n⚠️ *Remove code from bio after verification*")
        await interaction.response.edit_message(embed=e, view=VerifyView(self.uid, self.platform, username, code))

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
        # Auto-assign clipper role
        await assign_clipper_role(interaction)
        e = emb(f"✅ {pi['name']} Verified!", f"{pi['emoji']} **@{self.username}** connected!\n\nYou have **{vc}** verified account(s).\nRemove the code from your bio now.\n\n🎉 You can now submit posts in campaigns!")
        await interaction.response.edit_message(embed=e, view=AfterVerifyView(self.uid))

    @discord.ui.button(label="📋 Copy Code", style=discord.ButtonStyle.secondary)
    async def copy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"```\n{self.code}\n```", ephemeral=True)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        pool = await get_db()
        async with pool.acquire() as c:
            await c.execute("DELETE FROM accounts WHERE user_id=$1 AND platform=$2 AND verified=FALSE", str(self.uid), self.platform)
        await interaction.response.edit_message(embed=emb("❌ Cancelled"), view=None)

class AfterVerifyView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="🔗 Link Another", style=discord.ButtonStyle.success)
    async def another(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = emb("🔗 Link Another", "Select platform.")
        await interaction.response.edit_message(embed=e, view=ChoosePlatformView(interaction.user.id))

    @discord.ui.button(label="👤 View Profile", style=discord.ButtonStyle.primary)
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = await build_profile_card(interaction.user)
        await interaction.response.edit_message(embed=e, view=ViewAccountsView(interaction.user.id))

class UnlinkSelect(discord.ui.Select):
    def __init__(self, uid, accs):
        self.uid = uid
        opts = [discord.SelectOption(label=f"{a['platform'].title()} — @{a['platform_username']}", value=a["platform"], emoji=PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")) for a in accs]
        super().__init__(placeholder="Select to unlink...", options=opts, row=1)

    async def callback(self, interaction: discord.Interaction):
        pool = await get_db()
        async with pool.acquire() as c:
            await c.execute("DELETE FROM accounts WHERE user_id=$1 AND platform=$2", str(self.uid), self.values[0])
        await interaction.response.edit_message(embed=emb(f"✅ {self.values[0].title()} Unlinked"), view=AfterVerifyView(self.uid))

class UnlinkView(discord.ui.View):
    def __init__(self, uid, accs):
        super().__init__(timeout=120)
        self.add_item(UnlinkSelect(uid, accs))

    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = await build_profile_card(interaction.user)
        await interaction.response.edit_message(embed=e, view=ViewAccountsView(interaction.user.id))

# ═══════════════ CAMPAIGN PANEL ═══════════════

class CampaignView(discord.ui.View):
    def __init__(self, name="default"):
        super().__init__(timeout=None)
        self.campaign_name = name

    @discord.ui.button(label="Submissions", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="p_subs")
    async def submissions(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            clips = await get_clips(str(interaction.user.id))
            if not clips:
                await interaction.response.send_message("📋 **0** submissions.\nClick **Submit post** to start!", ephemeral=True)
                return
            desc = ""
            rate = await get_rate()
            for i, cl in enumerate(clips[:10], 1):
                em = PLATFORM_INFO.get(cl["platform"],{}).get("emoji","🔗")
                s = "✅" if cl["status"] == "paid" else "⏳" if cl["status"] == "pending" else "🔍"
                desc += f"{i}. {em} {s} **{cl['views']:,}** views — ${cl['views']*rate:.2f}\n"
            await interaction.response.send_message(embed=emb("📋 Your Submissions", desc), ephemeral=True)
        except Exception as ex:
            print(f"Subs error: {ex}")
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="Accounts", emoji="🔗", style=discord.ButtonStyle.secondary, custom_id="p_camp_accs")
    async def accounts(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            e = await build_profile_card(interaction.user)
            await interaction.response.send_message(embed=e, ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="Payouts", emoji="💸", style=discord.ButtonStyle.secondary, custom_id="p_payouts")
    async def payouts(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            clips = await get_clips(str(interaction.user.id))
            rate = await get_rate()
            tv = sum(c["views"] for c in clips)
            te = tv * rate
            pe = sum(c["views"] for c in clips if c["status"] in ("pending","tracking","under_review")) * rate
            pa = sum(c["views"] for c in clips if c["status"] == "paid") * rate
            e = emb("💸 Your Payouts")
            e.add_field(name="💵 Total Earned", value=f"**${te:.2f}**", inline=True)
            e.add_field(name="⏳ Pending", value=f"${pe:.2f}", inline=True)
            e.add_field(name="✅ Paid", value=f"${pa:.2f}", inline=True)
            u = await get_user(str(interaction.user.id))
            if u and u["payment_method"]:
                e.add_field(name="💳 Method", value=u["payment_method"], inline=False)
            await interaction.response.send_message(embed=e, ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="Stats", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="p_stats")
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            clips = await get_clips(str(interaction.user.id))
            rate = await get_rate()
            tv = sum(c["views"] for c in clips)
            accs = await get_verified_accounts(str(interaction.user.id))
            u = await get_user(str(interaction.user.id))
            tier = TIER_NAMES.get(u["tier"] if u else 0, "⚪ Unranked")
            e = discord.Embed(title=f"📊 {interaction.user.display_name}'s Stats", color=MAIN_COLOR)
            e.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            e.add_field(name="🎖️ Tier", value=tier, inline=True)
            e.add_field(name="👁 Views", value=f"{tv:,}", inline=True)
            e.add_field(name="📹 Posts", value=str(len(clips)), inline=True)
            e.add_field(name="💵 Earnings", value=f"${tv*rate:.2f}", inline=True)
            e.add_field(name="🔗 Accounts", value=str(len(accs)), inline=True)
            if clips:
                platforms = {}
                for cl in clips:
                    p = cl["platform"]
                    if p not in platforms: platforms[p] = {"views": 0, "count": 0}
                    platforms[p]["views"] += cl["views"]
                    platforms[p]["count"] += 1
                bd = ""
                for p, d in platforms.items():
                    em = PLATFORM_INFO.get(p,{}).get("emoji","🔗")
                    bd += f"{em} **{p.title()}**: {d['views']:,} views ({d['count']} posts)\n"
                e.add_field(name="📊 Breakdown", value=bd, inline=False)
            ft(e)
            await interaction.response.send_message(embed=e, ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

    @discord.ui.button(label="Submit post", emoji="➕", style=discord.ButtonStyle.success, custom_id="p_submit_post", row=2)
    async def submit_post(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            uid = str(interaction.user.id)
            pool = await get_db()
            async with pool.acquire() as c:
                ban = await c.fetchrow("SELECT * FROM bans WHERE user_id=$1", uid)
            if ban:
                await interaction.response.send_message(f"🚫 You are **banned**.\nReason: {ban['reason'] or '—'}", ephemeral=True)
                return
            accs = await get_verified_accounts(uid)
            if not accs:
                await interaction.response.send_message("❌ You need a **verified** social account!\nGo to #connect-socials first.", ephemeral=True)
                return
            async with pool.acquire() as c:
                camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(interaction.channel.id))
            if camp:
                if camp["deadline"] and datetime.utcnow() > camp["deadline"]:
                    await interaction.response.send_message("⏰ Campaign **expired**!", ephemeral=True)
                    return
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                async with pool.acquire() as c:
                    tc = await c.fetchrow("SELECT COUNT(*) as cnt FROM clips WHERE user_id=$1 AND campaign_id=$2 AND submitted_at >= $3", uid, str(camp["id"]), today_start)
                if tc and int(tc["cnt"]) >= camp["daily_limit"]:
                    await interaction.response.send_message(f"📛 Daily limit reached! Max **{camp['daily_limit']}** posts/day.", ephemeral=True)
                    return
            desc = "Select which account you're submitting from:\n\n"
            for a in accs:
                em = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
                desc += f"{em} **{a['platform'].title()}**: `@{a['platform_username']}` ✅\n"
            await interaction.response.send_message(embed=emb("➕ Submit Post", desc), view=SubmitPlatformView(uid, accs), ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error. Try again.", ephemeral=True)

class SubmitPlatformView(discord.ui.View):
    def __init__(self, uid, accs):
        super().__init__(timeout=120)
        self.add_item(SubmitPlatformSelect(uid, accs))

class SubmitPlatformSelect(discord.ui.Select):
    def __init__(self, uid, accs):
        self.uid = uid
        opts = [discord.SelectOption(label=f"{a['platform'].title()} — @{a['platform_username']}", value=a["platform"], emoji=PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")) for a in accs]
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
                await interaction.response.send_message("❌ Already submitted!", ephemeral=True)
                return
            # Get campaign id if in campaign channel
            camp = await c.fetchrow("SELECT id FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(interaction.channel.id))
            cid = str(camp["id"]) if camp else ""
            await c.execute("INSERT INTO clips(user_id,platform,url,views,earnings,status,campaign_id) VALUES($1,$2,$3,0,0,'tracking',$4)", str(self.uid), self.platform, url, cid)
        e = emb("✅ Post Submitted!", f"{pi['emoji']} **{pi['name']}**\n🔗 {url}\n\n📊 Views will be tracked automatically.\n⏳ Staff will review within **48 hours**.\n\n⚠️ Submit right after publishing!")
        await interaction.response.edit_message(embed=e, view=None)

# ═══════════════ SETUP ═══════════════

class SetupStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🚀 Start Setup", style=discord.ButtonStyle.success)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            e = emb("🌍 Step 1/2 — Country", "Select your country.")
            await interaction.response.edit_message(embed=e, view=SetupCountryView(interaction.user.id))
        except:
            await interaction.response.send_message("❌ Error.", ephemeral=True)

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
        e = emb("💵 Step 2/2 — Payment", f"✅ Country: **{self.values[0]}**\n\nSelect payment method:")
        await interaction.response.edit_message(embed=e, view=SetupPaymentView(self.uid))

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
                em = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
                d += f"{em} `@{a['platform_username']}` {'✅' if a['verified'] else '⏳'}\n"
        d += f"\n🌍 **Country:** {u['country']}\n💵 **Payment:** {self.method}"
        await interaction.response.edit_message(embed=emb("🎉 Setup Complete!", d), view=None)

# ═══════════════ PROFILE PANEL (for #your-profile) ═══════════════

class ProfilePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="👤 My Profile", style=discord.ButtonStyle.primary, custom_id="p_my_profile")
    async def my_profile(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            e = await build_full_profile(interaction.user)
            await interaction.response.send_message(embed=e, view=ProfileActionView(interaction.user.id), ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error.", ephemeral=True)

    @discord.ui.button(label="💰 Earnings", style=discord.ButtonStyle.success, custom_id="p_my_earnings")
    async def my_earnings(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            e = await build_earnings(interaction.user)
            await interaction.response.send_message(embed=e, ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error.", ephemeral=True)

    @discord.ui.button(label="🏆 Leaderboard", style=discord.ButtonStyle.secondary, custom_id="p_my_lb")
    async def my_lb(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            e = await build_lb()
            await interaction.response.send_message(embed=e, ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error.", ephemeral=True)

    @discord.ui.button(label="⚡ Setup Account", style=discord.ButtonStyle.success, custom_id="p_my_setup", row=2)
    async def my_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            u = await get_user(str(interaction.user.id))
            if u and u["setup_complete"]:
                await interaction.response.send_message("✅ Already set up! Click **👤 My Profile**.", ephemeral=True)
                return
            e = emb("⚡ Account Setup", "🌍 **Step 1** — Country\n💵 **Step 2** — Payment\n\n*Link socials in #connect-socials!*")
            await interaction.response.send_message(embed=e, view=SetupStartView(), ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error.", ephemeral=True)

class ProfileActionView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
        self.uid = uid

    @discord.ui.button(label="💰 Earnings", style=discord.ButtonStyle.success)
    async def earn(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = await build_earnings(interaction.user)
        await interaction.response.edit_message(embed=e, view=EarningsBackView(interaction.user.id))

    @discord.ui.button(label="✏️ Edit Account", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = emb("✏️ Edit Account", "What would you like to change?")
        await interaction.response.edit_message(embed=e, view=EditView(interaction.user.id))

    @discord.ui.button(label="🏆 Leaderboard", style=discord.ButtonStyle.secondary)
    async def lb(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = await build_lb()
        await interaction.response.edit_message(embed=e, view=LBBackView(interaction.user.id))

class EarningsBackView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
    @discord.ui.button(label="👤 Profile", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = await build_full_profile(interaction.user)
        await interaction.response.edit_message(embed=e, view=ProfileActionView(interaction.user.id))

class LBBackView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=120)
    @discord.ui.button(label="👤 Profile", style=discord.ButtonStyle.primary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = await build_full_profile(interaction.user)
        await interaction.response.edit_message(embed=e, view=ProfileActionView(interaction.user.id))

# ═══════════════ PROFILE ═══════════════

async def build_full_profile(user):
    uid = str(user.id)
    await ensure_user(user)
    u = await get_user(uid)
    accs = await get_accounts(uid)
    clips = await get_clips(uid)
    rate = await get_rate()
    tv = sum(c["views"] for c in clips)
    tier = TIER_NAMES.get(u["tier"] if u else 0, "⚪ Unranked")
    e = discord.Embed(title=f"👤 {user.display_name}", color=MAIN_COLOR)
    e.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    e.add_field(name="Status", value="✅ Verified" if u and u["setup_complete"] else "⚠️ Incomplete", inline=True)
    e.add_field(name="🎖️ Tier", value=tier, inline=True)
    e.add_field(name="📹 Posts", value=str(len(clips)), inline=True)
    e.add_field(name="👁 Views", value=f"{tv:,}", inline=True)
    e.add_field(name="💵 Earnings", value=f"${tv*rate:.2f}", inline=True)
    if u and u["country"]: e.add_field(name="🌍", value=u["country"], inline=True)
    if accs:
        t = "\n".join(f"{PLATFORM_INFO.get(a['platform'],{}).get('emoji','🔗')} **{a['platform'].title()}**: `@{a['platform_username']}` {'✅' if a['verified'] else '⏳'}" for a in accs)
        e.add_field(name="🔗 Socials", value=t, inline=False)
    ft(e)
    return e

class EditView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=300)
        self.uid = uid

    @discord.ui.button(label="🌍 Country", style=discord.ButtonStyle.success)
    async def country(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=emb("🌍 Change Country"), view=EditCountryView(i.user.id))

    @discord.ui.button(label="💵 Payment", style=discord.ButtonStyle.primary)
    async def pay(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=emb("💵 Change Payment"), view=EditPayView(i.user.id))

    @discord.ui.button(label="⬅️ Back", style=discord.ButtonStyle.secondary)
    async def back(self, i: discord.Interaction, b):
        await i.response.edit_message(embed=await build_full_profile(i.user), view=ProfileActionView(i.user.id))

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
        await i.response.edit_message(embed=await build_full_profile(i.user), view=ProfileActionView(i.user.id))

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
    e = discord.Embed(title="💰 Earnings", color=MAIN_COLOR)
    e.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    e.add_field(name="💵 Total", value=f"**${te:.2f}**", inline=True)
    e.add_field(name="⏳ Pending", value=f"${pe:.2f}", inline=True)
    e.add_field(name="✅ Paid", value=f"${pa:.2f}", inline=True)
    e.add_field(name="👁 Views", value=f"{tv:,}", inline=True)
    e.add_field(name="📹 Posts", value=str(len(clips)), inline=True)
    if clips:
        r = ""
        for cl in clips[:5]:
            em = PLATFORM_INFO.get(cl["platform"],{}).get("emoji","🔗")
            s = "✅" if cl["status"]=="paid" else "⏳"
            r += f"{s} {em} {cl['views']:,} views — ${cl['views']*rate:.2f}\n"
        e.add_field(name="📋 Recent", value=r, inline=False)
    ft(e)
    return e

# ═══════════════ LEADERBOARD ═══════════════

async def build_lb():
    data = await get_leaderboard()
    e = discord.Embed(title="🏆 Leaderboard", color=MAIN_COLOR)
    if not data or all(d[2] == 0 for d in data):
        e.description = "No submissions yet!"
    else:
        m = ["🥇","🥈","🥉"]
        t = ""
        for idx,(name,earn,views,clips) in enumerate(data):
            if views == 0: continue
            r = m[idx] if idx < 3 else f"**{idx+1}.**"
            t += f"{r} **{name}** — {views:,} views (${earn:.2f})\n"
        e.description = t or "No submissions yet!"
    ft(e)
    return e

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
            desc = "**Follow these steps to verify your tier:**\n\n"
            desc += "1️⃣ Select your connected account below\n"
            desc += "2️⃣ Upload a **screen recording** of your account analytics\n"
            desc += "3️⃣ Our staff will review it within **48 hours**\n"
            desc += "4️⃣ Your tier will be updated!\n\n"
            desc += "**Your verified accounts:**\n"
            for a in accs:
                em = PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")
                desc += f"{em} **{a['platform'].title()}**: `@{a['platform_username']}` ✅\n"
            e = discord.Embed(title="🎖️ Tier Verification", description=desc, color=MAIN_COLOR)
            e.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            ft(e)
            await interaction.response.send_message(embed=e, view=TierPlatformView(interaction.user.id, accs), ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error.", ephemeral=True)

    @discord.ui.button(label="📋 My Tier Status", style=discord.ButtonStyle.primary, custom_id="p_tier_status")
    async def tier_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await ensure_user(interaction.user)
            u = await get_user(str(interaction.user.id))
            tv = await get_total_views(str(interaction.user.id))
            accs = await get_verified_accounts(str(interaction.user.id))
            tier = TIER_NAMES.get(u["tier"] if u else 0, "⚪ Unranked")
            desc = f"**Current Tier:** {tier}\n**Total Views:** {tv:,}\n**Country:** {u['country'] if u else '—'}\n**Accounts:** {len(accs)}\n\n"
            desc += "💡 *Tiers are assigned by staff after review.*"
            e = discord.Embed(title=f"🎖️ {interaction.user.display_name}'s Tier", description=desc, color=MAIN_COLOR)
            e.set_thumbnail(url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
            ft(e)
            await interaction.response.send_message(embed=e, ephemeral=True)
        except:
            await interaction.response.send_message("❌ Error.", ephemeral=True)

class TierPlatformView(discord.ui.View):
    def __init__(self, uid, accs):
        super().__init__(timeout=120)
        self.add_item(TierPlatformSelect(uid, accs))

class TierPlatformSelect(discord.ui.Select):
    def __init__(self, uid, accs):
        self.uid = uid
        opts = [discord.SelectOption(label=f"{a['platform'].title()} — @{a['platform_username']}", value=a["platform"], emoji=PLATFORM_INFO.get(a["platform"],{}).get("emoji","🔗")) for a in accs]
        super().__init__(placeholder="▼ Select account...", options=opts)

    async def callback(self, interaction: discord.Interaction):
        pi = PLATFORM_INFO[self.values[0]]
        e = emb("📤 Upload Your Analytics", f"{pi['emoji']} **{pi['name']}** selected\n\n**Now upload a screen recording or screenshot** of your {pi['name']} analytics directly in this channel.\n\n📹 Show your:\n• Total views\n• Recent video performance\n• Account overview\n\n⏳ Staff will review within **48 hours** and assign your tier.\n\n*Just drag & drop or paste your file below!*")
        pool = await get_db()
        async with pool.acquire() as c:
            await c.execute("INSERT INTO clips(user_id,platform,url,views,earnings,status) VALUES($1,$2,$3,0,0,'under_review') ON CONFLICT DO NOTHING", str(self.uid), self.values[0], f"tier-verify-{self.uid}-{self.values[0]}")
        await interaction.response.edit_message(embed=e, view=None)

# ═══════════════ TICKET SYSTEM ═══════════════

TICKET_CATEGORIES = {
    "payment": {"label": "Payment Issue", "emoji": "💰", "desc": "Payment not received, wrong amount, delays"},
    "demographics": {"label": "Account Demographics", "emoji": "🌍", "desc": "Country change, account verification"},
    "stats": {"label": "Stats Not Updating", "emoji": "📊", "desc": "Views not counting, earnings stuck"},
    "campaign": {"label": "Campaign Question", "emoji": "🎯", "desc": "Rules, eligibility, deadlines"},
    "video": {"label": "Video Submission", "emoji": "📹", "desc": "Clip rejected, resubmission, uploads"},
    "business": {"label": "Business Inquiry", "emoji": "💼", "desc": "Partnerships, sponsorships, brands"},
    "general": {"label": "General Question", "emoji": "❓", "desc": "Anything else"},
}

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Payment Issue", emoji="💰", style=discord.ButtonStyle.secondary, custom_id="t_payment", row=0)
    async def t_payment(self, i: discord.Interaction, b): await create_ticket(i, "payment")
    @discord.ui.button(label="Account Demographics", emoji="🌍", style=discord.ButtonStyle.secondary, custom_id="t_demo", row=0)
    async def t_demo(self, i: discord.Interaction, b): await create_ticket(i, "demographics")
    @discord.ui.button(label="Stats Not Updating", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="t_stats", row=1)
    async def t_stats(self, i: discord.Interaction, b): await create_ticket(i, "stats")
    @discord.ui.button(label="Campaign Question", emoji="🎯", style=discord.ButtonStyle.secondary, custom_id="t_campaign", row=1)
    async def t_campaign(self, i: discord.Interaction, b): await create_ticket(i, "campaign")
    @discord.ui.button(label="Video Submission", emoji="📹", style=discord.ButtonStyle.secondary, custom_id="t_video", row=2)
    async def t_video(self, i: discord.Interaction, b): await create_ticket(i, "video")
    @discord.ui.button(label="Business Inquiry", emoji="💼", style=discord.ButtonStyle.secondary, custom_id="t_business", row=2)
    async def t_business(self, i: discord.Interaction, b): await create_ticket(i, "business")
    @discord.ui.button(label="General Question", emoji="❓", style=discord.ButtonStyle.secondary, custom_id="t_general", row=3)
    async def t_general(self, i: discord.Interaction, b): await create_ticket(i, "general")

async def create_ticket(interaction, category):
    try:
        uid = str(interaction.user.id)
        pool = await get_db()
        async with pool.acquire() as c:
            existing = await c.fetchrow("SELECT * FROM tickets WHERE user_id=$1 AND status='open'", uid)
        if existing:
            await interaction.response.send_message(f"❌ You already have an open ticket! <#{existing['channel_id']}>", ephemeral=True)
            return

        guild = interaction.guild
        cat_info = TICKET_CATEGORIES[category]
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        ticket_cat = discord.utils.get(guild.categories, name="TICKETS")
        if not ticket_cat:
            ticket_cat = await guild.create_category("TICKETS")

        channel = await guild.create_text_channel(f"ticket-{interaction.user.name}", category=ticket_cat, overwrites=overwrites)
        async with pool.acquire() as c:
            await c.execute("INSERT INTO tickets(user_id,channel_id,category) VALUES($1,$2,$3)", uid, str(channel.id), category)

        e = emb(f"{cat_info['emoji']} {cat_info['label']}", f"**Created by:** {interaction.user.mention}\n**Category:** {cat_info['label']}\n\n━━━━━━━━━━━━━━━━━━━━━\n\nPlease describe your issue below.\nA staff member will respond shortly.\n\n🔒 Only admins can close this ticket.")
        await channel.send(embed=e, view=TicketControlView())
        await channel.send(f"{interaction.user.mention} your ticket is ready!")
        await interaction.response.send_message(f"✅ Ticket created! → {channel.mention}", ephemeral=True)
    except Exception as ex:
        print(f"Ticket error: {ex}")
        await interaction.response.send_message("❌ Error creating ticket.", ephemeral=True)

def is_staff(member):
    """Check if member is admin or has support role"""
    if member.guild_permissions.administrator:
        return True
    support_roles = ["support", "staff", "mod", "moderator", "forge support"]
    return any(role.name.lower() in support_roles for role in member.roles)

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Claim Ticket", style=discord.ButtonStyle.success, custom_id="p_claim_ticket")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff or Admin only!", ephemeral=True)
            return

        pool = await get_db()
        async with pool.acquire() as c:
            ticket = await c.fetchrow("SELECT * FROM tickets WHERE channel_id=$1", str(interaction.channel.id))

        if not ticket:
            await interaction.response.send_message("❌ Ticket not found!", ephemeral=True)
            return

        # Get ticket category
        cat = ticket.get("category", "general")
        cat_info = TICKET_CATEGORIES.get(cat, TICKET_CATEGORIES["general"])

        # Update embed to show claimed
        claim_embed = discord.Embed(
            title=f"🎫 Ticket Claimed",
            description=f"**Claimed by:** {interaction.user.mention}\n**Category:** {cat_info['label']}\n\nStaff is now handling this ticket.",
            color=GREEN
        )
        footer(claim_embed)
        await interaction.response.send_message(embed=claim_embed)

        # DM the user
        try:
            user = await bot.fetch_user(int(ticket["user_id"]))
            dm_embed = discord.Embed(
                title="🎫 Your Ticket Has Been Claimed",
                description=(
                    f"Our team has picked up your ticket and is working on it.\n\n"
                    f"**Category:** {cat_info['label']}\n"
                    f"**Claimed by:** {interaction.user.name}\n\n"
                    f"You'll receive updates as staff responds."
                ),
                color=GREEN
            )
            footer(dm_embed)
            await user.send(embed=dm_embed)
        except:
            pass

    @discord.ui.button(label="💬 Reply to User", style=discord.ButtonStyle.primary, custom_id="p_reply_ticket")
    async def reply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff or Admin only!", ephemeral=True)
            return
        await interaction.response.send_modal(TicketReplyModal())

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="p_close_ticket")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff or Admin only!", ephemeral=True)
            return

        pool = await get_db()
        async with pool.acquire() as c:
            ticket = await c.fetchrow("SELECT * FROM tickets WHERE channel_id=$1", str(interaction.channel.id))
            await c.execute("UPDATE tickets SET status='closed' WHERE channel_id=$1", str(interaction.channel.id))

        # DM user that ticket is closed
        if ticket:
            cat = ticket.get("category", "general")
            cat_info = TICKET_CATEGORIES.get(cat, TICKET_CATEGORIES["general"])
            try:
                user = await bot.fetch_user(int(ticket["user_id"]))
                dm_embed = discord.Embed(
                    title=f"🔒 Ticket Closed — {cat_info['label']}",
                    description=(
                        f"Your ticket has been resolved and closed.\n\n"
                        f"**Category:** {cat_info['label']}\n"
                        f"**Closed by:** {interaction.user.name}\n\n"
                        f"If you need more help, create a new ticket!"
                    ),
                    color=RED
                )
                footer(dm_embed)
                await user.send(embed=dm_embed)
            except:
                pass

        e = emb("🔒 Ticket Closed", f"Closed by {interaction.user.mention}\nUser access has been removed. Ticket data preserved.")
        await interaction.response.send_message(embed=e)

        # Remove user's access to channel instead of deleting
        if ticket:
            try:
                member = interaction.guild.get_member(int(ticket["user_id"]))
                if member:
                    await interaction.channel.set_permissions(member, read_messages=False, send_messages=False)
            except:
                pass


class TicketReplyModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Reply to Ticket")
        self.reply_text = discord.ui.TextInput(
            label="Your response",
            placeholder="Type your reply to the user...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        self.add_item(self.reply_text)

    async def on_submit(self, interaction: discord.Interaction):
        pool = await get_db()
        async with pool.acquire() as c:
            ticket = await c.fetchrow("SELECT * FROM tickets WHERE channel_id=$1", str(interaction.channel.id))

        if not ticket:
            await interaction.response.send_message("❌ Ticket not found!", ephemeral=True)
            return

        cat = ticket.get("category", "general")
        cat_info = TICKET_CATEGORIES.get(cat, TICKET_CATEGORIES["general"])

        # Post reply in ticket channel
        reply_embed = discord.Embed(
            title="💬 Staff Response",
            description=f"**From:** {interaction.user.mention}\n\n{self.reply_text.value}",
            color=CYAN
        )
        footer(reply_embed)
        await interaction.response.send_message(embed=reply_embed)

        # DM the user
        try:
            user = await bot.fetch_user(int(ticket["user_id"]))
            dm_embed = discord.Embed(
                title="💬 Support Replied to Your Ticket",
                description=(
                    f"Our team just sent you a response.\n\n"
                    f"**Category:** {cat_info['label']}\n"
                    f"**From:** {interaction.user.name}\n\n"
                    f"**Response:**\n{self.reply_text.value}"
                ),
                color=CYAN
            )
            footer(dm_embed)
            await user.send(embed=dm_embed)
        except:
            pass

# ═══════════════ HELP ═══════════════

def build_help():
    e = discord.Embed(title="📚 Admin Commands", color=MAIN_COLOR)
    e.add_field(name="📌 Panels", value="`/postpanel` `/postprofile` `/postcampaign` `/posttier` `/postticket` `/postsuggestions` `/postrules` `/postfaq` `/postguide`", inline=False)
    e.add_field(name="🎯 Campaign", value="`/campaignlb` `/endcampaign` `/setlimit`", inline=False)
    e.add_field(name="💸 Payouts", value="`/sendpayout` `/pendingpayouts` `/payouthistory`", inline=False)
    e.add_field(name="🚫 Moderation", value="`/ban` `/unban` `/banlist` `/settier`", inline=False)
    e.add_field(name="🔧 Tools", value="`/embed` `/colors` `/announce` `/dmuser` `/setrate` `/allusers` `/userinfo` `/approveclip` `/help`", inline=False)
    ft(e)
    return e

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
                # Media-only: delete non-link messages
                if camp["media_only"]:
                    urls = re.findall(r'https?://\S+', message.content)
                    has_attachment = len(message.attachments) > 0
                    if not urls and not has_attachment:
                        try:
                            await message.delete()
                            await message.channel.send(f"{message.author.mention} Only links and media are allowed here!", delete_after=5)
                        except:
                            pass
                        return

                urls = re.findall(r'https?://\S+', message.content)
                if urls:
                    uid = str(message.author.id)
                    async with pool.acquire() as c:
                        ban = await c.fetchrow("SELECT * FROM bans WHERE user_id=$1", uid)
                    if ban:
                        await message.reply("🚫 Banned.", delete_after=5)
                        return
                    if camp["deadline"] and datetime.utcnow() > camp["deadline"]:
                        await message.reply("⏰ Expired!", delete_after=5)
                        return
                    v = await get_verified_accounts(uid)
                    if not v:
                        await message.reply("❌ Verify account first!", delete_after=10)
                        return
                    url = urls[0]
                    if camp["platform"]:
                        pi = PLATFORM_INFO.get(camp["platform"],{})
                        if pi and not re.search(pi.get("url_pattern",""), url, re.IGNORECASE):
                            await message.reply(f"❌ Only **{pi.get('name','')}** links!", delete_after=10)
                            return
                    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                    async with pool.acquire() as c:
                        tc = await c.fetchrow("SELECT COUNT(*) as cnt FROM clips WHERE user_id=$1 AND campaign_id=$2 AND submitted_at >= $3", uid, str(camp["id"]), today_start)
                    if tc and int(tc["cnt"]) >= camp["daily_limit"]:
                        await message.reply(f"📛 Daily limit ({camp['daily_limit']})!", delete_after=10)
                        return
                    async with pool.acquire() as c:
                        ex = await c.fetchrow("SELECT id FROM clips WHERE url=$1", url)
                        if ex:
                            await message.reply("⚠️ Already submitted!", delete_after=10)
                            return
                        await c.execute("INSERT INTO clips(user_id,platform,url,views,earnings,status,campaign_id) VALUES($1,$2,$3,0,0,'tracking',$4)", uid, camp["platform"] or "unknown", url, str(camp["id"]))
                    await message.add_reaction("✅")
        except Exception as ex:
            print(f"Msg error: {ex}")
    await bot.process_commands(message)

# ═══════════════ ON READY ═══════════════

@bot.event
async def on_ready():
    await init_db()
    bot.add_view(ConnectSocialsView())
    bot.add_view(TierVerifyView())
    bot.add_view(CampaignView())
    bot.add_view(TicketView())
    bot.add_view(TicketControlView())
    bot.add_view(SuggestionView())
    bot.add_view(ProfilePanelView())
    try:
        s = await bot.tree.sync()
        print(f"✅ Synced {len(s)} commands")
    except Exception as ex:
        print(f"❌ Sync: {ex}")
    print(f"✅ {bot.user} is live!")

# ═══════════════ ADMIN COMMANDS ═══════════════

@bot.tree.command(name="postpanel", description="[Admin] Post connect-socials panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_panel(i: discord.Interaction):
    e = emb("🔗 Manage Your Social Accounts", "Use the buttons below to manage your account.\n\n**🔗 Link Account**\nConnect your social media page.\n\n**👥 View Accounts**\nView your connected accounts, views & earnings.")
    await i.channel.send(embed=e, view=ConnectSocialsView())
    await i.response.send_message("✅ Posted!", ephemeral=True)

@bot.tree.command(name="postprofile", description="[Admin] Post profile panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_postprofile(i: discord.Interaction):
    e = emb("👤 Your Account", "Manage your Clip Forge account here!\n\n**👤 My Profile**\nView stats, accounts, tier & earnings.\n\n**💰 Earnings**\nTotal, pending & paid breakdown.\n\n**🏆 Leaderboard**\nSee where you rank.\n\n**⚡ Setup Account**\nFirst time? Set up country & payment.")
    await i.channel.send(embed=e, view=ProfilePanelView())
    await i.response.send_message("✅ Posted!", ephemeral=True)

@bot.tree.command(name="postcampaign", description="[Admin] Post campaign panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_postcampaign(i: discord.Interaction, name: str, platform: str = "", daily_limit: int = 50, deadline_hours: int = 0):
    if platform and platform.lower() not in PLATFORM_INFO:
        await i.response.send_message(f"❌ Use: {', '.join(PLATFORM_INFO.keys())}", ephemeral=True)
        return
    dl = datetime.utcnow() + timedelta(hours=deadline_hours) if deadline_hours > 0 else None
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO campaigns(name,channel_id,platform,created_by,daily_limit,deadline,media_only) VALUES($1,$2,$3,$4,$5,$6,TRUE)", name, str(i.channel.id), platform.lower() if platform else "", str(i.user.id), daily_limit, dl)
    pt = f" ({PLATFORM_INFO[platform.lower()]['name']} only)" if platform else ""
    dl_text = f"\n⏰ **Deadline:** <t:{int(dl.timestamp())}:R>" if dl else ""
    e = emb(f"🚀 {name} is now live!", f"Submissions are open{pt}.{dl_text}\n📛 **Daily limit:** {daily_limit} posts/user\n\n**👉 Submit your posts**\nClick **Submit post** below to start!\n\n⚠️ Submit right after publishing!\n\n*By clicking Submit post, you accept the campaign terms.*")
    await i.channel.send(embed=e, view=CampaignView(name))
    await i.response.send_message("✅ Posted!", ephemeral=True)

@bot.tree.command(name="posttier", description="[Admin] Post tier verification panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_posttier(i: discord.Interaction):
    e = emb("🎖️ Tier Verification", "Get your tier verified by our staff!\n\n**🎖️ Verify My Tier**\nSelect your account and upload analytics.\nStaff will review within 48 hours.\n\n**📋 My Tier Status**\nCheck your current tier.")
    await i.channel.send(embed=e, view=TierVerifyView())
    await i.response.send_message("✅ Posted!", ephemeral=True)

@bot.tree.command(name="postticket", description="[Admin] Post ticket panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_postticket(i: discord.Interaction):
    e = emb("🎫 Do you need any help?", "Click a **button below** to open a support ticket.\nYou'll get help from our team.\n\nWe usually respond within **12 hours on weekdays**, often faster during active campaigns.")
    await i.channel.send(embed=e, view=TicketView())
    await i.response.send_message("✅ Posted!", ephemeral=True)

@bot.tree.command(name="settier", description="[Admin] Set user's tier")
@app_commands.checks.has_permissions(administrator=True)
async def s_settier(i: discord.Interaction, user: discord.User, tier: int):
    if tier not in TIER_NAMES:
        await i.response.send_message(f"❌ Tier must be 0, 1, 2, or 3.\n0=Unranked, 1=Tier 1, 2=Tier 2, 3=Tier 3", ephemeral=True)
        return
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("UPDATE users SET tier=$1 WHERE user_id=$2", tier, str(user.id))
    tn = TIER_NAMES[tier]
    await i.response.send_message(embed=emb("✅ Tier Updated", f"**{user.mention}** → {tn}"))
    # DM user
    try:
        await user.send(embed=emb("🎖️ Tier Updated!", f"Your tier has been updated to **{tn}**!\nCheck your profile to see the change."))
    except:
        pass

@bot.tree.command(name="campaignlb", description="[Admin] Campaign leaderboard")
@app_commands.checks.has_permissions(administrator=True)
async def s_campaignlb(i: discord.Interaction):
    pool = await get_db()
    async with pool.acquire() as c:
        camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(i.channel.id))
    if not camp:
        await i.response.send_message("❌ No active campaign!", ephemeral=True)
        return
    rate = await get_rate()
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT u.username, COALESCE(SUM(c.views),0) as tv, COUNT(c.id) as tc FROM clips c JOIN users u ON c.user_id = u.user_id WHERE c.campaign_id = $1 GROUP BY u.username ORDER BY tv DESC LIMIT 15", str(camp["id"]))
    if not rows:
        await i.response.send_message("📊 No submissions yet!", ephemeral=True)
        return
    m = ["🥇","🥈","🥉"]
    t = ""
    for idx, r in enumerate(rows):
        rank = m[idx] if idx < 3 else f"**{idx+1}.**"
        t += f"{rank} **{r['username']}** — {int(r['tv']):,} views ({int(r['tc'])} posts)\n"
    await i.response.send_message(embed=emb(f"🏆 {camp['name']} Leaderboard", t))

@bot.tree.command(name="endcampaign", description="[Admin] End campaign")
@app_commands.checks.has_permissions(administrator=True)
async def s_endcampaign(i: discord.Interaction):
    pool = await get_db()
    async with pool.acquire() as c:
        camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(i.channel.id))
        if not camp:
            await i.response.send_message("❌ No active campaign!", ephemeral=True)
            return
        await c.execute("UPDATE campaigns SET active=FALSE WHERE id=$1", camp["id"])
    await i.response.send_message(embed=emb(f"🛑 {camp['name']} — Ended", "Submissions closed."))

@bot.tree.command(name="setlimit", description="[Admin] Set daily post limit")
@app_commands.checks.has_permissions(administrator=True)
async def s_setlimit(i: discord.Interaction, limit: int):
    pool = await get_db()
    async with pool.acquire() as c:
        camp = await c.fetchrow("SELECT * FROM campaigns WHERE channel_id=$1 AND active=TRUE", str(i.channel.id))
        if not camp:
            await i.response.send_message("❌ No active campaign!", ephemeral=True)
            return
        await c.execute("UPDATE campaigns SET daily_limit=$1 WHERE id=$2", limit, camp["id"])
    await i.response.send_message(embed=emb("✅ Limit Updated", f"**{limit}** posts/day"))

@bot.tree.command(name="ban", description="[Admin] Ban user")
@app_commands.checks.has_permissions(administrator=True)
async def s_ban(i: discord.Interaction, user: discord.User, reason: str = ""):
    pool = await get_db()
    async with pool.acquire() as c:
        try:
            await c.execute("INSERT INTO bans(user_id,reason,banned_by) VALUES($1,$2,$3)", str(user.id), reason, str(i.user.id))
        except:
            await i.response.send_message("⚠️ Already banned!", ephemeral=True)
            return
    await i.response.send_message(embed=emb("🚫 Banned", f"{user.mention}\nReason: {reason or '—'}"))
    try:
        await user.send(embed=emb("🚫 You have been banned", f"Reason: {reason or '—'}\nContact support if this is a mistake."))
    except:
        pass

@bot.tree.command(name="unban", description="[Admin] Unban user")
@app_commands.checks.has_permissions(administrator=True)
async def s_unban(i: discord.Interaction, user: discord.User):
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("DELETE FROM bans WHERE user_id=$1", str(user.id))
    await i.response.send_message(embed=emb("✅ Unbanned", f"{user.mention}"))

@bot.tree.command(name="banlist", description="[Admin] Show banned users")
@app_commands.checks.has_permissions(administrator=True)
async def s_banlist(i: discord.Interaction):
    pool = await get_db()
    async with pool.acquire() as c:
        bans = await c.fetch("SELECT * FROM bans ORDER BY created_at DESC")
    if not bans:
        await i.response.send_message("✅ No bans!", ephemeral=True)
        return
    t = "\n".join(f"• <@{b['user_id']}> — {b['reason'] or '—'}" for b in bans)
    await i.response.send_message(embed=emb("🚫 Banned Users", t))

@bot.tree.command(name="sendpayout", description="[Admin] Send payout")
@app_commands.checks.has_permissions(administrator=True)
async def s_sendpayout(i: discord.Interaction, user: discord.User, amount: float, note: str = ""):
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO payouts(user_id,amount,status,admin_id,note) VALUES($1,$2,'paid',$3,$4)", str(user.id), amount, str(i.user.id), note)
        await c.execute("UPDATE clips SET status='paid' WHERE user_id=$1 AND status IN ('pending','tracking','under_review')", str(user.id))
    await i.response.send_message(embed=emb("💸 Payout Sent!", f"**{user.mention}** — ${amount:.2f}\nNote: {note or '—'}"))
    try:
        await user.send(embed=emb("💸 You've been paid!", f"**${amount:.2f}**\nNote: {note or '—'}\n\nKeep clipping! 🎉"))
    except:
        pass

@bot.tree.command(name="pendingpayouts", description="[Admin] Pending payouts")
@app_commands.checks.has_permissions(administrator=True)
async def s_pendingpayouts(i: discord.Interaction):
    rate = await get_rate()
    pool = await get_db()
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT u.user_id,u.username,u.payment_method,COALESCE(SUM(c.views),0) as tv FROM users u JOIN clips c ON u.user_id=c.user_id WHERE c.status IN ('pending','tracking','under_review') GROUP BY u.user_id,u.username,u.payment_method HAVING SUM(c.views)>0 ORDER BY tv DESC")
    if not rows:
        await i.response.send_message("✅ No pending!", ephemeral=True)
        return
    t = ""
    total = 0
    for r in rows:
        amt = int(r["tv"]) * rate
        total += amt
        t += f"• **{r['username']}** — ${amt:.2f} [{r['payment_method'] or '—'}]\n"
    e = emb("⏳ Pending Payouts", t)
    e.add_field(name="💰 Total", value=f"**${total:.2f}**", inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="payouthistory", description="[Admin] Payout history")
@app_commands.checks.has_permissions(administrator=True)
async def s_payouthistory(i: discord.Interaction, user: discord.User = None):
    pool = await get_db()
    async with pool.acquire() as c:
        if user:
            payouts = await c.fetch("SELECT * FROM payouts WHERE user_id=$1 ORDER BY created_at DESC LIMIT 20", str(user.id))
        else:
            payouts = await c.fetch("SELECT * FROM payouts ORDER BY created_at DESC LIMIT 20")
    if not payouts:
        await i.response.send_message("📋 No payouts!", ephemeral=True)
        return
    t = ""
    total = 0
    for p in payouts:
        t += f"• <@{p['user_id']}> — **${p['amount']:.2f}** {p['note'] or ''}\n"
        total += p["amount"]
    e = emb("💸 Payout History", t)
    e.add_field(name="💰 Total", value=f"**${total:.2f}**", inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="setrate", description="[Admin] Set payment rate")
@app_commands.checks.has_permissions(administrator=True)
async def s_rate(i: discord.Interaction, rate: float):
    pool = await get_db()
    async with pool.acquire() as c:
        await c.execute("UPDATE settings SET value=$1 WHERE key='payment_rate'", str(rate))
    await i.response.send_message(embed=emb("✅ Rate Updated", f"${rate}/view"))

@bot.tree.command(name="allusers", description="[Admin] All users")
@app_commands.checks.has_permissions(administrator=True)
async def s_all(i: discord.Interaction):
    d = await get_leaderboard()
    if not d:
        await i.response.send_message("❌ None!", ephemeral=True)
        return
    t = "\n".join(f"• **{n}** — ${e:.2f} ({v:,} views, {cl} posts)" for n,e,v,cl in d)
    await i.response.send_message(embed=emb("👥 Users", t))

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
    tier = TIER_NAMES.get(u["tier"], "⚪ Unranked")
    e = discord.Embed(title=f"👤 {user.name}", color=MAIN_COLOR)
    e.set_thumbnail(url=user.display_avatar.url if user.display_avatar else None)
    e.add_field(name="Status", value="✅" if u["setup_complete"] else "⚠️", inline=True)
    e.add_field(name="Tier", value=tier, inline=True)
    e.add_field(name="Posts", value=str(len(clips)), inline=True)
    e.add_field(name="Views", value=f"{tv:,}", inline=True)
    e.add_field(name="Earnings", value=f"${tv*rate:.2f}", inline=True)
    e.add_field(name="Country", value=u["country"] or "—", inline=True)
    e.add_field(name="Payment", value=u["payment_method"] or "—", inline=True)
    if u["payment_details"]:
        e.add_field(name="Details", value=f"`{u['payment_details']}`", inline=False)
    if accs:
        e.add_field(name="Socials", value="\n".join(f"{PLATFORM_INFO.get(a['platform'],{}).get('emoji','🔗')} `@{a['platform_username']}` {'✅' if a['verified'] else '⏳'}" for a in accs), inline=False)
    ft(e)
    await i.response.send_message(embed=e)

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
    await i.response.send_message(embed=emb(f"✅ Clip #{clip_id} Approved"))

@bot.tree.command(name="announce", description="[Admin] DM all users")
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
            await user.send(embed=emb(f"📢 {title}", message))
            sent += 1
        except:
            failed += 1
    await i.followup.send(f"✅ Sent: {sent} | Failed: {failed}", ephemeral=True)

@bot.tree.command(name="dmuser", description="[Admin] DM a user")
@app_commands.checks.has_permissions(administrator=True)
async def s_dmuser(i: discord.Interaction, user: discord.User, message: str):
    try:
        await user.send(embed=emb("📬 Message from Clip Forge", message))
        await i.response.send_message(f"✅ DM sent to {user.mention}!", ephemeral=True)
    except:
        await i.response.send_message(f"❌ Can't DM {user.mention}.", ephemeral=True)

@bot.tree.command(name="embed", description="[Admin] Create custom embed")
@app_commands.checks.has_permissions(administrator=True)
async def s_embed(i: discord.Interaction):
    await i.response.send_modal(EmbedCreatorModal())

class EmbedCreatorModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Create Custom Embed")
        self.embed_title = discord.ui.TextInput(label="Title", required=False, max_length=256)
        self.embed_desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=True, max_length=4000)
        self.embed_color = discord.ui.TextInput(label="Color hex (default: 00D26A)", required=False, max_length=7, default="00D26A")
        self.embed_image = discord.ui.TextInput(label="Image URL (optional)", required=False, max_length=500)
        self.embed_ft = discord.ui.TextInput(label="Footer (optional)", required=False, max_length=200)
        self.add_item(self.embed_title)
        self.add_item(self.embed_desc)
        self.add_item(self.embed_color)
        self.add_item(self.embed_image)
        self.add_item(self.embed_ft)

    async def on_submit(self, interaction: discord.Interaction):
        cs = self.embed_color.value.strip().lstrip("#")
        try:
            color = int(cs, 16) if cs else MAIN_COLOR
        except:
            color = MAIN_COLOR
        desc = self.embed_desc.value.replace("\\n", "\n")
        e = discord.Embed(title=self.embed_title.value or None, description=desc, color=color)
        img = self.embed_image.value.strip()
        if img and img.startswith("http"):
            e.set_image(url=img)
        f = self.embed_ft.value.strip()
        e.set_footer(text=f or FOOTER)
        await interaction.response.send_message("**Preview:**", embed=e, view=EmbedPreviewView(e), ephemeral=True)

class EmbedPreviewView(discord.ui.View):
    def __init__(self, embed):
        super().__init__(timeout=300)
        self.embed = embed
    @discord.ui.button(label="✅ Post", style=discord.ButtonStyle.success)
    async def post(self, i: discord.Interaction, b):
        await i.channel.send(embed=self.embed)
        await i.response.edit_message(content="✅ Posted!", view=None)
    @discord.ui.button(label="✏️ Retry", style=discord.ButtonStyle.primary)
    async def edit(self, i: discord.Interaction, b):
        await i.response.send_modal(EmbedCreatorModal())
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, i: discord.Interaction, b):
        await i.response.edit_message(content="❌ Cancelled.", view=None)

@bot.tree.command(name="colors", description="[Admin] Color codes")
@app_commands.checks.has_permissions(administrator=True)
async def s_colors(i: discord.Interaction):
    await i.response.send_message(embed=emb("🎨 Color Codes", "`FF0000` 🔴 Red\n`FF8C00` 🟠 Orange\n`FFD700` 🟡 Gold\n`00D26A` 🟢 Green\n`00FFFF` 🔵 Cyan\n`0099FF` 🔵 Blue\n`7B68EE` 🟣 Purple\n`FF69B4` 🩷 Pink\n`2B2D31` ⚫ Discord Dark\n`FFFFFF` ⚪ White"), ephemeral=True)

@bot.tree.command(name="help", description="[Admin] All commands")
@app_commands.checks.has_permissions(administrator=True)
async def s_help(i: discord.Interaction):
    await i.response.send_message(embed=build_help(), ephemeral=True)

# ═══════════════ SUGGESTIONS ═══════════════

class SuggestionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💡 Submit Suggestion", style=discord.ButtonStyle.success, custom_id="p_suggest")
    async def suggest(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SuggestionModal())

class SuggestionModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Submit a Suggestion")
        self.suggestion = discord.ui.TextInput(
            label="Your suggestion",
            placeholder="What would make Clip Forge better?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000
        )
        self.add_item(self.suggestion)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="💡 New Suggestion",
            description=self.suggestion.value,
            color=0xFFD700
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text=f"From {interaction.user.name} • React to vote!")

        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

        await interaction.response.send_message("✅ Suggestion submitted! Others can vote on it.", ephemeral=True)

@bot.tree.command(name="postsuggestions", description="[Admin] Post suggestions panel")
@app_commands.checks.has_permissions(administrator=True)
async def s_postsuggestions(i: discord.Interaction):
    embed = discord.Embed(
        title="💡 Suggestions",
        description=(
            "Have an idea to make Clip Forge better?\n\n"
            "Click the button below to submit your suggestion. "
            "Other members can vote with 👍 or 👎.\n\n"
            "**Good suggestions include:**\n"
            "• New features you'd like to see\n"
            "• Campaign improvements\n"
            "• Server improvements\n"
            "• Payment system ideas\n"
            "• Anything that helps the community\n\n"
            "Top voted suggestions will be reviewed by staff! ⭐"
        ),
        color=0xFFD700
    )
    footer(embed)
    await i.channel.send(embed=embed, view=SuggestionView())
    await i.response.send_message("✅ Suggestions panel posted!", ephemeral=True)

# ═══════════════ RULES / FAQ / GUIDE ═══════════════

@bot.tree.command(name="postrules", description="[Admin] Post all server rules")
@app_commands.checks.has_permissions(administrator=True)
async def s_postrules(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    ch = i.channel
    c = 0xFF4757

    e1 = discord.Embed(title="📜 Clip Forge — Terms of Service & Rules", description=(
        "By joining Clip Forge, you agree to follow these guidelines, "
        "[Discord's Terms of Service](https://discord.com/terms), and our own Terms of Service.\n\n"
        "1. **Be Respectful**\n"
        "Treat everyone kindly and fairly, regardless of background, beliefs, or opinions. "
        "Harassment, bullying, or discrimination based on race, ethnicity, gender, disability, "
        "or any personal trait is strictly forbidden and will lead to immediate consequences.\n\n"
        "2. **Keep It Safe and Friendly**\n"
        "Sharing explicit, graphic, violent, or NSFW content is prohibited. "
        "All content must be suitable for community members of all ages.\n\n"
        "3. **No Fake Engagement or Botted Views**\n"
        "Our system detects fake engagement and botted views in campaigns. If detected, "
        "it will result in an immediate ban from all campaigns without warning. You are not "
        "allowed to artificially boost views in any way, including paid ads on your own clips.\n\n"
        "4. **No Spam or Disruptions**\n"
        "Avoid sending repetitive, excessive, or irrelevant messages that disrupt "
        "conversations or server activities.\n\n"
        "5. **No Advertising or Self-Promotion**\n"
        "Do not promote your business, service, product, or other Discord servers anywhere "
        "in Clip Forge, including direct messages, without explicit permission from staff. "
        "Unauthorized promotion results in an immediate ban."
    ), color=c)
    footer(e1)
    await ch.send(embed=e1)

    e2 = discord.Embed(description=(
        "6. **Clickbait Within Limits**\n"
        "Clickbait tactics are permitted to boost engagement, but clips must never portray "
        "the client (brand, company, artist, creator) negatively or harm their reputation. "
        "Always ensure your content maintains a positive and respectful representation.\n\n"
        "7. **Respect Privacy**\n"
        "Never share personal or private information about others without their explicit consent. "
        "This includes real names, addresses, phone numbers, or any identifying details.\n\n"
        "8. **No Illegal Activities**\n"
        "Do not discuss, encourage, or engage in any illegal activities including hacking, "
        "doxing, or actions violating real-world laws.\n\n"
        "9. **No Raiding or Mass Reporting**\n"
        "Planning, inciting, or participating in raids, or mass reporting of this or other "
        "Discord servers or clipping pages is strictly prohibited and will result in immediate bans.\n\n"
        "10. **No Impersonation**\n"
        "Impersonating staff members or other community members is prohibited and will result "
        "in immediate action."
    ), color=c)
    await ch.send(embed=e2)

    e3 = discord.Embed(description=(
        "11. **Clip Rejection Policy**\n"
        "Both Clip Forge and our clients reserve the right to approve or reject any submitted "
        "clip at our sole discretion. Approval is not final — a clip's verdict may be changed. "
        "It is your responsibility to follow all campaign requirements and guidelines. "
        "Only clips with a minimum engagement rate of 0.5% are eligible for approval.\n\n"
        "12. **Keep Clips Live for 30 Days After Payment**\n"
        "Once paid, your clips must stay live for **at least 30 days**. This helps clients "
        "measure campaign impact and protects the integrity of the promotion. Taking clips "
        "down early may result in bans or withheld access to future campaigns.\n\n"
        "13. **Mark Clips as Paid Promotion**\n"
        "All clips must follow **FTC guidelines** and be clearly marked as paid promotions "
        "where required (e.g. using TikTok's branded content tools or writing "
        '"ad"/"paid partnership" in the caption).\n\n'
        "14. **Campaign Payment Accuracy**\n"
        "During an active campaign, payment progress and percentages shown are estimates and "
        "may not always be 100% accurate in real time. At campaign close, the final payment "
        "is locked based on the client's actual budget. This does not remove money already "
        "paid — it only removes projected earnings that exceeded the budget."
    ), color=c)
    await ch.send(embed=e3)

    e4 = discord.Embed(description=(
        "15. **One Account Per Person**\n"
        "You are allowed only **one Discord account** linked to Clip Forge. Using alternate "
        "accounts to bypass bans, earn extra, or manipulate campaigns will result in a "
        "permanent ban across all accounts. Each social media account can only be connected "
        "to one Discord account.\n\n"
        "16. **Staff Decisions are Final**\n"
        "Staff members reserve the right to enforce rules at their discretion and may ban "
        "any member at any time if deemed necessary.\n\n"
        "17. **Use Support Channels Appropriately**\n"
        "Always open a support ticket for any issues or questions. General campaign-related "
        "questions should be directed to the designated chat channels. Do not ask for help "
        "on checking tickets faster or getting a response. We try to get to everyone as fast "
        "as we can.\n\n"
        "18. **Terms of Service Updates & Enforcement**\n"
        "These Terms of Service may be updated, modified, or replaced at any time at Clip "
        "Forge's sole discretion. It is your responsibility to stay up to date with the "
        "latest version and any related guidelines we publish. These Terms of Service are "
        "final and enforceable. If you fail to follow campaign rules, guidelines, or these "
        "Terms of Service, we may be unable to pay you, regardless of prior participation.\n\n"
        "19. **Ask Staff if Unsure**\n"
        "If you are uncertain about any rule or whether specific content is allowed, "
        "please reach out to a staff member before posting.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**Last updated:** March 2026\n\n"
        "Thanks for helping keep Clip Forge a clean, compliant, and money-making machine. 🔥"
    ), color=c)
    footer(e4)
    await ch.send(embed=e4)

    await i.followup.send("✅ Rules posted!", ephemeral=True)


@bot.tree.command(name="postfaq", description="[Admin] Post campaign FAQs")
@app_commands.checks.has_permissions(administrator=True)
async def s_postfaq(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    ch = i.channel
    c = 0x0099FF

    e1 = discord.Embed(title="❓ Clip Forge — Campaign FAQs", description=(
        "**How do campaigns work?**\n"
        "We partner with artists, brands, and creators. You create short-form clips "
        "promoting their content on TikTok, Instagram, YouTube, or X. We track your views "
        "and pay you based on performance.\n\n"
        "**How do I join a campaign?**\n"
        "Go to any active campaign channel and click **Submit post**. Select your verified "
        "account and paste your clip URL. That's it.\n\n"
        "**How are views counted?**\n"
        "Staff reviews and updates views for each submission. Views are tracked from the "
        "moment you submit your post.\n\n"
        "**When do I get paid?**\n"
        "Payouts are processed after campaign review. You'll receive a DM when payment is sent.\n\n"
        "**What's the payment rate?**\n"
        "Each campaign has its own rate (e.g. $2 per 1,000 views). Check the campaign "
        "announcement for details."
    ), color=c)
    footer(e1)
    await ch.send(embed=e1)

    e2 = discord.Embed(description=(
        "**Can I submit the same clip to multiple campaigns?**\n"
        "No. Each clip URL can only be submitted once across all campaigns.\n\n"
        "**Can I submit multiple clips to one campaign?**\n"
        "Yes, up to the daily limit set by each campaign.\n\n"
        "**What platforms are accepted?**\n"
        "YouTube, TikTok, Instagram, and X (Twitter). Each campaign may specify which "
        "platforms are allowed.\n\n"
        "**My views aren't updating?**\n"
        "Views are updated by staff. If you think there's an error, open a support ticket.\n\n"
        "**Can I delete my clip after getting paid?**\n"
        "No. Clips must stay live for at least **30 days** after payment. Removing clips "
        "early may result in bans.\n\n"
        "**What if my clip gets rejected?**\n"
        "If your clip is rejected, open a support ticket to understand why. "
        "Staff will review and guide you on what to fix before resubmitting.\n\n"
        "**How do I connect my social accounts?**\n"
        "Go to #connect-socials → Click **Link Account** → Follow the verification steps.\n\n"
        "**Still have questions?**\n"
        "Open a support ticket and our team will help you out!"
    ), color=c)
    footer(e2)
    await ch.send(embed=e2)

    await i.followup.send("✅ FAQs posted!", ephemeral=True)


@bot.tree.command(name="postguide", description="[Admin] Post getting started guide")
@app_commands.checks.has_permissions(administrator=True)
async def s_postguide(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    ch = i.channel
    c = 0x00FFFF

    e1 = discord.Embed(title="🔥 Clip Forge — Getting Started Guide", description=(
        "Welcome to Clip Forge! Here's how to set up your account and start earning.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**Step 1 — Connect Your Socials** 🔗\n"
        "Head to **#connect-socials** and click **Link Account**. Choose your platform "
        "(YouTube, TikTok, Instagram, or X), enter your username and profile URL, "
        "then verify by adding a code to your bio. Once verified, your account is connected.\n\n"
        "**Step 2 — Complete Account Setup** ⚡\n"
        "Go to **#your-profile** and click **Setup**. Select your country and choose your "
        "preferred payment method (PayPal, UPI, Bank Transfer, or Crypto). "
        "This is where your earnings will be sent.\n\n"
        "**Step 3 — Join Active Campaigns** 🎯\n"
        "Check the active campaign channels. Read the campaign details — pay rate, platform, "
        "and guidelines. Click **Submit post** and paste your clip URL to enter."
    ), color=c)
    footer(e1)
    await ch.send(embed=e1)

    e2 = discord.Embed(description=(
        "**Step 4 — Create & Post Clips** 📹\n"
        "Create engaging short-form content based on the campaign brief. Post it on the "
        "required platform. Submit the link right after publishing to ensure all views "
        "count towards your rewards.\n\n"
        "**Step 5 — Track Your Earnings** 📊\n"
        "Go to **#your-profile** and click **Profile** to see your stats, connected accounts, "
        "and tier. Click **Earnings** to see your total, pending, and paid amounts. "
        "In any campaign, click **Stats** for a detailed breakdown.\n\n"
        "**Step 6 — Get Paid** 💸\n"
        "Once your views are verified and the campaign is reviewed, admin will process "
        "your payout. You'll receive a DM confirmation when payment is sent.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**📌 Where to Go:**\n"
        "🔗 **#connect-socials** — Link & verify your accounts\n"
        "👤 **#your-profile** — View profile, earnings, setup\n"
        "🎖️ **#tier-verification** — Check & verify your tier\n"
        "🎯 **Campaign channels** — Submit clips & earn\n"
        "🎫 **#support** — Open a ticket if you need help\n\n"
        "Everything works with **buttons** — just click and follow the steps! 🚀"
    ), color=c)
    footer(e2)
    await ch.send(embed=e2)

    await i.followup.send("✅ Guide posted!", ephemeral=True)


# ═══════════════ VIEW MANAGEMENT ═══════════════

@bot.tree.command(name="updateclip", description="[Admin] Update views on a clip")
@app_commands.checks.has_permissions(administrator=True)
async def s_updateclip(i: discord.Interaction, clip_id: int, views: int):
    pool = await get_db()
    rate = await get_rate()
    async with pool.acquire() as c:
        cl = await c.fetchrow("SELECT * FROM clips WHERE id=$1", clip_id)
        if not cl:
            await i.response.send_message("❌ Clip not found!", ephemeral=True)
            return
        await c.execute("UPDATE clips SET views=$1,earnings=$2,last_checked=NOW() WHERE id=$3", views, views*rate, clip_id)
    await i.response.send_message(embed=discord.Embed(title="✅ Views Updated", description=f"Clip **#{clip_id}** → **{views:,}** views (${views*rate:.2f})", color=GREEN))

@bot.tree.command(name="updateviews", description="[Admin] Bulk update all clips for a user")
@app_commands.checks.has_permissions(administrator=True)
async def s_updateviews(i: discord.Interaction, user: discord.User, views_per_clip: int):
    pool = await get_db()
    rate = await get_rate()
    async with pool.acquire() as c:
        clips = await c.fetch("SELECT * FROM clips WHERE user_id=$1", str(user.id))
        if not clips:
            await i.response.send_message(f"❌ No clips for {user.mention}!", ephemeral=True)
            return
        for cl in clips:
            await c.execute("UPDATE clips SET views=$1,earnings=$2,last_checked=NOW() WHERE id=$3", views_per_clip, views_per_clip*rate, cl["id"])
    total = views_per_clip * len(clips)
    await i.response.send_message(embed=discord.Embed(title="✅ Views Updated", description=f"**User:** {user.mention}\n**Clips:** {len(clips)}\n**Views each:** {views_per_clip:,}\n**Total views:** {total:,}\n**Earnings:** ${total*rate:.2f}", color=GREEN))

@bot.tree.command(name="listclips", description="[Admin] List all clips for a user")
@app_commands.checks.has_permissions(administrator=True)
async def s_listclips(i: discord.Interaction, user: discord.User):
    clips = await get_clips(str(user.id))
    if not clips:
        await i.response.send_message(f"❌ No clips for {user.mention}!", ephemeral=True)
        return
    rate = await get_rate()
    t = ""
    for cl in clips[:20]:
        e = PLATFORM_INFO.get(cl["platform"],{}).get("emoji","🔗")
        s = "✅" if cl["status"]=="paid" else "⏳" if cl["status"]=="pending" else "🔍"
        t += f"**#{cl['id']}** {e} {s} {cl['views']:,} views — ${cl['views']*rate:.2f}\n`{cl['url'][:50]}`\n"
    embed = discord.Embed(title=f"📋 {user.name}'s Clips", description=t, color=DARK_BLUE)
    footer(embed)
    await i.response.send_message(embed=embed)

# ═══════════════ LEGACY ═══════════════

@bot.command(name="help")
@commands.has_permissions(administrator=True)
async def c_help(ctx):
    await ctx.send(embed=build_help())

# ═══════════════ START ═══════════════

if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN not found!")
