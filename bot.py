import os
import discord
import asyncio
import logging
import datetime
from itertools import cycle
from collections import defaultdict
from discord import app_commands, ui
from discord.ext import commands
import asyncpg
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('frostmod')

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

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

status_messages = [
    (discord.ActivityType.watching, "👀 Frostline Users"),
    (discord.ActivityType.playing, "❄️ Enhancing Server Moderation"),
    (discord.ActivityType.watching, "❓ for /help")
]
status_cycle = cycle(status_messages)

@bot.event
async def on_ready():
    logger.info(f"{bot.user.name} is ready. Connected to {len(bot.guilds)} guilds.")
    
    # Start background tasks
    bot.loop.create_task(rotate_status())
    bot.loop.create_task(daily_birthday_check())
    
    # Add persistent view for ticket buttons
    bot.add_view(TicketButton())
    
    # Log registered commands for debugging
    commands_registered = list(bot.tree.get_commands())
    logger.info(f"Registered {len(commands_registered)} slash commands")
    for cmd in commands_registered:
        logger.info(f"- /{cmd.name}: {cmd.description}")

async def daily_birthday_check():
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
                        logger.error(f"Birthday Announce ERROR: {e}")
        except Exception as e:
            logger.error(f"Birthday Check ERROR: {e}")

async def rotate_status():
    await bot.wait_until_ready()
    while not bot.is_closed():
        activity_type, message = next(status_cycle)
        activity = discord.Activity(type=activity_type, name=message)
        try:
            await bot.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            logger.exception(f"Status Rotation Error: Failed to change presence: {e}")
        await asyncio.sleep(60)  # Changed to 60 seconds to reduce API calls


# --- Helper Functions ---

# --- Chat Filter Wordlists ---
# These sets contain filtered words with different severity levels
# Words are stored in lowercase for case-insensitive matching
STRICT_WORDS = {
    # General profanity, mild offensive terms
    "fuck", "shit", "bitch", "fck", "whore", "ass", "damn", "bastard"
}

MODERATE_WORDS = {
    # More severe offensive terms and slurs
    "nigger", "wetback", "tranny", "rape", "cuck", "slut", "faggot"
}

LIGHT_WORDS = {
    # Most severe hate speech and slurs
    "nigger", "kike", "chink", "retard", "spic"
}

# Convert all words to lowercase for case-insensitive matching
STRICT_WORDS = {word.lower() for word in STRICT_WORDS}
MODERATE_WORDS = {word.lower() for word in MODERATE_WORDS}
LIGHT_WORDS = {word.lower() for word in LIGHT_WORDS}

def check_message_for_filter(message_content, filter_level):
    """Check if a message contains filtered words based on the filter level.
    
    Args:
        message_content (str): The message content to check
        filter_level (str): The filter level ('strict', 'moderate', or 'light')
        
    Returns:
        tuple: (bool, str) - Whether the message is blocked and the offending word if any
    """
    if not message_content or not filter_level:
        return False, None
        
    lowered = message_content.lower()
    
    # Use sets for more efficient lookups
    if filter_level == 'strict':
        for word in STRICT_WORDS | MODERATE_WORDS | LIGHT_WORDS:
            if word.lower() in lowered:
                return True, word
    elif filter_level == 'moderate':
        for word in MODERATE_WORDS | LIGHT_WORDS:
            if word.lower() in lowered:
                return True, word
    elif filter_level == 'light':
        for word in LIGHT_WORDS:
            if word.lower() in lowered:
                return True, word
    return False, None

