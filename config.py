"""
Configuration for sma_moxa_bridge.py - edit these values for your installation.

This is a normal Python file, so keep the syntax valid (quotes around text, commas in RULES).
"""

SMA_IP = "192.168.0.57"       # IP address of the Sunny Tripower
SMA_PORT = 502
SMA_UNIT_ID = 3               # SMA default unit ID for the inverter

# Which SMA value to switch on (all are signed 32-bit, watts):
#   30775 = Inverter AC power (total)          - always available
#   30867 = Grid feed-in power (export)         - needs SMA energy meter / Home Manager
#   30865 = Grid draw power (import)            - needs SMA energy meter / Home Manager
# For "use surplus solar", 30867 (feed-in) is usually the best choice.
SMA_POWER_REGISTER = 30775
SMA_FUNCTION_CODE = 4         # 4 = read input registers, 3 = read holding registers (SMA accepts both)

MOXA_IP = "192.168.0.254"      # IP address of the ioLogik E1214
MOXA_PORT = 502
MOXA_UNIT_ID = 1
MOXA_RELAY_COIL_BASE = 0      # Coil address of relay 0 (check the E1214 web console / manual Modbus table)

POLL_INTERVAL_S = 10          # how often to read the inverter
MAX_READ_FAILURES = 6         # after this many consecutive failed reads ...
FAILSAFE_RELAYS_OFF = True    # ... switch all managed relays off (True) or leave them as they are (False)

# One rule per relay you want to control (relay channels 0-5 on the E1214).
#   on_above_w  : switch ON when power >= this value
#   off_below_w : switch OFF when power <= this value  (keep it lower than on_above_w = hysteresis)
#   min_on_s    : once on, stay on at least this long
#   min_off_s   : once off, stay off at least this long
RULES = [
    {"relay": 0, "name": "Load 1", "on_above_w": 2500, "off_below_w": 1500, "min_on_s": 300, "min_off_s": 300},
    # {"relay": 1, "name": "Load 2", "on_above_w": 4000, "off_below_w": 3000, "min_on_s": 600, "min_off_s": 600},
]

LOG_FILE = None               # e.g. "/volume1/scripts/sma_moxa_bridge.log", or None for console only
LOG_MAX_BYTES = 1_000_000     # rotate the log file at this size ...
LOG_BACKUPS = 3               # ... and keep this many old files
STATUS_LOG_INTERVAL_S = 60    # log a status line (power + relay states) this often; 0 = off
