# Telegram Admin Bot — Features & Usage

This document outlines all ready features in the bot and how to use them effectively. It complements the README with practical, admin‑oriented guidance.

## Basics
- `start`: Starts or deep‑links into rule acceptance. In DMs shows a welcome and prompts to use `/panel`.
- `help`: Summarizes available commands and directs admins to `/panel` in DM.
- `rules`: Shows the group’s rules text (set by admins).
- `settings`: In groups, prompts to open the admin panel in DM; in DMs opens `/panel`.
- `panel`: Opens the admin control panel in private chat with the bot.
- `bot` (owners): Opens Bot Admin panel in DM for broadcasts, stats, and global blacklist.

Notes
- Run the bot as described in README, then promote it to admin in target groups with rights: Delete messages, Restrict/ban, Pin, Manage chat, Manage topics.
- Disable privacy in @BotFather so the bot can moderate non‑command messages.

## Moderation
- `warn` (reply): Adds a warning to the replied user. Escalates to a temporary mute when the warn limit is reached.
- `unwarn` (reply): Removes one warning from the replied user.
- `mute <duration>` (reply): Restricts the replied user from sending messages.
- `unmute` (reply): Lifts restrictions for the replied user.
- `ban <duration>` (reply): Bans the replied user.
- `unban` (reply): Unbans if currently banned.
- `purge <N>`: Deletes the last `N` messages before your command message.

Details
- Target by replying to the user’s message. Non‑admins are silently ignored.
- Duration format: `30s`, `10m`, `2h`, `3d`, or `perm` for no expiry.
- Warn escalation: after `warn_limit` warnings (default 3), the bot mutes temporarily and resets the user’s warns.
- Delete offense: optionally auto‑delete offending content for actions like warn/mute/ban.
- Ephemeral moderator responses: optional auto‑delete (e.g., 10s/30s) for bot replies.

Configure in Panel
- Moderation tab: set warn limit, toggle delete‑offense, pick ephemeral reply timeout, browse recent violators and apply quick actions (warn/mute/ban) from the list.

## Anti‑Spam & Content Safety
Flood Control
- Detects message floods per user in a time window. Default config: window 5s, threshold 8, mute 60s, ban 600s.
- Escalation: first warn, then mute, then temporary ban.

Content Rules
- Admin commands:
  - `addrule <word|regex> <delete|warn|mute|ban> <pattern>`
  - `listrules`
  - `delrule <id>`
- Behavior:
  - `word` checks case‑insensitive substring.
  - `regex` uses Python RE with `IGNORECASE`.
  - Actions: `delete`, `warn` (sends a general warning and triggers warn escalation), `mute`, `ban`.
  - Special action `reply` (set via panel) replies with custom text without deleting; other actions delete first.
  - Per‑rule escalation presets: e.g., “2 in 5m → mute”, “3 in 10m → ban”.

Links Policy
- Manage via Panel → Rules → Links Policy.
- Controls:
  - Block‑all toggle with default action (`delete`, `warn`, `mute`, `ban`).
  - Denylist and allowlist domain management (allowlist overrides all).
  - Per‑type actions: Invites, Telegram links, Shorteners, Other.
  - Night Mode: time window and timezone offset; can force block‑all during night hours.

Forward & Media Locks
- Manage via Panel → Rules → Forward & Media Locks.
- Apply per‑type actions (`allow`, `delete`, `warn`, `mute`, `ban`) for:
  - Forwards, Photo, Video, Document, Sticker, Voice, Audio, Animation, Video Note.

## Rules
- `rules`: Displays the configured rules or a default placeholder.
- `setrules <text>`: Set rules inline, or reply to a message with `/setrules` to use the replied text.
- Panel → Rules → “Edit Rules Text”.

Deep‑Linking to Rules
- The bot supports `/start` deep‑link payloads to show rules in DMs with an “Accept” button, e.g. `rulesu_<group_username>` or `rules64_<base64(group_id)>`.