async def get_filter_level(guild_id):
    """Get the filter level for a guild.
    
    Args:
        guild_id (int): The guild ID
        
    Returns:
        str: The filter level ('strict', 'moderate', or 'light')
    """
    try:
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT filter_level FROM servers WHERE guild_id = $1''', guild_id)
        return row['filter_level'] if row and row['filter_level'] else 'light'
    except Exception as e:
        logger.error(f"Error getting filter level for guild {guild_id}: {e}")
        return 'light'  # Default to light filtering if there's an error

async def set_filter_level(guild_id, level, guild_name=None):
    """Set the filter level for a guild.
    
    Args:
        guild_id (int): The guild ID
        level (str): The filter level to set
        guild_name (str, optional): The guild name
    """
    try:
        async with bot.db_pool.acquire() as conn:
            # Use upsert pattern for cleaner code
            await conn.execute('''
                INSERT INTO servers (guild_id, guild_name, filter_level) 
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id) 
                DO UPDATE SET filter_level = $3, guild_name = COALESCE($2, servers.guild_name)
            ''', guild_id, guild_name or "Unknown", level)
        logger.info(f"Set filter_level={level} for guild {guild_id}")
    except Exception as e:
        logger.error(f"Error setting filter level for guild {guild_id}: {e}")

# Helper functions for permission checks

async def is_admin(interaction):
    """Check if a user has admin permissions.
    
    Args:
        interaction (discord.Interaction): The interaction object
        
    Returns:
        bool: Whether the user has admin permissions
    """
    # First check for administrator permission or bot owner
    if interaction.user.guild_permissions.administrator or interaction.user.id == OWNER_ID:
        return True
        
    try:
        # Then check for mod role
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT mod_role_id FROM servers WHERE guild_id = $1''', interaction.guild.id)
        
        if row and row['mod_role_id']:
            mod_role = interaction.guild.get_role(row['mod_role_id'])
            if mod_role and mod_role in interaction.user.roles:
                logger.debug(f"User {interaction.user.name} has mod role: {mod_role.name}")
                return True
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        # Fall back to just checking administrator permission if DB fails
        return interaction.user.guild_permissions.administrator
        
    return False

async def db_execute(query, *args):
    """Execute a database query.
    
    Args:
        query (str): The SQL query to execute
        *args: The arguments for the query
        
    Returns:
        str: The result of the query execution
    """
    try:
        async with bot.db_pool.acquire() as conn:
            return await conn.execute(query, *args)
    except Exception as e:
        logger.error(f"Database execute error: {e}\nQuery: {query}\nArgs: {args}")
        raise

async def db_fetch(query, *args):
    """Fetch results from a database query.
    
    Args:
        query (str): The SQL query to execute
        *args: The arguments for the query
        
    Returns:
        list: The results of the query
    """
    try:
        async with bot.db_pool.acquire() as conn:
            return await conn.fetch(query, *args)
    except Exception as e:
        logger.error(f"Database fetch error: {e}\nQuery: {query}\nArgs: {args}")
        raise

# --- Moderation Commands ---

from discord import app_commands

