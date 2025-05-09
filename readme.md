# FrostMod V2 Discord Bot

FrostMod V2 is a powerful, scalable Discord moderation bot built for Frostline Solutions. It provides advanced moderation, onboarding, logging, and a branded ticketing system for support. Data is stored securely in PostgreSQL.

## Features

### Moderation & Security
- **Advanced Chat Filter**: Three-tiered word filter system (light, moderate, strict) with automatic warnings
- **Warning System**: Track and manage user infractions with `/warn`, `/warns`, and `/delwarns` commands
- **Message Purging**: Bulk delete messages with `/purge` and `/purgeuser` commands
- **Permission System**: Flexible admin/mod role system with server-specific configuration
- **Detailed Logging**: Comprehensive event logging for all moderation actions

### Member Management
- **Welcome System**: Customizable welcome messages with placeholders (`{user}`, `{membercount}`, `{servername}`)
- **Auto-Role**: Automatically assign roles to new members
- **Birthday System**: Track and announce member birthdays
- **Account Monitoring**: Flag new accounts and track join/leave patterns

### Server Management
- **Event Logging**: Track channel creation/deletion, member joins/leaves, username/avatar changes
- **Audit Integration**: Detailed logs with executor tracking for server events
- **Server Configuration**: Easy setup with dedicated commands for each feature

### Support System
- **Ticketing System**: Branded Frostline ticket system with private channels
- **Ticket Tracking**: All ticket actions are logged in the database for auditing
- **User-Friendly Interface**: Clean embeds and intuitive button interactions

### Engagement & Activities
- **Counting Game**: Interactive counting challenge for server members
- **Progress Tracking**: Count resets if a user breaks the sequence
- **Customizable Goals**: Set counting targets from 1 to 1000

### Technical Features
- **Slash Commands**: Modern Discord interaction system
- **PostgreSQL Database**: Reliable data storage for all bot features
- **Robust Error Handling**: Comprehensive logging and error recovery
- **Performance Optimized**: Efficient resource usage and API call management

## Ticketing System
- **/ticketchannel <channel>** — Admins set the ticket creation channel with a branded embed and "Open Ticket" button
- **Private Channels**: Each ticket creates a dedicated channel visible only to the user and staff
- **Ticket Management**: Both staff and the ticket creator can close tickets
- **Automatic Cleanup**: Channels are deleted after closing to keep the server organized

## Commands

### Server Configuration
- **/mrole <role>** — Set the moderator role for admin commands
- **/filter <level>** — Set chat filter level (light, moderate, strict)
- **/welcome <channel>** — Set the welcome channel for new members
- **/wmessage <message>** — Set the welcome message with placeholders: `{user}`, `{membercount}`, `{servername}`
- **/joinrole <role>** — Set the role automatically assigned to new members
- **/logschannel <channel>** — Set the channel for event and moderation logs
- **/ticketchannel <channel>** — Set the channel for ticket creation
- **/bdaychannel <channel>** — Set the channel for birthday announcements

### Moderation Tools
- **/warn <user> <reason>** — Warn a user and log the reason
- **/warns <user>** — View all warnings for a specific user
- **/delwarns <user>** — Delete all warnings for a specific user
- **/purge <amount>** — Delete up to 100 messages from the current channel
- **/purgeuser <user> <amount>** — Delete up to 100 messages from a specific user

### Birthday System
- **/setbirthday <mm/dd/yyyy>** — Set your birthday for server announcements
- **/delbday <user>** — Delete a birthday (users can delete their own; admins can delete any)
- **/testbirthdays** — Test birthday announcements for the current day

### Utility Commands
- **/avatar [user]** — Show a user's profile picture
- **/status** — Display bot uptime and latency
- **/support** — Get a link to the Frostline support server
- **/help** — Show all available commands

### Fun Commands
- **/twerkz** — Generates a random twerk message
- **/8ball <question>** — Ask the magic 8-ball a question
- **/coinflip** — Flip a coin and get heads or tails
- **/roll [dice] [sides]** — Roll dice with customizable count and sides
- **/joke** — Get a random joke
- **/countingchannel <channel>** — Set up a channel for the counting game
- **/maxcount <1-1000>** — Set the maximum target for the counting game

*All configuration and moderation commands require Administrator permission or the server's mod role (set with /mrole).*

## Permissions

FrostMod requires the following permissions to function properly:
- **Administrator** or the following specific permissions:
  - Manage Roles (for join roles)
  - Manage Channels (for ticket creation/deletion)
  - Manage Messages (for message filtering and purging)
  - View Channels & Send Messages (for all commands)
  - Embed Links (for rich embeds)
  - Read Message History (for purge commands)
  - Use External Emojis (for better UI)
  - Add Reactions (for interactive features)

## Setup Guide

1. **Invite the bot** to your server with the required permissions
2. **Set up logging** with `/logschannel #your-logs-channel`
3. **Configure moderation** with `/mrole @Your-Mod-Role` and `/filter moderate`
4. **Set up welcome system** with `/welcome #welcome-channel` and `/wmessage Welcome {user} to {servername}!`
5. **Enable tickets** with `/ticketchannel #support-channel`
6. **Set up birthdays** with `/bdaychannel #birthdays-channel`
7. **Enable the counting game** with `/countingchannel #counting-channel`

Once configured, all features will be active and ready to use!
