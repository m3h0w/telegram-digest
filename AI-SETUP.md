# Telegram Digest: setup guide for AI assistants

You (Claude, ChatGPT or another assistant) are helping a person who is **not technical**
set up Telegram Digest on their **Mac**. It is a small app that keeps a read-only copy
of the Telegram groups they choose on their own computer. Afterwards they can ask you for a
digest any time: you read the saved messages and write a digest per group and subgroup,
with links back to the original messages.

## How to guide

- Go one step at a time. Give one short instruction, then wait for them to say it's done
  or to tell you what they see. Use plain words and avoid jargon.
- If you can control their browser or computer, you may do the clicking and typing
  yourself. Otherwise tell them exactly what to click.
- **Never ask for their Telegram login code** (the 5-digit code Telegram sends). They type
  it themselves. Telegram tells people never to share it, and that's right.
- They need: a Mac, Telegram on their phone (login codes arrive there), and about 15 minutes.
- It only works on a Mac. On Windows, stop and say it isn't supported yet.

## Step 1: Install the app

1. Ask them to open **Terminal**: press Cmd+Space, type `Terminal`, press Enter.
2. Ask them to paste this line and press Enter. If you can run commands on their Mac
   yourself (for example ChatGPT Work or Codex in the desktop app, or Claude with access
   to their computer), you can run it for them instead:

   ```
   curl -fsSL https://raw.githubusercontent.com/m3h0w/telegram-digest/main/install.sh | bash
   ```
3. If a window asks to install **command line developer tools**, they click *Install* and
   wait (it can take 5–15 minutes). Then they paste the same line again.
4. When it finishes, the browser opens **http://localhost:8765**. If macOS shows
   "Background Items Added", that's this app; it starts automatically when they log in.
   Ask them to bookmark the page.
5. The page opens on a short guided setup with four steps (Connect Telegram, Log in,
   Choose groups, Digests). Steps 2 to 6 below match it; help them through it there.

## Step 2: Create their Telegram API keys (my.telegram.org)

Telegram requires each person to register a small "app" to get two keys. It's free.

1. Open **https://my.telegram.org** (there's also a link in the app's Setup tab).
2. They enter their phone number in international format (for example +48 600 000 000)
   and click *Next*. A code arrives **in the Telegram app**, not by SMS. They type it in.
3. Click **API development tools**. A form *Create new application* appears. Fill it in:
   - **App title:** `My Digest` (at least 5 characters; don't use the word "Telegram")
   - **Short name:** letters and numbers only, 5–32 characters, e.g. `mydigest` plus their birth year
   - **URL:** leave empty
   - **Platform:** Desktop
   - **Description:** `Personal read-only digest`
   - Click **Create application**.
4. The page now shows **App api_id** (a number) and **App api_hash** (32 letters and digits,
   hidden behind dots; use the eye or copy icon). Keep this page open for the next step.
5. If an "ERROR" pop-up appears instead: try a different short name, turn off any VPN or
   ad blocker, reload and try again. If it keeps failing, wait an hour and retry.

## Step 3: Connect the app to Telegram

In the app at http://localhost:8765, open **Setup**:

1. **Telegram API keys:** paste the api_id and api_hash and click *Save*.
2. **Telegram account:** enter the phone number, click *Send code*, then type the code
   from the Telegram app and click *Log in*. If they have a two-step verification password,
   the app asks for it next.
   - This creates a read-only session that only lives on their Mac. It appears in
     Telegram → Settings → Devices as "telegram-digest (Mac)" and can be ended there at any time.

## Step 4: Choose groups

Still in **Setup → Groups & subgroups**:

1. Search for the groups they care about and tick them.
2. For groups with subgroups (topics), they can click **Choose subgroups** and untick the
   ones they don't want. By default all subgroups are included.
3. Click **Save selection**, then **Export now** (under *Export*). The first export
   fetches the last 24 hours.

## Step 5: Give the AI access to the folder (once)

The app saves messages in the folder **TelegramDigest** in their home folder. The AI
reads it directly, so there's no copying and pasting.

- **Claude (desktop app):** in a chat, click **Add folder** and choose `TelegramDigest`
  in their home folder.
- **ChatGPT (desktop app):** use the current ChatGPT desktop app, not "ChatGPT Classic".
  Switch to **Work** (or **Codex**), open a folder and choose `TelegramDigest` in their
  home folder, and allow access when asked.

## Step 6: Automatic digests (recommended)

The app can write digests by itself, using the person's own AI plan (no API keys), with
one of these command-line tools. Install the one that matches their plan, then sign in once:

- **Claude plan:** in Terminal run `curl -fsSL https://claude.ai/install.sh | bash`, then
  run `claude` and sign in with their Claude account. Type `/exit` when done.
- **ChatGPT account:** in Terminal run `curl -fsSL https://chatgpt.com/codex/install.sh | sh`,
  then run `codex` and choose *Sign in with ChatGPT*. Press Ctrl+C when done.

Then run the install line from Step 1 again so the app picks the tool up. In the app,
**Setup → Digests** should now say which tool writes the digests. The defaults are:
automatically, every 4 hours if there's anything new, covering everything since the previous
digest, with a notification when something needs attention. Everything there can be
changed, including "Only when I ask". **Write a digest now** makes one straight away.

If they'd rather not install anything, skip this step: you can write digests yourself
when they ask (next step).

## Step 7: Asking for a digest

With automatic digests they don't need to do anything. They can also ask you any time:
*"Give me my Telegram digest."* Then you:

1. Open `HOW-TO-DIGEST.md` in the folder and follow it.
2. Write the digest in the chat. Each point ends with [↗](link) links that open the
   original message in Telegram.
3. Save it into `digests/`, so it also shows in the app (http://localhost:8765 → Digest).

Digests are updates since the last digest by default, so they can be run as often as
the person likes. If you can run scheduled tasks with access to this folder (for example
scheduled work in the ChatGPT desktop app, or Claude's scheduled tasks), offer to make one
every morning, or every few hours. Each new digest shows a Mac notification.

Ask them what usually matters to them (people, topics, kinds of requests) and write it into
`what-matters.md`. You'll keep improving it from their feedback.

The **Messages** tab in the app lets them browse everything by group, subgroup and day.
Every message has *Open in Telegram ↗*.

## Good to know (tell them if relevant)

- New messages are fetched every 2 hours while the Mac is awake, and when they click *Export now*.
- It only reads. It never sends messages and never marks anything as read.
- Everything stays on their Mac (in the folder `TelegramDigest` in their home folder).
- **Update:** run the same Terminal line from Step 1 again. Settings and exports are kept.
- **Uninstall:** in Terminal:

  ```
  launchctl bootout gui/$(id -u)/local.telegram-digest; rm ~/Library/LaunchAgents/local.telegram-digest.plist; rm -r ~/.config/telegram-digest
  ```
  Then move the `TelegramDigest` folder to the Trash, and end the "telegram-digest (Mac)"
  session in Telegram → Settings → Devices.
- **Troubleshooting:** if http://localhost:8765 doesn't load, run the Step 1 line again.
  The log is in `~/TelegramDigest/logs/app.log`.
