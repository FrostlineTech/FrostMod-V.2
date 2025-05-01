import os
import discord
from discord import app_commands, ui
from discord.ext import commands
import asyncpg
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

# Set up Discord intents before bot definition
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# FrostModBot definition
class FrostModBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, application_id=None)
        self.db_pool = None
        # Store bot start time as UTC datetime
        import datetime
        # Provided local time is 2025-04-27T17:57:20-05:00
        self.start_time = datetime.datetime(2025, 4, 27, 22, 57, 20, tzinfo=datetime.timezone.utc)

    async def setup_hook(self):
        # Register slash commands globally
        await self.tree.sync()
        
        # Also register slash commands to the test guild for immediate updates
        if TEST_GUILD_ID:
            test_guild = discord.Object(id=int(TEST_GUILD_ID))
            self.tree.copy_global_to(guild=test_guild)
            await self.tree.sync(guild=test_guild)
            print(f"Commands synced to test guild ID: {TEST_GUILD_ID}")
        
        # Log registered commands for debugging
        commands_registered = list(self.tree.get_commands())
        print(f"\n--- Registered {len(commands_registered)} slash commands ---")
        for cmd in commands_registered:
            print(f"- /{cmd.name}: {cmd.description}")
        print("-------------------------------------------\n")
        
        # Connect to PostgreSQL
        self.db_pool = await asyncpg.create_pool(
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            host=DB_HOST,
            port=DB_PORT
        )
        print("Connected to PostgreSQL!")

bot = FrostModBot()

from itertools import cycle
import asyncio

status_messages = [
    (discord.ActivityType.watching, "👀 Frostline Users"),
    (discord.ActivityType.playing, "❄️ Enhancing Server Moderation"),
    (discord.ActivityType.watching, "❓ for /help")
]
status_cycle = cycle(status_messages)

@bot.event
async def on_ready():
    print("Bot is ready. Starting status rotation.")
    bot.loop.create_task(rotate_status())
    bot.loop.create_task(daily_birthday_check())

async def daily_birthday_check():
    import datetime, asyncio
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.datetime.now(datetime.timezone.utc)
        # Calculate seconds until next midnight UTC
        tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (tomorrow - now).total_seconds()
        await asyncio.sleep(seconds_until_midnight)
        # Now it's midnight UTC: check for birthdays
        today = datetime.date.today()
        month = today.month
        day = today.day
        try:
            async with bot.db_pool.acquire() as conn:
                # Find all birthdays for today
                rows = await conn.fetch('''
                    SELECT * FROM birthdays WHERE EXTRACT(MONTH FROM birthday) = $1 AND EXTRACT(DAY FROM birthday) = $2
                ''', month, day)
                # Group by guild
                from collections import defaultdict
                guild_birthdays = defaultdict(list)
                for row in rows:
                    guild_birthdays[row['guild_id']].append(row)
                for guild_id, bdays in guild_birthdays.items():
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                    server_row = await conn.fetchrow('''SELECT birthday_channel_id FROM servers WHERE guild_id = $1''', guild_id)
                    if not server_row or not server_row['birthday_channel_id']:
                        continue
                    channel = guild.get_channel(server_row['birthday_channel_id'])
                    if not channel:
                        continue
                    # Collect mentions/usernames
                    mentions = []
                    for row in bdays:
                        member = guild.get_member(row['user_id'])
                        mentions.append(member.mention if member else row['username'])
                    mention_str = ' '.join(mentions)
                    msg = f"Happy Birthday {mention_str}!\nFrostline wishes you the best birthday wishes!"
                    embed = discord.Embed(
                        title="🎉 Happy Birthday! 🎉",
                        description=msg,
                        color=discord.Color.magenta()
                    )
                    embed.set_footer(text="FrostMod Birthday System")
                    try:
                        await channel.send(embed=embed)
                    except Exception as e:
                        print(f"[Birthday Announce ERROR] {e}")
        except Exception as e:
            print(f"[Birthday Check ERROR] {e}")

async def rotate_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        activity_type, message = next(status_cycle)
        activity = discord.Activity(type=activity_type, name=message)
        await bot.change_presence(status=discord.Status.online, activity=activity)
        await asyncio.sleep(5)

# --- Helper Functions ---

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

import asyncio

async def is_admin(interaction):
    if interaction.user.guild_permissions.administrator or interaction.user.id == OWNER_ID:
        return True
    async with bot.db_pool.acquire() as conn:
        row = await conn.fetchrow('''SELECT mod_role_id FROM servers WHERE guild_id = $1''', interaction.guild.id)
    if row and row['mod_role_id']:
        mod_role = interaction.guild.get_role(row['mod_role_id'])
        if mod_role and mod_role in interaction.user.roles:
            print(f"[is_admin DEBUG] User has mod role: {mod_role.name}")
            return True
    return False

