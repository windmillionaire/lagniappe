# Setup CLI presentation

These rules cover every installer command, `setup.sh`, `setup.cmd`, and shared
runner messages displayed during setup. Windows users run `.\setup.cmd` in
PowerShell; macOS and Linux users run `./setup.sh` in their usual terminal.
PowerShell may be hosted by Windows Terminal or the older Windows console.

The design follows the GitHub CLI Primer's
[components](https://github.com/cli/cli/blob/trunk/docs/primer/components/README.md),
[foundations](https://github.com/cli/cli/tree/trunk/docs/primer/foundations), and
[principles](https://github.com/cli/cli/tree/trunk/docs/primer/getting-started).
The punctuation policy and neutral information treatment below are Lagniappe
conventions where the Primer does not prescribe an exhaustive rule.

## Color and meaning

Use the terminal's normal foreground and background. Standard ANSI red, green,
yellow, and cyan carry emphasis; bright black (gray) is reserved for secondary
text. Color and symbols reinforce words: the message must remain understandable
without either. Do not use colored backgrounds, decorative boxes, emoji,
italics, or a different color for each section.

| Element | Presentation |
| --- | --- |
| Success | Green `✓`, normal message: `✓ Configuration saved` |
| Warning | Yellow `!`, normal message: `! Additional configuration required` |
| Failure | Red `✗`, normal message: `✗ Redis connection failed` |
| Pending state | Yellow `-`, normal message: `- Certificate pending` |
| Information | Normal prose, without a color or prefix |
| Neutral outcome | Normal `-` and message: `- Deployment skipped` |
| Question | Green `?`, bold question, cyan answer instructions |
| Text default | Normal text in parentheses: `(My workspace)` |
| Menu choice | Cyan number or key, normal label, optional gray annotation |
| Section heading | Bold normal foreground |
| Secondary text | Gray supplementary annotation; never essential instructions |
| Progress | Gray spinner and short activity label: `Configuring Redis...` |

Color only the marker in ordinary messages. Compact diagnostic tables may color
an explicit outcome word, such as `Verified`, `Pending`, or `Failed`. Feature
settings such as `enabled` and `disabled` stay neutral. A completed, verified
operation is success even when it disables or deletes something. Skipping an
optional operation or cancelling setup is a neutral outcome, not success or an
error. Preserve the existing process exit status when changing its presentation.

Warnings describe an actionable caveat, pending requirement, or recoverable
problem. Failures describe an operation that could not complete. Put longer
explanations below the short status, in normal prose. Preserve raw provider
diagnostics and their spacing separately from authored explanations.
Input validation failures use the error marker and explain how to correct the
answer. Keep normal state descriptions, such as a feature being disabled,
neutral; use success only when reporting a completed change or verification.

## Prompts and copy

- Use sentence case for headings, prompts, choices, labels, and statuses.
  Preserve proper names, exact UI labels, literal commands, and resource IDs.
- Prompts have one leading `?`, no trailing question mark, colon, or period,
  and exactly one space before input. Keep each answer hint together when
  wrapping; long literal defaults must remain intact.
- Show yes/no choices as `[Y/n]` or `[y/N]`, capitalizing the actual Enter
  default. Show action hints in brackets, such as `[Enter to retry; x to exit]`.
  Advertise only actions the existing input loop accepts.
- Show a text default in parentheses. Enter retains the existing default
  behavior. Text defaults are not completion suggestions and do not require
  a new input library.
- Headings, menu choices, and short status labels have no final punctuation.
  Explanatory sentences end in periods. Colons introduce values or instructions.
- Reserve `!` for the warning marker. Write `Setup complete`, not a celebratory
  sentence. Use `...` for ongoing activity or truncated progress labels.
- Use direct, concise wording. Retain every substantive instruction, caveat,
  confirmation, and next step. Never change validation, accepted answers,
  defaults, provider operations, or exit codes as part of presentation work.

```text
Application settings

Choose the name displayed in your installation.

? Application name (My workspace) [x to exit]
? Enable AI features [Y/n]

✓ Configuration saved
- Deployment skipped
```

## Layout and copyable values

Use one blank line between sections and paragraphs. Use two-space indentation
for supporting details and lists, `-` bullets for parallel items, and numbered
steps for ordered instructions. Continuations align beneath their text.

`runner/console.py` owns layout. Prose uses the available terminal width, leaves
the last terminal column free, and caps lines at 100 cells. It preserves long
tokens and accounts for ANSI styles and Unicode cell widths. Prompts retain
their final input space. Short summary rows align; narrow terminals stack
labels and values. Use borderless summaries and explicit empty-state messages.

Use `format_value(..., verbatim=True)` for identifiers, URLs, DNS records, and
paths. Add `standalone=True` for commands. Copyable content retains its exact
bytes and receives no added punctuation, hard wrapping, or ellipsis. Use the
platform-aware command helpers, including PowerShell's `.\setup.cmd` form.
Help examples use `<placeholder-values>` and `[optional-arguments]`, following
the Primer's [command syntax](https://github.com/cli/cli/blob/trunk/docs/command-line-syntax.md).
Retain the summary's existing safe-field allowlist.

## Shared implementation

`runner/presentation.py` owns semantic styles and the Rich renderer. Use its
`heading`, `info`, `status`, `success`, `warning`, `error`, `secondary`, and
`choice` helpers, plus `activity` for static progress text. They return formatted
strings compatible with the layout helpers. Call `output` (imported as `print`
in installer modules) to emit
already-laid-out text. It preserves literal brackets and copyable values;
automatic Rich markup, highlighting, emoji substitution, and wrapping are off.
Pass `raw=True` for unmodified third-party diagnostics.

Use `read_input` (imported as `input`) with `format_prompt` for interactive
questions. Input parsing stays with the existing caller. Pass a structured
`default` and/or `hint` to `format_prompt` where needed instead of styling an
entire question or embedding ambiguous answer syntax in prose.

Use `Formatter.progress` for one transient progress indicator. Keep its label
short and neutral and provide a clear completion label. Write progress messages
through the shared output helper. Input and visible subprocess output must
pause the active indicator; use `pause_progress` around inherited-output
subprocesses. Never redirect process-wide stdout/stderr into a live display.
Use `progress.ok()` for completion, `progress.fail()` for failure, and
`progress.skip("Settings unchanged")` for a neutral outcome. An optional
operation that failed must never finish with a success marker.

Rich is pinned in the installer requirements and installed through the existing
dependency transaction. Formatting must never install a dependency. Before Rich
is available, bootstrap, runtime errors, and read-only commands use plain text.
The native launchers use the same copy and ASCII status conventions. Standard
argparse help and usage output stay plain on every supported Python version.

Redirected output, basic terminals, unsupported Unicode encodings, terminals
narrower than 20 columns, and legacy Windows consoles use static progress.
`NO_COLOR` disables styling. Unsupported Unicode status markers become `[OK]`
and `[X]`. Modern terminals may animate, including PowerShell in Windows
Terminal. Prefer a steady static transcript whenever animation is unavailable.

## Verification

The setup console tests cover widths 12, 40, 60, 80, and 100; styled and plain
output; literal brackets; Unicode cell widths; prompts and defaults; copyable
values; and progress pause, resume, and cleanup. Run focused tests first, then
`venv/bin/python run.py test setup`, affected lifecycle/runner tests, and
`venv/bin/python run.py traceability --changed --check`.

Review representative transcripts for success, cancellation, validation retry,
provider failure, and manual next steps. Visually review Linux, macOS, and
PowerShell running `.\setup.cmd`, including PowerShell in Windows Terminal and
the older console host. Check for flashing labels, duplicate completion lines,
prompt collisions, narrow-window behavior, and readable plain fallbacks.

The offline preview makes no installation or provider changes:

```sh
venv/bin/python -m testing.utility.setup_console_preview
```

In PowerShell:

```powershell
.\venv\Scripts\python.exe -m testing.utility.setup_console_preview
```

The message audit covers the initial install and authentication instructions;
optional services and browser/DNS steps; deployment, upgrade, and handoff;
doctor, recovery, backup, archive, and restore; dependency setup; shared runner
messages; and native launcher output. HTML archive contents and raw output from
Google, pip, npm, Git, and other external tools retain their own formatting.
