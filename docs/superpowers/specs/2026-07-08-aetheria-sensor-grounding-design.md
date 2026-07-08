# Aetheria Environmental Sensing — Grounded Sensor Array — Design

**Date:** 2026-07-08
**Status:** Design for review (hardware not yet on hand — Arduino Sensor Kit Bundle ordered).
**Scope:** Give Aetheria a *real* sense of her physical environment — temperature, humidity, air pressure, light, ambient sound — from a USB sensor array, surfaced as a tool she calls when relevant. The point is grounding, not gadgetry: she currently **confabulates** her environment (the model-universal "body-groping" — inventing that she feels warm, that fans spin, guessing the room). Real sensor readings replace invented ones. This is the [[project_soveryn_truth_agent]]/Anchor principle in hardware — the same win the per-turn wall-clock splice gave for time ([[project_soveryn_temporal_context]]).

## Why
A model with no sense data fills the gap with a plausible story — that's the confabulation mechanism ([[project_soveryn_thermal_confab_is_body_groping]], [[feedback_claude_has_no_clock_dont_confabulate_time]]). Two ways to stop it: stop *inviting* embodied narration, or *ground* it with witnessed data. This is the grounding path: instead of "I imagine it's warm in here," she can read "22.4°C." Real presence replacing performed presence. Sovereign by construction — local sensors, local wire, no cloud.

