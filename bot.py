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
intents.presences = True  # Required for accurate status detection

# FrostModBot definition
class FrostModBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, application_id=None)
        self.db_pool = None
        # Store bot start time in Texas timezone (Central Time)
        import datetime
        import pytz
        
        # Define Texas timezone (Central Time)
        texas_tz = pytz.timezone('America/Chicago')
        
        # Record actual start time when bot initializes in Texas timezone
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        self.start_time = utc_now.astimezone(texas_tz)

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
        await asyncio.sleep(10)  


# --- Helper Functions ---

# --- Chat Filter Wordlists ---
# These sets contain filtered words with different severity levels
# Words are stored in lowercase for case-insensitive matching
STRICT_WORDS = {
    # General profanity, mild offensive terms
 
}

MODERATE_WORDS = {
    # More severe offensive terms and slurs
    "nigger", "wetback", "tranny", "rape", "cuck", "slut", "faggot", 
    "nazi", "dyke", "queer", "gay", "homo", "pedo", "pedophile", "loli", 
    "terrorist", "hitler", "kkk", "suicide", "kill yourself", "kys", "neck yourself", 
    "cancer", "beaner", "gook", "tard", "jew", "zipperhead", "inbred", 
    "incel", "simp", "whitetrash", "molest", "orgy", "gangbang"
}

LIGHT_WORDS = {
    # Most severe hate speech and slurs
    "nigger", "kike", "chink", "retard", "spic", "nigga", "fag", "faggot", "coon", 
    "monkey", "n1gg3r", "k1k3", "ch1nk", "r3tard", "sp1c", "n1gga", "f4g", "f4gg0t", 
    "c00n", "m0nk3y", "negro", "rape", "jap", "mong", "paki", "mongoloid", "towelhead", 
    "jihad", "goatfucker", "sandnigger", "beaner", "cracker", "guido", "gypsy"
}

# Convert all words to lowercase for case-insensitive matching
STRICT_WORDS = {word.lower() for word in STRICT_WORDS}
MODERATE_WORDS = {word.lower() for word in MODERATE_WORDS}
LIGHT_WORDS = {word.lower() for word in LIGHT_WORDS}

