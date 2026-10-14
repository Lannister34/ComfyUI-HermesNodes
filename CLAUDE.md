# hermes-nodes

## Project

<!-- TODO: fill in on first contact — the agent reads this file every session.
One paragraph: what this is and why. After that, links rather than retellings (one fact,
one place): architecture and how to run it, domain vocabulary, decisions (ADR). Then:
processes and the cost of their failure (what must never be restarted), check commands.
Keep your own text OUTSIDE the devkit markers — the toolkit rewrites section contents. -->

<!-- devkit:core:start -->
## Doing the work

**Scope.** Do what was asked — not less, not more. Finish the tedious parts. An unrequested refactor
of adjacent code is a separate slice; something worth fixing outside the scope gets mentioned, not
done.

**Verification.** A change is done when it has been run, not when it has been written. Before
reporting completion: lint, typecheck, and the tests covering what changed. Report the real output —
if something fails, say so and show it; if a step was skipped, name it. "Should work" is not a result.

**Secrets.** Never commit them. All configuration comes from validated environment variables.

## Comments

The only comment that may exist in code is a `// TODO:` line — known-incomplete work, naming what
has to happen, in English; no block or doc-comment forms. Everything else lives elsewhere: the what in names, types, and structure; the
why and the invariants in ADRs, docs, and tests. If code seems to need explaining, rename it, split
it, or move the fact to the document that owns it; a reader left with a question raises it with the
owner, and an explanatory comment appears only when the owner asks for one. Tool directives that
are lexically comments — `@ts-expect-error` with its stated reason, suppressions like
`biome-ignore` — are directives, not comments, and follow their own rules.

## Documentation

Written documentation is in **English** — this file, `README`, ADRs, anything under `docs/`,
including headings and TODOs. Keep one fact in one place: link to the document that owns a subject
rather than restating it, because two copies of a fact become one stale copy.

Not in scope: identifiers and domain vocabulary, which follow the codebase they live in — do not
rename or translate them as a side effect of touching something else. Code comments are governed by
the Comments rule: English, whatever the documentation language.

## Module seams

- **Narrow interface, substantial implementation.** A module earns its place by hiding more than it
  exposes. A wrapper that forwards its arguments and adds nothing is not a seam — inline it.
- **Depend on the narrow port, not the concrete implementation.** Consumers declare the slice of
  behaviour they need; adapters satisfy it. This is what keeps test doubles typed and swaps cheap.
- **Extract on trigger, not on feeling.** Split a unit the moment any of these arrives:
  - a second consumer of the same logic,
  - a multi-step operation that must succeed or fail atomically,
  - conditional state transitions living inline in a caller,
  - a query or transformation whose correctness is not obvious on sight.

  Until a trigger fires, leave it inline. Premature splitting produces shallow fragments that are
  harder to follow than the code they replaced.

## Structure

- **The entrypoint wires; it declares nothing.** An entrypoint constructs the app's pieces, connects
  them, starts them, and handles boot failure — nothing else. It exports nothing, nothing imports it,
  and logic does not hide in it as inline callbacks: a handler body longer than a delegation is a
  declaration in disguise. A config object, interface, helper, or service class living in the
  entrypoint is a file that has not been created yet; a run-guard (`if __main__`, `process.argv`
  checks) is the file admitting it is two files. Scope: deployable apps — a single-file tool is its
  own entrypoint, and this rule begins once the program grows past one file.
- **A file is one role, and grab-bag names are not roles.** The filename states what the file holds;
  every top-level declaration fits that statement. `utils`, `helpers`, `common`, `misc` state
  nothing — a declaration that only fits there is a declaration whose owner has not been found yet.
  Splitting follows the seam triggers above, not a count: a parser beside its error type is one
  role; a queue consumer beside an HTTP handler is two.
- **Config is one module per app.** The environment is read in exactly one place per app, validated
  at startup — named keys with types; a passthrough bag is not validation — and injected everywhere
  else. A default restated at a call site is a value with N owners: rotating it means finding all N,
  and missing one is silent. Any `process.env` / `os.environ` read outside the config module is a
  bug, entrypoint included. Same scope as the entrypoint rule: a single-file tool reading a variable
  is not an app.
- **Same-stack siblings share one skeleton.** Apps built on the same framework repeat one layout —
  same file names, same places, so a reader who knows one app knows them all. An app on a different
  stack follows that stack's idiom instead. Changing the skeleton is a recorded decision, not drift
  from the newest app.
- **Packages are entered through their surface.** Imports cross an app/package boundary only through
  the package's public entry point. Deep imports into internals and `export *` over another
  package's files dissolve the boundary. A surface is curated: a barrel that re-exports every
  internal file is not a surface but the absence of one — a package hides more than it exposes, same
  as any module. Direction is one-way: shared libs never import from apps; a lib that needs an app's
  type is a type that belongs in the lib.
