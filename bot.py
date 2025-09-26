import discord
from discord.ext import commands, tasks
import asyncio
import datetime

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix='!', intents=intents)

# -------------------------
# Data Stores
# -------------------------
study_time = {}
current_sessions = {}
rooms = {}  # channel_id : owner_id
focus_rooms = {}
next_room_num = 1
next_focus_room_num = 1
JOIN_CHANNEL_NAME = "Join to Create"
JOIN_FOCUS_CHANNEL_NAME = "Join Focused Study"
pomodoro_sessions = {}

sessions_count = {}
session_history = {}
last_session_date = {}
goals = {}
current_streak = {}

# -------------------------
# Helper Functions
# -------------------------
def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m" if h > 0 else f"{m}m"

def get_progress_bar(p, l=10):
    filled = int(p / 100 * l)
    return "█" * filled + "░" * (l - filled)

async def is_owner(ctx):
    if not ctx.author.voice:
        await ctx.send("Join a room first!")
        return False
    vc = ctx.author.voice.channel
    if vc.id in rooms and rooms[vc.id] == ctx.author.id:
        return True
    elif vc.id in focus_rooms and focus_rooms[vc.id] == ctx.author.id:
        return True
    await ctx.send("You are not the owner of this room!")
    return False

# -------------------------
# Events
# -------------------------
@bot.event
async def on_ready():
    print(f"{bot.user} is online!")

@bot.event
async def on_voice_state_update(member, before, after):
    global next_room_num
    if after.channel and after.channel.name == JOIN_CHANNEL_NAME:
        guild = member.guild
        category = after.channel.category
        if not category:
            print("Join category not found")
            return

        # Create default OPEN study room
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            member: discord.PermissionOverwrite(connect=True, manage_channels=True)
        }
        room_name = f"Study Room {next_room_num}"
        next_room_num += 1
        new_vc = await guild.create_voice_channel(room_name, overwrites=overwrites, category=category)
        rooms[new_vc.id] = member.id

        # Move member to new VC
        await member.move_to(new_vc)
        print(f"Created {room_name} for {member.display_name}")

# -------------------------
# Study Room Commands
# -------------------------
@bot.command(name='trust')
async def trust(ctx, user: discord.Member):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    await vc.set_permissions(user, connect=True, speak=True)
    await ctx.send(f"{user.mention} trusted to join your room!")

@bot.command(name='kick')
async def kick(ctx, user: discord.Member):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    await vc.set_permissions(user, overwrite=None)
    await ctx.send(f"{user.mention} kicked from your room!")