def check_message_for_filter(message_content, filter_level):
    """Check if a message contains filtered words based on the filter level.
    
    Args:
        message_content (str): The message content to check
        filter_level (str): The filter level ('none', 'strict', 'moderate', or 'light')
        
    Returns:
        tuple: (bool, str) - Whether the message is blocked and the offending word if any
    """
    if not message_content or not filter_level:
        return False, None
        
    # If filter level is set to none, don't filter any messages
    if filter_level == 'none':
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
        str: The filter level ('none', 'strict', 'moderate', or 'light')
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
@app_commands.describe(level="Filter level: none, light, moderate, or strict")
@app_commands.choices(level=[
    app_commands.Choice(name="None (no filtering)", value="none"),
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

async def get_channel_transcript(channel):
    """Get all messages from a channel and format them as a transcript."""
    messages = []
    async for message in channel.history(limit=None, oldest_first=True):
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author = f"{message.author} ({message.author.id})"
        content = message.content or "[No content]"
        
        # Handle embeds
        if message.embeds:
            for embed in message.embeds:
                content += f"\n[Embed: {embed.title or 'No Title'}]"
        
        # Handle attachments
        if message.attachments:
            for attachment in message.attachments:
                content += f"\n[Attachment: {attachment.filename} - {attachment.url}]"
                
        messages.append(f"[{timestamp}] {author}: {content}")
    
    return "\n".join(messages)

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
                    
                    await close_interaction.response.send_message("Closing ticket and saving transcript...", ephemeral=True)
                    
                    # Get the transcript before closing
                    transcript = await get_channel_transcript(ticket_channel)
                    
                    # Update the ticket status in the database and save transcript
                    async with bot.db_pool.acquire() as close_conn:
                        # Update ticket status
                        await close_conn.execute('''
                            UPDATE tickets 
                            SET status = 'closed', closed_at = CURRENT_TIMESTAMP, 
                                closed_by_id = $1, closed_by_username = $2
                            WHERE channel_id = $3
                        ''', close_interaction.user.id, str(close_interaction.user), ticket_channel.id)
                        
                        # Save the transcript
                        await close_conn.execute('''
                            INSERT INTO ticket_transcripts 
                            (guild_id, guild_name, channel_id, created_by_id, created_by_username, 
                            closed_by_id, closed_by_username, transcript_content, closed_at)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, CURRENT_TIMESTAMP)
                        ''', guild.id, guild.name, ticket_channel.id, 
                        user.id, str(user), close_interaction.user.id, str(close_interaction.user), transcript)
                    
                    # Send a closing message
                    closing_embed = discord.Embed(
                        title="❄️ Ticket Closed",
                        description=f"This ticket has been closed by {close_interaction.user.mention}.",
                        color=discord.Color.from_rgb(220, 20, 60),  # Crimson red for closed tickets
                        timestamp=discord.utils.utcnow()
                    )
                    closing_embed.add_field(name="Ticket Information", value=f"This channel will be deleted in 10 seconds. A transcript has been saved.")
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
@bot.tree.command(name="status", description="Show bot ping, server ping, and uptime with accurate measurements.")
async def status(interaction: discord.Interaction):
    """Show bot ping, server ping, and uptime with accurate measurements."""
    import datetime
    import time
    import asyncio
    import socket
    
    # Start by deferring the response so we don't timeout
    await interaction.response.defer(ephemeral=True)
    
    # More accurate ping calculation using round-trip time
    start_time = time.perf_counter()
    # Make a test API request
    await bot.http.request(discord.http.Route("GET", "/users/@me"))
    end_time = time.perf_counter()
    api_ping = round((end_time - start_time) * 1000)  # API ping in ms
    
    # Get WebSocket latency for comparison
    ws_ping = round(bot.latency * 1000)  # WebSocket ping in ms
    
    # Server ping calculation using socket connection
    server_ping = await get_discord_server_ping()
    
    # Uptime calculation using Texas timezone (Central Time)
    import pytz
    texas_tz = pytz.timezone('America/Chicago')
    now = datetime.datetime.now(datetime.timezone.utc).astimezone(texas_tz)
    delta = now - bot.start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime = f"{days}d {hours}h {minutes}m {seconds}s"
    
    # Create a rich embed with all info
    embed = discord.Embed(
        title="Bot Status", 
        color=discord.Color.blue(), 
        timestamp=now
    )
    
    # Connection info
    embed.add_field(name="API Ping", value=f"{api_ping} ms", inline=True)
    embed.add_field(name="WS Ping", value=f"{ws_ping} ms", inline=True)
    embed.add_field(name="Server Ping", value=f"{server_ping} ms", inline=True)
    
    # Bot info
    embed.add_field(name="Uptime", value=uptime, inline=False)
    
    # Add the bot start time in the footer (Texas time)
    embed.set_footer(text=f"Bot started: {bot.start_time.strftime('%Y-%m-%d %H:%M:%S')} CT | Powered by Frostline Solutions LLC")
    
    await interaction.followup.send(embed=embed, ephemeral=True)

# Function to measure server ping - not a command
async def get_discord_server_ping():
    """Measure ping to Discord's servers using TCP socket connection."""
    import socket
    import time
    import asyncio
    
    # Discord server hostnames to ping (we'll use the main gateway)
    # Possible servers: gateway.discord.gg, discord.com, media.discordapp.net
    hostnames = ['discord.com', 'gateway.discord.gg']
    ping_times = []
    
    # Run ping tests asynchronously
    for hostname in hostnames:
        try:
            # We'll run this in a thread pool since socket operations are blocking
            start = time.time()
            # Open a socket to Discord's server on port 443 (HTTPS)
            # This is a non-blocking way to check server response
            future = asyncio.get_event_loop().run_in_executor(None, lambda: 
                socket.create_connection((hostname, 443), timeout=5)
            )
            socket_obj = await asyncio.wait_for(future, timeout=5)
            socket_obj.close()  # Close the socket immediately after connection
            end = time.time()
            ping_time = round((end - start) * 1000)  # Convert to ms
            ping_times.append(ping_time)
        except Exception as e:
            logger.error(f"Error pinging {hostname}: {e}")
    
    # Return the average ping time, or 999 if all pings failed
    return round(sum(ping_times) / max(len(ping_times), 1)) if ping_times else 999

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
        # First handle the database operations
        row = None
        try:
            async with bot.db_pool.acquire() as conn:
                # Upsert the guild first
                await conn.execute('''
                    INSERT INTO servers (guild_id, guild_name) VALUES ($1, $2)
                    ON CONFLICT (guild_id) DO UPDATE SET guild_name = EXCLUDED.guild_name
                ''', member.guild.id, member.guild.name)
                
                # Use a simpler approach for datetime
                # Log the join event to database without using datetime objects directly
                await conn.execute('''
                    INSERT INTO user_joins (guild_id, user_id, username, joined_at) 
                    VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET 
                        username = EXCLUDED.username,
                        joined_at = CURRENT_TIMESTAMP
                ''', member.guild.id, member.id, str(member))
                
                # Fetch server configuration
                row = await conn.fetchrow('''
                    SELECT welcome_channel_id, welcome_message, join_role_id, logs_channel_id 
                    FROM servers WHERE guild_id = $1
                ''', member.guild.id)
                
                # Make sure member.created_at is timezone-aware for later comparisons
                member_created_at = member.created_at
                if member_created_at.tzinfo is None:
                    member_created_at = member_created_at.replace(tzinfo=datetime.timezone.utc)
        except Exception as e:
            logger.error(f"Error logging member join to database: {e}")
            
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
                        # Use the same timestamp throughout the function
                        now = datetime.datetime.now(datetime.timezone.utc)
                        embed = discord.Embed(
                            title=f"Welcome to {member.guild.name}!",
                            description=welcome_msg,
                            color=discord.Color.blue(),
                            timestamp=now
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
                        # Use the same timestamp throughout the function
                        now = datetime.datetime.now(datetime.timezone.utc)
                        embed = discord.Embed(
                            title="Member Joined",
                            description=f"{member.mention} joined the server",
                            color=discord.Color.green(),
                            timestamp=now
                        )
                        
                        # Add user information
                        embed.add_field(name="User ID", value=member.id, inline=True)
                        embed.add_field(name="Account Created", value=discord.utils.format_dt(member_created_at, style='R'), inline=True)
                        
                        # Check if account is new (less than 7 days old)
                        # Use the timezone-aware created_at we prepared earlier
                        now = datetime.datetime.now(datetime.timezone.utc)
                        account_age = (now - member_created_at).days
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

@bot.tree.command(name="leavemessage", description="Set the leave message for this server.")
@app_commands.describe(message="The leave message to send. Use {user} for the leaving member.")
async def leavemessage(interaction: discord.Interaction, message: str):
    """Set the leave message for members who leave the server. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET leave_message = $1 WHERE guild_id = $2
            ''', message, interaction.guild.id)
        print(f"[DB UPDATE] servers: Set leave_message for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message("Leave message updated!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to update leave message: {e}", ephemeral=True)

@bot.tree.command(name="lchannel", description="Set the leave channel for this server.")
@app_commands.describe(channel="The channel to send leave messages in.")
async def lchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set the channel for leave messages. Admin only."""
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET leave_channel_id = $1 WHERE guild_id = $2
            ''', channel.id, interaction.guild.id)
        print(f"[DB UPDATE] servers: Set leave_channel_id={channel.id} for guild {interaction.guild.name} ({interaction.guild.id})")
        await interaction.response.send_message(f"Leave channel set to {channel.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to set leave channel: {e}", ephemeral=True)

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

# --- Help Commands ---
@bot.tree.command(name="help", description="Show available commands and how to use them.")
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
        "🔍 **/filter** `<level>`\nSet chat filter level (none, light, moderate, strict).\n\n"
        "👋 **/welcome** `<channel>`\nSet the welcome channel for new members.\n\n"
        "💬 **/wmessage** `<message>`\nSet the welcome message. Use `{user}`, `{membercount}`, `{servername}`.\n\n"
        "🎭 **/joinrole** `<role>`\nSet the role automatically assigned to new members.\n\n"
        "📋 **/logschannel** `<channel>`\nSet the channel for event and moderation logs.\n\n"
        "🎫 **/ticketchannel** `<channel>`\nSet the channel for ticket creation.\n\n"
        "🎉 **/bdaychannel** `<channel>`\nSet the birthday announcement channel.\n\n"
        "🔢 **/countingchannel** `<channel>`\nSet the channel for the counting game."
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
        "👤 **/userinfo** `[user]`\nView detailed information about a server member.\n\n"
        "🖼️ **/avatar** `[user]`\nShow a user's profile picture.\n\n"
        "📈 **/status**\nDisplay bot uptime and latency.\n\n"
        "🆘 **/support**\nGet a link to the Frostline support server.\n\n"
        "❄️ **/help**\nShow this help message."
    )
    
    # Fun Commands
    fun_cmds = (
        "💃 **/twerkz**\nGenerates a random twerk message.\n\n"
        "🎱 **/8ball** `<question>`\nAsk the magic 8-ball a question.\n\n"
        "🪙 **/coinflip**\nFlip a coin and get heads or tails.\n\n"
        "🎲 **/roll** `[dice]` `[sides]`\nRoll dice with customizable count and sides.\n\n"
        "😂 **/joke**\nGet a random joke.\n\n"
        "🔢 **/maxcount** `<1-1000>`\nSet the maximum target for the counting game."
    )

    embed.add_field(name="━━━━━━━━ ⚙️ Server Configuration ━━━━━━━━", value=config_cmds, inline=False)
    embed.add_field(name="━━━━━━━━ 🛡️ Moderation Tools ━━━━━━━━", value=mod_cmds, inline=False)
    embed.add_field(name="━━━━━━━━ 🎂 Birthday System ━━━━━━━━", value=birthday_cmds, inline=False)
    embed.add_field(name="━━━━━━━━ 🔧 Utility Commands ━━━━━━━━", value=util_cmds, inline=False)
    embed.add_field(name="━━━━━━━━ 🎉 Fun Commands ━━━━━━━━", value=fun_cmds, inline=False)
    
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
async def on_voice_state_update(member, before, after):
    """Handle voice state update events - log when users join, leave, or move between voice channels."""
    # Skip updates not related to joining or leaving channels
    if before.channel == after.channel:
        return
    
    try:
        # Get guild configuration
        logs_channel_id = None
        
        try:
            async with bot.db_pool.acquire() as conn:
                row = await conn.fetchrow('SELECT logs_channel_id FROM servers WHERE guild_id = $1', member.guild.id)
                if row:
                    logs_channel_id = row['logs_channel_id']
        except Exception as e:
            logger.error(f"Error fetching logs channel for voice state update: {e}")
            
        # Create appropriate log message based on the type of change
        if before.channel is None and after.channel is not None:
            # User joined a voice channel
            action = "joined"
            channel = after.channel
            logger.info(f"Voice channel: {member} ({member.id}) joined {channel.name} in {member.guild.name}")
        elif before.channel is not None and after.channel is None:
            # User left a voice channel
            action = "left"
            channel = before.channel
            logger.info(f"Voice channel: {member} ({member.id}) left {channel.name} in {member.guild.name}")
        else:
            # User moved between voice channels
            action = "moved to"
            channel = after.channel
            logger.info(f"Voice channel: {member} ({member.id}) moved from {before.channel.name} to {after.channel.name} in {member.guild.name}")
        
        # Send log message to logs channel if configured
        if logs_channel_id:
            log_channel = member.guild.get_channel(logs_channel_id)
            if log_channel:
                try:
                    # Create embed for voice channel event
                    now = datetime.datetime.now(datetime.timezone.utc)
                    
                    # Set the embed color and title based on the action
                    embed = discord.Embed(
                        title=f"🔊 Voice Channel {action.title()}",
                        color=discord.Color.from_rgb(0, 191, 255),  # Frostline blue
                        timestamp=now
                    )
                    
                    # Add user info
                    embed.set_author(name=f"{member.name}", icon_url=member.display_avatar.url)
                    embed.add_field(name="User", value=f"{member.mention} ({member.id})", inline=False)
                    
                    # Add channel info
                    if action == "moved to":
                        embed.add_field(name="From Channel", value=f"{before.channel.mention} ({before.channel.name})", inline=True)
                        embed.add_field(name="To Channel", value=f"{after.channel.mention} ({after.channel.name})", inline=True)
                    else:
                        embed.add_field(name="Channel", value=f"{channel.mention} ({channel.name})", inline=False)
                    
                    # Set footer
                    embed.set_footer(text=f"Voice Activity • {member.guild.name}")
                    
                    await log_channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Error sending voice channel log for {member}: {e}")
    
    except Exception as e:
        logger.error(f"Error processing voice state update for {member} in {member.guild.name}: {e}")

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
                # Use a simpler approach for datetime
                # Log the leave in database using PostgreSQL's CURRENT_TIMESTAMP
                await conn.execute('''
                    INSERT INTO user_leaves (guild_id, guild_name, user_id, username, left_at)
                    VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ''', member.guild.id, member.guild.name, member.id, str(member))
                
                # Get join date if available
                join_row = await conn.fetchrow('''
                    SELECT joined_at FROM user_joins 
                    WHERE guild_id = $1 AND user_id = $2
                ''', member.guild.id, member.id)
                
                if join_row and join_row['joined_at']:
                    join_date = join_row['joined_at']
                    # Ensure both datetimes are timezone-aware
                    now = datetime.datetime.now(datetime.timezone.utc)
                    join_date_aware = join_date.replace(tzinfo=datetime.timezone.utc) if join_date.tzinfo is None else join_date
                    join_duration = now - join_date_aware
        except Exception as e:
            logger.error(f"Error logging member leave to database: {e}")
        
        # Get server configuration including logs channel, leave message, and leave channel
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT logs_channel_id, leave_message, leave_channel_id, welcome_channel_id 
                FROM servers WHERE guild_id = $1
            ''', member.guild.id)
            
        # Send custom leave message if configured
        # First try to use dedicated leave channel, fall back to welcome channel if not set
        leave_channel_id = row['leave_channel_id'] if row and row['leave_channel_id'] else (row['welcome_channel_id'] if row else None)
        if row and row['leave_message'] and leave_channel_id:
            leave_channel = member.guild.get_channel(leave_channel_id)
            if leave_channel:
                try:
                    # Format leave message with user mention
                    leave_msg = row['leave_message']
                    leave_msg = leave_msg.replace('{user}', str(member))
                    
                    # Create and send leave embed
                    now = datetime.datetime.now(datetime.timezone.utc)
                    embed = discord.Embed(
                        title=f"Member Left",
                        description=leave_msg,
                        color=discord.Color.red(),
                        timestamp=now
                    )
                    
                    # Add user avatar
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=f"Members: {member.guild.member_count}")
                    
                    await leave_channel.send(embed=embed)
                    logger.info(f"Sent leave message for {member} in {member.guild.name}")
                except Exception as e:
                    logger.error(f"Error sending custom leave message for {member}: {e}")
        
        # Send detailed leave log to logs channel
        if row and row['logs_channel_id']:
            log_channel = member.guild.get_channel(row['logs_channel_id'])
            if log_channel:
                try:
                    # Create member leave log embed
                    # Use a consistent timezone-aware datetime
                    now = datetime.datetime.now(datetime.timezone.utc)
                    
                    embed = discord.Embed(
                        title="Member Left",
                        description=f"{member.mention} has left the server",
                        color=discord.Color.red(),
                        timestamp=now
                    )
                    
                    # Add user information
                    embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
                    
                    # Add join date and duration if available
                    if join_date:
                        # Ensure join_date is timezone-aware for format_dt
                        join_date_aware = join_date.replace(tzinfo=datetime.timezone.utc) if join_date.tzinfo is None else join_date
                        embed.add_field(name="Joined", value=discord.utils.format_dt(join_date_aware, style='R'), inline=True)
                        
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
    try:
        # Ignore messages from bots
        if message.author.bot:
            return
        
        # Ignore direct messages
        if not message.guild:
            return
            
        # Check if this is a counting channel message
        try:
            counting_channel_id = await db_fetch(
                '''SELECT counting_channel FROM servers WHERE guild_id = $1''',
                message.guild.id
            )
            
            if counting_channel_id and counting_channel_id[0]['counting_channel'] and \
            message.channel.id == counting_channel_id[0]['counting_channel']:
                # This is a message in the counting channel
                await handle_counting_message(message)
                return  # Skip other checks for messages in counting channel
        except Exception as e:
            logger.error(f"Error checking counting channel: {e}")
            
        # Check if the message needs to be filtered
        filter_level = await get_filter_level(message.guild.id)
        is_filtered, filtered_word = check_message_for_filter(message.content, filter_level)
        
        if is_filtered:
            # Delete the filtered message
            try:
                await message.delete()
                # Send a warning message
                warning = await message.channel.send(
                    f"{message.author.mention}, your message was removed for containing filtered content.\n" +
                    f"The word `{filtered_word}` is not allowed in this server.")
                # Delete the warning after 5 seconds
                await asyncio.sleep(5)
                await warning.delete()
            except discord.errors.NotFound:
                # Message already deleted
                pass
            except discord.errors.Forbidden:
                # Bot doesn't have permission
                pass
                
            # Log the filtered message to the logs channel if set
            try:
                logs_channel_id = await db_fetch(
                    '''SELECT logs_channel_id FROM servers WHERE guild_id = $1''',
                    message.guild.id
                )
                
                if logs_channel_id and logs_channel_id[0]['logs_channel_id']:
                    logs_channel = bot.get_channel(logs_channel_id[0]['logs_channel_id'])
                    if logs_channel:
                        embed = discord.Embed(
                            title="Message Filtered",
                            description=f"A message by {message.author.mention} was filtered in {message.channel.mention}",
                            color=discord.Color.red()
                        )
                        embed.add_field(name="Filtered Word", value=f"`{filtered_word}`", inline=False)
                        embed.add_field(name="Message Content", value=f"`{message.content}`", inline=False)
                        embed.set_footer(text=f"User ID: {message.author.id}")
                        embed.timestamp = datetime.datetime.now()
                        
                        await logs_channel.send(embed=embed)
                        
                # Auto-warn the user for filtered content
                try:
                    # Add warning to database
                    await db_execute(
                        '''INSERT INTO warns (guild_id, guild_name, user_id, username, reason) 
                        VALUES ($1, $2, $3, $4, $5)''',
                        message.guild.id,
                        message.guild.name,
                        message.author.id,
                        message.author.name,
                        f"Automatic warning: Used filtered word '{filtered_word}'"
                    )
                    
                    # Try to notify user via DM
                    try:
                        await message.author.send(f"You have been automatically warned in **{message.guild.name}** for using a banned word.")
                    except Exception:
                        # If DM fails, send in channel
                        await message.channel.send(f"{message.author.mention}, you have been automatically warned for using a banned word.", delete_after=10)
                except Exception as e:
                    logger.error(f"Could not auto-warn user: {e}")
                    
            except Exception as e:
                logger.error(f"Error logging filtered message: {e}")
        
        # Process commands
        await bot.process_commands(message)
        
    except Exception as e:
        logger.error(f"Error in on_message event: {e}")

# --- Fun Commands ---
import random
import datetime
from datetime import timedelta

@bot.tree.command(name="twerkz", description="Generates a random twerk message")
async def twerkz(interaction: discord.Interaction):
    """Generate a random message from a predefined list of twerk messages."""
    # List of messages to randomly select from
    messages = [
        "Tristans gay dude",
        "Twerking in the moonlight",
        "Shake what your mama gave you",
        "Is it hot in here or is it just me twerking?",
        "Drop it like it's hot",
        "Twerk team captain reporting for duty",
        "Professional twerker at your service",
        "Twerk till ya can't twerk no more",
        "*intense twerking intensifies*"
    ]
    
    # Randomly select a message
    message = random.choice(messages)
    
    # Create an embed with Frostline branding
    embed = discord.Embed(
        title="❄️ Random Twerk Message",
        description=message,
        color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
    )
    embed.set_footer(text="Frostline Entertainment | Powered by FrostMod")
    
    # Send the message
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="8ball", description="Ask the magic 8-ball a question")
@app_commands.describe(question="The question you want to ask the magic 8-ball")
async def eightball(interaction: discord.Interaction, question: str):
    """Ask the magic 8-ball a question and get a mysterious answer."""
    responses = [
        "It is certain.",
        "It is decidedly so.",
        "Without a doubt.",
        "Yes – definitely.",
        "You may rely on it.",
        "As I see it, yes.",
        "Most likely.",
        "Outlook good.",
        "Yes.",
        "Signs point to yes.",
        "Reply hazy, try again.",
        "Ask again later.",
        "Better not tell you now.",
        "Cannot predict now.",
        "Concentrate and ask again.",
        "Don't count on it.",
        "My reply is no.",
        "My sources say no.",
        "Outlook not so good.",
        "Very doubtful."
    ]
    
    response = random.choice(responses)
    
    embed = discord.Embed(
        title="❄️ Magic 8-Ball",
        description=f"**Question:** {question}\n\n**Answer:** {response}",
        color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
    )
    embed.set_footer(text="Frostline Entertainment | Powered by Frostline Solutions LLC")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="coinflip", description="Flip a coin")
