# GhostProxy

**GhostSlice, applied automatically at request time.**

[GhostSlice](https://github.com/littlestjames82-sys/ghostslice) saves
tokens by slicing a project's context before you hand it to an
agent, but the workflow is manual: scan, slice, export, repeat.
GhostProxy sits locally between an agent client and the model API
and applies the same slicing to the context inside each request, so
the saving happens without changing how you work.

By Ghost Developer Studio. MIT licensed. **Zero dependencies**
(Python standard library only). Position in the Ghost stack:
GhostSlice governs what an agent *reads* when a human prepares it,
GhostProxy applies GhostSlice automatically at request time,
GhostVerify checks the result was sufficient, Agent Seatbelt
governs what an agent *does*.

Supported shape in v0.1: the **Anthropic Messages API** as sent by
**Claude Code**, one upstream, one client. Anything the proxy does
not recognise in that shape, and any other shape entirely, is
passed through untouched. OpenAI-shaped traffic is not a v0.1
feature.

## Trust, in plain words

A proxy between you and a model API has to earn its place. These
are the rules GhostProxy is built to, stated plainly so you can
check them:

- **Run this only on your own machine.** GhostProxy listens on
  127.0.0.1 (localhost) only. It refuses to bind to any other
  network interface in v0.1, so nothing else on your network can
  reach it.
- **GhostProxy never stores your API key, anywhere.** It never
  stores your API key in a file, a ledger, a log, or a report, and
  there is no settings screen that asks you to type it in. Your
  client keeps its own key and sends it with each request as
  usual; the proxy forwards that header to the upstream as-is and
  forgets it.
- **GhostProxy never logs your API key.** Test runs scan every
  file the proxy writes for planted canary keys and secrets; zero
  hits is the pass bar (see `tests/test_leak_scan.py`).
- **Fail-open, always.** If the proxy cannot parse a request, the
  slicer fails, or anything else goes wrong inside the proxy, the
  original request is forwarded untouched and the failure is
  recorded as a fallback in the ledger. A context tool must never
  be the reason an agent run dies.
- **Inspect what it did.** Every request leaves a transform map:
  which context files were kept, downgraded, or dropped, and why.
  If a number or a drop looks wrong, the record shows its reason.
- **Bypass it any time.** Pointing your client back at the real
  API takes one command (see Undo below), and with the proxy
  stopped nothing routes through it. There is no lock-in and no
  configuration the proxy changes behind your back: the setup
  below is a variable you set, in your shell, yourself.

One more rule, about your code: **if GhostSlice's secrets guard
flags a file in your context, that file is excluded and not sent
upstream**, even though your client included it. The drop is
recorded in the transform map as path + finding type only, never
the value. This is the one place the proxy removes content you
asked it to send, and it does so because sending a flagged secret
to a model API is the expensive kind of mistake.

Request bodies (your prompts and code) are **not logged by
default**. The ledger records counts, file paths, modes, and
reasons. A profile file cannot turn body logging on: it requires
an explicit `--log-bodies` flag typed by the person starting the
proxy, and in v0.1 the ledger schema holds no bodies even then.
The live view never shows code bodies.

## Install

No install needed to try it from a checkout (GhostSlice must be
importable; from sibling checkouts this happens automatically in
the examples below by putting both `src` folders on `PYTHONPATH`):

```bash
cd ghostproxy
PYTHONPATH=src:../ghostslice/src python3 -m ghostproxy --help
```

Requires Python 3.10 or newer.

## Quickstart (fake upstream, no API key, no spend)

The fastest safe look uses the bundled fake upstream, which
answers locally with canned JSON:

```bash
# terminal 1
python3 examples/fake_upstream.py 9999

# terminal 2
PYTHONPATH=src:../ghostslice/src python3 -m ghostproxy serve \
  --host 127.0.0.1 --port 8765 \
  --upstream http://127.0.0.1:9999 \
  --project examples/sample-project

# terminal 3
curl -s http://127.0.0.1:8765/v1/messages \
  -H "x-api-key: use-anything-this-is-local" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  --data @examples/request.example.json

# what did the proxy do to that request?
PYTHONPATH=src:../ghostslice/src python3 -m ghostproxy report \
  --project examples/sample-project
```

On startup the proxy prints a banner restating the local-only and
no-key rules and where its ledger lives, so the terms are on
screen before the first request, not just in this file.

## Setup with Claude Code

1. Start the proxy against your real project, pointed at the real
   upstream:

   ```bash
   PYTHONPATH=src:../ghostslice/src python3 -m ghostproxy serve \
     --host 127.0.0.1 --port 8765 \
     --upstream https://api.anthropic.com \
     --project ~/your-project
   ```

2. Check its health (read-only; a headers-only upstream check, no
   billable test call unless you pass `--live-check` and accept
   the labelled cost):

   ```bash
   PYTHONPATH=src:../ghostslice/src python3 -m ghostproxy doctor \
     --project ~/your-project --upstream https://api.anthropic.com
   ```

3. In the shell you launch Claude Code from, point it at the
   proxy:

   ```bash
   export ANTHROPIC_BASE_URL="http://127.0.0.1:8765"
   ```

   (`examples/setup-claude-code.sh` does exactly this.) Claude
   Code keeps using its own API key; the proxy never asks for it.

4. Work as usual. Watch the live view at
   `http://127.0.0.1:8765/` in your browser: last requests, token
   counts in and out, saving percentage, transform maps, and the
   fallback count. Token counts are **estimates** from the
   GhostSlice estimator (the same one, and the same estimator
   version stamp, as a manual GhostSlice export), priced from the
   same local, dated `prices.json`. Estimates, not billed amounts.

### Undo

One command returns Claude Code to talking to the Anthropic API
directly, exactly as before:

```bash
. examples/undo-claude-code.sh
```

That unsets `ANTHROPIC_BASE_URL` in your shell. Stop the proxy
with Ctrl-C in its terminal and nothing routes through it at all.
The bypass test in the suite verifies that direct traffic with
the proxy stopped behaves identically to direct traffic with no
proxy ever involved.

## How a request is transformed

Only recognisable project-file context blocks (GhostSlice bundle
sections) are transformed. Your prompt text, the system field,
conversation history, tool calls, images, and fields the proxy
does not know are never rewritten.

In order, per request:

1. **Exclude** junk and lockfiles, and any file the secrets guard
   flags (see the rule above).
2. **Downgrade modes** with GhostSlice's fit ladder (full, then
   signatures, then interfaces) until the context fits the
   per-request budget from your profile.