## Welcome
- Sends a welcome message on user join.
- Template supports `{first_name}` and `{group_title}`.
- Auto‑delete TTL can be set (Off, 60s, 300s, 900s).
- If Onboarding is configured to “require acceptance to unmute”, the bot initially mutes the new member and posts a DM deep‑link button in the group to read and accept rules before auto‑unmute.

Configure in Panel
- Welcome tab: toggle, edit template, set auto‑delete TTL, quick access to rules editor.

## Onboarding
Auto‑Approve Join Requests
- `joinapprove on|off`: Toggle automatic approval of join requests.
- Panel → Onboarding: toggle and see state.

Require Rules Acceptance
- Pre‑approval: if enabled, the bot DMs the user the rules with Accept/Decline before approving. Approval proceeds only after Accept.
- Post‑approval unmute: optionally require rules acceptance in DMs to lift a post‑approval mute in the group.
- The bot attempts to DM rules; Telegram may require the user to “start” the bot first.

Captcha Verification
- Restricts new members until verification completes, then unmutes.
- Modes: button (“I am human”) or simple math; configurable timeout (default 120s). On timeout the bot kicks (ban+unban) to remove the user.
- Configure in Panel → Onboarding (toggle, mode, timeout).

## Automations
Announcements
- Schedule a one‑off or repeating announcement from the panel. Options:
  - Send plain text provided in the panel.
  - Copy a message by sending it to the bot in DM when prompted (supports any message type).
  - Send media albums (photos/videos/documents/audio); the bot collects an album and schedules it as one announcement.
- Optional “notify me” behavior: when created from the panel, you receive a confirmation DM after the announcement is sent.

Rotate Pin
- Schedule periodic pin rotation: send a message (or copy one) each interval and pin it; optionally unpin the previous.

Timed Unmute/Unban
- From the panel, schedule a delayed unmute/unban by providing a user ID and delay.

Where to Configure
- Panel → Automations: choose Once or Repeat, pick delay/interval, then provide the content by replying with text or forwarding the source message.

## Forum Topics
- `topic_close`: Close the current forum topic (use inside a topic).
- `topic_open`: Reopen the current forum topic.
- `topic_rename <name>`: Rename the current topic.
- `topic_pin` (reply): Pin the replied message in the topic (use inside the topic and reply to target message).

## Audit
- Panel → Audit: browse recent moderation events with pagination.
- Panel → Moderation → Recent Violators: quick actions on last offenders.

## Language & Localization
- Built‑in locales: English (`en`) and Arabic (`ar`).
- Panel → Language: set per‑group language override; otherwise the bot picks based on user/group context and `DEFAULT_LANG`.

## Permissions & Safety
- Admin‑only actions: group admin status is revalidated via `getChatMember` with a short cache. Owners configured in `OWNER_IDS` always pass.
- The bot logs and gracefully handles Telegram API failures; some actions (e.g., DMs to users) may fail if privacy prevents the contact.

## Tips & Examples
- Mute a user for 2 hours: reply and send `\mute 2h`.
- Temp‑ban a user for a day: reply and send `\ban 1d`.
- Add a content rule to delete “buy now” ads: `\addrule word delete buy now`.
- Require pre‑approval with DM rules and Captcha: use Panel → Onboarding to enable “Require rules acceptance” and Captcha (math or button).

---
If you need help tweaking defaults (warn limit, anti‑spam thresholds, link policies), open `/panel` in DM and use the corresponding tabs. The bot persists all settings per group in SQLite and applies them immediately.

## Bot Admin (Owners)
- Access: DM the bot and send `/bot` (owner IDs set via `OWNER_IDS`).
- Broadcast:
  - Targets: all groups, all tracked users, or a specific chat ID.
  - Content: any message type (text/media), albums supported; uses `copy_message` or `send_media_group`.
  - Safety: shows a confirmation with target count before capturing content.
- Statistics: shows totals for groups, users, active automations, and violations.
- Global Blacklist (cross‑group):
  - Add/delete words and choose global action (`warn`, `mute`, `ban`).
  - Export/import config as JSON for backup and sharing.
