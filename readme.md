# FrostMod V2 Discord Bot

FrostMod V2 is a powerful, scalable Discord moderation bot built for Frostline Solutions. It provides advanced moderation, onboarding, logging, and a branded ticketing system for support. Data is stored securely in PostgreSQL.

## Features
- **Welcome System**: Greet new members with a customizable message (supports `{user}` and `{membercount}` placeholders).
- **Automatic Join Role**: Assign a role to new members automatically.
- **Moderation Tools**: Warn users, purge messages (by user or count), and manage infractions.
- **Logging System**: Log server events (channel creation/deletion, member joins/leaves, username/avatar changes) to a designated channel with branded embeds.
- **Ticketing System**: Branded Frostline ticket system with `/ticketchannel` setup, "Open Ticket" button, private ticket channels, and database tracking.
- **Birthday System**: Announce user birthdays in a dedicated channel.
- **Slash Commands**: Modern, easy-to-use Discord slash commands for all features.

## Ticketing System
- **/ticketchannel <channel>** — Admins set the ticket creation channel. The bot posts a branded embed with an "Open Ticket" button.
- **Open Ticket Button** — Users open a private support channel, visible only to them and staff.
- **Ticket Management** — Staff and the user can close tickets. Channels are deleted after closing, and all ticket actions are tracked in the database for auditing.

## Commands

### Admin/Mod Commands
- **/ticketchannel <channel>** — Set the channel for ticket creation (admins only)
- **/mrole <role>** — Set the moderator role for admin commands (admins only)
- **/welcome <channel>** — Set the welcome channel
- **/wmessage <message>** — Set the welcome message
- **/joinrole <role>** — Set the auto-join role
- **/logschannel <channel>** — Set the logs channel
- **/bdaychannel <channel>** — Set the birthday announcements channel
- **/warn <user> <reason>** — Warn a user with a reason (logs to logs channel if set)
- **/warns <user>** — List all warnings for a user
- **/delwarns <user>** — Delete all warnings for a user
- **/purge <amount>** — Delete a specified number of messages (1-100) from the current channel
- **/purgeuser <user> <amount>** — Delete a specified number of messages (1-100) from a specific user in the current channel
- **/testbirthdays** — Test birthday announcements for today
- **/delbday <user>** — Delete a user's birthday (users can only delete their own, admins/mods can delete any)

*All above commands require Administrator permission or the server's mod role (set with /mrole), unless otherwise noted.*

### Birthday Commands
- **/setbirthday mm/dd/yyyy** — Set your own birthday for birthday announcements

### Utility Commands
- **/avatar [user]** — Show a user's profile picture (avatar)
- **/support** — Get bot support from the Frostline development team
- **/help** — Show this help message
- **/status** — Show bot ping and uptime

