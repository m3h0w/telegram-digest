# Telegram Digest: setup guide for AI assistants

You (Claude, ChatGPT or another assistant) are helping a person who is **not technical**
set up Telegram Digest on their **Mac or Windows PC**. It is a small app that keeps a read-only copy
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
- They need: a Mac or a Windows 10/11 PC, Telegram on their phone (login codes arrive there),
  and about 15 minutes. For automatic digests: a paid Claude plan or any ChatGPT plan (Step 6
  sets this up). Ask which computer they use first; a few steps differ.
- Linux and phones-only aren't supported.

## Step 1: Install the app

**On Windows:**

1. Ask them to open **PowerShell**: press the Windows key, type `PowerShell`, press Enter.
   (Not "Run as administrator"; it isn't needed.)
2. Ask them to paste this line and press Enter (or run it for them if you can run commands
   on their PC):

   ```
   irm https://raw.githubusercontent.com/m3h0w/telegram-digest/main/install.ps1 | iex
   ```
3. If Python isn't installed, the installer installs it (a few minutes). If it says it
   couldn't, follow what it prints: install Python from python.org with
   "Add python.exe to PATH" ticked, open a new PowerShell window and paste the line again.
4. When it finishes, the browser opens **http://localhost:8765**. The app starts by itself
   whenever they log in. Ask them to bookmark the page.

**On a Mac:**

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

**Then, on either computer:** the page opens on a short guided setup with five steps (Connect
Telegram, Log in, Choose groups, Digests, Phone). Steps 2 to 7 below match it; help them
through it there.

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
   - This creates a read-only session that only lives on their computer. It appears in
     Telegram → Settings → Devices as "telegram-digest (Mac)" or "telegram-digest (Windows)"
     and can be ended there at any time.

## Step 4: Choose groups

Still in **Setup → Groups & subgroups**:

1. Search for the groups they care about and tick them.
2. For groups with subgroups (topics), they can click **Choose subgroups** and untick the
   ones they don't want. By default all subgroups are included.
3. Click **Save selection**, then **Export now** (under *Export*). The first export
   fetches the last 24 hours.

## Step 5: Give the AI access to the folder (once)

The app saves messages in the folder **TelegramDigest** in their home folder (on Windows:
`C:\Users\<their name>\TelegramDigest`). The AI reads it directly, so there's no copying
and pasting.

- **Claude (desktop app):** in a chat, click **Add folder** and choose `TelegramDigest`
  in their home folder.
- **ChatGPT (desktop app):** use the current ChatGPT desktop app, not "ChatGPT Classic".
  Switch to **Work** (or **Codex**), open a folder and choose `TelegramDigest` in their
  home folder, and allow access when asked.

## Step 6: Automatic digests (do this by default)

The app writes digests by itself using the person's own AI plan, through a small
command-line tool: **Claude Code** for Claude, **Codex** for ChatGPT. Nobody has these
installed by default, on any plan. Handle it for them; they shouldn't need to understand it.

1. **Ask which AI they pay for:** "Do you use Claude or ChatGPT?" If both, use the one
   they prefer. Explain in one sentence: "This lets the app use your plan to write
   digests. There's no extra cost."
   - **Claude:** Claude Code needs a paid Claude plan (Pro or higher). On Claude's free
     plan, use ChatGPT/Codex if they have it, otherwise skip this step.
   - **ChatGPT:** Codex is included with every ChatGPT plan, including Free, Go and Plus.
     Having the ChatGPT desktop app isn't enough; the command-line tool is still needed.
2. **Install it.** Run it yourself if you can run commands on their computer; otherwise have
   them paste it into Terminal (Mac) or PowerShell (Windows):
   - Claude, Mac: `curl -fsSL https://claude.ai/install.sh | bash`
   - Claude, Windows: `irm https://claude.ai/install.ps1 | iex`
   - ChatGPT, Mac: `curl -fsSL https://chatgpt.com/codex/install.sh | sh`
   - ChatGPT, Windows: `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"`

   On Windows, after installing, close PowerShell and open a new window before signing in,
   so it finds the new command.
3. **Sign in once.** This opens a browser window; *they* choose their account and allow
   access. Don't ask for their password.
   - Claude: run `claude`, choose the Claude account (subscription) login, finish in the
     browser, then type `/exit`.
   - ChatGPT: run `codex login` and choose *Sign in with ChatGPT*.
   - Never set up an API key for this. The app deliberately uses their plan instead.
4. **Let the app find it.** Run the install line from Step 1 again (it only refreshes the
   app; settings and messages are kept).
5. **Check.** In the app, **Settings → Digests → Written by** should say "Automatic choice
   (now: Claude Code)" or "(now: Codex)". Click **Write a digest now** and confirm a digest
   appears within a few minutes. If Settings shows "… failed … Is it signed in?", repeat
   the sign-in in step 3.

The app's own Setup also shows these steps (it asks "Which AI do you use?") if you're
helping without access to their computer.

The defaults are: automatically, every 4 hours if there's anything new, covering
everything since the previous digest, with a notification when something needs
attention. All of it can be changed in **Settings → Digests**, including "Only when I ask".

If they'd rather not install anything, skip this step: you can write digests yourself
when they ask (next step).

## Step 7: Digests on their phone (optional, recommended)

Digests can arrive as Telegram messages from their own private bot, so they see them on
their phone. The app's Setup shows this as the last step (and later in **Settings →
Digests on your phone**). You can't create the bot for them, because it happens in their
Telegram, but walk them through it:

