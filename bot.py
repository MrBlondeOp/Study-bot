import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio
import datetime
import os

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

study_category = None
next_room_num = 1
active_pomodoros = {}  # {user_id: asyncio.Task}

# -------------------------
# Focus Mode View (Buttons)
# -------------------------
class FocusView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Enable Focus', style=discord.ButtonStyle.green, emoji='🎯')
    async def enable_focus(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        user = interaction.user
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
            except discord.Forbidden:
                await interaction.response.send_message("❌ Bot lacks 'Manage Roles' permission!", ephemeral=True)
                return
        if focus_role not in user.roles:
            await user.add_roles(focus_role)
            embed = discord.Embed(
                title="🎯 Focus Mode Enabled",
                description="Distracting channels hidden. Only study channels visible. Use Disable to exit.",
                color=0x00ff00
            )
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
            embed = discord.Embed(
                title="🔓 Focus Mode Disabled",
                description="All channels visible again. Keep studying!",
                color=0xff9900
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("✅ Not in Focus Mode!", ephemeral=True)

# -------------------------
# Pomodoro View (Buttons)
# -------------------------
class PomodoroView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶️ Start Pomodoro", style=discord.ButtonStyle.green)
    async def start_button(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        if user_id in active_pomodoros:
            await interaction.response.send_message("❌ You already have a Pomodoro running! Stop it first.", ephemeral=True)
            return

        await interaction.response.send_message("🍅 Pomodoro started! Focus for 25 minutes.", ephemeral=True)

        async def run_pomodoro():
            focus, short_break, cycles = 25, 5, 4
            for cycle in range(1, cycles + 1):
                embed = discord.Embed(
                    title="🍅 Focus Time",
                    description=f"**Cycle {cycle}/{cycles}**\nFocus for `{focus}` minutes.",
                    color=discord.Color.red()
                )
                embed.set_footer(text=f"Started at {datetime.datetime.now().strftime('%H:%M:%S')}")
                await interaction.channel.send(f"{interaction.user.mention}", embed=embed)

                await asyncio.sleep(focus * 60)

                if cycle != cycles:
                    embed = discord.Embed(
                        title="☕ Break Time!",
                        description=f"Relax for `{short_break}` minutes.",
                        color=discord.Color.green()
                    )
                    await interaction.channel.send(f"{interaction.user.mention}", embed=embed)
                    await asyncio.sleep(short_break * 60)

            await interaction.channel.send(f"✅ {interaction.user.mention} All Pomodoro cycles complete! 🎉")
            del active_pomodoros[user_id]

        task = asyncio.create_task(run_pomodoro())
        active_pomodoros[user_id] = task

    @discord.ui.button(label="⏹️ Stop Pomodoro", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        if user_id not in active_pomodoros:
            await interaction.response.send_message("❌ You don’t have any active Pomodoro.", ephemeral=True)
        else:
            active_pomodoros[user_id].cancel()
            del active_pomodoros[user_id]
            await interaction.response.send_message("⏹️ Pomodoro stopped.", ephemeral=True)

    @discord.ui.button(label="ℹ️ Status", style=discord.ButtonStyle.blurple)
    async def status_button(self, interaction: discord.Interaction, button: Button):
        user_id = interaction.user.id
        if user_id not in active_pomodoros:
            await interaction.response.send_message("❌ No active Pomodoro.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ Your Pomodoro is currently running. Stay focused! 🎯", ephemeral=True)

# -------------------------
# Events
# -------------------------
@bot.event
async def on_ready():
    global study_category, next_room_num
    guild = bot.guilds[0]

    # Study Rooms setup
    study_category = discord.utils.get(guild.categories, name='Study Rooms')
    if study_category:
        existing_rooms = [ch for ch in study_category.voice_channels if ch.name.startswith('Study Room ') and ch.name.split()[-1].isdigit()]
        if existing_rooms:
            nums = [int(ch.name.split()[-1]) for ch in existing_rooms]
            next_room_num = max(nums) + 1
        else:
            next_room_num = 1
    else:
        print('❌ No "Study Rooms" category found!')

    # Focus Mode Embed
    focus_channel = discord.utils.get(guild.text_channels, name='focus-mode')
    if focus_channel:
        embed = discord.Embed(
            title="🎯 Focus Mode",
            description=(
                "Toggle Focus Mode to hide distractions and focus on studying.\n\n"
                "✅ **Enable Focus** → Hides all channels except study-related ones.\n"
                "❌ **Disable Focus** → Shows all channels again."
            ),
            color=0x00ff00
        )
        view = FocusView()
        await focus_channel.purge(limit=5)
        await focus_channel.send(embed=embed, view=view)
        print('📌 Focus Mode embed sent to #focus-mode channel.')
    else:
        print('❌ No #focus-mode text channel found – please create one.')

    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="StudySphere"))
    print(f"{bot.user} is online and ready!")

# -------------------------
# Commands
# -------------------------
@bot.command()
async def stats(ctx):
    embed = discord.Embed(
        title="📊 StudySphere Stats",
        description="Here will be your study statistics (coming soon!).",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command()
async def pomodoro(ctx):
    embed = discord.Embed(
        title="🍅 Pomodoro Timer",
        description=(
            "Stay productive using the Pomodoro technique!\n\n"
            "▶️ **Start Pomodoro** – 25 min focus + 5 min break × 4 cycles\n"
            "⏹️ **Stop Pomodoro** – Cancel your session\n"
            "ℹ️ **Status** – Check your progress"
        ),
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=PomodoroView())

TOKEN = os.getenv("DISCORD_TOKEN")  # Railway Variables me add karna hoga
bot.run(TOKEN)
