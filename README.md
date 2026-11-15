# telegram-digest

A small local web app at **http://localhost:8765**, for Mac and Windows, that keeps a
read-only copy of the Telegram groups (and subgroups/topics) you choose, so your AI
(Claude or ChatGPT) can write digests that link straight back to the original messages.

- **Read-only.** It only reads messages. It never sends anything and never marks
  messages as read, so your unread counts stay as they are.
- **Your login stays private.** The Telegram session (a full key to your account)
  lives in `~/.config/telegram-digest/`, outside this repo, readable only by you.
  It shows up in Telegram → Settings → Devices as "telegram-digest (Mac)" or "(Windows)".
- Runs in the background (launchd on a Mac, a Startup-folder runner on Windows), starts
  at login, restarts itself after updates, and saves new messages every 2 hours while the
  computer is awake.

## Install / update

Mac: paste into Terminal

```bash
curl -fsSL https://raw.githubusercontent.com/m3h0w/telegram-digest/main/install.sh | bash
```

Windows 10/11: paste into PowerShell (no administrator rights needed; installs Python if missing)

```powershell
irm https://raw.githubusercontent.com/m3h0w/telegram-digest/main/install.ps1 | iex
```

Or hand your AI assistant this sentence and let it lead you:
*"Help me set up Telegram Digest on my computer. Follow this guide step by step:
https://raw.githubusercontent.com/m3h0w/telegram-digest/main/AI-SETUP.md"*

From a clone of this repo: `bash setup.sh`.

Then do everything else in the browser:

- **Setup**: API keys (from my.telegram.org/apps), Telegram login, which groups and
  which subgroups to include, "Export now".
- **Messages**: browse by group → subgroup → day. Every message has
  *Open in Telegram ↗* (opens the app) and *web* (t.me) links.
- **Digest**: summaries per subgroup, every point linking to its source messages, with
  a Mac notification when one arrives. They're written either automatically by the app
  using Claude Code or Codex on your own plan (no API keys), or by your AI assistant when
  you ask (instructions for it are in `HOW-TO-DIGEST.md`).
- **Photos**: saved as small previews (about 800 px, kept 30 days), shown in Messages, and
  read by the digest (posters, schedules, screenshots), up to 20 per digest. Switch:
  Settings → Digests → More options.
- **Storage**: saved messages, photos and digests older than a week are deleted
  automatically (the newest digest is always kept). Settings → Storage changes both limits.
- **Digests on your phone**: optional; each digest arrives as a Telegram message from your
  own private bot (set up in two minutes from Settings), with links to the original messages.
- **Settings** (Setup tab), with defaults: fetch every 2 hours; digests automatic, every 4
  hours if anything is new, covering everything since the previous digest; notify when
  something needs attention; written by whichever of Claude Code or Codex is installed,
  with that tool's default model and effort (both changeable under Digests → More options).
  `what-matters.md` teaches the digest what needs your attention.

## Files

| Path | What |
|---|---|
| `exports/YYYY-MM-DD/<group>/<subgroup>.md` | readable log, one file per subgroup (`chat.md` for plain groups) |
| `exports/YYYY-MM-DD/<group>/messages.jsonl` | the same messages as JSON, with group/subgroup ids and Telegram links |
| `digests/*.json` | digests written by Claude (shown in the Digest tab) |
| `selection.json` | which groups / subgroups are exported |
| `what-matters.md` | what should count as "needs attention" (read and updated by the AI) |
| `settings.json` | settings from the Setup tab |
| `.env` | API keys |

`.env`, `exports/`, `digests/`, `selection.json`, `what-matters.md`, `settings.json`, logs and state are git-ignored.

## Digest format (for Claude)

```json
{"title": "...", "from": "ISO time", "to": "ISO time",
 "groups": [{"group_id": "-100…", "title": "...",
   "highlights": [{"text": "…", "refs": [message ids]}],
   "topics": [{"topic": "subgroup name", "topic_id": 5, "bullets": [{"text": "…", "refs": [ids]}]}]}]}
```

`topic_id` is optional (matched by name otherwise). `**bold**` works in text.

## Turning it off

```bash
launchctl bootout gui/$(id -u)/local.telegram-digest
rm ~/Library/LaunchAgents/local.telegram-digest.plist
rm -r ~/.config/telegram-digest
```

Then end the "telegram-digest (Mac)" session in Telegram → Settings → Devices.

## Publishing an update

Installed copies check `release.json` on GitHub about once a day. When its `version` is
higher than theirs, the app shows "A new version is available" with an **Update now**
button: it downloads that version, checks the code compiles, installs any missing package,
swaps the files in and restarts itself. Settings, the Telegram login and saved messages
are kept. To publish:

1. Bump `version` in `release.json` (a date works: `2026.11.20`; add `.1` for a second
   release on the same day) and write one line of `notes` (shown to people as-is).
2. List any new file in `files`. Set `"reinstall": true` only when an update needs the
   install line run again (for example a change to the background service setup).
3. Push. Pushes that don't bump the version reach nobody.

Copies that are git checkouts never update themselves. Installs from before version
2026.11.15 need the install line run once to get the button.

