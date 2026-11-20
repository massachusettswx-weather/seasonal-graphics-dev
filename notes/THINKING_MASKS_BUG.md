# The "thinking process" masks - a platform defect, not our data

**20 Nov 2026.**  The owner: *"Why does this keep happening on previous
chats?!?!"*  The "Thinking process" panel of the long project chats is a
wall of `✗` marks (`Hmm × × × — hmm × ×: ...`).  The sentence scaffolding
survives; **the words are gone**.

**The damage is in `thinking_content` ONLY.**  `msg_content` (the visible
answer), `tool_calls[].tool_call_args` and `tool_call_result_data` are
byte-intact in every damaged message, and so are the user's messages.
**The work of a turn is never lost - only the private reasoning is.**

## It is not a font, and not the storage layer

* Not a rendering bug: the STORED transcript itself contains the marks -
  read back through the `session_messages` API, the marks are in the text.
* Not a character-class filter: a deliberate probe put CJK `中文内容`,
  emoji `🤔`, `✓ → — ─` and accented/Cyrillic/Greek characters into BOTH
  the reasoning and the content channel, and every character came back
  intact.
* Not the storage layer: the same probe's CJK/emoji inside
  `tool_call_args` and the tool results are intact.
* Not the model's own marking: that survives in clean messages.

## The shape of the damage

* **One `✗` (U+2717) per lost token**, separated by the token separator.
* **Two or more ADJACENT mask-tokens = damage.  A single isolated `✗` is
  MiniMax's own "✓ / ✗" marking and is NOT damage.**  The two must not be
  confused - the doctor's report counts them separately (`runs` against
  `isolated`).
* The raw provider token **`<|endoftext|>` leaks into the same field**,
  and the MiniMax tool-call protocol (`</content>`, `<invoke>`, `<path>`)
  leaks into the reasoning channel on damaged messages.  The field is
  written straight from the provider's token stream, with the parts the
  assembler cannot attribute replaced by `✗`.

## The trigger (both factors are present in every damaged case)

| | reasoning (output tokens) | session context | measured loss |
|---|---|---|---|
| damaged | ≥ 641 | ≥ 290k | 641 tok → 22 % · 18k → 96 % · 31k → 97 % · 65k → 87 % |
| clean | ≤ 1,962 | ≤ 226k | - |

The two factors are confounded in the sample - **say both, not one**.

A second, avoidable contributor: the keepalive used to write into the
owner's own conversation every 20 minutes, which grew it to **347,658 of
512,000 tokens**.  The keepalive now runs in its own throwaway
conversation.

## What can be done, and what cannot

The runtime is **not** in the sandbox - the agent turn is orchestrated by
the remote daemon - so this **cannot be patched from here**; it has to go
upstream.

Our side, and it is enough to stop the bleeding:

1. **Keep the per-turn reasoning SHORT.**  Long reasoning in a big context
   is the trigger.
2. **Keep the context LEAN.**  Big tool output goes into a file and is
   analysed by a script, not printed into the conversation.
3. **Never rely on the transcript for continuity.**  The state lives in
   `notes/STATE.md` (in git) and in the agent's memory.

## The tool

`tools/transcript_doctor.py` audits any conversation and prints a damaged
one readable:

    python3 tools/transcript_doctor.py transcript.json
        the audit: which messages are damaged, and how badly
    python3 tools/transcript_doctor.py transcript.json --salvage
        the damaged messages printed so they can be read
    python3 tools/transcript_doctor.py transcript.json --json
        the same audit, as JSON

It reads a JSON file holding the messages in the shape the
`session_messages` API returns them (a list, or an object with a
`messages` list).
