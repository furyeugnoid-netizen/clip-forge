import discord
from discord.ext import commands
import json
import os
from datetime import datetime

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

DATABASE_FILE = 'clip_forge_data.json'
PAYMENT_RATE = 0.001

CYAN = 0x00ffff
LIGHT_CYAN = 0x00d4ff
DARK_BLUE = 0x0099ff
DARK_BG = 0x0a0a14

def load_database():
    try:
        if os.path.exists(DATABASE_FILE):
            with open(DATABASE_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"users": {}, "clips": [], "payment_rate": PAYMENT_RATE, "total_paid": 0}

def save_database(data):
    try:
        with open(DATABASE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except:
        pass

db = load_database()

class ConnectSocialsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔗 Link Account", style=discord.ButtonStyle.primary, custom_id="link_account")
    async def link_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Use: `!linkaccount [platform] [@username]`\n\nExample: `!linkaccount youtube @MyChannel`\n\n**Supported platforms:** youtube, instagram, tiktok, x", ephemeral=True)

    @discord.ui.button(label="👥 View Accounts", style=discord.ButtonStyle.secondary, custom_id="view_accounts")
    async def view_accounts(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id in db["users"] and db["users"][user_id].get("accounts"):
            accounts = db["users"][user_id]["accounts"]
            text = "\n".join([f"• {platform}: {username}" for platform, username in accounts.items()])
            embed = discord.Embed(title="Your Linked Accounts", description=text or "No accounts linked yet", color=LIGHT_CYAN)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ No accounts linked yet. Use `!linkaccount` to add one.", ephemeral=True)

    @discord.ui.button(label="🌍 Verify Demographics", style=discord.ButtonStyle.success, custom_id="verify_demo")
    async def verify_demo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Demographics verification coming soon! ✨", ephemeral=True)

class YourAccountView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📈 Analytics", style=discord.ButtonStyle.primary, custom_id="analytics")
    async def analytics(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id not in db["users"]:
            await interaction.response.send_message("❌ No data yet. Submit a clip first!", ephemeral=True)
            return
        user = db["users"][user_id]
        total_views = sum(clip.get("views", 0) for clip in user.get("clips", []))
        earnings = total_views * db["payment_rate"]
        embed = discord.Embed(title="📈 Your Analytics", color=LIGHT_CYAN)
        embed.add_field(name="Total Clips", value=str(len(user.get("clips", []))), inline=True)
        embed.add_field(name="Total Views", value=str(total_views), inline=True)
        embed.add_field(name="Earnings", value=f"${earnings:.2f}", inline=True)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="💵 Payouts", style=discord.ButtonStyle.secondary, custom_id="payouts")
    async def payouts(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id not in db["users"]:
            await interaction.response.send_message("❌ No earnings yet!", ephemeral=True)
            return
        user = db["users"][user_id]
        total_views = sum(clip.get("views", 0) for clip in user.get("clips", []))
        earnings = total_views * db["payment_rate"]
        embed = discord.Embed(title="💵 Your Payouts", color=DARK_BLUE)
        embed.add_field(name="Pending Earnings", value=f"${earnings:.2f}", inline=False)
        embed.add_field(name="Status", value="✅ Ready to withdraw", inline=False)
        embed.add_field(name="Payment Rate", value=f"${db['payment_rate']} per view", inline=False)
        embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="👥 Social Accounts", style=discord.ButtonStyle.success, custom_id="social_accounts")
    async def social_accounts(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        if user_id in db["users"] and db["users"][user_id].get("accounts"):
            accounts = db["users"][user_id]["accounts"]
            text = "\n".join([f"• {platform.upper()}: {username}" for platform, username in accounts.items()])
            embed = discord.Embed(title="Your Linked Accounts", description=text or "No accounts linked", color=CYAN)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("❌ No accounts linked. Use `!linkaccount` first!", ephemeral=True)

@bot.event
async def on_ready():
    print(f'✅ Bot logged in as {bot.user}')

@bot.command(name='connect')
async def connect(ctx):
    embed = discord.Embed(title="🔗 Connect Your Socials", description="Link your accounts to start earning!", color=LIGHT_CYAN)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    await ctx.send(embed=embed, view=ConnectSocialsView())

@bot.command(name='account')
async def account(ctx):
    embed = discord.Embed(title="👤 Your Account", description="Manage your clips and earnings", color=LIGHT_CYAN)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    await ctx.send(embed=embed, view=YourAccountView())

@bot.command(name='linkaccount')
async def linkaccount(ctx, platform: str, username: str):
    user_id = str(ctx.author.id)
    valid_platforms = ["youtube", "instagram", "tiktok", "x"]
    if platform.lower() not in valid_platforms:
        await ctx.send(f"❌ Invalid platform. Use: {', '.join(valid_platforms)}")
        return
    if user_id not in db["users"]:
        db["users"][user_id] = {"username": ctx.author.name, "accounts": {}, "clips": []}
    db["users"][user_id]["accounts"][platform.lower()] = username
    save_database(db)
    embed = discord.Embed(title="✅ Account Linked", description=f"**{platform.upper()}**: {username}", color=CYAN)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    await ctx.send(embed=embed)

@bot.command(name='submitclip')
async def submitclip(ctx, platform: str, url: str, views: int):
    user_id = str(ctx.author.id)
    if user_id not in db["users"]:
        await ctx.send("❌ Please link an account first using `!linkaccount`")
        return
    clip = {"platform": platform.lower(), "url": url, "views": views, "submitted_at": datetime.now().isoformat(), "earnings": views * db["payment_rate"]}
    db["users"][user_id]["clips"].append(clip)
    save_database(db)
    embed = discord.Embed(title="✅ Clip Submitted", description=f"**Platform:** {platform.upper()}\n**Views:** {views:,}\n**Earnings:** ${clip['earnings']:.2f}", color=LIGHT_CYAN)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    await ctx.send(embed=embed)

@bot.command(name='leaderboard')
async def leaderboard(ctx):
    if not db["users"]:
        await ctx.send("❌ No users yet!")
        return
    earnings_list = []
    for user_id, user_data in db["users"].items():
        total_views = sum(clip.get("views", 0) for clip in user_data.get("clips", []))
        earnings = total_views * db["payment_rate"]
        earnings_list.append((user_data.get("username", "Unknown"), earnings, total_views))
    earnings_list.sort(key=lambda x: x[1], reverse=True)
    text = ""
    for i, (username, earnings, views) in enumerate(earnings_list[:10], 1):
        text += f"{i}. **{username}** - ${earnings:.2f} ({views:,} views)\n"
    embed = discord.Embed(title="🏆 Top Earners Leaderboard", description=text or "No earnings yet", color=DARK_BLUE)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    await ctx.send(embed=embed)

@bot.command(name='analytics')
async def analytics(ctx):
    user_id = str(ctx.author.id)
    if user_id not in db["users"]:
        await ctx.send("❌ No data yet!")
        return
    user = db["users"][user_id]
    total_views = sum(clip.get("views", 0) for clip in user.get("clips", []))
    earnings = total_views * db["payment_rate"]
    embed = discord.Embed(title="📈 Your Analytics", color=LIGHT_CYAN)
    embed.add_field(name="Total Clips", value=str(len(user.get("clips", []))), inline=True)
    embed.add_field(name="Total Views", value=f"{total_views:,}", inline=True)
    embed.add_field(name="Earnings", value=f"${earnings:.2f}", inline=True)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    await ctx.send(embed=embed)

@bot.command(name='setpaymentrate')
@commands.has_permissions(administrator=True)
async def setpaymentrate(ctx, rate: float):
    db["payment_rate"] = rate
    save_database(db)
    embed = discord.Embed(title="✅ Payment Rate Updated", description=f"New rate: ${rate} per view", color=CYAN)
    await ctx.send(embed=embed)

@bot.command(name='allusers')
@commands.has_permissions(administrator=True)
async def allusers(ctx):
    if not db["users"]:
        await ctx.send("❌ No users yet")
        return
    text = ""
    for user_id, user_data in db["users"].items():
        total_views = sum(clip.get("views", 0) for clip in user_data.get("clips", []))
        earnings = total_views * db["payment_rate"]
        text += f"• **{user_data.get('username', 'Unknown')}** - ${earnings:.2f}\n"
    embed = discord.Embed(title="👥 All Users", description=text, color=DARK_BLUE)
    await ctx.send(embed=embed)

@bot.command(name='userinfo')
@commands.has_permissions(administrator=True)
async def userinfo(ctx, user: discord.User):
    user_id = str(user.id)
    if user_id not in db["users"]:
        await ctx.send(f"❌ No data for {user.mention}")
        return
    user_data = db["users"][user_id]
    total_views = sum(clip.get("views", 0) for clip in user_data.get("clips", []))
    earnings = total_views * db["payment_rate"]
    embed = discord.Embed(title=f"👤 {user.name}'s Info", color=LIGHT_CYAN)
    embed.add_field(name="Clips", value=len(user_data.get("clips", [])), inline=True)
    embed.add_field(name="Total Views", value=f"{total_views:,}", inline=True)
    embed.add_field(name="Earnings", value=f"${earnings:.2f}", inline=True)
    if user_data.get("accounts"):
        accounts = "\n".join([f"• {p.upper()}: {u}" for p, u in user_data["accounts"].items()])
        embed.add_field(name="Linked Accounts", value=accounts, inline=False)
    await ctx.send(embed=embed)

@bot.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(title="📚 Clip Forge Commands", description="Here are all available commands:", color=LIGHT_CYAN)
    embed.add_field(name="👤 User Commands", value="`!connect` - Link your social accounts\n`!account` - View your account & earnings\n`!linkaccount [platform] [username]` - Link a social account\n`!submitclip [platform] [url] [views]` - Submit a clip\n`!analytics` - View your analytics\n`!leaderboard` - Top earners\n", inline=False)
    embed.add_field(name="🔧 Admin Commands", value="`!setpaymentrate [amount]` - Set payment rate\n`!allusers` - List all users\n`!userinfo [user]` - Get user info\n", inline=False)
    embed.set_footer(text="Powered by ❤️ & ☕ | Clip Forge")
    await ctx.send(embed=embed)

TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN not found!")