async def coinflip(interaction: discord.Interaction):
    """Flip a coin and get heads or tails."""
    result = random.choice(["Heads", "Tails"])
    
    embed = discord.Embed(
        title="❄️ Coin Flip",
        description=f"The coin landed on: **{result}**!",
        color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
    )
    embed.set_footer(text="Frostline Entertainment | Powered by Frostline Solutions LLC")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="roll", description="Roll dice")
@app_commands.describe(
    dice="Number of dice to roll (default: 1)",
    sides="Number of sides on each die (default: 6)"
)
async def roll(interaction: discord.Interaction, dice: int = 1, sides: int = 6):
    """Roll a specified number of dice with a specified number of sides."""
    # Input validation
    if dice < 1 or dice > 10:
        await interaction.response.send_message("Please roll between 1 and 10 dice.", ephemeral=True)
        return
    if sides < 2 or sides > 100:
        await interaction.response.send_message("Dice must have between 2 and 100 sides.", ephemeral=True)
        return
    
    # Roll the dice
    results = [random.randint(1, sides) for _ in range(dice)]
    total = sum(results)
    
    # Format the results
    if dice == 1:
        result_text = f"You rolled a **{total}**!"
    else:
        result_text = f"You rolled: {', '.join(str(r) for r in results)}\nTotal: **{total}**"
    
    embed = discord.Embed(
        title=f"❄️ Dice Roll ({dice}d{sides})",
        description=result_text,
        color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
    )
    embed.set_footer(text="Frostline Entertainment | Powered by Frostline Solutions LLC")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="joke", description="Get a random joke")
