# Paragon PR7-SM: notes for Claude

**Paragon PR7-SM** is the owner's personal system monitor: Python (**PySide6** + **psutil**) that **works the way
Process Explorer works**, in the Paragon family look (PR7-Z ... PR7-IS, PR7-PM `ARYEZ/Paragon-PR7-PM`). Windows
10/11 x64 is the target; it runs on Linux for tests. The owner writes Python; explain the why.

## How it's built

- `pr7sm/procs.py` (no Qt): `Sampler.sample()` -> `Snapshot` (procs, `order` = the tree, `totals`). CPU per process
  from the cpu_times difference since the last sample (None on the first), private bytes (`memory_info().private` on
  Windows), working set, I/O. `tree`: a parent adopts a child only if it started first (PID reuse), parent 0 adopts
  nobody, orphans are top-level. Kinds (`KIND_ORDER`): ending / new last `highlight` s; then suspended, service
  (`service_pids`, refreshed every 10 s), own. History deques (`history`, `proc_history`, `core_history`).
  `commit_charge` = GetPerformanceInfo on Windows.
- `pr7sm/actions.py` (no Qt): kill, kill_tree (children first), suspend / resume, set_priority (Windows priority
  classes or nice values), dlls (memory_maps images), handles (open files + connections), find, details (the
  Properties' Image tab). Errors are `Problem` (access denied says to run as administrator).
- `pr7sm/winver.py`: file details via GetFileVersionInfoW / VerQueryValueW, cached per path.
- `pr7sm/main_window.py`: `ProcModel` is a flat list (never QStandardItemModel) where rows carry their depth;
  `RowDelegate` paints the tint (the theme's ::item rules make Qt ignore item backgrounds), the indent and the arrow;
  a refresh with the same rows only emits dataChanged (selection, scroll, collapsed branches stay). `sort_by`: asc,
  desc, then the tree. `ProcView` takes Del / Shift+Del / Enter / Space / arrows itself. Lower pane and Find load on
  threads (`sync = True` in tests). Dialogs: `PropertiesDialog`, `SystemInfoDialog`, `FindDialog`, `OptionsDialog`
  (they follow `window.updated`). `_ask` / `answers` / `said` for tests.
- `pr7sm/graphs.py`: `Graph` (newest sample at the right; `top=None` scales to the data). Draw lines with no brush:
  drawPath fills an open path's chord with the current brush.
- `pr7sm/taskmgr.py`: Replace Task Manager = HKLM IFEO `taskmgr.exe` Debugger `"<PR7-SM>" /taskmgr`, both registry
  views, only our value is ever removed (PR7-W's notepad.py pattern); `run_elevated` (ShellExecuteEx runas),
  `restart_as_admin`.
- `pr7sm/app.py`: one window per user (QLocalSocket, PR7-R's Windows fix); command-line modes never let an error
  escape (PR7-IS's lesson); `--selftest OUT.json` (CI runs it on the installed exe), `--replace-taskmgr`,
  `--restore-taskmgr`, `--uninstall`.
- Installer `installer/pr7sm.iss` (per user, AppId {DA18598E-10B7-4EA2-B221-71F0CFC56AA8} permanent; tasks taskmgr
  (unticked, elevated), desktopicon); CI installs it, `tools/verify_install.py installed|uninstalled`.
- Updates: `pr7sm/updates.py` / `update_ui.py` (the family's files, keep them in step; with PR7-U installed,
  update_ui offers it); `family.py`: the family's AppIds (PR7-SM included).

- `pr7sm/finish.py` (no Qt): the family's finish (OBSIDIAN / AURORA), one choice for every app: HKCU\Software\Paragon\Family "Finish" (a file elsewhere; PARAGON_FAMILY_FILE in tests, conftest). `finish.start` at start-up, `set_finish` saves it, app.py's 2 s timer `finish.follow`s another app's switch. The same file in every family app: keep them in step.

## The look (family rules)

- Theme is PR7-PM's (OBSIDIAN + AURORA). Colours: the family's only, row tints and graphs included (Process
  Explorer's blue / green / purple are orange / pearl / onyx here); Inter; labels UPPER CASE.
- The PR7-SM mark: PR7 `Logo.cpp` geometry plus S and M (PR7-IS's `S_SHAPE`, PR7-M's `M_SHAPE`); icon "7SM" by
  `tools/make_icon.py`, wizard art by `tools/make_installer_art.py`. Check visuals with
  `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT` (a made-up Windows machine through a stand-in sampler).

## Rules

- Behaviour questions: do what Process Explorer does (keys, colours, columns, Properties, System Information).
- Tests: `python -m pytest` (offscreen) on real processes the tests start (and end). Never the real settings
  (conftest), or, outside CI, the registry (HKLM IFEO is only written in tests/test_windows.py on CI).
- Releases: bump `__version__` in `pr7sm/__init__.py` and add a `## x.y.z` section to CHANGELOG.md, then push: CI
  publishes that version by itself once every check has passed. Run workflow / `v*` tags still work.
