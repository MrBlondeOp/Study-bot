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

# Storage
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

# Stats
sessions_count = {}
session_history = {}
last_session_date = {}
goals = {}
current_streak = {}

def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

def get_progress_bar(percentage, length=10):
    filled = int(percentage / 100 * length)
    return "█" * filled + "░" * (length - filled)

@bot.event
async def on_ready():
    global study_category, focus_category, next_room_num, next_focus_room_num
    guild = bot.guilds[0]
    
    study_category = discord.utils.get(guild.categories, name='Study Rooms')
    if study_category:
        existing_rooms = [ch for ch in study_category.voice_channels if ch.name.startswith('Study Room ') and ch.name.split()[-1].isdigit()]
        if existing_rooms:
            nums = [int(ch.name.split()[-1]) for ch in existing_rooms]
            next_room_num = max(nums) + 1
        else:
            next_room_num = 1
    else:
        print('No Study Rooms category - create manually.')
    
    focus_category = discord.utils.get(guild.categories, name='Focus')
    if not focus_category:
        try:
            focus_category = await guild.create_category('Focus')
        except:
            print('No perms for Focus.')
    
    focus_text = discord.utils.get(focus_category.text_channels, name='focus mode') if focus_category else None
    if not focus_text and focus_category:
        try:
            focus_text = await focus_category.create_text_channel('focus mode')
        except:
            print('No perms for focus mode.')
    
    if focus_text:
        embed = discord.Embed(title="Focus Mode", description="Toggle to hide distractions.", color=0x00ff00)
        view = FocusView()
        await focus_text.send(embed=embed, view=view)
    
    join_focus = discord.utils.get(focus_category.voice_channels, name=JOIN_FOCUS_CHANNEL_NAME) if focus_category else None
    if not join_focus and focus_category:
        try:
            await focus_category.create_voice_channel(JOIN_FOCUS_CHANNEL_NAME, overwrites={guild.default_role: discord.PermissionOverwrite(connect=True)})
        except:
            print('No perms for Join Focused Study.')
    
    join_channel = discord.utils.get(guild.voice_channels, name=JOIN_CHANNEL_NAME)
    if not join_channel:
        print('No Join to Create - create manually.')
    
    print(f'{bot.user} ready!')

@bot.command(name='leaderboard')
async def leaderboard(ctx):
    if not study_time:
        await ctx.send('No data!')
        return
    sorted_users = sorted(study_time.items(), key=lambda x: x[1], reverse=True)[:10]
    embed = discord.Embed(title='Leaderboard', color=0x00ff00)
    for i, (user_id, secs) in enumerate(sorted_users, 1):
        user = bot.get_user(user_id)
        username = user.display_name if user else f'User {user_id}'
        embed.add_field(name=f'{i}. {username}', value=format_time(secs), inline=False)
    await ctx.send(embed=embed)

@bot.command(name='stats')
async def stats(ctx):
    user_id = ctx.author.id
    if user_id not in study_time or study_time[user_id] == 0:
        await ctx.send("No stats!")
        return
    total = study_time[user_id]
    num = sessions_count.get(user_id, 0)
    history = session_history.get(user_id, [])
    avg = sum(history) / max(len(history), 1) if history else 0
    today = datetime.date.today()
    streak = current_streak.get(user_id, 0)
    last = last_session_date.get(user_id, today - datetime.timedelta(days=1))
    if last == today - datetime.timedelta(days=1):
        streak += 1
    else:
        streak = 1 if last != today else streak
    current_streak[user_id] = streak
    embed = discord.Embed(title=f"{ctx.author.display_name}'s Stats", color=0x0099ff)
    embed.add_field(name="Total", value=format_time(total), inline=True)
    embed.add_field(name="Sessions", value=str(num), inline=True)
    embed.add_field(name="Avg", value=format_time(avg), inline=True)
    embed.add_field(name="Streak", value=f"{streak} days", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='goal')
