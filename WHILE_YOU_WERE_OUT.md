# While You Were Out — Laptop Session, 2026-07-07

Read this on the home PC before doing anything else. Goal: compare this
session's changes against whatever was done at home last night (which,
as of this writing, was **never pushed to GitHub** — only the laptop's
work made it into `origin/main`).

**Commits pushed this session:**

- `17559a0` — Add per-camera device picker; fix hidden dropdowns and camera enumeration
- `a860bd4` — Initial commit (baseline snapshot of the project, pre-existing)

Run `git log --oneline` and `git diff a860bd4..17559a0` to see the exact diff.

---

## Context going in

This laptop had never actually pushed to GitHub before today — `a860bd4`
was the first commit ever made for this repo (a snapshot of the project
as it stood). Home PC changes from last night were made locally there but
apparently never committed/pushed, so they don't exist in git history at
all yet. **When you pull this on the home PC, check `git status` and
`git log` there first** — if last night's work is sitting as uncommitted
edits or unpushed local commits, you'll want to reconcile that manually
(likely a merge, not a fast-forward) rather than blindly pulling.

## What was asked for

1. Add support for selecting which physical camera (of however many are
   plugged in) feeds the "Input" and "Output" slots in the Live Camera
   tile. The user has 3 Thorcams connected to the laptop, but the app
   only actively uses 2 at a time (Input + Output).
2. Along the way, the user discovered the existing camera-settings
   selector buttons ("A · Input" / "B · Output") didn't do what they
   expected, and more seriously — **none of the dropdowns or numeric
   fields in the Live Camera tile were visible or clickable at all** on
   this laptop's screen. That turned out to be a real, previously
   unknown bug (see below), not a camera-picker issue.

## Changes made

### 1. New per-slot physical camera picker — `gui/widgets/camera_view.py`

Each camera pane (Input / Output) now has a `Cam:` dropdown next to its
editable label, populated with every detected camera serial number, plus
an "Auto (first found)" option. New signals:

- `camera_selection_changed(cam_idx: int, serial: str)` — emitted when
  the user picks a device for a slot.
- `refresh_cameras_requested()` — emitted by a new "⟳ Cameras" button in
  the top row, for rescanning after plugging/unplugging hardware.

Key behavior: picking a serial for one slot **automatically disables
that same serial in the other slot's dropdown**, so you can't assign the
same physical camera to both Input and Output. New public API:
`set_available_cameras(serials)`, `set_camera_serial(cam_idx, serial)`
(now also updates the picker, not just the label tooltip).

### 2. Dashboard wiring — `gui/dashboard.py`

- `_refresh_available_cameras()` — calls `list_cameras()` and pushes the
  result into the camera panel's pickers. Called once at startup and on
  the refresh button.
- `_on_camera_selection_changed(cam_idx, serial)` — persists the
  selection into `AppConfig.cameras[cam_idx].serial`, saves config, and
  **hot-reconnects** the affected camera worker if it's currently live.
  Defensively clears the *other* slot's serial if a duplicate is somehow
  requested (belt-and-suspenders on top of the UI-level exclusion).
  Update: `set_camera_serial` update, `save_config`.
- `_start_camera_b()` safety net: if Camera B is left on "Auto" (no
  serial assigned), it now explicitly avoids picking whatever serial
  Camera A actually connected to, by diffing against `list_cameras()`.
  Before this, two "Auto" slots could silently both connect to the same
  physical device.
- `_on_camera_a_connected` / `_on_camera_b_connected` now capture and
  display the actual serial the hardware reported (useful when a slot
  was left on Auto), instead of discarding it.

### 3. Real hardware bug fix — `core/hardware_bridge.py`

`list_cameras()` was **silently returning an empty list on this
machine**, always, for every camera. Root cause: it assumed
`Thorlabs.list_cameras_tlcam()` returns `(serial, model)` tuples and did
`for s, _ in ...`. On this machine's pylablib version it returns a flat
list of plain serial strings, so the tuple-unpack threw
`ValueError: too many values to unpack`, which got swallowed by a bare
`except Exception: return []`. Fixed to handle both shapes defensively.

**This means camera enumeration has probably been broken on this
machine this whole time**, independent of anything to do with the
camera picker feature. Worth checking whether the home PC's pylablib
version has the same issue — if `list_cameras()` there returns real
tuples, this was never a problem there, which would explain why nobody
caught it until now.

### 4. The real "buttons don't work" bug — `gui/hub_tile.py` (⭐ important)

This is the one worth reading carefully, since it's **not specific to
the camera picker** — it affects every dropdown and every numeric spin
box in every tile in the whole app, and would explain any past reports
of "controls are invisible/unclickable" anywhere in the UI.

