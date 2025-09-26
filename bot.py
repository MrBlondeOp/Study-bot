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
    
    if action == 'set' and time_str:
        try:
            if 'h' in time_str.lower():
                hours = float(time_str.lower().replace('h', ''))
                target = int(hours * 3600)
            elif 'm' in time_str.lower():
                minutes = float(time_str.lower().replace('m', ''))
                target = int(minutes * 60)
            else:
                target = int(time_str)  # Seconds
            goals[user_id] = {'target': target, 'current': 0, 'date': today}
            await ctx.send(f"✅ Daily goal set: {format_time(target)} (resets tomorrow). Use !progress to track!")
        except ValueError:
            await ctx.send("❌ Invalid time! Use e.g., !goal set 2h, 90m, or 3600 (seconds).")
        return
    
    if user_id not in goals:
        await ctx.send("❌ No goal set! Use !goal set <time> (e.g., 2h) to start.")
        return
    
    goal_data = goals[user_id]
    if goal_data['date'] != today:
        goal_data['current'] = 0  # Reset daily
    
    if action == 'clear':
        if user_id in goals:
            del goals[user_id]
        await ctx.send("🗑️ Goal cleared!")
        return
    
    # Default: Show current goal
    remaining = max(0, goal_data['target'] - goal_data['current'])
    embed = discord.Embed(title="🎯 Your Daily Goal", color=0x00ff00)
    embed.description = f"Target: {format_time(goal_data['target'])}\nCurrent: {format_time(goal_data['current'])}\nRemaining: {format_time(remaining)}"
    await ctx.send(embed=embed)

@bot.command(name='progress')
async def progress(ctx):
    user_id = ctx.author.id
    today = datetime.date.today()
    
    if user_id not in goals:
        await ctx.send("❌ No goal set! Use !goal set <time> to create one, then !progress.")
        return
    
    goal_data = goals[user_id]
    if goal_data['date'] != today:
        goal_data['current'] = 0
    
    percentage = min(100, (goal_data['current'] / goal_data['target']) * 100)
    bar = get_progress_bar(percentage)
    remaining = max(0, goal_data['target'] - goal_data['current'])
    eta = format_time(remaining) if remaining > 0 else "Done! 🎉"
    
    embed = discord.Embed(title="📈 Goal Progress", color=0x0099ff)
    embed.add_field(name="Progress", value=f"{bar} {percentage:.0f}%", inline=False)
    embed.add_field(name="Current / Target", value=f"{format_time(goal_data['current'])} / {format_time(goal_data['target'])}", inline=True)
    embed.add_field(name="Remaining", value=eta, inline=True)
    if percentage >= 100:
        embed.description = "✅ Goal achieved! Great job—set a new one tomorrow?"
    await ctx.send(embed=embed)

# New: FocusView for Buttons in "focus mode"
class FocusView(View):
    def __init__(self):
        super().__init__(timeout=None)  # Persistent

    @discord.ui.button(label='Enable Focus', style=discord.ButtonStyle.green, emoji='🎯')
    async def enable_focus(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        user = interaction.user
        
        # Find or create Focus Mode role
        focus_role = discord.utils.get(guild.roles, name='Focus Mode')
        if not focus_role:
            try:
                focus_role = await guild.create_role(
                    name='Focus Mode',
                    color=discord.Color.green(),
                    permissions=discord.Permissions.none(),
                    mentionable=False,
                    hoist=False
                )
                await focus_role.edit(position=1)  # Low hierarchy
                print(f'Created Focus Mode role: {focus_role.id}')
            except discord.Forbidden:
                await interaction.response.send_message("❌ Bot lacks 'Manage Roles' permission.", ephemeral=True)
                return
        
        # Add role if not present
        if focus_role not in user.roles:
            await user.add_roles(focus_role)
            embed_desc = "Distracting channels hidden. Only configured study channels visible.\nUse Disable to exit. VC time tracking active!"
            if user.voice and user.voice.channel and user.voice.channel.category == focus_category:
                embed_desc += "\n💡 You're in a Focus room—perfect! Time counting..."
            try:
                await user.send("🎯 Entered Focus Mode. Non-study channels now hidden. Stay productive!")
            except discord.Forbidden:
                pass
            await interaction.response.send_message(f"🎯 Focus Mode Enabled!\n{embed_desc}", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Focus Mode already enabled!", ephemeral=True)

    @discord.ui.button(label='Disable Focus', style=discord.ButtonStyle.red, emoji='🔓')
    async def disable_focus(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        user = interaction.user
        
        focus_role = discord.utils.get(guild.roles, name='Focus Mode')
        if not focus_role:
            await interaction.response.send_message("❌ No Focus Mode role found—create it first.", ephemeral=True)
            return
        
        # Remove role if present
        if focus_role in user.roles:
            await user.remove_roles(focus_role)
            try:
                await user.send("🔓 Exited Focus Mode. Full server access restored.")
            except discord.Forbidden:
                pass
            await interaction.response.send_message("🔓 Focus Mode Disabled! All channels visible again. Keep studying! 📚", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Focus Mode already disabled!", ephemeral=True)

# Voice Events (Enhanced for Stats/Goals + Focus Rooms)
@bot.event
async def on_voice_state_update(member, before, after):
    global next_room_num, next_focus_room_num
    
    if member == bot.user:
        return
    
    # Track study time (study or focus rooms)
    is_study_room = lambda ch: ch and ch.category == study_category and ch.name.startswith('Study Room ')
    is_focus_room = lambda ch: ch and ch.category == focus_category and ch.name.startswith('Focus Room ')
    
    today = datetime.date.today()
    user_id = member.id
    
    # On join to study/focus room: Start timer + init stats
    if after.channel and (is_study_room(after.channel) or is_focus_room(after.channel)):
        if user_id not in current_sessions:
            current_sessions[user_id] = time.time()
            # Init stats if needed
            if user_id not in session_history:
                session_history[user_id] = []
            if user_id not in sessions_count:
                sessions_count[user_id] = 0
            if user_id not in last_session_date:
                last_session_date[user_id] = today
            if user_id not in current_streak:
                current_streak[user_id] = 0
    
    # On leave from study/focus room: Add time + update stats/goals
    if before.channel and (is_study_room(before.channel) or is_focus_room(before.channel)) and user_id in current_sessions:
        start_time = current_sessions.pop(user_id)
        session_duration = time.time() - start_time
        
        # Update total time
        if user_id in study_time:
            study_time[user_id] += session_duration
        else:
            study_time[user_id] = session_duration
        
        # Stats updates
        sessions_count[user_id] += 1
        session_history[user_id].append(session_duration)
        if len(session_history[user_id]) > 10:
            session_history[user_id].pop(0)
        
        last_session_date[user_id] = today
        if user_id in current_streak and today == last_session_date.get(user_id, today) - datetime.timedelta(days=1):
            current_streak[user_id] += 1
        else:
            current_streak[user_id] = 1
        
        # Update daily goal
        if user_id in goals and goals[user_id]['date'] == today:
            goals[user_id]['current'] += session_duration
    
    # Auto-create general study room on join to "Join to Create"
    if after.channel and after.channel.name == JOIN_CHANNEL_NAME and (before.channel is None or before.channel != after.channel):
        guild = member.guild
        if not study_category:
            try:
                await member.send("❌ No 'Study Rooms' category found! Ask an admin to create it.")
            except:
               

import os
bot.run(os.getenv("DISCORD_TOKEN"))

        
        # Clean up