async def db_execute(query, *args):
    async with bot.db_pool.acquire() as conn:
        return await conn.execute(query, *args)

async def db_fetch(query, *args):
    async with bot.db_pool.acquire() as conn:
        return await conn.fetch(query, *args)

# --- Moderation Commands ---

# --- Birthday Commands ---
from discord.app_commands import describe

@bot.tree.command(name="testbirthdays", description="Test birthday announcements for today (admin only)")
async def testbirthdays(interaction: discord.Interaction):
    """Admin-only: Immediately run birthday announcement logic for this guild for today."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    import datetime
    today = datetime.date.today()
    month = today.month
    day = today.day
    try:
        async with bot.db_pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM birthdays WHERE guild_id = $1 AND EXTRACT(MONTH FROM birthday) = $2 AND EXTRACT(DAY FROM birthday) = $3
            ''', interaction.guild.id, month, day)
            if not rows:
                await interaction.response.send_message("No birthdays found for today in this server.", ephemeral=True)
                return
            server_row = await conn.fetchrow('''SELECT birthday_channel_id FROM servers WHERE guild_id = $1''', interaction.guild.id)
            if not server_row or not server_row['birthday_channel_id']:
                await interaction.response.send_message("Birthday channel is not set for this server.", ephemeral=True)
                return
            channel = interaction.guild.get_channel(server_row['birthday_channel_id'])
            if not channel:
                await interaction.response.send_message("Birthday channel not found in this server.", ephemeral=True)
                return
            mentions = []
            for row in rows:
                member = interaction.guild.get_member(row['user_id'])
                mentions.append(member.mention if member else row['username'])
            mention_str = ' '.join(mentions)
            msg = f"Happy Birthday {mention_str}!\nFrostline wishes you the best birthday wishes!"
            embed = discord.Embed(
                title="🎉 Happy Birthday! 🎉",
                description=msg,
                color=discord.Color.magenta()
            )
            embed.set_footer(text="FrostMod Birthday System")
            await channel.send(embed=embed)
            await interaction.response.send_message("Birthday announcement sent!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] {e}", ephemeral=True)

@bot.tree.command(name="delbday", description="Delete a user's birthday (admins can delete any, users can delete their own)")
@describe(user="The user whose birthday to delete")
async def delbday(interaction: discord.Interaction, user: discord.Member):
    """Delete a user's birthday. Users can delete their own, admins (or mod role) can delete any."""
    # Check if the user is deleting their own birthday or is admin
    is_self = user.id == interaction.user.id
    is_admin_user = await is_admin(interaction)
    if not (is_self or is_admin_user):
        await interaction.response.send_message("You can only delete your own birthday.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            result = await conn.execute(
                '''DELETE FROM birthdays WHERE guild_id = $1 AND user_id = $2''',
                interaction.guild.id, user.id
            )
        if result and result.startswith("DELETE"):
            print(f"[BIRTHDAY DELETED] {user} ({user.id}) in guild {interaction.guild.name} ({interaction.guild.id})")
            await interaction.response.send_message(f"Birthday for {user.display_name} deleted.", ephemeral=True)
        else:
            await interaction.response.send_message(f"No birthday found for {user.display_name}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Could not delete birthday: {e}", ephemeral=True)