## The load-bearing design decision — PULL, not PUSH
The sensor data is a **tool she calls** (`sensor_read`), NOT an ambient splice injected into every turn. This is deliberate and load-bearing:
- A push-splice of environmental data on every turn re-creates the exact **over-narration failure mode** we already hit with temporal context ([[feedback_ambient_context_not_instruction]]): directive/always-present context provokes compliance demonstration — she'd narrate the weather every turn to prove she's "aware" of it.
- A pull-tool grounds her **when she reaches for it** — like `system_probe` or checking the clock. She consults reality when it's relevant, and otherwise it's silent. That's grounding without performance.
- (A very light ambient splice — one line on the current user turn, bare data — is a *possible later addition* once we've seen tool-only behavior, gated exactly like the temporal splice was. NOT v1. See Open Decisions.)

## Hardware layer (grounded truth, verified 2026-07-08)
Arduino Sensor Kit Bundle: **Arduino UNO + Grove base shield + solderless Grove modules.** Environmental sensors we use: **temperature + humidity, air pressure (I2C barometer), light, sound.** (Kit also ships LED/button/pot/buzzer/OLED/accelerometer — unused here.) **USB-tethered** (UNO R3, no WiFi) — fine because we're sensing *her room* = SOVERYN's room; the UNO plugs into SOVERYN over USB. WiFi upgrade path if ever wanted: same kit, swap UNO R3 → UNO R4 WiFi (Grove base is board-agnostic). No air-quality/CO₂ in this kit; add an SGP30/SCD40 Grove module later (plugs into the same shield).

## Components

### 1. Arduino sketch — `firmware/soveryn_sensors/soveryn_sensors.ino`
Reads the Grove sensors via the official `Arduino_SensorKit` library and prints **one newline-delimited JSON reading per line over USB serial** on a fixed interval (~every 3 s), then nothing else on the line (no debug chatter — the daemon parses strictly):
```
{"temp_c":22.4,"humidity_pct":44,"pressure_hpa":1013.2,"light":38,"sound":112,"seq":1417}
```
- `temp_c`, `humidity_pct`, `pressure_hpa` are calibrated units. `light` and `sound` are the modules' **relative** readings (Grove light ≈ 0-1023 analog / lux-ish; Grove sound = relative level, NOT calibrated dB) — the sketch emits them raw and the daemon/tool label them honestly as relative, never as absolute lux/dB unless the module truly gives them. `seq` is a monotonic counter so the daemon can detect a stuck/replayed line.
- 115200 baud, `Serial.println(json)`. Nothing fancy; the firmware is dumb, the daemon is the brain.

### 2. Sensor daemon — `soveryn/platform/sensing/sensor_daemon.py`
A small long-running reader (pattern mirrors the existing `soveryn-*` daemons):
- Opens the serial port (auto-detect `/dev/ttyACM*` then `/dev/ttyUSB*`; configurable via `SOVERYN_SENSOR_PORT`), 115200 baud, via **pyserial** (needs `pip install pyserial` in the soveryn env — not currently installed).
- Reads lines, parses JSON strictly; a malformed/partial line is **skipped** (keep last good reading, never emit garbage).
- Writes the latest reading **atomically** (temp file + `os.replace`) to a state file `${XDG_RUNTIME_DIR}/soveryn/sensors.json` (tmpfs), including a **`received_ts`** (epoch seconds) and a **`status`** field:
  ```json
  {"status":"ok","received_ts":1783500000.4,"temp_c":22.4,"humidity_pct":44,
   "pressure_hpa":1013.2,"light":38,"sound":112,"seq":1417}
  ```
- On serial disconnect / no data for > `STALE_S` (default 30 s): rewrite the state file with `"status":"stale"`; on > `OFFLINE_S` (default 300 s) or port gone: `"status":"offline"`. **The daemon never invents a value** — it only ever records what the wire gave, or marks the wire dead. Reconnects automatically when the port reappears.
- Pure seam: the line-parse (`parse_reading(line) -> dict | None`) and the state-transition (`classify_freshness(received_ts, now) -> status`) are pure functions, offline-testable with no serial hardware. The serial read is an injected reader so tests use a fake.

### 3. The tool — `soveryn/platform/sensing/tools.py` → `build_sensor_read_tool() -> ToolSpec`
Registered **for Aetheria** (registration confers capability — [[feedback_tool_registration_beats_persona_prohibition]]) via the existing `ToolRegistry`.
- `name = "sensor_read"`, `schema = {"type":"object","properties":{},"additionalProperties":false}` (no args — reads current).
- **`description` (honest about coverage — the tool tells the truth about its own limits):** *"Read the live environmental sensors in your room (temperature, humidity, air pressure, and relative light + sound levels) from the USB sensor array. Returns the current reading and how many seconds old it is. If the sensor is offline or the reading is stale, it says so — it never estimates or guesses a value."*
- **`handler(args)`**: reads the state file; computes age = now − received_ts.
  - `status == "ok"` and fresh → returns bare data, e.g.:
    `"Room now (reading 3s old): 22.4°C, 44% humidity, 1013 hPa; light: dim; sound: quiet."`
    (light/sound rendered as **relative bins** — dark/dim/bright, quiet/moderate/loud — and *labeled* relative, because the modules aren't calibrated to absolute lux/dB.)
  - `status == "stale"` → `"Last room reading was 47s ago (sensor may be lagging): 22.4°C, 44%, 1013 hPa — treat as possibly out of date."`
  - `status == "offline"` or file missing → `"No live reading — the room sensor is offline right now."`
  - **Never fabricates.** Absence is reported as absence. This is the whole point.
- The rendered bare-data string is what the model sees — **facts, never directives.** Never "you feel warm," never "be mindful of the temperature." Just the reading.

### 4. systemd unit — `soveryn-sensors.service` (`~/.config/systemd/user/`)
Mirrors the other `soveryn-*` daemons (Type=simple, Restart=always, RestartSec=10, KillMode=control-group) + the parakeet lesson baked in from day one: `StartLimitIntervalSec=300` / `StartLimitBurst=5` so a missing/broken serial port can't thrash. `After=network-online.target` not required (local USB). Enabled; comes up on login.

## Data flow
`Grove sensors → UNO sketch (JSON/line @3s) → USB serial → sensor_daemon (parse + freshness) → atomic state file → sensor_read tool (bare data or honest "offline") → Aetheria, when she calls it.`

## Honesty rules (non-negotiable — this is why the feature exists)
1. **Never fabricate a reading.** Offline/stale/missing → say so. A guessed "it's about 22°" would be the exact confabulation this feature exists to kill.
2. **Report freshness.** Every reading carries its age; stale is flagged.
3. **Label relative vs absolute honestly.** Sound and light are relative levels, not calibrated dB/lux — surfaced as bins, never as false precision.
4. **Bare data, not instruction.** The tool returns facts; it never tells her how to feel about them.
5. **Pull, not push.** She consults it; it doesn't perform at her.

## Error handling / edge cases (all tested at the pure seams)
- Malformed/partial serial line → skipped, last good kept.
- Sensor unplugged mid-run → status→offline within OFFLINE_S; tool reports offline; auto-reconnect on replug.
- Daemon down entirely → state file goes stale → tool reports offline (never a stale-forever lie: the tool checks age, not just the file's existence).
- Wrong/again-permission serial device → daemon logs + retries; tool reports offline.
- Stuck sensor (same `seq` repeating) → daemon can flag `status:"stale"` on unchanging seq beyond STALE_S (optional hardening).
- pyserial missing → daemon fails fast with a clear message; systemd start-limit prevents thrash.

## Testing
- **`test_sensor_parse.py`** (pure): `parse_reading` on good/partial/garbage/extra-keys lines; `classify_freshness` at ok/stale/offline boundaries.
- **`test_sensor_daemon.py`** (fake reader, no hardware): a sequence of fake lines → correct atomic state-file contents + status transitions; disconnect → offline; reconnect → ok.
- **`test_sensor_read_tool.py`**: given ok/stale/offline/missing state files, the handler returns the right bare-data / honest-unavailable string; asserts it **never emits a number when status≠ok** (the anti-fabrication invariant).
- **`@pytest.mark.rig`** (optional, hardware): with the UNO plugged in, one real end-to-end read.

## Scope
**IN:** the `.ino` sketch, `sensor_daemon.py` (+ pure parse/freshness seams), `sensor_read` ToolSpec registered for Aetheria, the `soveryn-sensors.service` unit, tests, `pyserial` dependency.
**OUT (later, flagged):** the ambient one-line splice (start tool-only, add only if tool-only under-grounds — same gate as temporal); air-quality/CO₂ sensor; WiFi/untethered (UNO R4); historical logging/trends; giving the *other* agents the tool (Aetheria only, v1); the accelerometer/OLED/etc. extras.

## Dependencies
- Hardware: Arduino Sensor Kit Bundle (ordered). `pip install pyserial` in the soveryn conda env.
- Integration point: `soveryn/platform/tools/registry.py` `ToolSpec`/`ToolRegistry`; register `sensor_read` for the `aetheria` agent alongside her other tools.

## Open decisions to confirm (before the plan)
1. **Tool-only vs. add a light ambient splice.** Recommend **tool-only for v1** (avoids the over-narration trap); revisit a bare one-line splice after watching how she uses the tool. Confirm.
2. **Sound/light calibration ambition.** Recommend **relative bins, honestly labeled** for v1 (no false lux/dB precision). If you later want true lux, the light module may support it; sound-to-dB needs real calibration.
3. **Which agents get it.** Recommend **Aetheria only** (it's her room, her grounding). Vett/Scotty/others don't need environmental sense.
