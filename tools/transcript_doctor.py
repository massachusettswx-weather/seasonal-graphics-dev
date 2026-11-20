#!/usr/bin/env python3
"""Audit a conversation for the "thinking process" mask damage.

THE BUG (20 Nov 2026).  The runtime writes the assistant's REASONING with
parts of it replaced by U+2717 (the mark below), one mark per lost token.
The visible answer, the tool calls and the tool results are stored
intact - only the private reasoning is damaged.  The evidence and the
measurement are in notes/THINKING_MASKS_BUG.md.

THE RULE FOR TELLING DAMAGE FROM THE MODEL'S OWN MARKING.  MiniMax marks
its own reasoning with a single check or cross.  So:

  * two or more ADJACENT marks = damage;
  * a single isolated mark = the model's own marking, not damage.

The marks are separated by the token separator, so "adjacent" means that
only whitespace lies between them.

WHAT IT READS.  A JSON file holding the session's messages, in the shape
the session_messages API returns them (a list, or an object with a
"messages" list).  Every message is looked for a reasoning field
("thinking_content", "thinking", "reasoning_content") and for the visible
one ("msg_content", "content").

    python3 tools/transcript_doctor.py transcript.json
        the audit: which messages are damaged, and how badly

    python3 tools/transcript_doctor.py transcript.json --salvage
        the damaged messages printed so they can be read

    python3 tools/transcript_doctor.py transcript.json --json
        the same audit, as JSON
"""
import argparse
import json
import os
import re
import sys

MARK = "\u2717"
# the provider's and the tool protocol's own tokens, which leak into the
# reasoning channel of a damaged message
LEAKS = ("<|endoftext|>", "</content>", "<invoke>", "<path>")
THINK_KEYS = ("thinking_content", "thinking", "reasoning_content")
CONTENT_KEYS = ("msg_content", "content")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def messages(doc):
    """The list of messages, whatever shape the export has."""
    if isinstance(doc, list):
        out = doc
    elif isinstance(doc, dict):
        out = None
        for k in ("messages", "data", "items", "results", "history"):
            if isinstance(doc.get(k), list):
                out = doc[k]
                break
        if out is None:
            out = [doc]
    else:
        out = []
    msgs = []
    for m in out:
        if isinstance(m, dict):
            msgs.append(m)
    return msgs


def pick(m, keys):
    for k in keys:
        v = m.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def think_of(m):
    return pick(m, THINK_KEYS)


def content_of(m):
    return pick(m, CONTENT_KEYS)


def damage_runs(text):
    """The maximal runs of ADJACENT marks: (start, end, count) each."""
    runs = []
    pos = [m.start() for m in re.finditer(re.escape(MARK), text)]
    if not pos:
        return runs
    start = prev = pos[0]
    count = 1
    for p in pos[1:]:
        gap = text[prev + 1:p]
        if gap.strip() == "":          # only whitespace between them
            count += 1
        else:
            runs.append((start, prev + 1, count))
            start = p
            count = 1
        prev = p
    runs.append((start, prev + 1, count))
    return runs


def audit(text):
    """What the damage did to one reasoning field."""
    runs = damage_runs(text)
    # a run of ONE mark is the model's own marking, not damage
    damaged = sum(r[2] for r in runs if r[2] >= 2)
    singles = sum(1 for r in runs if r[2] == 1)
    leaks = [l for l in LEAKS if l in text]
    return {"marks": text.count(MARK), "damaged_tokens": damaged,
            "runs": len([r for r in runs if r[2] >= 2]),
            "isolated": singles, "leaks": leaks, "chars": len(text)}


def salvage(text):
    """The reasoning with every damaged run marked, so it can be read."""
    out = text
    for start, end, count in reversed(damage_runs(text)):
        if count < 2:                  # the model's own marking: keep it
            continue
        out = out[:start] + "[%d tokens lost]" % count + out[end:]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("transcript", help="the JSON file with the messages")
    ap.add_argument("--salvage", action="store_true",
                    help="print the damaged messages so they can be read")
    ap.add_argument("--json", action="store_true", help="the audit as JSON")
    ap.add_argument("--only-damaged", action="store_true",
                    help="in --salvage, print only the damaged messages")
    args = ap.parse_args()

    if not os.path.exists(args.transcript):
        print("no such file: %s" % args.transcript)
        return 2
    msgs = messages(load(args.transcript))

    rows = []
    for i, m in enumerate(msgs):
        th = think_of(m)
        if not th:
            continue
        a = audit(th)
        a.update({"index": i, "role": m.get("role", "?"),
                  "damaged": a["damaged_tokens"] > 0})
        rows.append(a)

    if args.json:
        print(json.dumps(rows, indent=1))
        return 0

    if not rows:
        print("no reasoning field in %s" % args.transcript)
        return 0

    print("the audit of %s" % args.transcript)
    print("  %d message(s) carry a reasoning field" % len(rows))
    bad = [r for r in rows if r["damaged"]]
    for r in rows:
        flag = "DAMAGED" if r["damaged"] else "clean  "
        print("  [%3d] %-9s %-8s marks=%-5d lost=%-5d runs=%-3d isolated=%-3d"
              % (r["index"], r["role"], flag, r["marks"], r["damaged_tokens"],
                 r["runs"], r["isolated"]))
        if r["leaks"]:
            print("        the protocol leaked into the reasoning: %s"
                  % ", ".join(r["leaks"]))
    print("  %d of %d message(s) are damaged" % (len(bad), len(rows)))
    if bad:
        lost = sum(r["damaged_tokens"] for r in bad)
        marks = sum(r["marks"] for r in bad)
        print("  %d of %d marks in the damaged messages are lost tokens"
              % (lost, marks))

    if args.salvage:
        print("")
        print("== the messages, readable ==")
        for i, m in enumerate(msgs):
            th = think_of(m)
            if not th:
                continue
            if args.only_damaged and not audit(th)["damaged_tokens"]:
                continue
            print("")
            print("--- message %d (%s) ---" % (i, m.get("role", "?")))
            c = content_of(m)
            if c:
                print("THE ANSWER (intact):")
                print(c[:4000])
            if th:
                print("THE REASONING (damaged parts marked):")
                print(salvage(th)[:4000])
            for tc in (m.get("tool_calls") or []):
                if isinstance(tc, dict):
                    print("TOOL CALL: %s %s" % (tc.get("name", "?"),
                                                str(tc.get("arguments", ""))[:300]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