async def joke(interaction: discord.Interaction):
    """Get a random joke."""
    jokes = [
        "Why don't scientists trust atoms? Because they make up everything!",
        "What's the best thing about Switzerland? I don't know, but the flag is a big plus.",
        "I told my wife she was drawing her eyebrows too high. She looked surprised.",
        "Why did the scarecrow win an award? Because he was outstanding in his field!",
        "I'm reading a book about anti-gravity. It's impossible to put down!",
        "What do you call a fake noodle? An impasta!",
        "Why don't eggs tell jokes? They'd crack each other up!",
        "How do you organize a space party? You planet!",
        "Why did the bicycle fall over? Because it was two tired!",
        "What's orange and sounds like a parrot? A carrot!",
        "Why did the golfer bring two pairs of pants? In case he got a hole in one!",
        "How do you make a tissue dance? Put a little boogie in it!",
        "Why couldn't the leopard play hide and seek? Because he was always spotted!"
    ]
    
    joke = random.choice(jokes)
    
    embed = discord.Embed(
        title="❄️ Random Joke",
        description=joke,
        color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
    )
    embed.set_footer(text="Frostline Entertainment | Powered by Frostline Solutions LLC")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="utilities", description="View Frostline's company utilities, plugins, and social media links")
async def utilities(interaction: discord.Interaction):
    """Display Frostline's company utilities, plugins, and social media links."""
    # Create the main embed with Frostline branding
    main_embed = discord.Embed(
        title="❄️ Frostline Utilities",
        description="Explore Frostline's ecosystem of plugins, social media, and resources.",
        color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
    )
    
    # Add Minecraft Plugins section
    main_embed.add_field(
        name="🧩 Minecraft Plugins",
        value=(
            "**Classes - GuildWar Addon**\n"
            "[SpigotMC Link](https://www.spigotmc.org/resources/classes-guildwars-addon.125026/)\n\n"
            "**GuildWars - Factions Plugin**\n"
            "[SpigotMC Link](https://www.spigotmc.org/resources/guildwars-factions-plugin.124999/)\n\n"
            "**FrostGui**\n"
            "[SpigotMC Link](https://www.spigotmc.org/resources/frostgui.124878/)"
        ),
        inline=False
    )
    
    # Add Social Media section
    main_embed.add_field(
        name="📱 Social Media",
        value=(
            "**Instagram**\n"
            "[Follow Us](https://www.instagram.com/frostlinesolutions_llc/)\n\n"
            "**Facebook**\n"
            "[Like Our Page](https://www.facebook.com/FROSTLINELLC/)\n\n"
            "**YouTube**\n"
            "[Subscribe](https://www.youtube.com/@FrostLinesolutionsLLC)"
        ),
        inline=False
    )
    
    # Add GitHub section
    main_embed.add_field(
        name="💻 GitHub Innovation Lab",
        value="[Browse Our Repositories](https://github.com/FrostlineTech?tab=repositories)",
        inline=False
    )
    
    # Set footer with company branding
    main_embed.set_footer(text="Frostline Entertainment | Powered by Frostline Solutions LLC")
    
    # Send the embed
    await interaction.response.send_message(embed=main_embed)

