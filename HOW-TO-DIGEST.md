# For AI assistants: how to make a Telegram digest from this folder

This folder belongs to Telegram Digest, a local app that saves a read-only copy of
the Telegram groups its owner picked. When they ask for a digest, or a scheduled
task asks you for one, do the following. Don't ask them to copy or paste anything.

## 1. Read what matters to them

Read `what-matters.md` first and apply it, above all to **Needs attention**.

- When they tell you what they do or don't care about ("never flag shopping",
  "always tell me about sauna or kitchen shifts", "I'm on the welcome team"), update
  `what-matters.md` under the right heading. Then say in one line what you changed.
- The section *Feedback from the digest* collects clicks from the app ("Not important
  to me: …", "Flag things like this: …"). When a pattern is clear, turn those lines
  into a short rule under the right heading and remove the lines you folded in.
- Keep the file short and in their words. Never put phone numbers or other people's
  private details in it.

## 2. Get the newest messages

The app fetches on its own schedule. To make sure the digest is current, create an
empty file named `fetch-now` in this folder. Within about a minute the app fetches,
deletes the file and updates `last_export` in `.state.json`. Wait for that, for up to 2
minutes. If it doesn't happen, go ahead with what's there and say the app may not be
running (they can check http://localhost:8765).

## 3. Pick the period

- **Default: an update since the last digest.** Find the newest file in `digests/` (by
  its `to` time) and cover from its `to` until now.
- If there's no earlier digest, or they ask for "today", "yesterday" or "the last 24
  hours", cover that instead.
- **If there are no new messages in the period, don't write a digest file.** Just say
  there's nothing new.

## 4. Read the messages

- `exports/YYYY-MM-DD/<group>/messages.jsonl` has one JSON object per line:
  `id, date (ISO, local time), group_id, group, topic_id, topic, sender, text, media,
  reply_to (id of the message it replies to), forwarded, link (t.me), app_link (tg://)`.
  `topic` is the subgroup name; it's empty for groups without subgroups.
- Read the folders for every day the period touches, and filter on `date`.
- For updates, read some messages from just before the period too, so replies to
  older messages make sense. Summarise only what's new.

## 5. Write the digest

In the chat:

- Start with **Needs attention**, shaped by `what-matters.md`: requests for help,
  things people (or the owner) are asked to do, deadlines, decisions, anything
  mentioning the owner. Leave it out if nothing qualifies.
- Then a short section per group and subgroup, most active first, with 1–4 bullets each.
  Skip subgroups with nothing meaningful.
- End every bullet with links to its source messages: `[↗](link)`, using each message's `link`.
- Be concrete (who, what, when) and brief. Use only what's in the messages.
- Don't repeat phone numbers or other personal details; say "in the thread" instead.

## 6. Save it so it shows in the app

Write `digests/<YYYY-MM-DD-HHMM>.json`, named after the end of the period. It then
appears at http://localhost:8765 → Digest, with clickable source links, the original
messages and a Mac notification:

```json
{
  "title": "Update, Saturday afternoon",
  "from": "2026-11-14T14:00:00+00:00",
  "to": "2026-11-14T17:30:00+00:00",
  "groups": [
    {
      "group_id": "-1001234567890",
      "title": "group name",
      "highlights": [{"text": "**Bold** works.", "refs": [22285, 22287]}],
      "topics": [
        {"topic": "subgroup name", "bullets": [{"text": "…", "refs": [22249]}]}
      ]
    }
  ]
}
```

- `from` and `to` are the period (ISO with time zone). `refs` are message `id`s from
  that group. `group_id` and `topic` must match the export.
- Title: a short plain name, like "Saturday" for a full day, or "Update, Saturday
  afternoon" for an update.

## Rules

- Read `exports/`, `.state.json` and `what-matters.md`. Write only `digests/`,
  `what-matters.md` and the `fetch-now` trigger. Leave everything else alone.
- This app never sends Telegram messages, and you shouldn't either.