1. In Telegram, open **@BotFather** (Telegram's official bot maker, with a blue tick).
2. Press **Start**, send `/newbot`, send a name (e.g. *My Digest*), then a username that
   ends in `bot` (e.g. *mydigest_2026_bot*; add numbers if it's taken).
3. BotFather replies with a **token** like `123456789:AAH…`. They copy it and paste it into
   the app, then click **Connect**.
4. The app shows **Open @theirbot in Telegram**. They click it and press **Start**. The app
   notices by itself and the bot says hi.

The bot only ever messages them; their own account still never sends anything. By default
every digest is sent; in Settings they can choose "Only when something needs attention" or
turn it off. If they ever lose the token, BotFather's `/mybots` shows it again.

## Step 8: Asking for a digest

With automatic digests they don't need to do anything. They can also ask you any time:
*"Give me my Telegram digest."* Then you:

1. Open `HOW-TO-DIGEST.md` in the folder and follow it.
2. Write the digest in the chat. Each point ends with [↗](link) links that open the
   original message in Telegram.
3. Save it into `digests/`, so it also shows in the app (http://localhost:8765 → Digest).

Digests are updates since the last digest by default, so they can be run as often as
the person likes. If you can run scheduled tasks with access to this folder (for example
scheduled work in the ChatGPT desktop app, or Claude's scheduled tasks), offer to make one
every morning, or every few hours. Each new digest shows a notification on their computer.

Ask them what usually matters to them (people, topics, kinds of requests) and write it into
`what-matters.md`. You'll keep improving it from their feedback.

The **Messages** tab in the app lets them browse everything by group, subgroup and day.
Every message has *Open in Telegram ↗*.

## Good to know (tell them if relevant)

- New messages are fetched every 2 hours while the computer is awake, and right before each digest.
- It only reads. It never sends messages and never marks anything as read.
- Everything stays on their computer (in the folder `TelegramDigest` in their home folder).
- **Update:** run the same line from Step 1 again. Settings and saved messages are kept.
- **Uninstall on Windows:** in PowerShell:

  ```
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*TelegramDigest*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Remove-Item "$([Environment]::GetFolderPath('Startup'))\Telegram Digest.lnk"; Remove-Item -Recurse "$HOME\.config\telegram-digest"
  ```
  Then delete the `TelegramDigest` folder in their user folder, and end the
  "telegram-digest (Windows)" session in Telegram → Settings → Devices.
- **Uninstall on a Mac:** in Terminal:

  ```
  launchctl bootout gui/$(id -u)/local.telegram-digest; rm ~/Library/LaunchAgents/local.telegram-digest.plist; rm -r ~/.config/telegram-digest
  ```
  Then move the `TelegramDigest` folder to the Trash, and end the "telegram-digest (Mac)"
  session in Telegram → Settings → Devices.
- **Troubleshooting:** if http://localhost:8765 doesn't load, run the Step 1 line again.
  The log is in `TelegramDigest/logs/app.log` in their home folder.