@bot.tree.command(name="frosthelp", description="Post a permanent help embed in a specified channel.")
@app_commands.describe(channel="The channel to post the help embed in.")
async def frosthelp(interaction: discord.Interaction, channel: discord.TextChannel):
    """Post a permanent help embed in a specified channel. Admins and moderators only."""
    # Check if user has permission (admin or mod role)
    if not await is_admin(interaction):
        await interaction.response.send_message("You must be an administrator or have the mod role to use this command.", ephemeral=True)
        return
    
    try:
        # Create multiple embeds to stay within Discord's 4096 character limit per embed
        # Main welcome embed
        main_embed = discord.Embed(
            title="❄️ FrostMod Command Center",
            description="""
:wave: **Welcome to the FrostMod Command Center!**
This guide provides comprehensive information on all available commands.
Find the perfect tool for your needs, organized by category below.

Use the navigation below to view commands by category:
- 🛡️ **Moderation Tools**
- ⚙️ **Server Configuration**
- 🔢 **Counting Game**
- 🎂 **Birthday System**
- 🔧 **Utility Features**
- 🎲 **Fun Commands**
- ❄️ **Frostline Utilities**

:bulb: **Need additional help?** Contact a server administrator or moderator.
""",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
        )
        
        # Add a thumbnail to make the embed more visually appealing
        main_embed.set_thumbnail(url="https://i.imgur.com/tLXG6Rx.png")  # FrostMod logo placeholder - replace with actual logo URL
        
        # Moderation embed
        mod_embed = discord.Embed(
            title="🛡️ Moderation Commands",
            description="""
**`/warn`** `<user> <reason>`
> :warning: Issue an official warning to a user that gets logged in the database.
> Warns are tracked and can be viewed by moderators at any time.

**`/warns`** `<user>`
> :page_facing_up: View a user's complete warning history with reasons and timestamps.
> Provides helpful context for moderator decisions.

**`/delwarns`** `<user> <count>`
> :wastebasket: Remove a specific number of warnings from a user's record.
> Removes the most recent warnings first.

**`/purge`** `<amount>`
> :broom: Quickly delete multiple messages from the current channel.
> Can remove up to 100 messages that are less than 14 days old.

**`/purgeuser`** `<user> <amount>`
> :broom: Delete messages from a specific user within the channel.
> Great for targeted cleanup of problematic content.

**`/filter`** `<level>` - Set filter level (none, light, moderate, strict)
> :no_entry: Set the server's word filter strength level.
> Options: strict (most words filtered), moderate, or light (minimal filtering).

**`/mrole`** `<role>`
> :key: Designate which role has moderation permissions for bot commands.
> Users with this role can use admin-level commands.
""",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
        )
        
        # Server configuration embed
        config_embed = discord.Embed(
            title="⚙️ Server Configuration Commands",
            description="""
**`/welcome`** `<channel>`
> :door: Set where new member welcome messages will be displayed.
> Creates a personalized greeting when members join.

**`/wmessage`** `<text>`
> :envelope: Customize the welcome message sent when members join.
> Supports variables like {user} and {server}.

**`/lchannel`** `<channel>`
> :wave: Configure which channel shows departure messages.
> Notifies when members leave the server.

**`/leavemessage`** `<text>`
> :envelope_with_arrow: Customize the message sent when members leave.
> Supports variables like {user} and {server}.

**`/logschannel`** `<channel>`
> :pencil: Designate where server activity logs will be sent.
> Tracks moderation actions, channel changes, and more.

**`/joinrole`** `<role>`
> :label: Set an automatic role assigned to new members upon joining.
> Streamlines the onboarding process for new users.

**`/ticketchannel`** `<channel>`
> :ticket: Configure where users can create support tickets.
> Creates an interactive interface for users to get help.
""",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
        )
        
        # Counting and Birthday embed
        counting_bday_embed = discord.Embed(
            title="🔢 Counting Game & 🎂 Birthday System",
            description="""
:1234: **━━━━ COUNTING GAME ━━━━**

**`/countingchannel`** `<channel>`
> :1234: Set the channel for the counting game.
> Members take turns counting up from 1 to the max count.

**`/maxcount`** `<number>`
> :chart_with_upwards_trend: Set the maximum target number for the counting game.
> When reached, the game resets and starts again.

:birthday: **━━━━ BIRTHDAY SYSTEM ━━━━**

**`/setbirthday`** `<date>`
> :cake: Register your birthday to receive server celebrations.
> Format: MM-DD (example: 05-15 for May 15th).

**`/bdaychannel`** `<channel>`
> :partying_face: Set where birthday announcements will appear.
> Members with birthdays get special recognition.

**`/delbday`** `<user>`
> :x: Remove a birthday from the system.
> Users can delete their own; admins can delete any.

**`/testbirthdays`**
> :test_tube: Test the birthday announcement system for today's birthdays.
> Admin only command for verifying birthday configurations.
""",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
        )
        
        # Utility and Fun Commands embed
        utility_fun_embed = discord.Embed(
            title="🔧 Utility Features & 🎲 Fun Commands",
            description="""
:wrench: **━━━━ UTILITY FEATURES ━━━━**

**`/userinfo`** `<user>`
> :bust_in_silhouette: View detailed information about a server member.
> Shows join date, roles, permissions, and more.

**`/ping`**
> :signal_strength: Check the bot's response time and latency.
> Useful for verifying if the bot is responsive.

**`/uptime`**
> :clock3: See how long the bot has been running since last restart.
> Displays in days, hours, minutes, and seconds.

**`/utilities`**
> ❄️ View Frostline's company utilities, plugins, and social media links.
> Access all Frostline resources in one convenient place.

:game_die: **━━━━ FUN COMMANDS ━━━━**

**`/joke`**
> :laughing: Get a random joke to lighten the mood.
> Family-friendly humor for everyone to enjoy.

**`/8ball`** `<question>`
> :8ball: Ask the magic 8-ball a yes/no question.
> Provides a random mystical answer to your query.

**`/coinflip`**
> :coin: Flip a virtual coin that lands on heads or tails.
> Perfect for making quick decisions.
""",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
        )
        
        # Add footer to all embeds
        footer_text = "FrostMod v2.0 | Powered by Frostline Solutions LLC"
        timestamp = datetime.datetime.now()
        
        for embed in [main_embed, mod_embed, config_embed, counting_bday_embed, utility_fun_embed]:
            embed.set_footer(text=footer_text)
            embed.timestamp = timestamp
        
        # Respond to the interaction first
        await interaction.response.defer(ephemeral=True)
        
        # Send each embed as a separate message
        main_message = await channel.send(embed=main_embed)
        await channel.send(embed=mod_embed)
        await channel.send(embed=config_embed)
        await channel.send(embed=counting_bday_embed)
        help_message = await channel.send(embed=utility_fun_embed)
        
        # Update the database to store the help channel ID
        async with bot.db_pool.acquire() as conn:
            # Check if the server exists, if not, create it
            count = await conn.fetchval('''
                SELECT COUNT(*) FROM servers WHERE guild_id = $1
            ''', interaction.guild.id)
            
            if count == 0:
                # Server doesn't exist in database, insert it
                await conn.execute('''
                    INSERT INTO servers (guild_id, guild_name, help_channel_id) 
                    VALUES ($1, $2, $3)
                ''', interaction.guild.id, interaction.guild.name, channel.id)
            else:
                # Server exists, update help_channel_id
                await conn.execute('''
                    UPDATE servers SET help_channel_id = $1, guild_name = $2 WHERE guild_id = $3
                ''', channel.id, interaction.guild.name, interaction.guild.id)
        
        # Use followup instead of response.send_message since we've already responded
        await interaction.followup.send(f"Help center has been successfully set up in {channel.mention}. All command information is now available there.", ephemeral=True)
        
        logger.info(f"Help channel set to {channel.id} for guild {interaction.guild.name} ({interaction.guild.id})")
        
    except Exception as e:
        logger.error(f"Error setting up help center: {e}")
        # Check if the interaction has already been responded to
        if interaction.response.is_done():
            await interaction.followup.send(f"Error setting up help center: {e}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Error setting up help center: {e}", ephemeral=True)

# Function to check if user has moderator role
async def is_moderator(interaction):
    """Check if a user has the moderator role set for the guild."""
    try:
        if interaction.user.guild_permissions.administrator or interaction.user.id == OWNER_ID:
            return True
            
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow('''SELECT mod_role_id FROM servers WHERE guild_id = $1''', interaction.guild.id)
            
        if row and row['mod_role_id']:
            mod_role = interaction.guild.get_role(row['mod_role_id'])
            if mod_role and mod_role in interaction.user.roles:
                return True
                
        return False
    except Exception as e:
        logger.error(f"Error checking moderator status: {e}")
        return False