@bot.tree.command(name="setbirthday", description="Set your birthday (mm/dd/yyyy)")
@describe(date="Your birthday in mm/dd/yyyy format")
async def setbirthday(interaction: discord.Interaction, date: str):
    """Allow a user to set their birthday."""
    import datetime
    try:
        # Parse date
        birthday = datetime.datetime.strptime(date, "%m/%d/%Y").date()
        # Prevent future dates
        if birthday > datetime.date.today():
            await interaction.response.send_message("Birthday cannot be in the future!", ephemeral=True)
            return
        # Insert or update birthday
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO birthdays (guild_id, guild_name, user_id, username, birthday)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    birthday = EXCLUDED.birthday
            ''',
                interaction.guild.id,
                interaction.guild.name,
                interaction.user.id,
                interaction.user.name,
                birthday
            )
        print(f"[BIRTHDAY ADDED/UPDATED] {interaction.user} ({interaction.user.id}) in guild {interaction.guild.name} ({interaction.guild.id}): {birthday}")
        await interaction.response.send_message(f"Your birthday has been set to {birthday.strftime('%B %d, %Y')}!", ephemeral=True)
    except ValueError:
        await interaction.response.send_message("Invalid date format! Please use mm/dd/yyyy.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Could not set birthday: {e}", ephemeral=True)

@bot.tree.command(name="bdaychannel", description="Set the channel for birthday announcements (admin only)")
@describe(channel="The channel to announce birthdays in")
async def bdaychannel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set the channel for birthday announcements. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to set the birthday channel.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET birthday_channel_id = $1 WHERE guild_id = $2
            ''', channel.id, interaction.guild.id)
        print(f"[DB UPDATE] servers: Set birthday_channel_id={channel.id} for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message(f"Birthday announcements will be sent in {channel.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Could not set birthday channel: {e}", ephemeral=True)

# --- Ticket System ---

@bot.tree.command(name="ticketchannel", description="Set the channel for ticket creation.")
@app_commands.describe(channel="The channel where users can create tickets.")
async def ticketchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set the channel for ticket creation. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET ticket_channel_id = $1 WHERE guild_id = $2
            ''', channel.id, interaction.guild.id)
            
            # Check if the server exists in the database, if not insert it
            server_exists = await conn.fetchval('''
                SELECT COUNT(*) FROM servers WHERE guild_id = $1
            ''', interaction.guild.id)
            
            if server_exists == 0:
                await conn.execute('''
                    INSERT INTO servers (guild_id, ticket_channel_id) VALUES ($1, $2)
                ''', interaction.guild.id, channel.id)
        
        # Create and send the ticket embed with button
        await create_ticket_embed(channel)
        
        print(f"[DB UPDATE] servers: Set ticket_channel_id={channel.id} for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message(f"Ticket channel set to {channel.mention}. A ticket creation embed has been posted in that channel.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to set ticket channel: {e}", ephemeral=True)

# Ticket Button UI
class TicketButton(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="Open Ticket", style=discord.ButtonStyle.primary, custom_id="create_ticket", emoji="❄️")
    async def create_ticket_button(self, interaction: discord.Interaction, button: ui.Button):
        # Check if user already has an open ticket
        async with bot.db_pool.acquire() as conn:
            existing_ticket = await conn.fetchrow('''
                SELECT * FROM tickets 
                WHERE guild_id = $1 AND created_by_id = $2 AND status = 'open'
            ''', interaction.guild.id, interaction.user.id)
            
            if existing_ticket:
                channel = interaction.guild.get_channel(existing_ticket['channel_id'])
                if channel:
                    await interaction.response.send_message(f"You already have an open ticket: {channel.mention}", ephemeral=True)
                    return
            
            # Create a new ticket
            await create_new_ticket(interaction)

async def create_ticket_embed(channel):
    """Create and send the ticket embed with button to the specified channel."""
    embed = discord.Embed(
        title="❄️ Frostline Support Tickets",
        description="Need assistance? Click the button below to create a support ticket.",
        color=discord.Color.from_rgb(0, 191, 255)  # Deep sky blue for Frostline branding
    )
    embed.add_field(name="How it works", value="When you create a ticket, a private channel will be created where you can discuss your issue with our staff.")
    embed.set_footer(text=f"Frostline Support System | Powered by FrostMod")
    
    # Clear existing messages if any
    try:
        await channel.purge(limit=10, check=lambda m: m.author == bot.user and "Support Ticket System" in m.content)
    except:
        pass
    
    # Send the embed with the button
    await channel.send(embed=embed, view=TicketButton())

async def create_new_ticket(interaction):
    """Create a new support ticket."""
    guild = interaction.guild
    user = interaction.user
    
    # Defer the response since ticket creation might take a moment
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Get the next ticket number for this guild
        async with bot.db_pool.acquire() as conn:
            ticket_count = await conn.fetchval('''
                SELECT COUNT(*) FROM tickets WHERE guild_id = $1
            ''', guild.id)
            
            ticket_number = ticket_count + 1
            
            # Create the ticket channel
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            
            # Add permissions for admin roles
            admin_role = None
            mod_role_id = await conn.fetchval('''
                SELECT mod_role_id FROM servers WHERE guild_id = $1
            ''', guild.id)
            
            if mod_role_id:
                mod_role = guild.get_role(mod_role_id)
                if mod_role:
                    overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
            # Create the ticket channel
            channel_name = f"ticket-{ticket_number}-{user.name}".lower().replace(' ', '-')
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                reason=f"Support ticket created by {user}"
            )
            
            # Save the ticket in the database
            await conn.execute('''
                INSERT INTO tickets (guild_id, guild_name, created_by_id, created_by_username, channel_id)
                VALUES ($1, $2, $3, $4, $5)
            ''', guild.id, guild.name, user.id, str(user), ticket_channel.id)
            
            # Create the initial ticket message
            embed = discord.Embed(
                title=f"❄️ Frostline Support | Ticket #{ticket_number}",
                description=f"Thank you for creating a ticket, {user.mention}. A staff member will assist you shortly.",
                color=discord.Color.from_rgb(0, 191, 255),  # Deep sky blue for Frostline branding
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Instructions", value="Please describe your issue in detail, and a staff member will respond as soon as possible.")
            embed.set_footer(text=f"Frostline Support | Ticket ID: {ticket_number}")
            
            # Create the close ticket button
            class CloseTicketView(ui.View):
                def __init__(self):
                    super().__init__(timeout=None)
                
                @ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id=f"close_ticket_{ticket_channel.id}", emoji="❌")
                async def close_ticket(self, close_interaction: discord.Interaction, button: ui.Button):
                    # Only staff or the ticket creator can close the ticket
                    if close_interaction.user.id != user.id and not await is_admin(close_interaction):
                        await close_interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
                        return
                    
                    await close_interaction.response.send_message("Closing ticket...", ephemeral=True)
                    
                    # Update the ticket status in the database
                    async with bot.db_pool.acquire() as close_conn:
                        await close_conn.execute('''
                            UPDATE tickets 
                            SET status = 'closed', closed_at = CURRENT_TIMESTAMP, 
                                closed_by_id = $1, closed_by_username = $2
                            WHERE channel_id = $3
                        ''', close_interaction.user.id, str(close_interaction.user), ticket_channel.id)
                    
                    # Send a closing message
                    closing_embed = discord.Embed(
                        title="❄️ Ticket Closed",
                        description=f"This ticket has been closed by {close_interaction.user.mention}.",
                        color=discord.Color.from_rgb(220, 20, 60),  # Crimson red for closed tickets
                        timestamp=discord.utils.utcnow()
                    )
                    closing_embed.add_field(name="Ticket Information", value=f"This channel will be deleted in 10 seconds.")
                    closing_embed.set_footer(text="Frostline Support System | Thank you for using our services")
                    await ticket_channel.send(embed=closing_embed)
                    
                    # Always delete the channel after a delay
                    await asyncio.sleep(10)  # Give users time to see the closing message
                    try:
                        await ticket_channel.delete(reason="Ticket closed")
                    except Exception as e:
                        print(f"Error deleting ticket channel: {e}")
            
            # Send the welcome message with close button
            await ticket_channel.send(f"{user.mention} {guild.default_role.mention}", embed=embed, view=CloseTicketView())
            
            # Notify the user
            await interaction.followup.send(f"Your ticket has been created: {ticket_channel.mention}", ephemeral=True)
            
    except Exception as e:
        print(f"Error creating ticket: {e}")
        await interaction.followup.send(f"Error creating ticket: {e}", ephemeral=True)

# --- Utility Commands ---
@bot.tree.command(name="status", description="Show bot ping and uptime.")
async def status(interaction: discord.Interaction):
    """Show bot ping and uptime."""
    import datetime
    # Ping in ms
    ping = round(bot.latency * 1000)
    # Uptime calculation
    now = datetime.datetime.now(datetime.timezone.utc)
    delta = now - bot.start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime = f"{days}d {hours}h {minutes}m {seconds}s"
    embed = discord.Embed(title="Bot Status", color=discord.Color.blue())
    embed.add_field(name="Ping", value=f"{ping} ms", inline=True)
    embed.add_field(name="Uptime", value=uptime, inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="mrole", description="Set the moderator role that can use admin commands.")
@app_commands.describe(role="The role to grant moderator permissions.")
async def mrole(interaction: discord.Interaction, role: discord.Role):
    """Set the moderator role for this server."""
    if not interaction.user.guild_permissions.administrator and interaction.user.id != OWNER_ID:
        await interaction.response.send_message("You must be an administrator or the bot owner to set the mod role.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''UPDATE servers SET mod_role_id = $1 WHERE guild_id = $2''', role.id, interaction.guild.id)
        print(f"[DB UPDATE] servers: Set mod_role_id={role.id} for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message(f"Mod role set to {role.mention}. Members with this role can now use admin commands.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to set mod role: {e}", ephemeral=True)

@bot.tree.command(name="warn", description="Warn a user with a reason (admin only)")
@app_commands.describe(user="The user to warn", reason="The reason for the warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Warn a user in the server and log the reason. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        await db_execute(
            '''INSERT INTO warns (guild_id, guild_name, user_id, username, reason) VALUES ($1, $2, $3, $4, $5)''',
            interaction.guild.id, interaction.guild.name, user.id, user.display_name, reason
        )
        print(f"[DB INSERT] warns: {user} ({user.id}) warned by {interaction.user} ({interaction.user.id}) in guild {interaction.guild.name} ({interaction.guild.id}) for reason: {reason}")
        await interaction.response.send_message(f"Warned {user.mention} for: {reason}", ephemeral=False)
        # Log to server's logs channel if set
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', interaction.guild.id)
        if row and row['logs_channel_id']:
            log_channel = interaction.guild.get_channel(row['logs_channel_id'])
            if log_channel:
                embed = discord.Embed(
                    title="User Warned",
                    description=f"**User:** {user.mention}\n**Moderator:** {interaction.user.mention}\n**Reason:** {reason}",
                    color=discord.Color.orange()
                )
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else discord.Embed.Empty)
                embed.set_thumbnail(url=user.display_avatar.url)
                await log_channel.send(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to warn user: {e}", ephemeral=True)

@bot.tree.command(name="delwarns", description="Delete all warnings for a user in this server (admin only)")
@app_commands.describe(user="The user to delete warnings for")
async def delwarns(interaction: discord.Interaction, user: discord.Member):
    """Delete all warnings for a specific user in this server. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        result = await db_execute(
            '''DELETE FROM warns WHERE guild_id = $1 AND user_id = $2''',
            interaction.guild.id, user.id
        )
        print(f"[DB DELETE] warns: All warnings for {user} ({user.id}) in guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message(f"All warnings for {user.mention} have been deleted.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to delete warnings: {e}", ephemeral=True)

@bot.tree.command(name="warns", description="List all warnings for a user in this server (admin only)")
@app_commands.describe(user="The user to list warnings for")
async def warns(interaction: discord.Interaction, user: discord.Member):
    """List all warnings for a specific user in this server. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        rows = await db_fetch(
            '''SELECT reason, warned_at FROM warns WHERE guild_id = $1 AND user_id = $2 ORDER BY warned_at DESC''',
            interaction.guild.id, user.id
        )
        warns_count = len(rows)
        if warns_count == 0:
            await interaction.response.send_message(f"{user.mention} has no warnings in this server.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Warnings for {user.display_name}",
            description=f"Total warnings: {warns_count}",
            color=discord.Color.orange()
        )
        for row in rows:
            embed.add_field(
                name=row['warned_at'].strftime('%Y-%m-%d %H:%M:%S'),
                value=f"Reason: {row['reason']}",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to fetch warnings: {e}", ephemeral=True)

@bot.event
async def on_member_join(member):
    print("on_member_join fired!")  # Basic log for testing
    try:
        async with bot.db_pool.acquire() as conn:
            # Upsert the guild first
            await conn.execute('''
                INSERT INTO servers (guild_id, guild_name) VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE SET guild_name = EXCLUDED.guild_name
            ''', member.guild.id, member.guild.name)
            print(f"[DB UPSERT] servers: {member.guild.name} ({member.guild.id})")
            # Now log the join
            await conn.execute('''
                INSERT INTO user_joins (guild_id, user_id, username) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, user_id) DO NOTHING
            ''', member.guild.id, member.id, str(member))
            print(f"[DB INSERT] user_joins: {member} ({member.id}) in guild {member.guild.name} ({member.guild.id})")
            # Fetch welcome channel, message, and join role
            row = await conn.fetchrow('''
                SELECT welcome_channel_id, welcome_message, join_role_id FROM servers WHERE guild_id = $1
            ''', member.guild.id)
            # Assign join role if set
            if row and row['join_role_id']:
                role = member.guild.get_role(row['join_role_id'])
                if role:
                    try:
                        await member.add_roles(role, reason="Auto join role")
                    except Exception as e:
                        print(f"Error assigning join role: {e}")
            # Send welcome message if set
            if row and row['welcome_channel_id'] and row['welcome_message']:
                channel = member.guild.get_channel(row['welcome_channel_id'])
                if channel:
                    welcome_msg = row['welcome_message'].replace('{user}', member.mention).replace('{membercount}', str(member.guild.member_count))
                    embed = discord.Embed(description=welcome_msg, color=discord.Color.blue())
                    if member.guild.icon:
                        embed.set_thumbnail(url=member.guild.icon.url)
                    embed.set_author(name=member.guild.name)
                    await channel.send(embed=embed)
            print(f"Logged join: {member} in guild {member.guild.name}")
    except Exception as e:
        print(f"Error logging join for {member} in guild {member.guild.name}: {e}")

# ------------------------------
# Server Configuration Commands
# ------------------------------

@bot.tree.command(name="welcome", description="Set the welcome channel for this server.")
@app_commands.describe(channel="The channel to send welcome messages in.")
async def welcome(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set the channel for welcome messages. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET welcome_channel_id = $1 WHERE guild_id = $2
            ''', channel.id, interaction.guild.id)
        print(f"[DB UPDATE] servers: Set welcome_channel_id={channel.id} for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message(f"Welcome channel set to {channel.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to set welcome channel: {e}", ephemeral=True)

@bot.tree.command(name="wmessage", description="Set the welcome message for this server.")
@app_commands.describe(message="The welcome message to send. Use {user} for the new member, {membercount} for the member count.")
async def wmessage(interaction: discord.Interaction, message: str):
    """Set the welcome message for new members. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET welcome_message = $1 WHERE guild_id = $2
            ''', message, interaction.guild.id)
        print(f"[DB UPDATE] servers: Set welcome_message for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message("Welcome message updated!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to update welcome message: {e}", ephemeral=True)

@bot.tree.command(name="joinrole", description="Set a role to assign to new members on join.")
@app_commands.describe(role="The role to assign to new members.")
async def joinrole(interaction: discord.Interaction, role: discord.Role):
    """Set the role to assign to new members. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET join_role_id = $1 WHERE guild_id = $2
            ''', role.id, interaction.guild.id)
        print(f"[DB UPDATE] servers: Set join_role_id={role.id} for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message(f"Join role set to {role.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to set join role: {e}", ephemeral=True)

@bot.tree.command(name="logschannel", description="Set the logging channel for this server.")
@app_commands.describe(channel="The channel to send logs in.")
async def logschannel(interaction: discord.Interaction, channel: discord.TextChannel):
    # Only allow admins
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET logs_channel_id = $1 WHERE guild_id = $2
            ''', channel.id, interaction.guild.id)
        print(f"[DB UPDATE] servers: Set logs_channel_id={channel.id} for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message(f"Logging channel set to {channel.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to set logging channel: {e}", ephemeral=True)


@bot.tree.command(name="avatar", description="Show a user's profile picture.")
@app_commands.describe(user="The user to get the avatar of (optional)")
async def avatar(interaction: discord.Interaction, user: discord.User = None):
    user = user or interaction.user
    embed = discord.Embed(title=f"{user.display_name}'s Avatar")
    embed.set_image(url=user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help", description="Show help for FrostMod commands.")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="❄️ FrostMod Help Center",
        description="""
━━━━━━━━━━━━━━━━━━━━━━━━━━
Welcome to **FrostMod**! Here are all the commands you can use.
━━━━━━━━━━━━━━━━━━━━━━━━━━

> **Tip:** Use `/command` in chat. `<angle brackets>` = required, `[square brackets]` = optional.
        """,
        color=discord.Color.from_rgb(0, 183, 255)  # Frost/cyan blue
    )
    embed.set_thumbnail(url=interaction.client.user.display_avatar.url if interaction.client.user.display_avatar else discord.Embed.Empty)

    admin_cmds = (
        "🛡️ **/warn** `<user>` `<reason>`\nWarn a user and log the reason. Example: `/warn @User Spamming`.\n\n"
        "🛡️ **/warns** `<user>`\nView all warnings for a user.\n\n"
        "🛡️ **/delwarns** `<user>`\nDelete all warnings for a user.\n\n"
        "🧹 **/purge** `<amount>`\nBulk delete messages (1-100) from this channel.\n\n"
        "🧹 **/purgeuser** `<user>` `<amount>`\nDelete up to 100 messages from a specific user.\n\n"
        "🛡️ **/mrole** `<role>`\nSet the moderator role for admin commands.\n\n"
        "👋 **/welcome** `<channel>`\nSet the welcome channel.\n\n"
        "💬 **/wmessage** `<message>`\nSet the welcome message. Use `{user}` and `{membercount}`.\n\n"
        "🎉 **/bdaychannel** `<channel>`\nSet the birthday announcement channel.\n\n"
        "📋 **/logschannel** `<channel>`\nSet the moderation logs channel.\n\n"
        "🎭 **/joinrole** `<role>`\nAssign a role to new members."
    )

    birthday_cmds = (
        "🎂 **/setbirthday** `<mm/dd/yyyy>`\nSet your birthday for server birthday announcements.\n\n"
        "🎉 **/testbirthdays**\n(Admin) Test birthday announcements for today.\n\n"
        "🎂 **/delbday** `<user>`\nDelete a user's birthday. Users can delete their own; admins/mods can delete anyone's."
    )

    util_cmds = (
        "🖼️ **/avatar** `[user]`\nShow a user's profile picture.\n\n"
        "🆘 **/support**\nGet a link to the Frostline support Discord.\n\n"
        "📈 **/status**\nShow the bot's ping and uptime.\n\n"
        "❄️ **/help**\nShow this help message."
    )

    embed.add_field(name="━━━━━━━━ 🛡️ Admin/Mod Commands ━━━━━━━━", value=admin_cmds, inline=False)
    embed.add_field(name="━━━━━━━━ 🎂 Birthday Commands ━━━━━━━━", value=birthday_cmds, inline=False)
    embed.add_field(name="━━━━━━━━ 🔧 Utility Commands ━━━━━━━━", value=util_cmds, inline=False)
    embed.set_footer(text="FrostMod • Need help? Use /support or join the support server!", icon_url=interaction.client.user.display_avatar.url if interaction.client.user.display_avatar else discord.Embed.Empty)
    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(name="support", description="Get support for the bot.")
async def support(interaction: discord.Interaction):
    embed = discord.Embed(
        title="FrostMod Support",
        description="Get bot support from The bot's development team at the official Frostline Discord: https://discord.gg/BjbUXwFF6n",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)



@bot.tree.command(name="purge", description="Delete a specified number of messages from the channel (admin only)")
@app_commands.describe(amount="The number of messages to delete (1-100)")
async def purge(interaction: discord.Interaction, amount: int):
    """Delete a specified number of messages from the channel. Admin only."""
    if not is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
        
    # Validate the amount
    if amount < 1 or amount > 100:
        await interaction.response.send_message("You can only delete between 1 and 100 messages at a time.", ephemeral=True)
        return
        
    # Defer the response since purging might take some time
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Bulk delete messages (only works for messages <14 days old)
        deleted = await interaction.channel.purge(limit=amount)
        deleted_count = len(deleted)

        # If fewer messages were deleted than requested, try to delete older messages one-by-one
        if deleted_count < amount:
            # Fetch messages again, skipping those already deleted
            to_delete = []
            async for msg in interaction.channel.history(limit=amount*2):
                if msg not in deleted and not msg.pinned:
                    to_delete.append(msg)
                if len(to_delete) >= (amount - deleted_count):
                    break
            # Delete individually with delay to avoid rate limits
            import logging
            for msg in to_delete:
                try:
                    await msg.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.7)  # 700ms between deletes
                except discord.errors.HTTPException as e:
                    if e.status == 429:
                        retry_after = getattr(e, 'retry_after', None)
                        if retry_after is None:
                            # Try to parse from response if available
                            retry_after = getattr(e.response, 'headers', {}).get('Retry-After')
                            try:
                                retry_after = float(retry_after)
                            except (TypeError, ValueError):
                                retry_after = 2.0  # fallback
                        logging.warning(f"Rate limited while deleting message. Sleeping for {retry_after} seconds.")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logging.error(f"Failed to delete message: {e}")
                        continue

        # Send confirmation
        await interaction.followup.send(f"Successfully deleted {deleted_count} messages.", ephemeral=True)
        
        # Log to server's logs channel if set
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', interaction.guild.id)
        if row and row['logs_channel_id']:
            log_channel = interaction.guild.get_channel(row['logs_channel_id'])
            if log_channel:
                embed = discord.Embed(
                    title="Messages Purged",
                    description=f"**Channel:** {interaction.channel.mention}\n**Amount:** {deleted_count} messages\n**Moderator:** {interaction.user.mention}",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else discord.Embed.Empty)
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                await log_channel.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to delete messages in this channel.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"An error occurred while purging messages: {e}", ephemeral=True)

@bot.tree.command(name="purgeuser", description="Delete a specified number of messages from a specific user (admin only)")
@app_commands.describe(
    user="The user whose messages to delete",
    amount="The number of messages to check (1-100)"
)
async def purgeuser(interaction: discord.Interaction, user: discord.Member, amount: int):
    """Delete a specified number of messages from a specific user in the channel. Admin only."""
    if not is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
        
    # Validate the amount
    if amount < 1 or amount > 100:
        await interaction.response.send_message("You can only check between 1 and 100 messages at a time.", ephemeral=True)
        return
        
    # Defer the response since purging might take some time
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Define a check function to filter messages by the specified user
        def check_user(message):
            return message.author.id == user.id
            
        # Delete messages from the specified user
        deleted = await interaction.channel.purge(limit=amount, check=check_user)
        
        # Send confirmation
        await interaction.followup.send(f"Successfully deleted {len(deleted)} messages from {user.mention}.", ephemeral=True)
        
        # Log to server's logs channel if set
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', interaction.guild.id)
        if row and row['logs_channel_id']:
            log_channel = interaction.guild.get_channel(row['logs_channel_id'])
            if log_channel:
                embed = discord.Embed(
                    title="User Messages Purged",
                    description=f"**Channel:** {interaction.channel.mention}\n**User:** {user.mention}\n**Amount:** {len(deleted)} messages\n**Moderator:** {interaction.user.mention}",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else discord.Embed.Empty)
                embed.set_thumbnail(url=user.display_avatar.url)
                await log_channel.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to delete messages in this channel.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"An error occurred while purging messages: {e}", ephemeral=True)

@bot.event
async def on_member_remove(member):
    # Log member leave
    try:
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', member.guild.id)
        if row and row['logs_channel_id']:
            channel = member.guild.get_channel(row['logs_channel_id'])
            if channel:
                embed = discord.Embed(description=f"{member.mention} has left the server.", color=discord.Color.red())
                embed.set_author(name=member.guild.name)
                await channel.send(embed=embed)
    except Exception as e:
        print(f"Error logging member leave: {e}")

@bot.event
async def on_guild_channel_create(channel):
    # Log channel creation with executor
    if not hasattr(channel, 'guild'):
        return
    try:
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', channel.guild.id)
        if row and row['logs_channel_id']:
            log_channel = channel.guild.get_channel(row['logs_channel_id'])
            if log_channel:
                # Try to get the user who created the channel from audit logs
                executor = None
                async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
                    if entry.target.id == channel.id:
                        executor = entry.user
                        break
                embed = discord.Embed(
                    title="Channel Created",
                    description=f"**Channel:** {channel.mention}",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                if executor:
                    embed.add_field(name="Created by", value=f"{executor} ({executor.id})", inline=True)
                    embed.set_thumbnail(url=executor.display_avatar.url)
                else:
                    embed.add_field(name="Created by", value="Unknown", inline=True)
                embed.set_author(name=channel.guild.name, icon_url=channel.guild.icon.url if channel.guild.icon else discord.Embed.Empty)
                await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Error logging channel creation: {e}")

@bot.event
async def on_guild_channel_delete(channel):
    # Log channel deletion with executor
    if not hasattr(channel, 'guild'):
        return
    try:
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', channel.guild.id)
        if row and row['logs_channel_id']:
            log_channel = channel.guild.get_channel(row['logs_channel_id'])
            if log_channel:
                # Try to get the user who deleted the channel from audit logs
                executor = None
                async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
                    if entry.target.id == channel.id:
                        executor = entry.user
                        break
                embed = discord.Embed(
                    title="Channel Deleted",
                    description=f"**Channel:** #{channel.name}",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                if executor:
                    embed.add_field(name="Deleted by", value=f"{executor} ({executor.id})", inline=True)
                    embed.set_thumbnail(url=executor.display_avatar.url)
                else:
                    embed.add_field(name="Deleted by", value="Unknown", inline=True)
                embed.set_author(name=channel.guild.name, icon_url=channel.guild.icon.url if channel.guild.icon else discord.Embed.Empty)
                await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Error logging channel deletion: {e}")

@bot.event
async def on_user_update(before, after):
    # Check if username or avatar changed
    username_changed = before.name != after.name
    avatar_changed = before.avatar != after.avatar
    
    # Only proceed if something changed
    if not (username_changed or avatar_changed):
        return
    
    # Log changes to all servers this user is in
    for guild in bot.guilds:
        # Check if user is in this guild
        member = guild.get_member(after.id)
        if not member:
            continue
            
        try:
            # Check if this guild has a logs channel set
            async with bot.db_pool.acquire() as conn:
                row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', guild.id)
            
            if row and row['logs_channel_id']:
                log_channel = guild.get_channel(row['logs_channel_id'])
                if log_channel:
                    # Create embed for the change
                    embed = discord.Embed(
                        title="User Updated",
                        color=discord.Color.blue(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_author(name=f"{after}", icon_url=after.display_avatar.url)
                    
                    # Add fields based on what changed
                    if username_changed:
                        embed.add_field(name="Username Changed", value=f"**Before:** {before.name}\n**After:** {after.name}", inline=False)
                    
                    if avatar_changed:
                        embed.add_field(name="Avatar Changed", value="User updated their profile picture", inline=False)
                        if before.avatar:
                            embed.set_thumbnail(url=before.avatar.url)
                        embed.set_image(url=after.display_avatar.url)
                    
                    # Send the embed to the logs channel
                    await log_channel.send(embed=embed)
        except Exception as e:
            print(f"Error logging user update: {e}")

# Persistent views for ticket buttons
@bot.event
async def on_ready():
    print("Bot is ready. Starting status rotation.")
    bot.loop.create_task(rotate_status())
    bot.loop.create_task(daily_birthday_check())
    
    # Add persistent view for ticket buttons
    bot.add_view(TicketButton())
    
    # Initialize database tables if they don't exist
    try:
        async with bot.db_pool.acquire() as conn:
            # Create servers table if it doesn't exist
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS servers (
                    guild_id BIGINT PRIMARY KEY,
                    welcome_channel_id BIGINT,
                    welcome_message TEXT,
                    join_role_id BIGINT,
                    logs_channel_id BIGINT,
                    mod_role_id BIGINT,
                    birthday_channel_id BIGINT,
                    ticket_channel_id BIGINT
                )
            ''')
            
            # Create warnings table if it doesn't exist
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS warnings (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    moderator_id BIGINT,
                    reason TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create birthdays table if it doesn't exist
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS birthdays (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    birthday DATE,
                    UNIQUE(guild_id, user_id)
                )
            ''')
            
            # Create tickets table if it doesn't exist
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    guild_name VARCHAR(100) NOT NULL,
                    created_by_id BIGINT NOT NULL,
                    created_by_username VARCHAR(100) NOT NULL,
                    closed_by_id BIGINT,
                    closed_by_username VARCHAR(100),
                    channel_id BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    status VARCHAR(20) DEFAULT 'open'
                )
            ''')
            
            # Create indexes for faster lookups
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_tickets_guild_id ON tickets(guild_id)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_tickets_created_by_id ON tickets(created_by_id)')
            
            print("Database tables initialized successfully!")
    except Exception as e:
        print(f"Error initializing database tables: {e}")

if __name__ == "__main__":
    bot.run(TOKEN)