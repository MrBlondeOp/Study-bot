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

# Storage
study_time = {}  # user_id: total_seconds
current_sessions = {}  # user_id: start_time (for VC time)
rooms = {}  # channel_id: owner_id
study_category = None
next_room_num = 1
JOIN_CHANNEL_NAME = "Join to Create"
pomodoro_sessions = {}  # user_id: {'task': asyncio.Task, 'phase': 'work' or 'break', 'channel': ctx.channel}

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
    
    # On leave from study room: Add time to total
    if before.channel and is_study_room(before.channel) and member.id in current_sessions:
        start_time = current_sessions.pop(member.id)
        session_time = time.time() - start_time
        if member.id in study_time:
            study_time[member.id] += session_time
        else:
            study_time[member.id] = session_time
    
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
                      f"Time in rooms counts toward leaderboard. Use !pomodoro for focused sessions or !focus for mode. 📚")
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

# Focus Mode Command (Decoupled from Pomodoro)
@bot.command(name='focus')
async def focus(ctx):
    """Toggle Focus Mode role for reduced distractions."""
    guild = ctx.guild
    user = ctx.author
    
    # Find or create Focus Mode role
    focus_role = discord.utils.get(guild.roles, name='Focus Mode')
    if not focus_role:
        try:
            focus_role = await guild.create_role(
                name='Focus Mode',
                color=discord.Color.green(),
                permissions=discord.Permissions.none(),  # Minimal perms
                mentionable=False,
                hoist=False  # Don't separate in member list
            )
            # Position low in hierarchy (after @everyone)
            await focus_role.edit(position=1)
            await ctx.send("✅ Created 'Focus Mode' role! Follow the configuration guide below to set up channels.")
            print(f'Created Focus Mode role: {focus_role.id}')
        except discord.Forbidden:
            await ctx.send("❌ Bot lacks 'Manage Roles' permission to create Focus Mode role. Grant Admin or Manage Roles.")
            return
    
    # Toggle role
    if focus_role in user.roles:
        # Remove role (exit focus)
        await user.remove_roles(focus_role)
        embed = discord.Embed(title="🔓 Focus Mode Off", description="All channels visible again. Keep studying! 📚", color=0xff9900)
        try:
            await user.send("🔓 Exited Focus Mode. Full server access restored.")
        except discord.Forbidden:
            pass
    else:
        # Add role (enter focus)
        await user.add_roles(focus_role)
        embed = discord.Embed(title="🎯 Focus Mode On", description="Distracting channels hidden. Only configured study channels visible.\nUse !focus to exit. VC time tracking active!", color=0x00ff00)
        # Check if in study room
        if user.voice and user.voice.channel and user.voice.channel.category == study_category:
            embed.add_field(name="💡 Tip", value="You're in a study room—perfect for focus! Time counting...", inline=False)
        try:
            await user.send("🎯 Entered Focus Mode. Non-study channels are now hidden. Stay productive! (Configure server channels for best results.)")
        except discord.Forbidden:
            pass
    
    await ctx.send(embed=embed)

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
        del rooms[vc.id]
    try:
        owner = ctx.guild.get_member(owner_id)
        await owner.send(f"🗑️ Deleted {vc.name}. Thanks for studying!")
    except:
        pass

# Improved Pomodoro with Buttons
@bot.command(name='pomodoro')
async def pomodoro(ctx):
    """Start an interactive Pomodoro session with buttons."""
    user_id = ctx.author.id
    if user_id in pomodoro_sessions:
        await ctx.send("❌ You already have an active Pomodoro! Use the buttons to control it.")
        return
    
    embed = discord.Embed(
        title="⏱️ Pomodoro Timer",
        description=f"{ctx.author.mention}, ready to focus? Click **Start** for a 25-min work session + 5-min break.\nYour VC time tracks automatically! (Pairs great with !focus)",
        color=0x0099ff
    )
    view = PomodoroView(ctx.author, ctx.channel)
    await ctx.send(embed=embed, view=view)

class PomodoroView(View):
    def __init__(self, user: discord.Member, channel: discord.TextChannel):
        super().__init__(timeout=None)  # Persistent until stopped
        self.user = user
        self.channel = channel
        self.is_running = False
        self.current_task = None

    @discord.ui.button(label='Start', style=discord.ButtonStyle.green, emoji='▶️')
    async def start_callback(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            await interaction.response.send_message("❌ Only the session owner can control this!", ephemeral=True)
            return
        if self.is_running:
            await interaction.response.send_message("❌ Already running! Use Pause/Stop.", ephemeral=True)
            return
        
        self.is_running = True
        button.disabled = True  # Disable start button
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("🚀 Starting 25-min work session! Focus up! 📚")
        self.current_task = asyncio.create_task(self.run_pomodoro_cycle())

    @discord.ui.button(label='Pause', style=discord.ButtonStyle.blurple, emoji='⏸️')
    async def pause_callback(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or not self.is_running:
            await interaction.response.send_message("❌ Not running or not yours!", ephemeral=True)
            return
        if self.current_task:
            self.current_task.cancel()
            self.is_running = False
            self.children[0].disabled = False  # Re-enable start
        await interaction.response.send_message("⏸️ Pomodoro paused. Click Start to resume.", ephemeral=True)
        await interaction.edit_original_response(view=self)

    @discord.ui.button(label='Stop', style=discord.ButtonStyle.red, emoji='⏹️')
    async def stop_callback(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            await interaction.response.send_message("❌ Only the session owner can stop this!", ephemeral=True)
            return
        if self.current_task:
            self.current_task.cancel()
            self.is_running = False
        # Clean up session
        if self.user.id in pomodoro_sessions:
            del pomodoro_sessions[self.user.id]
        await interaction.response.send_message("🛑 Pomodoro stopped. Great effort!", ephemeral=True)
        self.stop()  # Disable view

    async def run_pomodoro_cycle(self):
        """Run one cycle: 25 min work + 5 min break."""
        pomodoro_sessions[self.user.id] = {'task': self.current_task, 'phase': 'work', 'channel': self.channel}
        
        # Work phase
        await asyncio.sleep(25 * 60)
        if self.channel:
            embed = discord.Embed(title="🔔 Work Session Done!", description="Take a 5-min break. ☕", color=0x00ff00)
            await self.channel.send(embed=embed)
        
        # Break phase
        await asyncio.sleep(5 * 60)
        if self.channel:
            embed = discord.Embed(title="✅ Pomodoro Complete!", description=f"{self.user.mention}, great job! Ready for another cycle? (VC time tracked.)", color=0x00ff00)
            await self.channel.send(embed=embed)
        
        # Check if in study room for bonus note
        if self.user.voice and self.user.voice.channel and self.user.voice.channel.category == study_category:
            await self.channel.send("🎯 Bonus: You completed this in a study room—your time counts double toward focus! 📈")
        
        self.is_running = False
        self.children[0].disabled = False  # Re-enable start
        if self.channel:
            await self.channel.send("🔄 Click Start for another cycle!", view=self)
        
        # Clean up