@bot.tree.command(name="serverinfo", description="Display comprehensive information about this server")
async def serverinfo(interaction: discord.Interaction):
    """Display detailed information and statistics about the current server."""
    guild = interaction.guild
    
    # Get creation date and format it
    created_at = guild.created_at.strftime("%Y-%m-%d %H:%M:%S")
    # Calculate server age
    now = datetime.datetime.now(datetime.timezone.utc)
    age = now - guild.created_at
    days = age.days
    years, days = divmod(days, 365)
    months, days = divmod(days, 30)
    age_str = f"{years} years, {months} months, {days} days"
    
    # Get member statistics
    total_members = guild.member_count
    bot_count = len([m for m in guild.members if m.bot])
    human_count = total_members - bot_count
    online_count = len([m for m in guild.members if m.status != discord.Status.offline]) if guild.chunked else "Unknown"
    
    # Get channel statistics
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    categories = len(guild.categories)
    total_channels = text_channels + voice_channels + categories
    
    # Get role count (excluding @everyone)
    role_count = len(guild.roles) - 1
    
    # Get emoji statistics
    emoji_count = len(guild.emojis)
    emoji_limit = guild.emoji_limit
    animated_emoji = len([e for e in guild.emojis if e.animated])
    static_emoji = emoji_count - animated_emoji
    
    # Get boosting info
    premium_tier = str(guild.premium_tier)
    premium_subscribers = len(guild.premium_subscribers)
    
    # Get verification level
    verification_level = str(guild.verification_level).capitalize()
    
    # Get content filter level
    explicit_content_filter = str(guild.explicit_content_filter).replace('_', ' ').capitalize()
    
    # Get features
    features = ", ".join(guild.features).replace("_", " ").title() if guild.features else "None"
    
    # Get server owner
    owner = guild.owner
    
    # Create the embed
    embed = discord.Embed(
        title=f"❄️ {guild.name} Server Information",
        description=f"Detailed statistics and information about this server.",
        color=discord.Color.from_rgb(0, 191, 255)  # Frostline branding blue
    )
    
    # Add server icon as thumbnail if available
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    # Add general information
    embed.add_field(name="⏰ Created On", value=f"{created_at}\n({age_str} ago)", inline=False)
    embed.add_field(name="👑 Owner", value=f"{owner.mention if owner else 'Unknown'}", inline=True)
    embed.add_field(name="🌐 Region", value=f"Discord Managed", inline=True)
    embed.add_field(name="🔒 Verification", value=verification_level, inline=True)
    
    # Add server stats
    embed.add_field(name="👥 Members", value=f"Total: {total_members}\nHumans: {human_count}\nBots: {bot_count}", inline=True)
    embed.add_field(name="💬 Channels", value=f"Total: {total_channels}\nText: {text_channels}\nVoice: {voice_channels}\nCategories: {categories}", inline=True)
    embed.add_field(name="🌟 Emojis", value=f"Total: {emoji_count}/{emoji_limit}\nStatic: {static_emoji}\nAnimated: {animated_emoji}", inline=True)
    
    # Add more server info
    embed.add_field(name="🔰 Roles", value=f"{role_count}", inline=True)
    embed.add_field(name="💠 Boost Level", value=f"Level {premium_tier}\nBoosters: {premium_subscribers}", inline=True)
    embed.add_field(name="🔞 Content Filter", value=explicit_content_filter, inline=True)
    
    if features != "None":
        embed.add_field(name="✨ Features", value=features, inline=False)
    
    # Add server ID
    embed.set_footer(text=f"Server ID: {guild.id} | Powered by Frostline Solutions LLC")
    embed.timestamp = now
    
    # Get database stats if available
    try:
        async with bot.db_pool.acquire() as conn:
            # Get warning count
            warn_count = await conn.fetchval(
                '''SELECT COUNT(*) FROM warns WHERE guild_id = $1''',
                guild.id
            )
            
            # Get FrostMod configuration info
            config = await conn.fetchrow(
                '''SELECT 
                    welcome_channel_id, 
                    leave_channel_id, 
                    logs_channel_id, 
                    join_role_id, 
                    ticket_channel_id, 
                    birthday_channel_id,
                    filter_level,
                    mod_role_id
                FROM servers WHERE guild_id = $1''',
                guild.id
            )
            
            if config:
                frostmod_config = []
                
                if config['welcome_channel_id']:
                    channel = guild.get_channel(config['welcome_channel_id'])
                    if channel:
                        frostmod_config.append(f"Welcome Channel: {channel.mention}")
                        
                if config['leave_channel_id']:
                    channel = guild.get_channel(config['leave_channel_id'])
                    if channel:
                        frostmod_config.append(f"Leave Channel: {channel.mention}")
                        
                if config['logs_channel_id']:
                    channel = guild.get_channel(config['logs_channel_id'])
                    if channel:
                        frostmod_config.append(f"Logs Channel: {channel.mention}")
                        
                if config['ticket_channel_id']:
                    channel = guild.get_channel(config['ticket_channel_id'])
                    if channel:
                        frostmod_config.append(f"Ticket Channel: {channel.mention}")
                        
                if config['birthday_channel_id']:
                    channel = guild.get_channel(config['birthday_channel_id'])
                    if channel:
                        frostmod_config.append(f"Birthday Channel: {channel.mention}")
                
                if config['join_role_id']:
                    role = guild.get_role(config['join_role_id'])
                    if role:
                        frostmod_config.append(f"Join Role: {role.mention}")
                        
                if config['mod_role_id']:
                    role = guild.get_role(config['mod_role_id'])
                    if role:
                        frostmod_config.append(f"Mod Role: {role.mention}")
                        
                if config['filter_level']:
                    frostmod_config.append(f"Filter Level: {config['filter_level'].capitalize()}")
                
                if frostmod_config:
                    embed.add_field(
                        name="⚙️ FrostMod Configuration", 
                        value="\n".join(frostmod_config), 
                        inline=False
                    )
                
                if warn_count:
                    embed.add_field(
                        name="⚠️ Moderation Stats", 
                        value=f"Total Warnings: {warn_count}", 
                        inline=False
                    )
    except Exception as e:
        logger.error(f"Error fetching database stats for serverinfo: {e}")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="userinfo", description="View detailed information about a server member")
async def userinfo(interaction: discord.Interaction, user: discord.Member = None):
    """:bust_in_silhouette: View detailed information about a server member.
    Shows join date, roles, status, and more."""
    # If no user is specified, use the command invoker
    if user is None:
        user = interaction.user
    
    # Get current time for calculating durations
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Get account creation date and format it
    created_at = user.created_at.strftime("%Y-%m-%d %H:%M:%S")
    account_age = now - user.created_at
    account_age_days = account_age.days
    account_years, account_days = divmod(account_age_days, 365)
    account_months, account_days = divmod(account_days, 30)
    account_age_str = f"{account_years} years, {account_months} months, {account_days} days"
    
    # Get join date and format it
    joined_at = user.joined_at.strftime("%Y-%m-%d %H:%M:%S") if user.joined_at else "Unknown"
    if user.joined_at:
        server_age = now - user.joined_at
        server_age_days = server_age.days
        server_years, server_days = divmod(server_age_days, 365)
        server_months, server_days = divmod(server_days, 30)
        server_age_str = f"{server_years} years, {server_months} months, {server_days} days"
    else:
        server_age_str = "Unknown"
    
    # Get user status and activity if available
    status = str(user.status).capitalize() if hasattr(user, 'status') and user.status else "Unknown"
    activity = ""
    if user.activities:
        for act in user.activities:
            if isinstance(act, discord.CustomActivity) and act.name:
                activity = f"Custom Status: {act.name}"
                break
            elif isinstance(act, discord.Activity):
                activity_type = str(act.type).split('.')[-1].capitalize()
                activity = f"{activity_type}: {act.name}"
                break
    
    # Get user roles (excluding @everyone)
    roles = [role.mention for role in user.roles if role.name != "@everyone"]
    roles_str = ", ".join(roles) if roles else "No roles"
    
    # Create embed
    embed = discord.Embed(
        title=f"User Information for {user.display_name}",
        color=user.color if user.color != discord.Color.default() else discord.Color.from_rgb(0, 191, 255)
    )
    
    # Add user avatar
    if user.avatar:
        embed.set_thumbnail(url=user.avatar.url)
    
    # Add banner if available
    if hasattr(user, 'banner') and user.banner:
        embed.set_image(url=user.banner.url)
    
    # Basic user info
    embed.add_field(name="📛 Username", value=f"{user.name}", inline=True)
    if user.display_name != user.name:
        embed.add_field(name="🏷️ Display Name", value=f"{user.display_name}", inline=True)
    
    embed.add_field(name="🤖 Bot", value="Yes" if user.bot else "No", inline=True)
    
    # Membership details
    embed.add_field(name="🔰 Account Created", value=f"{created_at}\n({account_age_str} ago)", inline=False)
    embed.add_field(name="📆 Joined Server", value=f"{joined_at}\n({server_age_str} ago)", inline=False)
    
    # Status and activity
    if status != "Unknown":
        embed.add_field(name="🔵 Status", value=status, inline=True)
    if activity:
        embed.add_field(name="🎮 Activity", value=activity, inline=True)
    
    # Boosting status
    if hasattr(user, 'premium_since') and user.premium_since:
        boosting_since = user.premium_since.strftime("%Y-%m-%d")
        boost_age = now - user.premium_since
        boost_days = boost_age.days
        embed.add_field(name="💠 Server Booster", value=f"Since {boosting_since} ({boost_days} days)", inline=False)
    
    # Roles section
    if len(roles) > 0:
        # If there are too many roles, summarize
        if len(roles_str) > 1024:
            embed.add_field(name=f"🏅 Roles ({len(roles)})", value=f"{len(roles)} roles (too many to display)", inline=False)
        else:
            embed.add_field(name=f"🏅 Roles ({len(roles)})", value=roles_str, inline=False)
    
    # Get user permissions if available
    if interaction.guild:
        permissions = user.guild_permissions
        key_perms = []
        if permissions.administrator:
            key_perms.append("Administrator")
        elif permissions.manage_guild:
            key_perms.append("Manage Server")
        elif permissions.manage_roles:
            key_perms.append("Manage Roles")
        elif permissions.manage_channels:
            key_perms.append("Manage Channels")
        elif permissions.manage_messages:
            key_perms.append("Manage Messages")
        elif permissions.moderate_members:
            key_perms.append("Moderate Members")
            
        if key_perms:
            embed.add_field(name="🔑 Key Permissions", value=", ".join(key_perms), inline=False)
    
    # Get database info if available
    try:
        async with bot.db_pool.acquire() as conn:
            # Get warning count for this user
            warn_count = await conn.fetchval(
                '''SELECT COUNT(*) FROM warns WHERE guild_id = $1 AND user_id = $2''',
                interaction.guild.id, user.id
            )
            
            # Get birthday if set
            birthday = await conn.fetchval(
                '''SELECT birthday FROM birthdays WHERE guild_id = $1 AND user_id = $2''',
                interaction.guild.id, user.id
            )
            
            # Add warning count if any
            if warn_count and warn_count > 0:
                embed.add_field(name="⚠️ Warnings", value=str(warn_count), inline=True)
            
            # Add birthday if set
            if birthday:
                embed.add_field(name="🎂 Birthday", value=birthday, inline=True)
    except Exception as e:
        logger.error(f"Error fetching database info for userinfo: {e}")
    
    # Add user ID in footer
    embed.set_footer(text=f"User ID: {user.id} | Powered by Frostline Solutions LLC")
    embed.timestamp = now
    
    await interaction.response.send_message(embed=embed)

