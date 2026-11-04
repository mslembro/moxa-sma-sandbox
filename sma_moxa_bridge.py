#!/usr/bin/env python3
"""
SMA Sunny Tripower 5.0 SE  ->  Moxa ioLogik E1214 bridge

Reads power from the SMA inverter over Modbus TCP and switches relays on the
Moxa E1214 based on thresholds (with hysteresis and minimum on/off times so
connected loads don't flap on and off with every passing cloud).

Settings live in config.py next to this script (or pass --config PATH).

Requirements:   pip install pymodbus      (works with pymodbus 3.x)
Run:            python3 sma_moxa_bridge.py
Test once:      python3 sma_moxa_bridge.py --once --dry-run
"""

import argparse
import importlib.util
import inspect
import logging
import logging.handlers
import os
import signal
import sys
import time

from pymodbus.client import ModbusTcpClient

SMA_NAN_S32 = -0x80000000     # SMA returns 0x80000000 when a value is "not available" (e.g. at night)

log = logging.getLogger("sma_moxa")
cfg = None                    # the loaded config module, set by load_config()


def load_config(path):
    """Load the settings file (a plain Python file) and check that nothing is missing."""
    global cfg
    spec = importlib.util.spec_from_file_location("sma_moxa_config", path)
    if spec is None or spec.loader is None:
        sys.exit(f"Cannot load config file: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except FileNotFoundError:
        sys.exit(f"Config file not found: {path}")
    required = ["SMA_IP", "SMA_PORT", "SMA_UNIT_ID", "SMA_POWER_REGISTER", "SMA_FUNCTION_CODE",
                "MOXA_IP", "MOXA_PORT", "MOXA_UNIT_ID", "MOXA_RELAY_COIL_BASE", "POLL_INTERVAL_S",
                "MAX_READ_FAILURES", "FAILSAFE_RELAYS_OFF", "RULES", "LOG_FILE", "LOG_MAX_BYTES",
                "LOG_BACKUPS", "STATUS_LOG_INTERVAL_S"]
    missing = [n for n in required if not hasattr(module, n)]
    if missing:
        sys.exit(f"Config file {path} is missing: {', '.join(missing)}")
    cfg = module


def unit_kwarg(func, unit_id):
    """pymodbus renamed the unit-id argument over time (unit -> slave -> device_id)."""
    params = inspect.signature(func).parameters
    for name in ("device_id", "slave", "unit"):
        if name in params:
            return {name: unit_id}
    return {}


def read_sma_power(client):
    """Return SMA power in watts, 0 if the inverter reports 'not available', or None on error."""
    if not client.connected and not client.connect():
        log.warning("Cannot connect to SMA at %s:%s", cfg.SMA_IP, cfg.SMA_PORT)
        return None
    func = client.read_input_registers if cfg.SMA_FUNCTION_CODE == 4 else client.read_holding_registers
    try:
        rr = func(cfg.SMA_POWER_REGISTER, count=2, **unit_kwarg(func, cfg.SMA_UNIT_ID))
    except Exception as exc:
        log.warning("SMA read error: %s", exc)
        client.close()
        return None
    if rr.isError():
        log.warning("SMA returned error: %s", rr)
        return None
    raw = (rr.registers[0] << 16) | rr.registers[1]   # big-endian word order
    value = raw - 0x100000000 if raw & 0x80000000 else raw
    if value == SMA_NAN_S32:
        return 0
    return value


def write_relay(client, relay, state, dry_run=False):
    """Switch one E1214 relay. Returns True on success."""
    if dry_run:
        log.info("[dry-run] would set relay %d -> %s", relay, "ON" if state else "OFF")
        return True
    if not client.connected and not client.connect():
        log.warning("Cannot connect to Moxa at %s:%s", cfg.MOXA_IP, cfg.MOXA_PORT)
        return False
    func = client.write_coil
    try:
        rr = func(cfg.MOXA_RELAY_COIL_BASE + relay, state, **unit_kwarg(func, cfg.MOXA_UNIT_ID))
    except Exception as exc:
        log.warning("Moxa write error: %s", exc)
        client.close()
        return False
    if rr.isError():
        log.warning("Moxa returned error: %s", rr)
        return False
    return True


def read_relays(client):
    """Read current state of the 6 E1214 relays, or None on error."""
    if not client.connected and not client.connect():
        return None
    func = client.read_coils
    try:
        rr = func(cfg.MOXA_RELAY_COIL_BASE, count=6, **unit_kwarg(func, cfg.MOXA_UNIT_ID))
    except Exception:
        client.close()
        return None
    if rr.isError():
        return None
    return list(rr.bits[:6])


class RelayRule:
    def __init__(self, cfg):
        self.relay = cfg["relay"]
        self.name = cfg.get("name", f"Relay {self.relay}")
        self.on_above = cfg["on_above_w"]
        self.off_below = cfg["off_below_w"]
        self.min_on = cfg.get("min_on_s", 0)
        self.min_off = cfg.get("min_off_s", 0)
        self.state = None            # unknown until first read from the Moxa
        self.last_change = 0.0

    def desired(self, power, now):
        """Return the state this relay should be in (True/False), respecting hysteresis and timers."""
        held = now - self.last_change
        if self.state:
            if power <= self.off_below and held >= self.min_on:
                return False
            return True
        if power >= self.on_above and held >= self.min_off:
            return True
        return False


def main():
    ap = argparse.ArgumentParser(description="SMA -> Moxa E1214 relay bridge")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py"),
                    help="settings file (default: config.py next to this script)")
    ap.add_argument("--once", action="store_true", help="run one cycle and exit (for testing)")
    ap.add_argument("--dry-run", action="store_true", help="read the SMA but don't switch any relays")
    ap.add_argument("--verbose", "-v", action="store_true", help="log every reading")
    args = ap.parse_args()
    load_config(args.config)

    handlers = [logging.StreamHandler(sys.stdout)]
    if cfg.LOG_FILE:
        handlers.append(logging.handlers.RotatingFileHandler(
            cfg.LOG_FILE, maxBytes=cfg.LOG_MAX_BYTES, backupCount=cfg.LOG_BACKUPS))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    logging.getLogger("pymodbus").setLevel(logging.CRITICAL)

    sma = ModbusTcpClient(cfg.SMA_IP, port=cfg.SMA_PORT, timeout=3)
    moxa = ModbusTcpClient(cfg.MOXA_IP, port=cfg.MOXA_PORT, timeout=3)
    rules = [RelayRule(r) for r in cfg.RULES]

    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # Start from the relays' actual state so a restart doesn't toggle anything.
    current = read_relays(moxa)
    if current is None:
        log.warning("Could not read relay states from Moxa yet; will assume OFF")
        current = [False] * 6
    for r in rules:
        r.state = bool(current[r.relay])
        log.info("%s (relay %d) starts %s", r.name, r.relay, "ON" if r.state else "OFF")

    failures = 0
    last_power = None
    last_status = 0.0
    log.info("Running: SMA %s (unit %d) reg %d -> Moxa %s, polling every %ds%s",
             cfg.SMA_IP, cfg.SMA_UNIT_ID, cfg.SMA_POWER_REGISTER, cfg.MOXA_IP, cfg.POLL_INTERVAL_S,
             " [DRY RUN]" if args.dry_run else "")
    for r in rules:
        log.info("Rule: %s (relay %d) ON at >= %d W, OFF at <= %d W, min on %ds / min off %ds",
                 r.name, r.relay, r.on_above, r.off_below, r.min_on, r.min_off)
    log.info("Fail-safe: %s after %d failed reads", "relays OFF" if cfg.FAILSAFE_RELAYS_OFF else "leave relays as is",
             cfg.MAX_READ_FAILURES)

    while running:
        now = time.monotonic()
        power = read_sma_power(sma)

        if power is None:
            failures += 1
            log.warning("SMA read failed (%d in a row)", failures)
            if failures == cfg.MAX_READ_FAILURES and cfg.FAILSAFE_RELAYS_OFF:
                log.error("SMA unreachable %d times in a row - switching managed relays OFF", failures)
                for r in rules:
                    if r.state and write_relay(moxa, r.relay, False, args.dry_run):
                        r.state, r.last_change = False, now
                        log.info("%s (relay %d) -> OFF (fail-safe)", r.name, r.relay)
        else:
            if failures >= cfg.MAX_READ_FAILURES:
                log.info("SMA reachable again after %d failed reads", failures)
            elif failures:
                log.info("SMA read OK again after %d failed read(s)", failures)
            elif last_power is None:
                log.info("First SMA reading: %d W", power)
            failures = 0
            last_power = power
            log.debug("SMA power: %d W", power)
            for r in rules:
                want = r.desired(power, now)
                if want != r.state:
                    if write_relay(moxa, r.relay, want, args.dry_run):
                        log.info("%s (relay %d) -> %s at %d W (was %s for %ds)",
                                 r.name, r.relay, "ON" if want else "OFF", power,
                                 "ON" if r.state else "OFF", now - r.last_change if r.last_change else 0)
                        r.state, r.last_change = want, now
                    else:
                        log.warning("%s (relay %d): failed to switch %s at %d W - will retry",
                                    r.name, r.relay, "ON" if want else "OFF", power)

        if cfg.STATUS_LOG_INTERVAL_S and now - last_status >= cfg.STATUS_LOG_INTERVAL_S:
            last_status = now
            parts = []
            for r in rules:
                held = f" for {int(now - r.last_change)}s" if r.last_change else ""
                parts.append(f"{r.name}: {'ON' if r.state else 'OFF'}{held}")
            log.info("Status: SMA %s | %s",
                     f"{last_power} W" if power is not None else "UNAVAILABLE", " | ".join(parts))

        if args.once:
            print(f"SMA power: {power} W" if power is not None else "SMA read FAILED")
            print("Relays:", read_relays(moxa) if not args.dry_run else "(dry-run, not read)")
            break

        for _ in range(cfg.POLL_INTERVAL_S * 10):
            if not running:
                break
            time.sleep(0.1)

    sma.close()
    moxa.close()
    log.info("Stopped")


if __name__ == "__main__":
    main()