async def goal(ctx, action=None, *, time_str=None):
    user_id = ctx.author.id
    today = datetime.date.today()
    if action == 'set' and time_str:
        try:
            if 'h' in time_str.lower():
                target = int(float(time_str.lower().replace('h', '')) * 3600)
            elif 'm' in time_str.lower():
                target = int(float(time_str.lower().replace('m', '')) * 60)
            else:
                target = int(time_str)
            goals[user_id] = {'target': target, 'current': 0, 'date': today}
            await ctx.send(f"Goal: {format_time(target)}")
        except:
            await ctx.send("Invalid time!")
        return
    if user_id not in goals:
        await ctx.send("No goal! Use !goal set <time>")
        return
    data = goals[user_id]
    if data['date'] != today:
        data['current'] = 0
    if action == 'clear':
        del goals[user_id]
        await ctx.send("Cleared!")
        return
    remaining = max(0, data['target'] - data['current'])
    embed = discord.Embed(title="Goal", color=0x00ff00)
    embed.description = f"Target: {format_time(data['target'])}\nCurrent: {format_time(data['current'])}\nRemaining: {format_time(remaining)}"
    await ctx.send(embed=embed)

@bot.command(name='progress')
async def progress(ctx):
    user_id = ctx.author.id
    today = datetime.date.today()
    if user_id not in goals:
        await ctx.send("No goal!")
        return
    data = goals[user_id]
    if data['date'] != today:
        data['current'] = 0
    perc = min(100, (data['current'] / data['target']) * 100)
    bar = get_progress_bar(perc)
    remaining = max(0, data['target'] - data['current'])
    eta = format_time(remaining) if remaining > 0 else "Done!"
    embed = discord.Embed(title="Progress", color=0x0099ff)
    embed.add_field(name="Bar", value=f"{bar} {perc:.0f}%", inline=False)
    embed.add_field(name="Current/Target", value=f"{format_time(data['current'])} / {format_time(data['target'])}", inline=True)
    embed.add_field(name="Remaining", value=eta, inline=True)
    if perc >= 100:
        embed.description = "Achieved!"
    await ctx.send(embed=embed)

class FocusView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Enable', style=discord.ButtonStyle.green, emoji='🎯')
    async def enable(self, interaction, button):
        guild = interaction.guild
        user = interaction.user
        role = discord.utils.get(guild.roles, name='Focus Mode')
        if not role:
            try:
                role = await guild.create_role(name='Focus Mode', color=0x00ff00, permissions=discord.Permissions.none())
            except:
                await interaction.response.send_message("No perms!", ephemeral=True)
                return
        if role not in user.roles:
            await user.add_roles(role)
            await interaction.response.send_message("Enabled!", ephemeral=True)
        else:
            await interaction.response.send_message("Already enabled!", ephemeral=True)

    @discord.ui.button(label='Disable', style=discord.ButtonStyle.red, emoji='🔓')
    async def disable(self, interaction, button):
        guild = interaction.guild
        user = interaction.user
        role = discord.utils.get(guild.roles, name='Focus Mode')
        if role and role in user.roles:
            await user.remove_roles(role)
            await interaction.response.send_message("Disabled!", ephemeral=True)
        else:
            await interaction.response.send_message("Already disabled!", ephemeral=True)

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
    embed = discord.Embed(title="Pomodoro Timer", description="25min work + 5min break cycles.", color=0x00ff00)
    view = PomodoroView(ctx.author.id)
    await ctx.send(embed=embed, view=view)

