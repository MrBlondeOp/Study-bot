import discord
from discord.ext import commands
import asyncio
import datetime
import time
import os
from discord.ui import Button, View

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

study_time = {}
current_sessions = {}
rooms = {}
focus_rooms = {}
study_category = None
focus_category = None
next_room_num = 1
next_focus_room_num = 1
JOIN_CHANNEL_NAME = "Join to Create"
JOIN_FOCUS_CHANNEL_NAME = "Join Focused Study"
pomodoro_sessions = {}
delete_timers = {}

sessions_count = {}
session_history = {}
last_session_date = {}
goals = {}
current_streak = {}

def format_time(s):
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    return f"{h}h {m}m" if h > 0 else f"{m}m"

def get_progress_bar(p, l=10):
    f = int(p / 100 * l)
    return "█" * f + "░" * (l - f)

@bot.event
async def on_ready():
    global study_category, focus_category, next_room_num, next_focus_room_num
    g = bot.guilds[0]
    study_category = discord.utils.get(g.categories, name='Study Rooms')
    if study_category:
        e = [ch for ch in study_category.voice_channels if ch.name.startswith('Study Room ') and ch.name.split()[-1].isdigit()]
        if e:
            n = [int(ch.name.split()[-1]) for ch in e]
            next_room_num = max(n) + 1
        else:
            next_room_num = 1
    else:
        print('No Study Rooms category.')
    focus_category = discord.utils.get(g.categories, name='Focus')
    if not focus_category:
        try:
            focus_category = await g.create_category('Focus')
        except:
            print('No perms for Focus.')
    focus_text = discord.utils.get(focus_category.text_channels, name='focus mode') if focus_category else None
    if not focus_text and focus_category:
        try:
            focus_text = await focus_category.create_text_channel('focus mode')
        except:
            print('No perms for focus mode.')
    if focus_text:
        e = discord.Embed(title="Focus Mode", description="Toggle to hide distractions.", color=0x00ff00)
        v = FocusView()
        await focus_text.send(embed=e, view=v)
    join_focus = discord.utils.get(focus_category.voice_channels, name=JOIN_FOCUS_CHANNEL_NAME) if focus_category else None
    if not join_focus and focus_category:
        try:
            await focus_category.create_voice_channel(JOIN_FOCUS_CHANNEL_NAME, overwrites={g.default_role: discord.PermissionOverwrite(connect=True)})
        except:
            print('No perms for Join Focused Study.')
    join_channel = discord.utils.get(g.voice_channels, name=JOIN_CHANNEL_NAME)
    if not join_channel:
        print('No Join to Create.')
    print(f'{bot.user} ready!')

@bot.command(name='leaderboard')
async def leaderboard(ctx):
    if not study_time:
        await ctx.send('No data!')
        return
    s = sorted(study_time.items(), key=lambda x: x[1], reverse=True)[:10]
    e = discord.Embed(title='Leaderboard', color=0x00ff00)
    for i, (uid, secs) in enumerate(s, 1):
        u = bot.get_user(uid)
        un = u.display_name if u else f'User {uid}'
        e.add_field(name=f'{i}. {un}', value=format_time(secs), inline=False)
    await ctx.send(embed=e)