@bot.command(name='lock')
async def lock(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    await vc.set_permissions(ctx.guild.default_role, connect=False)
    await ctx.send("Room locked!")

@bot.command(name='unlock')
async def unlock(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    await vc.set_permissions(ctx.guild.default_role, connect=True, speak=True)
    await ctx.send("Room unlocked!")

@bot.command(name='delete')
async def delete_room(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    if vc.id in rooms:
        del rooms[vc.id]
    elif vc.id in focus_rooms:
        del focus_rooms[vc.id]
    await vc.delete()
    await ctx.send("Your study room was deleted!")

# -------------------------
# Stats & Goals Commands
# -------------------------
@bot.command(name='stats')
async def stats(ctx):
    uid = ctx.author.id
    if uid not in study_time or study_time[uid] == 0:
        await ctx.send("No stats yet!")
        return
    t = study_time[uid]
    n = sessions_count.get(uid, 0)
    h = session_history.get(uid, [])
    a = sum(h) / max(len(h), 1) if h else 0
    td = datetime.date.today()
    st = current_streak.get(uid, 0)
    ld = last_session_date.get(uid, td - datetime.timedelta(days=1))
    if ld == td - datetime.timedelta(days=1):
        st += 1
    else:
        st = 1 if ld != td else st
    current_streak[uid] = st
    e = discord.Embed(title=f"{ctx.author.display_name}'s Stats", color=0x0099ff)
    e.add_field(name="Total", value=format_time(t), inline=True)
    e.add_field(name="Sessions", value=str(n), inline=True)
    e.add_field(name="Avg", value=format_time(a), inline=True)
    e.add_field(name="Streak", value=f"{st} days", inline=False)
    await ctx.send(embed=e)

@bot.command(name='goal')
async def goal(ctx, action=None, *, time_str=None):
    uid = ctx.author.id
    td = datetime.date.today()
    if action == 'set' and time_str:
        try:
            if 'h' in time_str.lower():
                t = int(float(time_str.lower().replace('h',''))*3600)
            elif 'm' in time_str.lower():
                t = int(float(time_str.lower().replace('m',''))*60)
            else:
                t = int(time_str)
            goals[uid] = {'target': t, 'current': 0, 'date': td}
            await ctx.send(f"Goal set: {format_time(t)}")
        except:
            await ctx.send("Invalid time format!")
        return
    if uid not in goals:
        await ctx.send("No goal! Use !goal set <time>")
        return
    d = goals[uid]
    if d['date'] != td:
        d['current'] = 0
    if action == 'clear':
        del goals[uid]
        await ctx.send("Goal cleared!")
        return
    r = max(0, d['target'] - d['current'])
    e = discord.Embed(title="Goal", color=0x00ff00)
    e.description = f"Target: {format_time(d['target'])}\nCurrent: {format_time(d['current'])}\nRemaining: {format_time(r)}"
    await ctx.send(embed=e)

@bot.command(name='progress')
async def progress(ctx):
    uid = ctx.author.id
    td = datetime.date.today()
    if uid not in goals:
        await ctx.send("No goal set!")
        return
    d = goals[uid]
    if d['date'] != td:
        d['current'] = 0
    p = min(100, (d['current']/d['target'])*100)
    b = get_progress_bar(p)
    r = max(0, d['target'] - d['current'])
    eta = format_time(r) if r>0 else "Done!"
    e = discord.Embed(title="Progress", color=0x0099ff)
    e.add_field(name="Bar", value=f"{b} {p:.0f}%", inline=False)
    e.add_field(name="Current/Target", value=f"{format_time(d['current'])} / {format_time(d['target'])}", inline=True)
    e.add_field(name="Remaining", value=eta, inline=True)
    if p>=100:
        e.description="Goal Achieved!"
    await ctx.send(embed=e)

# -------------------------
# Leaderboard
# -------------------------
@bot.command(name='leaderboard')
async def leaderboard(ctx):
    if not study_time:
        await ctx.send("No study time yet!")
        return
    top10 = sorted(study_time.items(), key=lambda x:x[1], reverse=True)[:10]
    e = discord.Embed(title="Leaderboard", color=0x00ff00)
    for i, (uid, secs) in enumerate(top10,1):
        user = bot.get_user(uid)
        uname = user.display_name if user else f'User {uid}'
        e.add_field(name=f"{i}. {uname}", value=format_time(secs), inline=False)
    await ctx.send(embed=e)

# -------------------------
# Pomodoro (Basic)
# -------------------------
class PomodoroView(discord.ui.View):
    def __init__(self, uid):
        super().__init__(timeout=None)
        self.uid = uid

    @discord.ui.button(label="Start Pomodoro", style=discord.ButtonStyle.green, emoji="▶️")
    async def start(self, interaction, button):
        if interaction.user.id != self.uid:
            await interaction.response.send_message("Only starter can use this!", ephemeral=True)
            return
        if self.uid in pomodoro_sessions:
            await interaction.response.send_message("Pomodoro already running!", ephemeral=True)
            return

        pomodoro_sessions[self.uid] = {'phase':'work','duration':25*60}
        await interaction.response.send_message("Pomodoro started: 25min work!", ephemeral=True)
        asyncio.create_task(self.run_pomodoro(interaction))

    async def run_pomodoro(self, interaction):
        data = pomodoro_sessions[self.uid]
        await asyncio.sleep(data['duration'])
        # switch to break
        pomodoro_sessions[self.uid] = {'phase':'break','duration':5*60}
        await interaction.followup.send("Work done! 5min break started!", ephemeral=True)
        await asyncio.sleep(5*60)
        del pomodoro_sessions[self.uid]
        await interaction.followup.send("Pomodoro finished!", ephemeral=True)

@bot.command(name='pomodoro')
async def pomodoro(ctx):
    view = PomodoroView(ctx.author.id)
    e = discord.Embed(title="Pomodoro Timer", description="25min work + 5min break", color=0x00ff00)
    await ctx.send(embed=e, view=view)

# -------------------------
# Run Bot
# -------------------------
import os
bot.run(os.getenv("DISCORD_TOKEN"))