# Counting game logic
async def handle_counting_message(message):
    """Process a message in the counting channel."""
    try:
        # Try to convert message content to an integer
        try:
            count = int(message.content.strip())
        except ValueError:
            # Not a valid number, delete the message
            await message.delete()
            warning = await message.channel.send(
                f"{message.author.mention}, only numbers are allowed in the counting channel.")
            await asyncio.sleep(5)
            await warning.delete()
            return
            
        # Get current count status from database
        logger.info(f"Fetching count status for guild {message.guild.id} ({message.guild.name})")
        game_data = await db_fetch(
            '''SELECT current_count, last_user_id, max_count, last_message_id 
               FROM counting_game WHERE guild_id = $1''',
            message.guild.id
        )
        
        # If no game data found, initialize it
        if not game_data:
            logger.info(f"Initializing new counting game for guild {message.guild.id} ({message.guild.name})")
            # Start a new game at count 0
            await db_execute(
                '''INSERT INTO counting_game(guild_id, current_count, max_count) 
                   VALUES($1, 0, 100)''',
                message.guild.id
            )
            game_data = [{"current_count": 0, "last_user_id": None, "max_count": 100, "last_message_id": None}]
            logger.info(f"Created new counting game entry in database for guild {message.guild.id}")
        
        current_count = game_data[0]["current_count"]
        last_user_id = game_data[0]["last_user_id"]
        max_count = game_data[0]["max_count"]
        
        # Check if the same user is counting twice in a row
        if last_user_id and last_user_id == message.author.id:
            await message.delete()
            warning = await message.channel.send(
                f"{message.author.mention}, you can't count twice in a row! Wait for someone else to continue.")
            await asyncio.sleep(5)
            await warning.delete()
            return
            
        # Check if the count is the next number in sequence
        expected_count = current_count + 1
        if count != expected_count:
            # Wrong number, reset the game
            await message.add_reaction('❌')
            
            # Create reset embed
            embed = discord.Embed(
                title="❌ Counting Failed",
                description=f"**{message.author.display_name}** broke the count by entering **{count}**",
                color=discord.Color.red()
            )
            embed.add_field(name="Expected Number", value=str(expected_count), inline=True)
            embed.add_field(name="Current Count", value="The count has been reset to 0", inline=True)
            embed.set_footer(text="Start counting from 1 again!")
            embed.timestamp = datetime.datetime.now()
            
            # Reset the game
            logger.info(f"Resetting count for guild {message.guild.id} ({message.guild.name}) - wrong number entered by {message.author.name} ({message.author.id})")
            await db_execute(
                '''UPDATE counting_game 
                   SET current_count = 0, last_user_id = NULL, last_message_id = $2 
                   WHERE guild_id = $1''',
                message.guild.id, message.id
            )
            logger.info(f"Count reset to 0 in database for guild {message.guild.id}")
            
            await message.channel.send(embed=embed)
            return
            
        # Correct number!
        await message.add_reaction('✅')
        
        # Update the count in the database
        logger.info(f"Updating count to {count} for guild {message.guild.id} ({message.guild.name}), user: {message.author.name} ({message.author.id})")
        await db_execute(
            '''UPDATE counting_game 
               SET current_count = $2, last_user_id = $3, last_message_id = $4 
               WHERE guild_id = $1''',
            message.guild.id, count, message.author.id, message.id
        )
        logger.info(f"Count successfully updated to {count} in database")
        
        # Check if we reached the max count (victory)
        if count >= max_count:
            # Create victory embed
            embed = discord.Embed(
                title="🎉 Counting Victory",
                description=f"The server has successfully counted to **{max_count}**!",
                color=discord.Color.from_rgb(0, 191, 255)  # Frostline blue
            )
            embed.add_field(name="Final Count", value=str(count), inline=True)
            embed.add_field(name="Last Counter", value=message.author.mention, inline=True)
            embed.set_footer(text="The count has been reset. Start from 1 again!")
            embed.timestamp = datetime.datetime.now()
            
            # Reset the game for next round
            logger.info(f"Victory achieved for guild {message.guild.id} ({message.guild.name})! Resetting count for new game.")
            await db_execute(
                '''UPDATE counting_game 
                   SET current_count = 0, last_user_id = NULL 
                   WHERE guild_id = $1''',
                message.guild.id
            )
            logger.info(f"Count reset to 0 after victory in database for guild {message.guild.id}")
            
            await message.channel.send(embed=embed)
            
    except Exception as e:
        logger.error(f"Error in counting game: {e}")