@bot.tree.command(name="filter", description="Set the chat filter level for this server (admin only)")
@app_commands.describe(level="Filter level: light, moderate, or strict")
@app_commands.choices(level=[
    app_commands.Choice(name="Light (only blocks egregious text)", value="light"),
    app_commands.Choice(name="Moderate (no slurs)", value="moderate"),
    app_commands.Choice(name="Strict (fully family friendly)", value="strict")
])
async def filter_command(interaction: discord.Interaction, level: app_commands.Choice[str]):
    """Admin-only: Set the chat filter level for this server."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    await set_filter_level(interaction.guild.id, level.value, interaction.guild.name)
    await interaction.response.send_message(f"Chat filter level set to **{level.value}**.", ephemeral=True)

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
    try:
        # Parse date
        birthday = datetime.datetime.strptime(date, "%m/%d/%Y").date()
        
        # Validate the date
        today = datetime.date.today()
        
        # Prevent future dates
        if birthday > today:
            await interaction.response.send_message("Birthday cannot be in the future!", ephemeral=True)
            return
            
        # Reasonable age check (older than 120 years is unlikely)
        years_ago = today.replace(year=today.year - 120)
        if birthday < years_ago:
            await interaction.response.send_message("Please enter a valid birthday. The date you entered is too far in the past.", ephemeral=True)
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
        
        logger.info(f"Birthday added/updated for {interaction.user} ({interaction.user.id}) in guild {interaction.guild.name}: {birthday}")
        
        # Send confirmation with formatted date
        formatted_date = birthday.strftime('%B %d, %Y')
        embed = discord.Embed(
            title="Birthday Set",
            description=f"Your birthday has been set to **{formatted_date}**!",
            color=discord.Color.magenta()
        )
        embed.set_footer(text="You'll receive birthday wishes on your special day!")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except ValueError:
        await interaction.response.send_message("Invalid date format! Please use mm/dd/yyyy (for example: 12/25/2000).", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in setbirthday command: {e}")
        await interaction.response.send_message("An error occurred while setting your birthday. Please try again later.", ephemeral=True)

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
    """Handle member join events - log to database, assign roles, and send welcome messages."""
    logger.info(f"Member joined: {member} ({member.id}) in guild {member.guild.name} ({member.guild.id})")
    
    try:
        async with bot.db_pool.acquire() as conn:
            # Upsert the guild first
            await conn.execute('''
                INSERT INTO servers (guild_id, guild_name) VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE SET guild_name = EXCLUDED.guild_name
            ''', member.guild.id, member.guild.name)
            
            # Log the join event to database
            await conn.execute('''
                INSERT INTO user_joins (guild_id, user_id, username, joined_at) 
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET 
                    username = EXCLUDED.username,
                    joined_at = EXCLUDED.joined_at
            ''', member.guild.id, member.id, str(member), discord.utils.utcnow())
            
            # Fetch server configuration
            row = await conn.fetchrow('''
                SELECT welcome_channel_id, welcome_message, join_role_id, logs_channel_id 
                FROM servers WHERE guild_id = $1
            ''', member.guild.id)
            
            if not row:
                return
                
            # Assign join role if set
            if row['join_role_id']:
                role = member.guild.get_role(row['join_role_id'])
                if role:
                    try:
                        await member.add_roles(role, reason="Auto join role")
                        logger.info(f"Assigned role {role.name} to {member} in {member.guild.name}")
                    except Exception as e:
                        logger.error(f"Error assigning join role to {member}: {e}")
            
            # Send welcome message if set
            if row['welcome_channel_id'] and row['welcome_message']:
                channel = member.guild.get_channel(row['welcome_channel_id'])
                if channel:
                    try:
                        # Format welcome message with user mention and member count
                        welcome_msg = row['welcome_message']
                        welcome_msg = welcome_msg.replace('{user}', member.mention)
                        welcome_msg = welcome_msg.replace('{membercount}', str(member.guild.member_count))
                        welcome_msg = welcome_msg.replace('{servername}', member.guild.name)
                        
                        # Create and send welcome embed
                        embed = discord.Embed(
                            title=f"Welcome to {member.guild.name}!",
                            description=welcome_msg,
                            color=discord.Color.blue(),
                            timestamp=discord.utils.utcnow()
                        )
                        
                        # Add user avatar and server icon
                        embed.set_thumbnail(url=member.display_avatar.url)
                        if member.guild.icon:
                            embed.set_author(name=member.guild.name, icon_url=member.guild.icon.url)
                        else:
                            embed.set_author(name=member.guild.name)
                            
                        embed.set_footer(text=f"Member #{member.guild.member_count}")
                        
                        await channel.send(embed=embed)
                        logger.info(f"Sent welcome message for {member} in {member.guild.name}")
                    except Exception as e:
                        logger.error(f"Error sending welcome message for {member}: {e}")
            
            # Log to server's logs channel if set
            if row['logs_channel_id']:
                log_channel = member.guild.get_channel(row['logs_channel_id'])
                if log_channel:
                    try:
                        # Create member join log embed
                        embed = discord.Embed(
                            title="Member Joined",
                            description=f"{member.mention} joined the server",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        
                        # Add user information
                        embed.add_field(name="User ID", value=member.id, inline=True)
                        embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, style='R'), inline=True)
                        
                        # Check if account is new (less than 7 days old)
                        account_age = (discord.utils.utcnow() - member.created_at).days
                        if account_age < 7:
                            embed.add_field(name="⚠️ New Account", value=f"Account created {account_age} days ago", inline=False)
                        
                        embed.set_thumbnail(url=member.display_avatar.url)
                        embed.set_footer(text=f"Member #{member.guild.member_count}")
                        
                        await log_channel.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Error sending join log for {member}: {e}")
                        
    except Exception as e:
        logger.error(f"Error processing member join for {member} in {member.guild.name}: {e}")

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
    """Display a comprehensive help menu with all available commands."""
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

    # Server Configuration Commands
    config_cmds = (
        "⚙️ **/mrole** `<role>`\nSet the moderator role for admin commands.\n\n"
        "🔍 **/filter** `<level>`\nSet chat filter level (light, moderate, strict).\n\n"
        "👋 **/welcome** `<channel>`\nSet the welcome channel for new members.\n\n"
        "💬 **/wmessage** `<message>`\nSet the welcome message. Use `{user}`, `{membercount}`, `{servername}`.\n\n"
        "🎭 **/joinrole** `<role>`\nSet the role automatically assigned to new members.\n\n"
        "📋 **/logschannel** `<channel>`\nSet the channel for event and moderation logs.\n\n"
        "🎫 **/ticketchannel** `<channel>`\nSet the channel for ticket creation.\n\n"
        "🎉 **/bdaychannel** `<channel>`\nSet the birthday announcement channel."
    )

    # Moderation Commands
    mod_cmds = (
        "🛡️ **/warn** `<user>` `<reason>`\nWarn a user and log the reason.\n\n"
        "🛡️ **/warns** `<user>`\nView all warnings for a specific user.\n\n"
        "🛡️ **/delwarns** `<user>`\nDelete all warnings for a specific user.\n\n"
        "🧹 **/purge** `<amount>`\nDelete up to 100 messages from the current channel.\n\n"
        "🧹 **/purgeuser** `<user>` `<amount>`\nDelete up to 100 messages from a specific user."
    )

    # Birthday System Commands
    birthday_cmds = (
        "🎂 **/setbirthday** `<mm/dd/yyyy>`\nSet your birthday for server announcements.\n\n"
        "🎂 **/delbday** `<user>`\nDelete a birthday (users can delete their own; admins can delete any).\n\n"
        "🎉 **/testbirthdays**\nTest birthday announcements for the current day."
    )

    # Utility Commands
    util_cmds = (
        "🖼️ **/avatar** `[user]`\nShow a user's profile picture.\n\n"
        "📈 **/status**\nDisplay bot uptime and latency.\n\n"
        "🆘 **/support**\nGet a link to the Frostline support server.\n\n"
        "❄️ **/help**\nShow this help message."
    )

    embed.add_field(name="━━━━━━━━ ⚙️ Server Configuration ━━━━━━━━", value=config_cmds, inline=False)
    embed.add_field(name="━━━━━━━━ 🛡️ Moderation Tools ━━━━━━━━", value=mod_cmds, inline=False)
    embed.add_field(name="━━━━━━━━ 🎂 Birthday System ━━━━━━━━", value=birthday_cmds, inline=False)
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
    # Fix: await the is_admin check
    if not await is_admin(interaction):
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
            for msg in to_delete:
                try:
                    await msg.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.7)  # 700ms between deletes
                except discord.errors.HTTPException as e:
                    if e.status == 429:
                        retry_after = getattr(e, 'retry_after', 2.0)
                        logger.warning(f"Rate limited while deleting message. Sleeping for {retry_after} seconds.")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"Failed to delete message: {e}")
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
    # Fix: await the is_admin check
    if not await is_admin(interaction):
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
        deleted_count = len(deleted)
        
        # Send confirmation
        await interaction.followup.send(f"Successfully deleted {deleted_count} messages from {user.mention}.", ephemeral=True)
        
        # Log to server's logs channel if set
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', interaction.guild.id)
        if row and row['logs_channel_id']:
            log_channel = interaction.guild.get_channel(row['logs_channel_id'])
            if log_channel:
                embed = discord.Embed(
                    title="User Messages Purged",
                    description=f"**Channel:** {interaction.channel.mention}\n**User:** {user.mention}\n**Amount:** {deleted_count} messages\n**Moderator:** {interaction.user.mention}",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else discord.Embed.Empty)
                embed.set_thumbnail(url=user.display_avatar.url)
                await log_channel.send(embed=embed)
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to delete messages in this channel.", ephemeral=True)
    except discord.HTTPException as e:
        logger.error(f"Error in purgeuser command: {e}")
        await interaction.followup.send(f"An error occurred while purging messages: {e}", ephemeral=True)

@bot.event
async def on_member_remove(member):
    """Handle member leave events - log to database and send leave messages."""
    logger.info(f"Member left: {member} ({member.id}) from guild {member.guild.name} ({member.guild.id})")
    
    try:
        # Get join date if available
        join_date = None
        join_duration = None
        
        try:
            async with bot.db_pool.acquire() as conn:
                # Log the leave in database
                await conn.execute('''
                    INSERT INTO user_leaves (guild_id, user_id, username, left_at)
                    VALUES ($1, $2, $3, $4)
                ''', member.guild.id, member.id, str(member), discord.utils.utcnow())
                
                # Get join date if available
                join_row = await conn.fetchrow('''
                    SELECT joined_at FROM user_joins 
                    WHERE guild_id = $1 AND user_id = $2
                ''', member.guild.id, member.id)
                
                if join_row and join_row['joined_at']:
                    join_date = join_row['joined_at']
                    join_duration = discord.utils.utcnow() - join_date
        except Exception as e:
            logger.error(f"Error logging member leave to database: {e}")
        
        # Send leave message to logs channel
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', member.guild.id)
            
        if row and row['logs_channel_id']:
            log_channel = member.guild.get_channel(row['logs_channel_id'])
            if log_channel:
                try:
                    # Create member leave log embed
                    embed = discord.Embed(
                        title="Member Left",
                        description=f"{member.mention} has left the server",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    
                    # Add user information
                    embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
                    
                    # Add join date and duration if available
                    if join_date:
                        embed.add_field(name="Joined", value=discord.utils.format_dt(join_date, style='R'), inline=True)
                        
                    if join_duration:
                        days = join_duration.days
                        hours, remainder = divmod(join_duration.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        
                        duration_str = ""
                        if days > 0:
                            duration_str += f"{days} days, "
                        if hours > 0 or days > 0:
                            duration_str += f"{hours} hours, "
                        duration_str += f"{minutes} minutes"
                        
                        embed.add_field(name="Member For", value=duration_str, inline=True)
                    
                    embed.set_thumbnail(url=member.display_avatar.url)
                    
                    await log_channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Error sending leave message: {e}")
    except Exception as e:
        logger.error(f"Error processing member leave for {member} in {member.guild.name}: {e}")

@bot.event
async def on_guild_channel_create(channel):
    """Log channel creation events to the server's logs channel."""
    # Skip if not a guild channel
    if not hasattr(channel, 'guild'):
        return
        
    try:
        # Get the logs channel for this guild
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', channel.guild.id)
            
        if not row or not row['logs_channel_id']:
            return
            
        log_channel = channel.guild.get_channel(row['logs_channel_id'])
        if not log_channel:
            return
            
        # Try to get the user who created the channel from audit logs
        executor = None
        try:
            async for entry in channel.guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_create):
                if entry.target.id == channel.id:
                    executor = entry.user
                    break
        except Exception as e:
            logger.error(f"Error fetching audit logs for channel creation: {e}")
            
        # Create the embed with channel information
        embed = discord.Embed(
            title="Channel Created",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        
        # Add channel details based on type
        channel_type = str(channel.type).replace('_', ' ').title()
        embed.add_field(name="Channel", value=f"{channel.mention} (`{channel.name}`)", inline=False)
        embed.add_field(name="Type", value=channel_type, inline=True)
        
        # Add category if applicable
        if hasattr(channel, 'category') and channel.category:
            embed.add_field(name="Category", value=channel.category.name, inline=True)
            
        # Add executor information if available
        if executor:
            embed.add_field(name="Created By", value=f"{executor.mention} ({executor.id})", inline=False)
            embed.set_thumbnail(url=executor.display_avatar.url)
        else:
            embed.add_field(name="Created By", value="Unknown", inline=False)
            
        embed.set_author(name=channel.guild.name, icon_url=channel.guild.icon.url if channel.guild.icon else discord.Embed.Empty)
        embed.set_footer(text=f"Channel ID: {channel.id}")
        
        await log_channel.send(embed=embed)
        logger.info(f"Logged channel creation: {channel.name} in {channel.guild.name}")
    except Exception as e:
        logger.error(f"Error logging channel creation for {channel.name} in {channel.guild.name}: {e}")

@bot.event
async def on_guild_channel_delete(channel):
    """Log channel deletion events to the server's logs channel."""
    # Skip if not a guild channel
    if not hasattr(channel, 'guild'):
        return
        
    try:
        # Get the logs channel for this guild
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', channel.guild.id)
            
        if not row or not row['logs_channel_id']:
            return
            
        log_channel = channel.guild.get_channel(row['logs_channel_id'])
        if not log_channel:
            return
            
        # Try to get the user who deleted the channel from audit logs
        executor = None
        try:
            async for entry in channel.guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_delete):
                if entry.target.id == channel.id:
                    executor = entry.user
                    break
        except Exception as e:
            logger.error(f"Error fetching audit logs for channel deletion: {e}")
            
        # Create the embed with channel information
        embed = discord.Embed(
            title="Channel Deleted",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        
        # Add channel details
        channel_type = str(channel.type).replace('_', ' ').title()
        embed.add_field(name="Channel Name", value=f"#{channel.name}", inline=False)
        embed.add_field(name="Channel ID", value=channel.id, inline=True)
        embed.add_field(name="Type", value=channel_type, inline=True)
        
        # Add category if applicable
        if hasattr(channel, 'category') and channel.category:
            embed.add_field(name="Category", value=channel.category.name, inline=True)
            
        # Add executor information if available
        if executor:
            embed.add_field(name="Deleted By", value=f"{executor.mention} ({executor.id})", inline=False)
            embed.set_thumbnail(url=executor.display_avatar.url)
        else:
            embed.add_field(name="Deleted By", value="Unknown", inline=False)
            
        embed.set_author(name=channel.guild.name, icon_url=channel.guild.icon.url if channel.guild.icon else discord.Embed.Empty)
        
        await log_channel.send(embed=embed)
        logger.info(f"Logged channel deletion: {channel.name} in {channel.guild.name}")
    except Exception as e:
        logger.error(f"Error logging channel deletion for {channel.name} in {channel.guild.name}: {e}")

@bot.event
async def on_user_update(before, after):
    """Log user profile changes (username, avatar) to all servers the user is in."""
    # Check if username or avatar changed
    username_changed = before.name != after.name
    avatar_changed = before.avatar != after.avatar
    discriminator_changed = before.discriminator != after.discriminator
    
    # Only proceed if something changed
    if not (username_changed or avatar_changed or discriminator_changed):
        return
        
    logger.info(f"User updated: {before} -> {after}")
    
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
            
            if not row or not row['logs_channel_id']:
                continue
                
            log_channel = guild.get_channel(row['logs_channel_id'])
            if not log_channel:
                continue
                
            # Create embed for the change
            embed = discord.Embed(
                title="User Profile Updated",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Set author with new username and avatar
            embed.set_author(name=str(after), icon_url=after.display_avatar.url)
            
            # Add user ID field
            embed.add_field(name="User ID", value=after.id, inline=False)
            
            # Add fields based on what changed
            changes = []
            
            if username_changed:
                embed.add_field(
                    name="Username Changed", 
                    value=f"**Before:** {before.name}\n**After:** {after.name}", 
                    inline=False
                )
                changes.append("username")
            
            if discriminator_changed and before.discriminator != '0' and after.discriminator != '0':
                embed.add_field(
                    name="Discriminator Changed", 
                    value=f"**Before:** #{before.discriminator}\n**After:** #{after.discriminator}", 
                    inline=False
                )
                changes.append("discriminator")
            
            if avatar_changed:
                embed.add_field(
                    name="Avatar Changed", 
                    value="User updated their profile picture", 
                    inline=False
                )
                changes.append("avatar")
                
                # Show before and after avatars if available
                if before.avatar:
                    embed.set_thumbnail(url=before.avatar.url)
                embed.set_image(url=after.display_avatar.url)
            
            # Set footer with summary of changes
            embed.set_footer(text=f"Changed: {', '.join(changes)}")
            
            # Send the embed to the logs channel
            await log_channel.send(embed=embed)
            logger.info(f"Logged user update for {after} in {guild.name}")
            
        except Exception as e:
            logger.error(f"Error logging user update for {after} in {guild.name}: {e}")

# This duplicate on_ready event has been removed and merged with the one above

@bot.event
async def on_message(message):
    # Skip processing for bot messages or DMs
    if message.author.bot or not message.guild:
        return
        
    try:
        # Check message against filter
        filter_level = await get_filter_level(message.guild.id)
        blocked, reason = check_message_for_filter(message.content, filter_level)
        
        if blocked:
            # Try to delete the message
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention}, your message was deleted because you used a banned word and have been warned. 3 or more warnings may lead to disciplinary action.",
                    delete_after=7
                )
            except Exception as e:
                logger.error(f"Could not delete filtered message: {e}")
                
            # Auto-warn user for filtered word
            try:
                # Add warning to database
                async with bot.db_pool.acquire() as conn:
                    await conn.execute(
                        '''INSERT INTO warns (guild_id, guild_name, user_id, username, reason) VALUES ($1, $2, $3, $4, $5)''',
                        message.guild.id,
                        message.guild.name,
                        message.author.id,
                        message.author.name,
                        f"Automatic warning: Used banned word in message."
                    )
                logger.info(f"Auto-warned {message.author} ({message.author.id}) in guild {message.guild.name} for filtered word")
                
                # Log to server's logs channel if set
                async with bot.db_pool.acquire() as conn:
                    row = await conn.fetchrow('''SELECT logs_channel_id FROM servers WHERE guild_id = $1''', message.guild.id)
                if row and row['logs_channel_id']:
                    log_channel = message.guild.get_channel(row['logs_channel_id'])
                    if log_channel:
                        embed = discord.Embed(
                            title="Message Filtered",
                            description=f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Filter Level:** {filter_level}",
                            color=discord.Color.orange(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.set_author(name=message.guild.name, icon_url=message.guild.icon.url if message.guild.icon else discord.Embed.Empty)
                        embed.set_thumbnail(url=message.author.display_avatar.url)
                        await log_channel.send(embed=embed)
                
                # Notify the user via DM
                try:
                    await message.author.send(f"You have been automatically warned in **{message.guild.name}** for using a banned word.")
                except Exception:
                    # If DM fails, send in channel
                    await message.channel.send(f"{message.author.mention}, you have been automatically warned for using a banned word.", delete_after=10)
            except Exception as e:
                logger.error(f"Could not auto-warn user: {e}")
        else:
            # Process commands if message wasn't filtered
            await bot.process_commands(message)
    except Exception as e:
        logger.error(f"Error in on_message event: {e}")

if __name__ == "__main__":
    bot.run(TOKEN)