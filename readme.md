# FrostMod V2 Discord Bot

FrostMod V2 is a Discord bot designed for server moderation, user onboarding, and event logging. It uses a local PostgreSQL database for persistent storage of server settings and logs.

## Features
- **Welcome System**: Greet new members with a customizable welcome message (supports `{user}` and `{membercount}` placeholders) in a channel of your choice.
- **Automatic Join Role**: Assign a specific role to new members automatically.
- **Moderation Tools**: Warn users, purge messages, and keep track of user infractions.
- **Logging System**: Log important server events (channel creation/deletion, member joins/leaves, username/avatar changes) to a designated channel with detailed, attractive embeds.
- **Slash Commands**: Modern, easy-to-use Discord slash commands for all features.

## Commands

### Admin/Mod Commands
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



