import discord
from discord.ext import commands
import asyncio
import datetime
import time
from discord.ui import Button, View

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Storage (Existing + New for Stats/Goals)
study_time = {}  # user_id: total_seconds (lifetime)
current_sessions = {}  # user_id: start_time (for VC time)
rooms = {}  # channel_id: owner_id (general study rooms)
focus_rooms = {}  # channel_id: owner_id (focus rooms)
study_category = None
focus_category = None
next_room_num = 1
next_focus_room_num = 1
JOIN_CHANNEL_NAME = "Join to Create"
JOIN_FOCUS_CHANNEL_NAME = "Join Focused Study"
pomodoro_sessions = {}  # user_id: {'task': asyncio.Task, 'phase': 'work' or 'break', 'channel': ctx.channel}

# New: Stats & Goals
sessions_count = {}  # user_id: total_sessions
session_history = {}  # user_id: list of durations (last 10 for avg)
last_session_date = {}  # user_id: last_date (for streaks)
goals = {}  # user_id: {'target': secs, 'current': 0, 'date': date_obj}
current_streak = {}  # user_id: streak_days

def format_time(seconds):
    """Convert seconds to HH:MM format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

def get_progress_bar(percentage, length=10):
    """Unicode progress bar."""
    filled = int(percentage / 100 * length)
    return "█" * filled + "░" * (length - filled)

@bot.event
async def on_ready():
    global study_category, focus_category, next_room_num, next_focus_room_num
    guild = bot.guilds[0]
    
    # Existing Study Category
    study_category = discord.utils.get(guild.categories, name='Study Rooms')
    if study_category:
        existing_rooms = [ch for ch in study_category.voice_channels if ch.name.startswith('Study Room ') and ch.name.split()[-1].isdigit()]
        if existing_rooms:
            nums = [int(ch.name.split()[-1]) for ch in existing_rooms]
            next_room_num = max(nums) + 1
            print(f'Next study room number: {next_room_num}')
        else:
            next_room_num = 1
            print('Starting study rooms from 1.')
    else:
        print('❌ No "Study Rooms" category found!')
    
    # Focus Category Setup
    focus_category = discord.utils.get(guild.categories, name='Focus')
    if not focus_category:
        try:
            focus_category = await guild.create_category('Focus', position=len(guild.categories))  # At end
            print('Created Focus category.')
        except discord.Forbidden:
            print('❌ Bot lacks perms to create Focus category.')
    else:
        print('Focus category found.')
    
    # Look for or create "focus mode" text channel
    focus_text_channel = discord.utils.get(focus_category.text_channels, name='focus mode') if focus_category else None
    if not focus_text_channel:
        try:
            focus_text_channel = await focus_category.create_text_channel('focus mode')
            print('Created "focus mode" channel.')
        except discord.Forbidden:
            print('❌ Bot lacks perms to create "focus mode" channel.')
    
    # Send persistent Focus Mode embed with buttons if channel exists
    if focus_text_channel:
        focus_role = discord.utils.get(guild.roles, name='Focus Mode')
        role_mention = focus_role.mention if focus_role else "Focus Mode role"
        embed = discord.Embed(
            title="🎯 Focus Mode Controls",
            description=f"Toggle {role_mention} to hide distracting channels (e.g., #memes). Only study/Focus channels visible when enabled.\n\n**Setup Tip:** Server admin—allow 'View Channel' for {role_mention} on study channels; deny on others (Server Settings > Channels > Permissions).",
            color=0x00ff00
        )
        embed.add_field(name="How It Works", value="• Enable: Hides non-study channels.\n• Disable: Restores full access.\n• Use with !pomodoro or Focus VCs for max productivity!", inline=False)
        view = FocusView()  # Persistent view
        await focus_text_channel.send(embed=embed, view=view)
        print('Sent Focus Mode embed with buttons to "focus mode".')
    
    # Create Join Focused Study voice channel if missing
    join_focus_channel = discord.utils.get(focus_category.voice_channels, name=JOIN_FOCUS_CHANNEL_NAME) if focus_category else None
    if not join_focus_channel and focus_category:
        try:
            await focus_category.create_voice_channel(JOIN_FOCUS_CHANNEL_NAME, overwrites={guild.default_role: discord.PermissionOverwrite(connect=True)})
            print('Created Join Focused Study voice channel.')
        except discord.Forbidden:
            print('❌ Bot lacks perms to create Join Focused Study.')
    
    # Check for general Join channel
    join_channel = discord.utils.get(guild.voice_channels, name=JOIN_CHANNEL_NAME)
    if not join_channel:
        print(f'❌ No "{JOIN_CHANNEL_NAME}" channel found!')
    
    print(f'{bot.user} has logged in! Ready for StudySphere. Voice events active. Stats/Goals enabled.')

# Leaderboard (Unchanged)
@bot.command(name='leaderboard')
async def leaderboard_cmd(ctx):
    if not study_time:
        await ctx.send('🏆 No study time yet—start joining study rooms!')
        return
    
    sorted_users = sorted(study_time.items(), key=lambda x: x[1], reverse=True)[:10]
    embed = discord.Embed(title='🏆 StudySphere Leaderboard (Time)', color=0x00ff00)
    for i, (user_id, secs) in enumerate(sorted_users, 1):
        user = bot.get_user(user_id)
        username = user.display_name if user else f'User {user_id}'
        time_str = format_time(secs)
        embed.add_field(name=f'{i}. {username}', value=time_str, inline=False)
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

# Personal Stats Command
@bot.command(name='stats')
async def stats(ctx):
    user_id = ctx.author.id
    if user_id not in study_time or study_time[user_id] == 0:
        await ctx.send("📊 No study stats yet—join a study or focus room to start tracking!")
        return
    
    total_time = study_time[user_id]
    num_sessions = sessions_count.get(user_id, 0)
    history = session_history.get(user_id, [])
    avg_session = sum(history) / max(len(history), 1) if history else 0
    today = datetime.date.today()
    streak = current_streak.get(user_id, 0)
    last_date = last_session_date.get(user_id, today - datetime.timedelta(days=1))
    if last_date == today:
        pass  # Already counted
    elif last_date == today - datetime.timedelta(days=1):
        streak += 1
    else:
        streak = 1
    current_streak[user_id] = streak  # Update
    
    embed = discord.Embed(title=f"📊 {ctx.author.display_name}'s Study Stats", color=0x0099ff)
    embed.add_field(name="Total Time", value=format_time(total_time), inline=True)
    embed.add_field(name="Sessions", value=str(num_sessions), inline=True)
    embed.add_field(name="Avg Session", value=format_time(avg_session), inline=True)
    embed.add_field(name="Current Streak", value=f"{streak} days", inline=False)
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

# Goals Commands
@bot.command(name='goal')
async def goal(ctx, action=None, *, time_str=None):
    user_id = ctx.author.id
    today = datetime.date.today()
    
    if action == 'set' and ⬤

import os
bot.run(os.getenv("DISCORD_TOKEN"))

        
        # Clean up