`HubTile._relax_content_minimums()` runs on every tile at setup time. It
strips minimum-size constraints from child widgets (so tiles can be
resized down small) by setting `setMinimumSize(0, 0)` and
`QSizePolicy.Ignored` on anything **not** in a hardcoded whitelist:
`QLineEdit, QPushButton, QCheckBox, QTextEdit, QPlainTextEdit, QLabel`.

**`QComboBox` and `QDoubleSpinBox`/`QSpinBox` were never in that
whitelist.** `Ignored` size policy tells Qt's layout engine "give this
widget whatever size you want, including 0" — so under any space
pressure (e.g. a 1366×768 laptop screen with a smaller computed UI
scale than whatever screen this was last verified on), those widgets
get crushed to literal 0-pixel width while buttons/labels (exempted)
stay fully visible. That's exactly what looked like "buttons that don't
work" — the widgets were rendering as zero-width, unclickable ghosts.

Fix: added `QComboBox`, `QDoubleSpinBox`, `QSpinBox` to the exemption
whitelist. Verified against a real (non-offscreen, non-mocked) render —
every dropdown across the camera tile (`View:`, ROI mode, exposure, FPS,
white balance, and the new `Cam:` picker) now gets its real computed
width instead of 0.

**If the home PC runs on a bigger/higher-res monitor**, this bug may
never have manifested there (more available layout space = never
triggers the `Ignored` shrink-to-zero path), which is probably why it
went unnoticed until testing on this laptop specifically.

## Real hardware verification

All 3 physical cameras connected to this laptop were tested directly
(outside the GUI, via `core.hardware_bridge`) — enumerate, connect,
start acquisition, grab one real frame each, close cleanly:

| Serial | Frame shape | dtype | Notes |
|---|---|---|---|
| `36143` | 1080×1440×3 | float64 | color (Bayer/RGB), decent brightness |
| `36158` | 1080×1440×3 | float64 | color, dimmer (mean ~167 vs ~536) |
| `38173` | 1080×1440 | uint16 | **mono sensor** — different from the other two |

All 3 streamed successfully one at a time. The app only actively runs 2
workers simultaneously (Input + Output) by design — that part wasn't
changed.

## Known rough edges (user said "doesn't need to be perfect yet")

- The camera picker's "Auto" fallback with 3+ cameras connected is
  simplistic — it just avoids re-using Camera A's serial, it doesn't do
  anything smarter (e.g. remembering last-used-per-role). With 3 cameras
  plugged in, if both slots are left on "Auto", which of the 2
  *non-A* cameras gets picked for B is arbitrary (whatever
  `list_cameras()` returns first that isn't A). Explicit selection via
  the new picker is the reliable path — leaving both on "Auto" with 3+
  cameras is still ambiguous by design.
- No visual "identify/flash" way to tell which physical camera is which
  serial number besides reading the label sticker on the camera itself.
  Was offered to the user as a future improvement, not yet built.
- Tile-resize edge cases around the new picker combos weren't
  exhaustively tested at very small tile sizes (only verified at a
  reasonably sized tile, ~890×625).
- `float64` color frames straight off the camera (before any app-side
  processing) are notably heavy (~37 MB/frame at 1440×1080×3). The
  camera_view display path already downcasts to `float32`/`uint8` before
  painting (from a prior session's perf pass), but this is worth keeping
  in mind if further lag shows up specifically with these 2 color
  cameras.

## Accidental config pollution (already fixed, but flagging for transparency)

Mid-session, a diagnostic test using mocked camera serials
(`SN-222`/`SN-333`) accidentally wrote those fake values into the real
`user_config/app_config.json` (an environment-variable redirect to a
temp config dir didn't actually work, since `config.py` doesn't honor
that variable). This was caught and reverted immediately —
`cameras[0].serial` / `cameras[1].serial` / `camera_serial` were reset
back to `null`, and the real calibration values
(`efficiency_reference_mean: 139.51574491636`, custom `beam_roi`,
`Z925` stage config, etc.) were verified untouched throughout. Nothing
bad should have made it into git (`user_config/` is gitignored, was
never committed either way), but worth knowing about if numbers ever
look off.

## What to do next (on the home PC)

1. Check `git status` / `git log` on the home PC *before* pulling
   anything — reconcile whatever last night's uncommitted/unpushed work
   is against `origin/main` first, since this laptop's history starts
   from a completely different baseline commit (`a860bd4`) than
   whatever the home PC has locally.
2. Once synced, `git diff a860bd4..17559a0` to review the diff described
   above end-to-end.
3. Re-test `core.hardware_bridge.list_cameras()` directly there — if it
   already worked fine (real tuples from pylablib), that confirms the
   bug was specific to this laptop's pylablib version and not something
   that needs further generalization.
4. Re-test the Live Camera tile's dropdowns on the home PC's monitor. If
   the `hub_tile.py` bug never manifested there (bigger screen, more
   layout room), that's expected — the fix is still correct and safe to
   keep either way, it does not change behavior on screens where there
   was already enough room.
5. Run the full simulation as planned.