@bot.command(name='stats')
async def stats(ctx):
    uid = ctx.author.id
    if uid not in study_time or study_time[uid] == 0:
        await ctx.send("No stats!")
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
                t = int(float(time_str.lower().replace('h', '')) * 3600)
            elif 'm' in time_str.lower():
                t = int(float(time_str.lower().replace('m', '')) * 60)
            else:
                t = int(time_str)
            goals[uid] = {'target': t, 'current': 0, 'date': td}
            await ctx.send(f"Goal: {format_time(t)}")
        except:
            await ctx.send("Invalid time!")
        return
    if uid not in goals:
        await ctx.send("No goal! Use !goal set <time>")
        return
    d = goals[uid]
    if d['date'] != td:
        d['current'] = 0
    if action == 'clear':
        del goals[uid]
        await ctx.send("Cleared!")
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
        await ctx.send("No goal!")
        return
    d = goals[uid]
    if d['date'] != td:
        d['current'] = 0
    p = min(100, (d['current'] / d['target']) * 100)
    b = get_progress_bar(p)
    r = max(0, d['target'] - d['current'])
    eta = format_time(r) if r > 0 else "Done!"
    e = discord.Embed(title="Progress", color=0x0099ff)
    e.add_field(name="Bar", value=f"{b} {p:.0f}%", inline=False)
    e.add_field(name="Current/Target", value=f"{format_time(d['current'])} / {format_time(d['target'])}", inline=True)
    e.add_field(name="Remaining", value=eta, inline=True)
    if p >= 100:
        e.description = "Achieved!"
    await ctx.send(embed=e)

class FocusView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Enable', style=discord.ButtonStyle.green, emoji='🎯')
    async def enable(self, i, b):
        g = i.guild
        u = i.user
        r = discord.utils.get(g.roles, name='Focus Mode')
        if not r:
            try:
                r = await g.create_role(name='Focus Mode', color=0x00ff00, permissions=discord.Permissions.none())
            except:
                await i.response.send_message("No perms!", ephemeral=True)
                return
        if r not in u.roles:
            await u.add_roles(r)
            await i.response.send_message("Enabled!", ephemeral=True)
        else:
            await i.response.send_message("Already enabled!", ephemeral=True)

    @discord.ui.button(label='Disable', style=discord.ButtonStyle.red, emoji='🔓')
    async def disable(self, i, b):
        g = i.guild
        u = i.user
        r = discord.utils.get(g.roles, name='Focus Mode')
        if r and r in u.roles:
            await u.remove_roles(r)
            await i.response.send_message("Disabled!", ephemeral=True)
        else:
            await i.response.send_message("Already disabled!", ephemeral=True)

async def is_owner(ctx):
    if not ctx.author.voice:
        await ctx.send("Join room!")
        return False
    vc = ctx.author.voice.channel
    if vc.category == study_category and vc.id in rooms:
        if ctx.author.id != rooms[vc.id]:
            await ctx.send("Owner only!")
            return False
    elif vc.category == focus_category and vc.id in focus_rooms:
        if ctx.author.id != focus_rooms[vc.id]:
            await ctx.send("Owner only!")
            return False
    else:
        await ctx.send("Not in room!")
        return False
    return True

@bot.command(name='trust')
async def trust(ctx, user: discord.Member):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    ow = discord.PermissionOverwrite(connect=True, speak=True)
    await vc.set_permissions(user, overwrite=ow)
    await ctx.send(f"{user.mention} trusted.")

@bot.command(name='kick')
async def kick(ctx, user: discord.Member):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    await vc.set_permissions(user, overwrite=None)
    await ctx.send(f"Kicked {user.mention}.")

