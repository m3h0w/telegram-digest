# For AI assistants: how to make a Telegram digest from this folder

This folder belongs to Telegram Digest, a local app that saves a read-only copy of
the Telegram groups its owner picked. When they ask for a digest, do the following.
Don't ask them to copy or paste anything.

## 1. Read the messages

- `exports/YYYY-MM-DD/<group>/messages.jsonl` has one JSON object per line:
  `id, date (ISO, local time), group_id, group, topic_id, topic, sender, text, media,
  reply_to (id of the message it replies to), forwarded, link (t.me), app_link (tg://)`.
  `topic` is the subgroup name; it's empty for groups without subgroups.
- For "today", "since yesterday" or "the last 24 hours", read today's and yesterday's
  folders and filter on `date`.
- `exports/YYYY-MM-DD/<group>/<subgroup>.md` holds the same messages in readable form.
- `.state.json` → `last_export` says when messages were last fetched. If that's more than
  about 3 hours ago, mention that the newest messages may be missing and suggest opening
  http://localhost:8765 and clicking *Export now*.

## 2. Write the digest in the chat

- Start with **Needs attention**: requests for help, things people (or the owner) are
  asked to do, deadlines, decisions, anything mentioning the owner.
- Then a short section per group and subgroup, most active first, with 1–4 bullets each.
  Skip subgroups with nothing meaningful.
- End every bullet with links to its source messages: `[↗](link)`, using each message's `link`.
- Be concrete (who, what, when) and brief. Use only what's in the messages.
- Don't repeat phone numbers or other personal details; say "in the thread" instead.

## 3. Save it so it shows in the app

Also write the digest to `digests/<YYYY-MM-DD-HHMM>.json`. It then appears at
http://localhost:8765 → Digest, with clickable source links and the original messages:

```json
{
  "title": "Telegram digest · 14 Nov",
  "from": "2026-11-13T20:30:00+00:00",
  "to": "2026-11-14T20:30:00+00:00",
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

`refs` are message `id`s from that group. `group_id` and `topic` must match the export.

## Rules

- Only read `exports/` and `.state.json`, and only write to `digests/`. Leave everything else alone.
- This app never sends Telegram messages, and you shouldn't either.
