import discord
from discord.ext import commands
import asyncio
import os
import datetime
import time
from discord.ui import Button, View

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Storage
study_time = {}  # user_id: total_seconds
current_sessions = {}  # user_id: start_time (for VC time)
rooms = {}  # channel_id: owner_id
study_category = None
next_room_num = 1
JOIN_CHANNEL_NAME = "Join to Create"
pomodoro_sessions = {}  # user_id: {'task': asyncio.Task, 'phase': 'work' or 'break', 'channel': ctx.channel}

# Stats storage
sessions_count = {}  # user_id: total_sessions
session_history = {}  # user_id: list of session durations (last 10)
last_session_date = {}  # user_id: last date
current_streak = {}  # user_id: current streak days

def format_time(seconds):
    """Convert seconds to HH:MM format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

@bot.event
async def on_ready():
    global study_category, next_room_num
    guild = bot.guilds[0]
    
    study_category = discord.utils.get(guild.categories, name='Study Rooms')
    if study_category:
        existing_rooms = [ch for ch in study_category.voice_channels if ch.name.startswith('Study Room ') and ch.name.split()[-1].isdigit()]
        if existing_rooms:
            nums = [int(ch.name.split()[-1]) for ch in existing_rooms]
            next_room_num = max(nums) + 1
            print(f'Next room number: {next_room_num}')
        else:
            next_room_num = 1
            print('Starting from room 1.')
    else:
        print('❌ No "Study Rooms" category found!')
    
    join_channel = discord.utils.get(guild.voice_channels, name=JOIN_CHANNEL_NAME)
    if not join_channel:
        print(f'❌ No "{JOIN_CHANNEL_NAME}" channel found!')
    
    # Set bot status
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="StudySphere"))
    
    # Focus Mode Embed in "focus mode" channel
    focus_channel = discord.utils.get(guild.text_channels, name='focus mode')
    if focus_channel:
        embed = discord.Embed(
            title="🎯 Focus Mode",
            description="Toggle to hide distractions and focus on studying. Only study channels visible when enabled.",
            color=0x00ff00
        )
        view = FocusView()
        await focus_channel.send(embed=embed, view=view)
        print('Focus Mode embed sent to "focus mode" channel.')
    else:
        print('❌ No "focus mode" text channel found – create it for Focus Mode buttons.')
    
    print(f'{bot.user} has logged in! Ready for StudySphere. Voice events active.')

# Leaderboard (Time-Based)
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

# Stats Command
@bot.command(name='stats')
async def stats(ctx):
    user_id = ctx.author.id
    today = datetime.date.today()
    
    if user_id not in study_time or study_time[user_id] == 0:
        await ctx.send("📊 No study stats yet! Join a study room to start tracking time.")
        return
    
    total_time = study_time[user_id]
    num_sessions = sessions_count.get(user_id, 0)
    history = session_history.get(user_id, [])
    avg_session = sum(history) / max(len(history), 1) if history else 0
    
    # Streak calculation
    streak = current_streak.get(user_id, 0)
    last_date = last_session_date.get(user_id, today - datetime.timedelta(days=1))
    if last_date.date() == today - datetime.timedelta(days=1):
        streak += 1
    elif last_date.date() != today:
        streak = 1
    current_streak[user_id] = streak
    
    embed = discord.Embed(title=f"📊 {ctx.author.display_name}'s Study Stats", color=0x0099ff)
    embed.add_field(name="Total Time", value=format_time(total_time), inline=True)
    embed.add_field(name="Sessions", value=str(num_sessions), inline=True)
    embed.add_field(name="Avg Session", value=format_time(avg_session), inline=True)
    embed.add_field(name="Streak", value=f"{streak} days", inline=False)
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

# Voice Events (VC Time Tracking + Auto-Create)
@bot.event
async def on_voice_state_update(member, before, after):
    global next_room_num
    
    if member == bot.user:
        return
    
    # Track study time (only in study rooms)
    is_study_room = lambda ch: ch and ch.category == study_category and ch.name.startswith('Study Room ')
    
    # On join to study room: Start timer
    if after.channel and is_study_room(after.channel) and member.id not in current_sessions:
        current_sessions[member.id] = time.time()
        if member.id not in session_history:
            session_history[member.id] = []
        if member.id not in sessions_count:
            sessions_count[member.id] = 0
        if member.id not in last_session_date:
            last_session_date[member.id] = datetime.date.today()
        if member.id not in current_streak:
            current_streak[member.id] = 0
    
    # On leave from study room: Add time to total, update stats
    if before.channel and is_study_room(before.channel) and member.id in current_sessions:
        start_time = current_sessions.pop(member.id)
        session_time = time.time() - start_time
        if member.id in study_time:
            study_time[member.id] += session_time
        else:
            study_time[member.id] = session_time
        
        # Update sessions and history
        sessions_count[member.id] += 1
        session_history[member.id].append(session_time)
        if len(session_history[member.id]) > 10:  # Keep last 10
            session_history[member.id].pop(0)
        
        today = datetime.date.today()
        last_session_date[member.id] = today
        
        # Streak update
        if member.id in current_streak:
            prev_date = last_session_date.get(member.id, today) - datetime.timedelta(days=1)
            if today == prev_date:
                current_streak[member.id] += 1
            else:
                current_streak[member.id] = 1
    
    # Auto-create on join to "Join to Create"
    if after.channel and after.channel.name == JOIN_CHANNEL_NAME and (before.channel is None or before.channel != after.channel):
        guild = member.guild
        if not study_category:
            try:
                await member.send("❌ No 'Study Rooms' category found! Ask an admin to create it.")
            except:
                pass
            return
        
        channel_name = f"Study Room {next_room_num}"
        # Default UNLOCKED
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True, speak=True),
            member: discord.PermissionOverwrite(connect=True, speak=True, manage_channels=True)
        }
        
        try:
            new_vc = await study_category.create_voice_channel(channel_name, overwrites=overwrites)
            rooms[new_vc.id] = member.id
            next_room_num += 1
            
            await member.move_to(new_vc)
            
            dm_msg = (f"🔊 Created and moved you to your unlocked {channel_name}! Anyone can join by default.\n"
                      f"• !lock - Lock to trusted only\n"
                      f"• !trust @user - Grant access even if locked\n"
                      f"• !kick @user - Remove access\n"
                      f"• !unlock - Open to everyone\n"
                      f"• !delete - Close the room\n"
                      f"Time in rooms counts toward leaderboard. Use !pomodoro for focused sessions or Focus Mode buttons for mode. 📚")
            try:
                await member.send(dm_msg)
            except discord.Forbidden:
                pass
                
        except discord.Forbidden:
            fallback_msg = (f"🔊 Created your unlocked {channel_name}! Manually join it (permission issue).\n"
                            f"Commands: !trust @user, !lock, etc. Time tracks automatically. 📚")
            try:
                await member.send(fallback_msg)
            except discord.Forbidden:
                pass
    
    # Auto-delete empty rooms
    if before.channel and before.channel.category == study_category and len(before.channel.members) == 0:
        try:
            await before.channel.delete()
            if before.channel.id in rooms:
                del rooms[before.channel.id]
        except discord.Forbidden:
            pass

# Focus Mode View (Buttons for Enable/Disable)
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
                await focus_role.edit(position=1)  # Low in hierarchy
                print(f'Created Focus Mode role: {focus_role.id}')
            except discord.Forbidden:
                await interaction.response.send_message("❌ Bot lacks 'Manage Roles' permission!", ephemeral=True)
                return
        
        # Add role if not present
        if focus_role not in user.roles:
            await user.add_roles(focus_role)
            embed = discord.Embed(title="🎯 Focus Mode Enabled", description="Distracting channels hidden. Only study channels visible. Use Disable to exit.", color=0x00ff00)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("✅ Already in Focus Mode!", ephemeral=True)

    @discord.ui.button(label='Disable Focus', style=discord.ButtonStyle.red, emoji='🔓')
    async def disable_focus(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        user = interaction.user
        
        focus_role = discord.utils.get(guild.roles, name='Focus Mode')
        if focus_role and focus_role in user.roles:
            await user.remove_roles(focus_role)
            embed = discord.Embed(title="🔓 Focus Mode Disabled", description="All channels visible again. Keep studying!", color=0xff9900)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("✅ Not in Focus Mode!", ephemeral=True)

# Owner Commands
async def is_owner(ctx):
    if not ctx.author.voice:
        await ctx.send("❌ Join your study room first!")
        return False
    vc = ctx.author.voice.channel
    if vc.id not in rooms:
        await ctx.send("❌ This isn't a study room (use 'Join to Create' to make one)!")
        return False
    if ctx.author.id != rooms[vc.id]:
        await ctx.send("❌ Only the room owner can use this command!")
        return False
    return True

@bot.command(name='trust')
async def trust(ctx, user: discord.Member):
    """Owner grants trusted access (overrides lock)."""
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    overwrite = discord.PermissionOverwrite(connect=True, speak=True)
    await vc.set_permissions(user, overwrite=overwrite)
    await ctx.send(f"✅ Trusted {user.mention} for {vc.name} (can join even if locked)! They can now manually join the room.")

@bot.command(name='kick')
async def kick(ctx, user: discord.Member):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    await vc.set_permissions(user, overwrite=None)
    await ctx.send(f"👢 Kicked {user.mention} from {vc.name} (removed access).")

@bot.command(name='lock')
async def lock(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    role = ctx.guild.default_role
    overwrite = discord.PermissionOverwrite(connect=False, speak=False)
    await vc.set_permissions(role, overwrite=overwrite)
    await ctx.send(f"🔒 {vc.name} is now locked (@everyone denied; use !trust @user to allow access)!")

@bot.command(name='unlock')
async def unlock(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    role = ctx.guild.default_role
    overwrite = discord.PermissionOverwrite(connect=True, speak=True)
    await vc.set_permissions(role, overwrite=overwrite)
    await ctx.send(f"🔓 {vc.name} is now unlocked (everyone can join)!")

@bot.command(name='delete')
async def delete_room(ctx):
    if not await is_owner(ctx):
        return
    vc = ctx.author.voice.channel
    owner_id = rooms[vc.id]
    await vc.delete()
    if vc.id in rooms:
       
        
bot.run(os.getenv("DISCORD_TOKEN"))