3. **Drop duplicates** using GhostSlice's exact and near
   duplicate detection.

Per-request results land in a JSONL ledger (in the project, next
to GhostSlice's history) with fields GhostBench can consume:
project, files seen, files sliced or dropped with reasons (the
transform map), tokens in, tokens out (context and total request
kept separate, because history you cannot slice should not pad
the saving), added latency, fallback used yes or no, and the
estimator version. `ghostproxy report` rolls the ledger up.

When GhostVerify is installed, its pre-flight verdict on the
transformed context can be recorded per request. In v0.1 the
verdict is recorded only; the proxy never blocks a request on it.

Your project profile is the same `.ghostslice.json` GhostSlice
uses, plus a `proxy` section (host, port, upstream, per-project
on/off, budget). Unknown keys fail loudly,
as everywhere else in the family. See
`examples/profile.example.json`.

## Honest limits

- Token counts and costs are estimates from a local, dated price
  table, the same labelled estimates GhostSlice prints. Your
  bill is the provider's number, not this one.
- Savings are lower than bundle savings on chatty sessions:
  conversation history dominates those requests and history is
  deliberately out of the proxy's reach. Reports keep sliced
  context and total request sizes separate so the difference is
  visible rather than averaged away.
- API shapes change. The supported shape and client above are
  what v0.1 is tested against; traffic that does not match is
  passed through untouched rather than guessed at.
- Added latency is measured per request and recorded in the
  ledger. No performance promises are made.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

The suite runs entirely against a fake upstream on 127.0.0.1: the
fail-open battery (malformed JSON, oversize bodies, slicer
failure, upstream 500s, mid-stream drops), the canary leak scan
over everything the proxy writes, transform rules, parity against
a manual GhostSlice export, the bypass test, and doctor/report
checks. No test contacts a real upstream or spends anything.

## Layout

```
PLAN.md       the v0.1 plan this build follows
README.md     this file
src/ghostproxy/  the proxy core (server, transform, ledger, doctor, CLI)
tests/        the suite described above, incl. tests/leakscan.py
examples/     fake upstream, sample project, profile/request/map
              examples, setup and undo scripts (see examples/README.md)
```
