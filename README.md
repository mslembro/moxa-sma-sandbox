# SMA → Moxa bridge

Reads the power of an SMA Sunny Tripower (5.0 SE) over Modbus TCP and switches relays on a
Moxa ioLogik E1214 when the power crosses thresholds. Use it to turn on loads (boiler, heat pump,
EV charger, …) when there is solar surplus.

Hysteresis (separate on/off thresholds) and minimum on/off times keep a load from flapping
with every passing cloud.

## Files

| File | Purpose |
|------|---------|
| `sma_moxa_bridge.py` | the bridge itself |
| `config.py` | all settings (IP addresses, registers, rules, logging) - edit this |
| `requirements.txt` | Python dependency (`pymodbus`) |

## Install

Needs Python 3.8+ and pymodbus 3.x.

```bash
pip install -r requirements.txt
```

## Configure

Edit `config.py`. The important settings:

- `SMA_IP`, `SMA_UNIT_ID` - the inverter (Modbus TCP must be enabled on it; unit ID is usually 3).
- `SMA_POWER_REGISTER` - which value to switch on:
  `30775` inverter AC power (always available), `30867` grid feed-in or `30865` grid draw
  (both need an SMA energy meter / Home Manager). For "use surplus solar", feed-in is usually best.
- `MOXA_IP`, `MOXA_RELAY_COIL_BASE` - the E1214 and the coil address of relay 0.
- `RULES` - one entry per relay:

  | Key | Meaning |
  |-----|---------|
  | `relay` | relay channel 0-5 |
  | `name` | label used in the log |
  | `on_above_w` | switch ON when power ≥ this (watts) |
  | `off_below_w` | switch OFF when power ≤ this; keep it below `on_above_w` |
  | `min_on_s` / `min_off_s` | minimum time to stay on / off after a switch |

- `LOG_FILE` - set a path (e.g. `/volume1/scripts/sma_moxa_bridge.log`) to log to a file. It
  rotates at `LOG_MAX_BYTES` and keeps `LOG_BACKUPS` old files. `None` logs to the console only.
- `STATUS_LOG_INTERVAL_S` - how often a status line is logged (`0` = never).

Use a different settings file with `--config /path/to/other_config.py`.

## Run

```bash
python3 sma_moxa_bridge.py
```

Stop with Ctrl+C or SIGTERM. Relays keep their current state when the script stops.

### Testing

| Command | What it does |
|---------|--------------|
| `python3 sma_moxa_bridge.py --once --dry-run` | read the SMA once, apply the rules, switch nothing |
| `python3 sma_moxa_bridge.py --once` | one real cycle, relays can switch |
| `python3 sma_moxa_bridge.py -v` | run continuously and log every reading |

To check the switching without waiting for sunshine, make a copy of `config.py` with low
thresholds (e.g. on at 50 W, off at 20 W, `min_*_s` 0), run with `--config` pointing to it, and
check the relay afterwards. The script does not turn relays off when it stops, so switch them off
yourself afterwards.

## What the log shows

```
INFO Rule: Load 1 (relay 0) ON at >= 2500 W, OFF at <= 1500 W, min on 300s / min off 300s
INFO First SMA reading: 104 W
INFO Status: SMA 104 W | Load 1: OFF for 640s          <- every STATUS_LOG_INTERVAL_S
INFO Load 1 (relay 0) -> ON at 2600 W (was OFF for 640s)
WARNING SMA read failed (3 in a row)
ERROR SMA unreachable 6 times in a row - switching managed relays OFF
INFO SMA reachable again after 9 failed reads
```

If the log is empty, check that `LOG_FILE` is set and writable, and that the script is running.

## Safety behaviour

- **Fail-safe:** after `MAX_READ_FAILURES` failed SMA reads in a row, the managed relays are
  switched off (`FAILSAFE_RELAYS_OFF = True`), so loads don't run on stale data.
- **At night** the SMA reports "not available"; this is treated as 0 W, so loads switch off.
- **On startup** the script reads the real relay states from the Moxa, so a restart doesn't toggle
  anything.
- Only the relays listed in `RULES` are touched.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `Cannot connect to SMA` | Modbus TCP enabled on the inverter, IP, port 502, same network |
| `SMA returned error` | `SMA_UNIT_ID`, register number; 30867/30865 need an energy meter |
| `Cannot connect to Moxa` | Modbus/TCP enabled on the E1214, IP, port 502 |
| Relay doesn't switch but no error | `MOXA_RELAY_COIL_BASE` and the relay wiring |
| `Config file ... is missing: X` | the setting `X` was removed from `config.py` |
