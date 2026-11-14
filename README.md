# telegram-digest

A small local web app at **http://localhost:8765** that keeps a read-only copy of
the Telegram groups (and subgroups/topics) you choose, so Claude can write digests
that link straight back to the original messages.

- **Read-only.** It only reads messages. It never sends anything and never marks
  messages as read, so your unread counts stay as they are.
- **Your login stays private.** The Telegram session (a full key to your account)
  lives in `~/.config/telegram-digest/`, outside this repo, readable only by you.
  It shows up in Telegram → Settings → Devices as "telegram-digest (Mac)".
- Runs in the background via launchd, starts at login, and exports new messages
  every 2 hours while the Mac is awake.

## Install / update

For anyone (Mac): paste into Terminal

```bash
curl -fsSL https://raw.githubusercontent.com/m3h0w/telegram-digest/main/install.sh | bash
```

Or hand your AI assistant this sentence and let it lead you:
*"Help me set up Telegram Digest on my Mac. Follow this guide step by step:
https://raw.githubusercontent.com/m3h0w/telegram-digest/main/AI-SETUP.md"*

From a clone of this repo: `bash setup.sh`.

Then do everything else in the browser:

- **Setup**: API keys (from my.telegram.org/apps), Telegram login, which groups and
  which subgroups to include, "Export now".
- **Messages**: browse by group → subgroup → day. Every message has
  *Open in Telegram ↗* (opens the app) and *web* (t.me) links.
- **Digest**: digests your AI assistant writes into `digests/` after reading this folder
  (instructions for it are in `HOW-TO-DIGEST.md`), per subgroup, every point linking to
  its source messages.

## Files

| Path | What |
|---|---|
| `exports/YYYY-MM-DD/<group>/<subgroup>.md` | readable log, one file per subgroup (`chat.md` for plain groups) |
| `exports/YYYY-MM-DD/<group>/messages.jsonl` | the same messages as JSON, with group/subgroup ids and Telegram links |
| `digests/*.json` | digests written by Claude (shown in the Digest tab) |
| `selection.json` | which groups / subgroups are exported |
| `.env` | API keys |

`.env`, `exports/`, `digests/`, `selection.json`, logs and state are git-ignored.

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