@bot.tree.command(name="countingchannel", description="Set the channel for counting game")
@app_commands.describe(channel="The channel to use for counting")
@app_commands.guild_only()
async def countingchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set the channel for the counting game. Admin only."""
    # Check if user has admin permissions
    if not await is_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
        
    try:
        # Update the counting channel in the database
        logger.info(f"Setting counting channel to {channel.id} ({channel.name}) for guild {interaction.guild.id} ({interaction.guild.name})")
        await db_execute(
            '''UPDATE servers SET counting_channel = $2 WHERE guild_id = $1''',
            interaction.guild.id, channel.id
        )
        logger.info(f"Counting channel updated in database for guild {interaction.guild.id}")
        
        # Initialize or reset the counting game for this guild
        game_exists = await db_fetch(
            '''SELECT 1 FROM counting_game WHERE guild_id = $1''',
            interaction.guild.id
        )
        
        if not game_exists:
            logger.info(f"Creating new counting game entry for guild {interaction.guild.id} ({interaction.guild.name})")
            await db_execute(
                '''INSERT INTO counting_game(guild_id, current_count, max_count) 
                   VALUES($1, 0, 100)''',
                interaction.guild.id
            )
            logger.info(f"New counting game entry created in database")
        else:
            logger.info(f"Resetting existing counting game for guild {interaction.guild.id} ({interaction.guild.name})")
            await db_execute(
                '''UPDATE counting_game 
                   SET current_count = 0, last_user_id = NULL 
                   WHERE guild_id = $1''',
                interaction.guild.id
            )
            logger.info(f"Existing counting game reset in database")
        
        # Set fixed max count to 100
        max_count = 100
        
        # Create embed for channel setup
        embed = discord.Embed(
            title="🔢 Counting Channel Set",
            description=f"The counting game channel has been set to {channel.mention}.",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline blue
        )
        embed.add_field(name="How to Play", value="Count sequentially starting from 1. Each user can only count once in a row.", inline=False)
        embed.add_field(name="Goal", value=f"Reach **{max_count}** without making a mistake!", inline=False)
        embed.add_field(name="Rules", value="• Only numbers are allowed\n• Must count in sequence\n• No counting twice in a row\n• If someone makes a mistake, count resets to 0", inline=False)
        embed.set_footer(text="Use /maxcount to adjust the maximum target number")
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
        
        # Send a starting message to the counting channel
        start_embed = discord.Embed(
            title="🔢 Counting Game",
            description=f"Let's start counting from **1** to **{max_count}**!",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline blue
        )
        start_embed.add_field(name="Current Count", value="0", inline=True)
        start_embed.add_field(name="Next Number", value="1", inline=True)
        
        # Add rules and instructions to the same embed
        start_embed.add_field(name="How to Play", value="Count sequentially starting from 1. Each user can only count once in a row.", inline=False)
        start_embed.add_field(name="Goal", value=f"Reach **{max_count}** without making a mistake!", inline=False)
        start_embed.add_field(name="Rules", value="• Only numbers are allowed\n• Must count in sequence\n• No counting twice in a row\n• If someone makes a mistake, count resets to 0", inline=False)
        start_embed.set_footer(text="Use /maxcount to adjust the maximum target number | Start by sending the number 1 in this channel")
        
        await channel.send(embed=start_embed)
        
    except Exception as e:
        logger.error(f"Error setting counting channel: {e}")
        await interaction.response.send_message(f"Error setting counting channel: {str(e)}", ephemeral=True)

@bot.tree.command(name="maxcount", description="Set the maximum target for the counting game")
@app_commands.describe(maximum="The maximum number to count up to (1-1000)")
@app_commands.guild_only()
async def maxcount(interaction: discord.Interaction, maximum: int):
    """Set the maximum target number for the counting game. Admin only."""
    # Check if user has admin permissions
    if not await is_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
        
    # Validate the maximum count
    if maximum < 1 or maximum > 1000:
        await interaction.response.send_message("The maximum count must be between 1 and 1000.", ephemeral=True)
        return
        
    try:
        # Check if counting is set up for this guild
        counting_channel = await db_fetch(
            '''SELECT counting_channel FROM servers WHERE guild_id = $1''',
            interaction.guild.id
        )
        
        if not counting_channel or not counting_channel[0]['counting_channel']:
            await interaction.response.send_message(
                "Please set up a counting channel first using /countingchannel.", 
                ephemeral=True
            )
            return
            
        # Update the maximum count in the database
        game_exists = await db_fetch(
            '''SELECT 1 FROM counting_game WHERE guild_id = $1''',
            interaction.guild.id
        )
        
        if not game_exists:
            logger.info(f"Creating new counting game with max_count={maximum} for guild {interaction.guild.id} ({interaction.guild.name})")
            await db_execute(
                '''INSERT INTO counting_game(guild_id, current_count, max_count) 
                   VALUES($1, 0, $2)''',
                interaction.guild.id, maximum
            )
            logger.info(f"New counting game created with max_count={maximum} in database")
        else:
            logger.info(f"Updating max_count to {maximum} for guild {interaction.guild.id} ({interaction.guild.name})")
            await db_execute(
                '''UPDATE counting_game SET max_count = $2 WHERE guild_id = $1''',
                interaction.guild.id, maximum
            )
            logger.info(f"Updated max_count to {maximum} in database")
        
        # Create confirmation embed
        embed = discord.Embed(
            title="🔢 Counting Goal Updated",
            description=f"The maximum counting target has been set to **{maximum}**.",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline blue
        )
        embed.add_field(name="Current Game", value="The current counting game will continue with the new maximum.", inline=False)
        embed.set_footer(text="Good luck counting to the new goal!")
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
        
        # Update the counting channel with the new max
        channel_id = counting_channel[0]['counting_channel']
        channel = bot.get_channel(channel_id)
        
        if channel:
            # Get current game state
            game_data = await db_fetch(
                '''SELECT current_count FROM counting_game WHERE guild_id = $1''',
                interaction.guild.id
            )
            
            current_count = game_data[0]["current_count"] if game_data else 0
            
            update_embed = discord.Embed(
                title="🔢 Counting Goal Changed",
                description=f"The goal has been updated to count to **{maximum}**!",
                color=discord.Color.from_rgb(0, 191, 255)  # Frostline blue
            )
            update_embed.add_field(name="Current Count", value=str(current_count), inline=True)
            update_embed.add_field(name="Next Number", value=str(current_count + 1), inline=True)
            update_embed.set_footer(text="Continue counting from where you left off")
            
            await channel.send(embed=update_embed)
        
    except Exception as e:
        logger.error(f"Error setting count maximum: {e}")
        await interaction.response.send_message(f"Error setting count maximum: {str(e)}", ephemeral=True)

@bot.tree.command(name="updatecount", description="Update the counting game with messages sent while bot was offline")
@app_commands.describe(count="The current count to update to")
@app_commands.guild_only()
async def updatecount(interaction: discord.Interaction, count: int):
    """Update the counting game with the current count when messages were sent while bot was offline. Admin only."""
    # Check if user has admin permissions
    if not await is_admin(interaction):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return
        
    try:
        # Check if counting is set up for this guild
        counting_channel = await db_fetch(
            '''SELECT counting_channel FROM servers WHERE guild_id = $1''',
            interaction.guild.id
        )
        
        if not counting_channel or not counting_channel[0]['counting_channel']:
            await interaction.response.send_message(
                "Please set up a counting channel first using /countingchannel.", 
                ephemeral=True
            )
            return
            
        # Validate the count
        if count < 0:
            await interaction.response.send_message("The count must be a non-negative number.", ephemeral=True)
            return
            
        # Get current game data
        game_data = await db_fetch(
            '''SELECT current_count, max_count FROM counting_game WHERE guild_id = $1''',
            interaction.guild.id
        )
        
        if not game_data:
            logger.info(f"Creating new counting game with current_count={count} for guild {interaction.guild.id} ({interaction.guild.name})")
            await db_execute(
                '''INSERT INTO counting_game(guild_id, current_count, max_count) 
                   VALUES($1, $2, 100)''',
                interaction.guild.id, count
            )
            max_count = 100
            logger.info(f"New counting game created with current_count={count} in database")
        else:
            logger.info(f"Updating current_count to {count} for guild {interaction.guild.id} ({interaction.guild.name})")
            await db_execute(
                '''UPDATE counting_game SET current_count = $2, last_user_id = NULL WHERE guild_id = $1''',
                interaction.guild.id, count
            )
            max_count = game_data[0]['max_count']
            logger.info(f"Updated current_count to {count} in database")
        
        # Create confirmation embed
        embed = discord.Embed(
            title="🔢 Counting Game Updated",
            description=f"The current count has been updated to **{count}**.",
            color=discord.Color.from_rgb(0, 191, 255)  # Frostline blue
        )
        embed.add_field(name="Next Number", value=str(count + 1), inline=True)
        embed.add_field(name="Goal", value=str(max_count), inline=True)
        embed.set_footer(text="The counting game has been updated to reflect messages sent while the bot was offline.")
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
        
        # Update the counting channel with the new count
        channel_id = counting_channel[0]['counting_channel']
        channel = bot.get_channel(channel_id)
        
        if channel:
            update_embed = discord.Embed(
                title="🔢 Counting Game Updated",
                description=f"The count has been updated to **{count}** to reflect messages sent while the bot was offline.",
                color=discord.Color.from_rgb(0, 191, 255)  # Frostline blue
            )
            update_embed.add_field(name="Current Count", value=str(count), inline=True)
            update_embed.add_field(name="Next Number", value=str(count + 1), inline=True)
            update_embed.add_field(name="Goal", value=str(max_count), inline=True)
            update_embed.set_footer(text="Continue counting from the updated number")
            
            await channel.send(embed=update_embed)
        
    except Exception as e:
        logger.error(f"Error updating count: {e}")
        await interaction.response.send_message(f"Error updating count: {str(e)}", ephemeral=True)

if __name__ == "__main__":
    bot.run(TOKEN)