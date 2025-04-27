import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncpg
from dotenv import load_dotenv

# Load environment variables at the top
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

# --------------------
# Warn System Commands
# --------------------

# --- Helper Functions ---
# (Moved below bot instantiation)

# ... (keep import and config code above this)

# Set up Discord intents before bot definition
intents = discord.Intents.default()
intents.members = True

# FrostModBot definition
class FrostModBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, application_id=None)
        self.db_pool = None

    async def setup_hook(self):
        # Register slash commands
        await self.tree.sync()
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

# --- Helper Functions ---

def is_admin(interaction):
    return interaction.user.guild_permissions.administrator

async def db_execute(query, *args):
    async with bot.db_pool.acquire() as conn:
        return await conn.execute(query, *args)

async def db_fetch(query, *args):
    async with bot.db_pool.acquire() as conn:
        return await conn.fetch(query, *args)

# --- Warn System Commands ---

@bot.tree.command(name="warn", description="Warn a user with a reason (admin only)")
@app_commands.describe(user="The user to warn", reason="The reason for the warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    """Warn a user in the server and log the reason. Admin only."""
    if not is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        await db_execute(
            '''INSERT INTO warns (guild_id, guild_name, user_id, username, reason) VALUES ($1, $2, $3, $4, $5)''',
            interaction.guild.id, interaction.guild.name, user.id, user.display_name, reason
        )
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

@bot.tree.command(name="warns", description="List all warnings for this server (admin only)")
async def warns(interaction: discord.Interaction):
    """List all warnings for this server. Admin only."""
    if not is_admin(interaction):
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        rows = await db_fetch(
            '''SELECT username, reason, warned_at, guild_name FROM warns WHERE guild_id = $1 ORDER BY warned_at DESC''',
            interaction.guild.id
        )
        if not rows:
            await interaction.response.send_message("No warnings found for this server.", ephemeral=True)
            return
        guild_name = rows[0]['guild_name'] if rows else interaction.guild.name
        embed = discord.Embed(title=f"Warnings for {guild_name}", color=discord.Color.orange())
        for row in rows:
            embed.add_field(
                name=row['username'],
                value=f"Reason: {row['reason']}\nAt: {row['warned_at'].strftime('%Y-%m-%d %H:%M:%S')}",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to fetch warnings: {e}", ephemeral=True)

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

intents = discord.Intents.default()
intents.members = True

class FrostModBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, application_id=None)
        self.db_pool = None

    async def setup_hook(self):
        # Register slash commands
        await self.tree.sync()
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
            # Now log the join
            await conn.execute('''
                INSERT INTO user_joins (guild_id, user_id, username) VALUES ($1, $2, $3)
            ''', member.guild.id, member.id, str(member))
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
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET welcome_channel_id = $1 WHERE guild_id = $2
            ''', channel.id, interaction.guild.id)
        await interaction.response.send_message(f"Welcome channel set to {channel.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to set welcome channel: {e}", ephemeral=True)

@bot.tree.command(name="wmessage", description="Set the welcome message for this server.")
@app_commands.describe(message="The welcome message to send. Use {user} for the new member, {membercount} for the member count.")
async def wmessage(interaction: discord.Interaction, message: str):
    """Set the welcome message for new members. Admin only."""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET welcome_message = $1 WHERE guild_id = $2
            ''', message, interaction.guild.id)
        await interaction.response.send_message("Welcome message updated!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to update welcome message: {e}", ephemeral=True)

@bot.tree.command(name="joinrole", description="Set a role to assign to new members on join.")
@app_commands.describe(role="The role to assign to new members.")
async def joinrole(interaction: discord.Interaction, role: discord.Role):
    """Set the role to assign to new members. Admin only."""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET join_role_id = $1 WHERE guild_id = $2
            ''', role.id, interaction.guild.id)
        await interaction.response.send_message(f"Join role set to {role.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"[ERROR] Failed to set join role: {e}", ephemeral=True)

@bot.tree.command(name="logschannel", description="Set the logging channel for this server.")
@app_commands.describe(channel="The channel to send logs in.")
async def logschannel(interaction: discord.Interaction, channel: discord.TextChannel):
    # Only allow admins
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You must be an administrator to use this command.", ephemeral=True)
        return
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute('''
                UPDATE servers SET logs_channel_id = $1 WHERE guild_id = $2
            ''', channel.id, interaction.guild.id)
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
        title="FrostMod Help",
        description="Welcome to FrostMod! Here are the available commands.",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="/avatar [user]",
        value="Show a user's profile picture. If no user is specified, shows your own.",
        inline=False
    )
    embed.add_field(
        name="/welcome <channel>",
        value="Set the welcome channel for this server. Only admins can use this.",
        inline=False
    )
    embed.add_field(
        name="/wmessage <message>",
        value=(
            "Set the welcome message for this server (admin only). "
            "You can use placeholders in your message:\n"
            "- `{user}`: Mentions the new member\n"
            "- `{membercount}`: Shows the server's member count\n\n"
            "**Example:**\n"
            "`Welcome {user}! You are member #{membercount} of our community!`"
            "\n"
        ),
        inline=False
    )
    embed.add_field(
        name="/joinrole <role>",
        value="Set a role to automatically assign to new members (admin only).",
        inline=False
    )
    embed.add_field(
        name="/logschannel <channel>",
        value=(
            "Set the logging channel for server events (admin only). "
            "The bot will log channel creations, deletions, member joins, leaves, and warnings to this channel."
        ),
        inline=False
    )
    embed.add_field(
        name="/support",
        value="Get bot support from the Frostline development team.",
        inline=False
    )
    embed.add_field(
        name="/warn <user> <reason>",
        value="Warn a user with a reason (admin only). This will be logged in the server's logs channel if set.",
        inline=False
    )
    embed.add_field(
        name="/warns",
        value="List all warnings for this server (admin only).",
        inline=False
    )
    embed.add_field(
        name="/help",
        value="Show this help message.",
        inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="support", description="Get support for the bot.")
async def support(interaction: discord.Interaction):
    embed = discord.Embed(
        title="FrostMod Support",
        description="Get bot support from The bot's development team at the official Frostline Discord: https://discord.gg/BjbUXwFF6n",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)



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

if __name__ == "__main__":
    bot.run(TOKEN)
