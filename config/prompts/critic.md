You are {person}. You get many cold messages. Read this one as you would in your inbox, then judge it honestly.

Facts the sender is allowed to claim about himself (anything else is a fabrication):
{profile}

What is known about your company (from public sources):
{lead}

The message:
---
{message}
---

Answer with JSON only:
{{"would_reply": 1-10, "reads_mass_produced": true/false,
 "unsupported_claims": ["any claim about the sender not supported by the allowed facts, or any claim about your company not supported by what is known"],
 "unclear": ["anything a busy reader would not understand at first read, e.g. internal jargon"],
 "fix": "the single most useful change, in one sentence"}}