@bot.command(name='lock')
async def lock(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    ow = discord.PermissionOverwrite(connect=False)
    await vc.set_permissions(ctx.guild.default_role, overwrite=ow)
    await ctx.send("Locked!")

@bot.command(name='unlock')
async def unlock(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    ow = discord.PermissionOverwrite(connect=True, speak=True)
    await vc.set_permissions(ctx.guild.default_role, overwrite=ow)
    await ctx.send("Unlocked!")

@bot.command(name='delete')
async def delete_room(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    if vc.id in rooms:
        del rooms[vc.id]
    elif vc.id in focus_rooms:
        del focus_rooms[vc.id]
    if vc.id in delete_timers:
        delete_timers[vc.id].cancel()
    await vc.delete()
    await ctx.send("Room deleted!")

@bot.command(name='pomodoro')
async def pomodoro(ctx):
    e = discord.Embed(title="Pomodoro", description="25min work + 5min break.", color=0x00ff00)
    v = PomodoroView(ctx.author.id)
    await ctx.send(embed=e, view=v)

class PomodoroView(View):
    def __init__(self, uid):
        super().__init__(timeout=None)
        self.uid = uid

    @discord.ui.button(label='Start', style=discord.ButtonStyle.green, emoji='▶️')
    async def start(self, i, b):
        if i.user.id != self.uid:
            await i.response.send_message("Only starter!", ephemeral=True)
            return
        if self.uid in pomodoro_sessions:
            await i.response.send_message("Already running!", ephemeral=True)
            return
        pomodoro_sessions[self.uid] = {'phase': 'work', 'duration': 25*60, 'channel': i.channel, 'message': i.message, 'paused': False, 'pause_time': 0}
        t = asyncio.create_task(pomodoro_timer(self.uid))
        pomodoro_sessions[self.uid]['task'] = t
        b.disabled = True
        await i.response.edit_message(view=self)
        await i.followup.send(f"{i.user.mention} 25min work! ⏰")

    @discord.ui.button(label='Pause', style=discord.ButtonStyle.blurple, emoji='⏸️')
    async def pause(self, i, b):
        if i.user.id != self.uid:
            return
        s = pomodoro_sessions.get(self.uid)
        if not s or s['paused']:
            await i.response.send_message("Not running!", ephemeral=True)
            return
        s['paused'] = True
        s['pause_time'] = time.time()
        b.label = 'Resume'
        b.emoji = '▶️'
        await i.response.edit_message(view=self)

    @discord.ui.button(label='Stop', style=discord.ButtonStyle.red, emoji='⏹️')
    async def stop(self, i, b):
        if i.user.id != self.uid:
            return
        s = pomodoro_sessions.get(self.uid)
        if s:
            s['task'].cancel()
            del pomodoro_sessions[self.uid]
            b.disabled = True
            await i.response.edit_message(view=self)
            await i.followup.send("Stopped!")

async def pomodoro_timer(uid):
    s = pomodoro_sessions[uid]
    c = s['channel']
    while True:
        ph = s['phase']
        d = s['duration']
        et = time.time() + d
        while time.time() < et:
            if s['paused']:
                await asyncio.sleep(1)
                et += time.time() - s['pause_time']
                s['pause_time'] = time.time()
                continue
            await asyncio.sleep(1)
        if ph == 'work':
            await c.send(f"{bot.get_user(uid).mention} Work done! 5min break ☕")
            s['phase'] = 'break'
            s['duration'] = 5 * 60
        else:
            await c.send(f"{bot.get_user(uid).mention} Break over! 25min work ⏰")
            s['phase'] = 'work'
            s['duration'] = 25 * 60

async def auto_delete(ch_id):
    await asyncio.sleep(300)
    ch = bot.get_channel(ch_id)
    if ch and len(ch.members) == 0:
        if ch_id in rooms:
            del rooms[ch_id]
        elif ch_id in focus_rooms:
            del focus_rooms[ch_id]
        await ch.delete()

@bot.event
async def on_voice_state_update(m, before, after):
    global next_room_num, next_focus_room_num
    if m == bot.user:
        return
    g = m.guild
    is_study = lambda ch: ch and ch.category == study_category and ch.name.startswith('Study Room ')
    is_focus = lambda ch: ch and ch.category == focus_category and ch.name.startswith('Focus Room ')
    td = datetime.date.today()
    uid = m.id
    if after.channel and (is_study(after.channel) or is_focus(after.channel)):
        if uid not in current_sessions:
            current_sessions[uid] = time.time()
            if uid not in session_history:
                session_history[uid] = []
            if uid not in sessions_count:
                sessions_count[uid] = 0
            if uid not in last_session_date:
                last_session_date[uid] = td
            if uid not in current_streak:
                current_streak[uid] = 0
    if before.channel and (is_study(before.channel) or is_focus(before.channel)) and uid in current_sessions:
        st = current_sessions.pop(uid)
        dur = time
bot.run(os.getenv("DISCORD_TOKEN"))
