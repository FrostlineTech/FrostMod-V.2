# FrostMod V2 Discord Bot

FrostMod V2 is a Discord bot designed for server moderation, user onboarding, and event logging. It uses a local PostgreSQL database for persistent storage of server settings and logs.

## Features
- **Welcome System**: Greet new members with a customizable welcome message (supports `{user}` and `{membercount}` placeholders) in a channel of your choice.
- **Automatic Join Role**: Assign a specific role to new members automatically.
- **Moderation Tools**: Warn users, purge messages, and keep track of user infractions.
- **Logging System**: Log important server events (channel creation/deletion, member joins/leaves, username/avatar changes) to a designated channel with detailed, attractive embeds.
- **Slash Commands**: Modern, easy-to-use Discord slash commands for all features.

## Commands

- **/mrole <role>**
  - Set a moderator role for your server. Members with this role can use all admin-only commands, even if they do not have the Administrator permission. Only server admins or the bot owner can use this command.

- **/avatar [user]**
  - Shows the profile picture (avatar) of the specified user, or your own if omitted.

- **/welcome <channel>**
  - Set the channel where welcome messages will be sent (admin or mod role).

- **/wmessage <message>**
  - Set the welcome message for new members. Supports `{user}` (new member) and `{membercount}` (current server member count) placeholders. Example: `Welcome {user}! You are member #{membercount}.`

- **/joinrole <role>**
  - Set a role to automatically assign to new members (admin or mod role).

- **/logschannel <channel>**
  - Set the channel where server events (channel creation, deletion, member joins/leaves) are logged (admin or mod role).

- **/bdaychannel <channel>**
  - Set the channel where birthday announcements will be posted (admin or mod role).

- **/warn <user> <reason>**
  - Warn a user with a reason (admin or mod role). This will be logged in the server's logs channel if set.

- **/warns <user>**
  - List all warnings for a specific user (admin or mod role).

- **/delwarns <user>**
  - Delete all warnings for a specific user (admin or mod role).

- **/purge <amount>**
  - Delete a specified number of messages (1-100) from the current channel (admin or mod role).

- **/purgeuser <user> <amount>**
  - Delete a specified number of messages (1-100) from a specific user in the current channel (admin or mod role).

- **/support**
  - Get bot support from the Frostline development team.

- **/setbirthday mm/dd/yyyy**
  - Set your own birthday for birthday announcements (users can only set their own birthday).

- **/help**
  - Lists all available commands and usage information.



