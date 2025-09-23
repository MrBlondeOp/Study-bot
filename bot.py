import discord
from discord.ext import commands
import asyncio
import datetime
import os  # For secret token
from flask import Flask  # For keeping bot awake
import threading  # To run bot + web together

# Simple web server to keep Replit awake
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive! 🚀"

# Your bot code (unchanged except token)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

leaderboard = {}
rooms = {}
study_category = None
next_room_num = 1
JOIN_CHANNEL_NAME = "Join to Create"  # Change if your channel name is different (e.g., capitalized)

@bot.event
async def on_ready():
    global study_category, next_room_num
    guild = bot.guilds[0]
    print(f'Bot connected to guild: {guild.name} (ID: {guild.id})')
    
    study_category = discord.utils.get(guild.categories, name='Study Rooms')
    if study_category:
        print(f'Found "Study Rooms" category: {study_category.id}')
        existing_rooms = [ch for ch in study_category.voice_channels if ch.name.startswith('Study Room ')]
        if existing_rooms:
            nums = [int(ch.name.split()[-1]) for ch in existing_rooms if ch.name.split()[-1].isdigit()]
            next_room_num = max(nums) + 1 if nums else 1
            print(f'Existing rooms found. Next room number: {next_room_num}')
        else:
            print('No existing study rooms. Starting from 1.')
    else:
        print('❌ WARNING: No "Study Rooms" category found! Create it exactly as "Study Rooms".')
    
    join_channel = discord.utils.get(guild.voice_channels, name=JOIN_CHANNEL_NAME)
    if join_channel:
        print(f'Found "{JOIN_CHANNEL_NAME}" channel: {join_channel.id}')
    else:
        print(f'❌ WARNING: No "{JOIN_CHANNEL_NAME}" voice channel found!')
    
    print(f'{bot.user} has logged in! Ready for StudySphere.')

# All your other code (leaderboard, commands, events) – paste the rest here exactly as before
# (checkin, leaderboard, on_voice_state_update, is_owner, invite, kick, lock, unlock, delete, pomodoro, on_command_error)

@bot.command(name='checkin')
async def checkin(ctx):
    user_id = ctx.author.id
    if user_id in leaderboard:
        leaderboard[user_id] += 1
    else:
        leaderboard[user_id] = 1
    await ctx.send(f'✅ {ctx.author.mention} checked in! You now have {leaderboard[user_id]} points.')

@bot.command(name='leaderboard')
async def leaderboard_cmd(ctx):
    if not leaderboard:
        await ctx.send('🏆 No points yet—start studying!')
        return
    sorted_users = sorted(leaderboard.items(), key=lambda x: x[1], reverse=True)[:10]
    embed = discord.Embed(title='🏆 StudySphere Leaderboard', color=0x00ff00)
    for i, (user_id, points) in enumerate(sorted_users, 1):
        user = bot.get_user(user_id)
        username = user.display_name if user else f'User {user_id}'
        embed.add_field(name=f'{i}. {username}', value=f'{points} points', inline=False)
    embed.timestamp = datetime.datetime.now()
    await ctx.send(embed=embed)

@bot.event
async def on_voice_state_update(member, before, after):
    global next_room_num
    
    before_name = before.channel.name if before.channel else "None"
    after_name = after.channel.name if after.channel else "None"
    print(f'Voice update: {member.display_name} - Before: {before_name} -> After: {after_name}')
    
    if after.channel and after.channel.name == JOIN_CHANNEL_NAME:
        if before.channel is None or before.channel != after.channel:
            guild = member.guild
            if not study_category:
                try:
                    await member.send("❌ No 'Study Rooms' category found!")
                except:
                    pass
                return
            
            channel_name = f"Study Room {next_room_num}"
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(connect=False, speak=False),
                member: discord.PermissionOverwrite(connect=True, speak=True)
            }
            
            try:
                new_vc = await study_category.create_voice_channel(channel_name, overwrites=overwrites)
                rooms[new_vc.id] = member.id
                next_room_num += 1
                await member.move_to(new_vc)
                
                dm_msg = (f"🔊 Created your private {channel_name}! Commands: !invite, !kick, !lock, !unlock, !delete")
                try:
                    await member.send(dm_msg)
                except discord.Forbidden:
                    pass
                print(f'✅ Created and moved to {channel_name}')
            except Exception as e:
                print(f'❌ Error: {e}')
    
    if before.channel and before.channel.category == study_category and len(before.channel.members) == 0:
        try:
            await before.channel.delete()
            if before.channel.id in rooms:
                del rooms[before.channel.id]
            print(f'✅ Deleted empty room {before.channel.name}')
        except Exception as e:
            print(f'❌ Delete error: {e}')

async def is_owner(ctx):
    if not ctx.author.voice:
        await ctx.send("❌ Join your study room first!")
        return False
    vc = ctx.author.voice.channel
    if vc.id not in rooms:
        await ctx.send("❌ Not a study room!")
        return False
    if ctx.author.id != rooms[vc.id]:
        await ctx.send("❌ Only owner can use this!")
        return False
    return True

@bot.command(name='invite')
async def invite(ctx, user: discord.Member):
    if not await is_owner(ctx): return
    vc = ctx.author.voice.channel
    overwrite = discord.PermissionOverwrite(connect=True, speak=True)
    await vc.set_permissions(user, overwrite=overwrite)
    await ctx.send(f"✅ Invited {user.mention}!")

@bot.command(name='kick')
async def kick(ctx, user: discord.Member):
    if not await is_owner(ctx): return
    vc = ctx.author.voice.channel
    await vc.set_permissions(user, overwrite=None)
    await ctx.send(f"👢 Kicked {user.mention}!")

@bot.command(name='lock')
async def lock(ctx):
    if not await is_owner(ctx): return
    vc = ctx.author.voice.channel
    role = ctx.guild.default_role
    overwrite = discord.PermissionOverwrite(connect=False, speak=False)
    await vc.set_permissions(role, overwrite=overwrite)
    await ctx.send("🔒 Locked!")

@bot.command(name='unlock')
async def unlock(ctx):
    if not await is_owner(ctx): return
    vc = ctx.author.voice.channel
    role = ctx.guild.default_role
    overwrite = discord.PermissionOverwrite(connect=True, speak=True)
    await vc.set_permissions(role, overwrite=overwrite)
    await ctx.send("🔓 Unlocked!")

@bot.command(name='delete')
async def delete_room(ctx):
    if not await is_owner(ctx): return
    vc = ctx.author.voice.channel
    await vc.delete()
    if vc.id in rooms:
        del rooms[vc.id]

@bot.command(name='pomodoro')
async def pomodoro(ctx):
    user_id = ctx.author.id
    await ctx.send(f'⏱️ Starting 25-min session!')
    await asyncio.sleep(25 * 60)
    if any(m.id == user_id for m in ctx.channel.members if hasattr(ctx, 'channel')):
        await ctx.send('🔔 Break time! 5 min...')
        await asyncio.sleep(5 * 60)
        await ctx.send('✅ Pomodoro done! +5 points.')
        if user_id in leaderboard:
            leaderboard[user_id] += 5
        else:
            leaderboard[user_id] = 5
    else:
        await ctx.send('⏰ You left—no points.')

@bot.event
async def on_command_error(ctx, error):
    await ctx.send('❌ Error—use !help.')

# Run bot in background + web server
def run_bot():
    bot.run(os.getenv('DISCORD_TOKEN'))  # Uses secret token

if __name__ == '__main__':
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=8080, debug=False)