- **Spike code never migrates into `apps/`.** A spike proves a hypothesis and is discarded; what
  survives is knowledge, recorded in a `FINDINGS.md` beside the spike. Graduating a spike is an
  explicit act: implement the finding into the skeleton, from scratch — the finding may be the code
  itself, and then it is rebuilt in place with its tests, not moved. Launch mechanics that were
  convenient for the spike are part of what gets discarded.

## Layering

Decision logic must be callable without touching the network, disk, clock, or environment. Push I/O
to the edges and keep the middle pure. If exercising one branch needs a live database, the branch is
in the wrong place — that is the test telling you where the seam belongs.

## Fault tolerance

Handling an error where it happens is the easy half. This is about what the *system* does when a
part of it stops.

Every boundary that can fail — network, storage, queue, subprocess, external API — has an explicit
error path. No silently swallowed errors, no unhandled rejections. Retries are bounded, idempotent,
and time out.

For anything crossing a process boundary or persisting state, answer three questions before writing
it:

- **If this dies mid-operation, what is left behind?** Partial writes, orphaned jobs, held locks,
  half-finished uploads. Something has to reclaim them — name what.
- **If this runs twice, what breaks?** If the answer is "nothing", say why: an idempotency key, a
  conditional update, a unique constraint. "It won't run twice" is not an answer.
- **If a dependency is down for an hour, what happens?** Apply backpressure, degrade, or fail fast —
  pick one deliberately. Unbounded buffering is not a choice, it is a leak.

Data has an owner at every instant. The window where a record is written but not yet claimed, or
claimed but not yet durable, is where data goes missing — make it explicit and short.

## Tests

A slice that adds behaviour adds its tests in the same commit. Tests are deterministic: no wall
clock, no network, no dependence on execution order. Assert on observable behaviour, not internals —
a test that breaks when you rename a private method is a maintenance tax, not a check.

## Bugs

A fix that only makes the symptom go away is half the work. Name the root cause and the class it
belongs to, because the class decides what happens next:

- **The toolchain should have caught it** — missing lint rule, loose type, unvalidated boundary.
  Tighten the toolchain, same commit.
- **An uncovered case** — add the test that would have failed, same commit.
- **A wrong assumption about something external** — pin it with a test at that boundary whose name
  states what surprised you.
- **Ordering, concurrency, or lifecycle** — fix the immediate break, then *propose* the design change.
- **Architecture** — the seam is in the wrong place. Fix the break, propose the redesign, do not
  start it.

The last two are proposals, not work. A bug report is not authorization to refactor.
<!-- devkit:core:end -->

<!-- devkit:design:start -->
## Design before code

Before implementing anything beyond a local edit, state three things:

1. **The seam being touched** — which module owns this change, and what its interface is.
2. **The alternative rejected** — the other plausible shape, and why it loses here.
3. **The failure modes introduced** — the new ways this can break, and where each is handled.

A change that introduces a new external boundary — queue, HTTP client, provider adapter, storage
backend, background job — also states its test strategy and flags any harness that does not exist
yet. Propose the tooling; do not wait to be asked for it.

## ADRs

A decision graduates to `docs/adr/` when it is **expensive to reverse**: a datastore, a transport,
a queue, an inference engine, a boundary between services, a schema-ownership rule. Cheap, local,
easily-undone choices stay in the code.

Format: `docs/adr/NNNN-short-slug.md`, following `0000-template.md`. Record the alternatives that
lost, and name a fallback wherever one exists — the fallback is what makes a risky choice
acceptable.
<!-- devkit:design:end -->

<!-- devkit:review:start -->
## Review

Work is reviewed before it is reported as done, not after. Run the `code-review` agent over the diff,
address blocking findings, then hand back. The pre-commit gate is a backstop for when this gets
forgotten — reaching it means the loop was skipped.
<!-- devkit:review:end -->

<!-- devkit:git:start -->
## Commits

- Capitalized imperative subject (`Add preset validation`, `Fix wildcard parsing`), optionally with a Conventional Commits type prefix (`feat(wan): ...`, `fix:`); git's default merge messages pass.
- **English, subject and body — whatever language the project itself is written in.** The type
  prefixes are English already, and a history in two languages is greppable in neither. This is not
  negotiated per project: unlike documentation, commit messages have no local-audience argument, and
  history outlives the team that wrote it.
- One meaningful slice per commit; it builds and passes checks on its own.
- Subject in the imperative, under ~72 characters, no trailing period. A body only when it carries
  what the subject cannot: the *why*, a constraint, a consequence.
- No trailers, sign-offs, tool attribution, or decorative marks.
<!-- devkit:git:end -->
