# BlenderSQL

**Let an AI assistant see and edit what's in your Blender file.**

<!-- TODO: 20-30s screen capture here — e.g. "recolor the hat" / "find the heaviest meshes" / "clean up the file". A demo gif is the whole pitch for this page. -->

BlenderSQL is a Blender add-on that lets an AI coding assistant — Claude, Copilot, Codex, whatever you use — read and change your `.blend` while Blender is open: objects, grease pencil, materials, animation, the sequencer, all of it. You describe what you want in plain language; the assistant works out the rest. Every change it makes is an ordinary Blender undo step, so nothing's scary — Ctrl+Z still works.

(Under the hood it talks to a live view of your file in SQL. You never have to write any.)

> **Blender 5.1.** BlenderSQL tracks Blender 5.1's data model (layered Actions, Grease Pencil v3, the renamed sequencer types). Other versions aren't supported yet.

## What you can do with it

Once it's connected, you just ask. A sampler:

**Understand a file**
- "What's in this scene? Is anything broken or orphaned?"
- "Why is this file so heavy — which meshes have the most geometry?"
- "Find every object whose constraint points at something that doesn't exist anymore."

**Edit it**
- "The character in the bucket hat — recolor the hat to red."
- "Rename the objects that still have default `.001` / `.002` names to something sensible."
- "Key the camera's location on frame 1 and frame 48."

**Tidy it up**
- "Purge all the orphaned data."
- "Reorganize my collections — group cameras, characters, and props per scene."
- "Remove the material slots nothing actually uses."

It can also **render a single object on its own** so the assistant can literally look at what it's working on — useful when datablock names don't tell you much.

## Why it's nice

- **Use whatever assistant you already have.** It isn't tied to one vendor or app.
- **It reads *and* writes.** Most "let the AI see your scene" tools only look; this one edits too.
- **Everything is undoable.** A prompt went sideways? Ctrl+Z, like any other Blender action.
- **Nothing to sync or re-export.** It works on the file you have open, live — change something in Blender and the assistant sees it immediately, and vice versa.
- **Barely any setup.** Install the add-on, install the skills plugin, done. No server to configure.

## What about Blender's MCP?

Blender has its own MCP add-on now (in Blender Labs), and it's good — I've used it, it works well. This isn't an either/or; run both if you want.

BlenderSQL is a different bet. Instead of a fixed set of tools the assistant calls one at a time, it gets a query language over Blender's whole data model. A `.blend` is, under the hood, a pile of linked tables — datablocks, material slots, grease-pencil layers/frames/strokes, action channels, keyframes — so a database-shaped view fits it naturally:

- **One question instead of ten round-trips.** "Which materials aren't used by anything?", "the heaviest meshes that also have a Subdivision modifier", "every object whose constraint points at something that's gone" — each is a single query, not a loop of tool calls.
- **No ceiling.** When a query isn't the right shape, the assistant runs Python (`bpy`) directly through the same interface — so anything an MCP can do, it can do here too.
- **Nothing is hidden.** The assistant can ask what tables and columns exist and go from there — it isn't boxed in by whatever tools someone chose to expose.
- **Looking and editing work the same way**, and every edit is a normal Blender undo step.

My experience is that SQL is a surprisingly good model for an AI agent to work in.

## Getting started

### 1. Install the add-on

Grab the zip for your OS from the [latest release](https://github.com/thebabush/blendersql/releases/latest), then in Blender:

**Edit → Preferences → Get Extensions → Install from Disk…**, pick the zip, and tick **BlenderSQL** in the list.

It starts its local server automatically — you don't have to do anything else. (You can toggle that, or stop/start the server, in the add-on's preferences. Requires Blender 5.1.)

### 2. Install the skills into your coding assistant

For Claude Code:

```
/install-plugin https://github.com/thebabush/blendersql-skills
```

(For Codex, point it at the `Skills/` folder of that repo.) This teaches the assistant the `/blendersql:*` commands — one per area: `connect`, `scene`, `grease_pencil`, `mesh`, `materials`, `animation`, `modifiers`, `vse`, `assets`, `analysis`, `python`, `functions`.

### 3. Connect and go

With Blender open, in your assistant:

```
/blendersql:connect Connect to the Blender I have open and tell me what's in this file.
```

From there, just talk to it — see [What you can do with it](#what-you-can-do-with-it).

Prefer to keep Blender headless? The assistant can also launch Blender in the background for you and work on a `.blend` without ever opening the UI — just ask. (That path uses the `blendersql` command-line tool; see [DEVELOPMENT.md](DEVELOPMENT.md#the-cli).)

## Under the hood

BlenderSQL exposes Blender's data as ~78 live SQL tables plus a set of editing functions, served over a small localhost HTTP endpoint, with a Python escape hatch for anything that isn't a query. If you want the technical picture — architecture, the full table and function reference, the HTTP API, the command-line tool, building from source, contributing — see **[DEVELOPMENT.md](DEVELOPMENT.md)**.

## Disclosure

This is mostly vibecoded, it's young, and I mostly use it for my own Grease Pencil / 2D animation. Every edit is a normal Blender undo step, so it's not reckless — but it hasn't been stress-tested by lots of people on lots of files. So: poke at it, use it on copies and side projects, hit `save` before turning an agent loose. Don't point it at the production files at Pixar. (Yet.)

## Credits

Heavy inspiration from [**idasql**](https://github.com/allthingsida/idasql) by [Elias Bachaalany (@0xeb)](https://github.com/0xeb) — the project that pioneered exposing a host application's internal data model as live SQL virtual tables so any agent can query and edit it. I'm a heavy idasql user myself and consider it a game-changer for reverse engineering — if that's your space, go look. BlenderSQL applies the same idea to Blender, independently implemented in Python on [apsw](https://rogerbinns.github.io/apsw/). Big thanks to Elias.

## License

[Mozilla Public License 2.0](LICENSE).