class PomodoroView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label='Start', style=discord.ButtonStyle.green, emoji='▶️')
    async def start(self, interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only starter can control!", ephemeral=True)
            return
        if self.user_id in pomodoro_sessions:
            await interaction.response.send_message("Already running!", ephemeral=True)
            return
        pomodoro_sessions[self.user_id] = {'phase': 'work', 'duration': 25*60, 'channel': interaction.channel, 'message': interaction.message, 'paused': False, 'pause_time': 0}
        task = asyncio.create_task(pomodoro_timer(self.user_id))
        pomodoro_sessions[self.user_id]['task'] = task
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{interaction.user.mention} 25min work started! ⏰")

    @discord.ui.button(label='Pause', style=discord.ButtonStyle.blurple, emoji='⏸️')
    async def pause(self, interaction, button):
        if interaction.user.id != self.user_id:
            return
        session = pomodoro_sessions.get(self.user_id)
        if not session or session['paused']:
            await interaction.response.send_message("Not running!", ephemeral=True)
            return
        session['paused'] = True
        session['pause_time'] = time.time()
        button.label = 'Resume'
        button.emoji = '▶️'
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label='Stop', style=discord.ButtonStyle.red, emoji='⏹️')
    async def stop(self, interaction, button):
        if interaction.user.id != self.user_id:
            return
        session = pomodoro_sessions.get(self.user_id)
        if session:
            session['task'].cancel()
            del pomodoro_sessions[self.user_id]
            button.disabled = True
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("Stopped!")

async def pomodoro_timer(user_id):
    session = pomodoro_sessions[user_id]
    channel = session['channel']
    while True:
        phase = session['phase']
        duration = session['duration']
        end_time = time.time() + duration
        while time.time() < end_time:
            if session['paused']:
                await asyncio.sleep(1)
                end_time += time.time() - session['pause_time']
                session['pause_time'] = time.time()
                continue
            await asyncio.sleep(1)
        if phase == 'work':
            await channel.send(f"{bot.get_user(user_id).mention} Work done! 5min break ☕")
            session['phase'] = 'break'
            session['duration'] = 5*60
        else:
            await channel.send(f"{bot.get_user(user_id).mention} Break over! 25min work ⏰")
            session['phase'] = 'work'
            session['duration'] = 25*60

async def auto_delete(channel_id):
    await asyncio.sleep(300)  # 5min
    channel = bot.get_channel(channel_id)
    if channel and len(channel.members) == 0:
        if channel_id in rooms:
            del rooms[channel_id]
        elif channel_id in focus_rooms:
            del focus_rooms[channel_id]
        await channel.delete()

@bot.event
async def on_voice_state_update(member, before, after):
    global next_room_num, next_focus_room_num
    if member == bot.user:
        return
    
    # Time tracking
    is_study = lambda ch: ch and ch.category == study_category and ch.name.startswith('Study Room ')
    is_focus = lambda ch: ch and ch.category == focus_category and ch.name.startswith('Focus Room ')
    today = datetime.date.today()
    user_id = member.id
    
    if after.channel and (is_study(after.channel) or is_focus(after.channel)):
        if user_id not in current_sessions:
            current_sessions[user_id] = time.time()
            if user_id not in session_history:
                session_history[user_id] = []
            if user_id not in sessions_count:
                sessions_count[user_id] = 0
            if user_id not in last_session_date:
                last_session_date[user_id] = today
            if user_id not in current_streak:
                current_streak[user_id] = 0
    
    if before.channel and (is_study(before.channel) or is_focus(before.channel)) and user_id in current_sessions:
        start = current_sessions.pop(user_id)
        duration = time.time() - start
        study_time[user_id] = study_time.get(user_id, 0) + duration
        sessions_count[user_id] += 1
        session_history[user_id].append(duration)
        if len(session_history[user_id]) > 10:
            session_history[user_id].pop(0)
        last_session_date[user_id] = today
        if user_id in current_streak and today == last_session_date.get(user_id, today) - datetime.timedelta(days=1):
            current_streak[user_id] += 1
        else:
            current_streak[user_id] = 1
        if user_id in goals and goals[user_id]['date'] == today:
            goals[user_id]['current'] += duration
    
    # Auto-create study room
    if after.channel and after.channel.name == JOIN_CHANNEL_NAME and (before.channel is None or before.channel != after.channel):
        if not study_category:
            try:
                await member.send("No Study Rooms category!")
            except:
                pass
            return
        room_name = f"Study Room {next_room_num}"
        overwrites = {guild.default_role: discord

import os
bot.run(os.getenv("DISCORD_TOKEN"))
