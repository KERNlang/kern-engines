# kern-engines

Drive interactive CLI agents (Claude, Codex, models CLIs, …) by talking to them through a **pseudo-terminal (PTY)** — the same kernel primitive `expect`, `tmux`, and `asciinema` use — as if a human were typing into a terminal, and scrape the output. **Engine-agnostic:** add a CLI by declaring an `EngineConfig`, no code changes.

> Single source of truth for the PTY driver, consumed as a **git submodule** by [`agon`](https://github.com/KERNlang/agon), [`kern-sight`](https://github.com/KERNlang/kern-sight), and any other tool that needs to drive a CLI under a pty. Fix a bug here once; each consumer pulls the submodule and rebuilds.

Polyglot: a **Python implementation** (canonical) + a thin **TypeScript shell** that spawns the Python daemon and proxies messages over stdin/stdout as NDJSON. Zero native Node dependencies; the Python runtime is stdlib-only.

## Why a PTY

Some CLIs expose their full capability only through the **interactive terminal UI** — a non-interactive/programmatic mode may be missing, limited, or behave differently. Driving the real TUI through a pty lets a tool reuse exactly what a human at the keyboard gets, with no separate integration surface to maintain. It's a standard automation technique; the process on the other end can't tell a pty from a physical terminal because, at the kernel level, there is no difference.

## How consumers ship it to end users

The submodule is for *developer* sync — end users never run `git`. At **build time**, each consumer bundles this package's Python into its own artifact:

- **agon** (`npm i -g` / brew): the npm `files` field ships `py/kern_engines/**/*.py`; the TS shell sets `PYTHONPATH` to the bundled `py/` dir and runs `python3 -m kern_engines.cli.daemon`. No `pip`, no `git` — end users only need Python 3.9+.
- **kern-sight** (`.vsix`): the extension's build copies `py/` into `dist/python/` so the `.vsix` is self-contained; the extension sets `PYTHONPATH` to the bundled copy.

So: edit here → `git submodule update` in each consumer → rebuild → each artifact embeds the new version.

## Architecture

```
┌─ consumer (TS) ────────────────────────────────────────────┐
│  dispatch / dispatchStream / dispatchAgent / *AgentStream  │
│       ↓  lazy-import the TS shell, spawn one session       │
└────────┬───────────────────────────────────────────────────┘
         ↓
┌─ cli/claude.ts  (TS shell) ────────────────────────────────┐
│  spawn('python3', ['-m', 'kern_engines.cli.daemon',        │
│                     '<engine>', '--mode', 'agent'])        │
│  NDJSON over stdin/stdout                                  │
└────────┬───────────────────────────────────────────────────┘
         ↓  stdio JSON-RPC
┌─ kern_engines/cli/daemon.py ───────────────────────────────┐
│  one PtyTuiSession alive for the life of the daemon        │
└────────┬───────────────────────────────────────────────────┘
         ↓  pty.fork() + os.execvp("<engine>", ...)
┌─ the engine's interactive TUI ──────────────────────────────┐
│  runs against the live session — same as a human typing     │
└─────────────────────────────────────────────────────────────┘
```

## Layout

```
kern_engines/
├── package.json            # npm workspace; ships dist/ + py/
├── pyproject.toml          # Python package; package-dir = py/
├── tsconfig.json · tsup.config.ts
├── index.ts                # TS barrel
├── cli/
│   ├── session.ts          # generic TS PtyCliSession (spawns the daemon)
│   └── claude.ts           # ClaudeCliSession TS shim
└── py/
    ├── kern_engines/cli/
    │   ├── pty_session.py   # generic PtyTuiSession + EngineConfig
    │   ├── configs.py       # per-engine EngineConfig instances + REGISTRY
    │   ├── daemon.py        # stdio NDJSON daemon
    │   ├── claude.py        # ClaudeCliSession convenience alias
    │   └── model_probe.py   # live /model list probe
    └── tests/               # pytest cover (not shipped)
```

### How the daemon is found (any install method, no pip)

The TS shell (`cli/session.ts`) sets `PYTHONPATH` to the `py/` root by **walking up from its own `import.meta.url`** until it finds `py/kern_engines/__init__.py`. Because the built JS (`dist/`) and the Python (`py/`) ship as siblings under the package root, `python3 -m kern_engines.cli.daemon` resolves identically whether the consumer runs from a checkout, a git worktree, or a global `npm i -g` install — for any cwd, with no `pip install`. The only runtime prerequisite is `python3` on PATH (the daemon is stdlib-only). `pip install -e .` still works for Python-only dev.

## API

### Python (canonical)

```python
from kern_engines.cli.claude import ClaudeCliSession

with ClaudeCliSession() as cs:
    reply = cs.ask("hello, can you say 'pong'?")

# Generic class:
from kern_engines.cli.pty_session import PtyTuiSession
from kern_engines.cli.configs import CLAUDE

with PtyTuiSession(CLAUDE, mode="agent") as cs:
    reply = cs.ask("edit greeting.txt: hello world → hello pong")

# Streaming: ask_stream is a generator; deltas are intermediate
# snapshots, the final clean response is the StopIteration.value.
with ClaudeCliSession() as cs:
    chunks = list(cs.ask_stream("hello"))
```

### TypeScript

```ts
import { ClaudeCliSession } from '@kernlang/agon-engines/cli/claude';

const cs = await ClaudeCliSession.spawn({ cwd: '/path/to/workspace' });
try {
  const reply = await cs.ask("hello");
  const gen = cs.askStream("explain this");
  while (true) {
    const next = await gen.next();
    if (next.done) break;          // next.value = final clean text
    process.stdout.write(next.value);
  }
} finally {
  await cs.close();
}
```

## Install

- **Python:** just `python3` 3.9+ on PATH. No `pip install`. Runtime imports are stdlib-only (`pty`, `select`, `os`, `signal`, `fcntl`, `termios`, `json`). We deliberately avoid `pyte`/terminal-emulator libraries — they choke on some TUIs' byte streams; the hot path is raw bytes + ANSI strip at the end. A `pyproject.toml` is provided for `pip install -e .` if you prefer.
- **Node / TypeScript:** no native dependencies — the TS shell only spawns `python3`. No `node-pty`, no `@xterm/headless`, no native build step.

## Adding a new engine

Two files:

1. **`py/kern_engines/cli/configs.py`** — declare an `EngineConfig`:

    ```python
    CODEX = EngineConfig(
        id="codex",
        binary="codex",
        prompt_marker_bytes=b"▶",          # shown when ready for input
        response_marker="◆",               # prefixes assistant text
        chrome_regex=r"(?:status|tokens?\)|...)",
        env_strip=("CODEX_SESSION_ID", "..."),
        agent_extra_argv=("--auto-edit", "--skip-git-check"),
    )
    REGISTRY[CODEX.id] = CODEX
    ```

2. **`cli/codex.ts`** — a five-line TS wrapper around `PtyCliSession.spawn('codex', opts)`.

No new pty plumbing, daemon, or IPC layer.

## Hard constraints

- **ANSI sanitisation on input.** ESC/C0 control bytes (except TAB/LF) and DEL are stripped from prompts before write — defensive against model-generated prompts containing terminal escapes.
- **Response-end detection is heuristic.** Idle window + response-marker + hard timeout; none alone is trusted. Tuned per engine.
- **Cleanup is bounded.** SIGTERM → 2s grace → SIGKILL → 1s reap → close fd. Idempotent; `with` (Python) / `try/finally` (TS) covers every exit path.
- **Single in-flight `ask()` per session.** Lock (Python) / busy flag (TS) serialises calls.
- **No native Node deps.** Avoids node-pty's build toolchain and `@xterm/headless` parser hangs.

## Known limitations

- **Streaming is coarse.** A TUI typically renders the full assistant block in one or two frames after the spinner, so `askStream` yields a handful of deltas per turn, not per token. Use it for live-progress UX; use `ask` for the final text.
- **Agent mode trusts the workspace.** Agent dispatch skips the workspace trust dialog — the caller opts in by routing through it.
- **One session per dispatch.** Consumers spawn + close a session per dispatch, so daemon startup (~2s) is paid every turn. A future optimisation is pooling daemons per `(engine, cwd, mode)`.
