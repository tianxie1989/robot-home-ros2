#!/usr/bin/env python3
"""
MPU6050 IMU Hardware Test for Raspberry Pi 5
=============================================

Standalone hardware test script — NOT a ROS2 node.
Reads accelerometer, gyroscope and temperature from MPU6050 via I2C.

Hardware:
  MPU6050 on I2C-1 (GPIO2=SDA, GPIO3=SCL), address 0x68
  Physical pins: Pin 3 (SDA), Pin 5 (SCL)

Keyboard Controls (non-blocking, no Enter needed):
  R  - Print detailed snapshot with timestamp and roll/pitch
  Q  - Quit

Usage:
  python3 test_imu.py

Requirements:
  - smbus2 (preferred)
  - Must run on Raspberry Pi with I2C enabled
  - If smbus2 not available, runs in simulation mode with realistic fake data
"""

import sys
import time
import math
import random
import select
import termios
import tty
from datetime import datetime

# ─── MPU6050 Constants ─────────────────────────────────────────────────────────
I2C_BUS     = 1
I2C_ADDR    = 0x68
REG_PWR_MGMT_1 = 0x6B
REG_ACCEL_XOUT_H = 0x3B   # 6 bytes: AX, AY, AZ (2 bytes each, big-endian)
REG_TEMP_OUT_H   = 0x41   # 2 bytes
REG_GYRO_XOUT_H  = 0x43   # 6 bytes: GX, GY, GZ

# Conversion factors (default config after wake: ±2g accel, ±250°/s gyro)
ACCEL_SCALE = 16384.0   # LSB per g  (±2g → 16384 LSB/g)
GYRO_SCALE  = 131.0     # LSB per °/s (±250°/s → 131 LSB/(°/s))
G           = 9.80665   # m/s² per g

# ─── Backend detection ─────────────────────────────────────────────────────────
_BACKEND = 'simulation'
_smbus2  = None


def _detect_backend():
    global _BACKEND, _smbus2
    try:
        import smbus2 as _s
        _smbus2 = _s
        _BACKEND = 'smbus2'
    except ImportError:
        _BACKEND = 'simulation'


def _fallback_to_sim(reason):
    """Switch to simulation mode, printing the reason."""
    global _BACKEND
    _BACKEND = 'simulation'
    print(f"[WARN] Falling back to simulation mode: {reason}")


_detect_backend()

# ─── Non-blocking single-key input ─────────────────────────────────────────────

class _KeyInput:
    """Non-blocking single-keyboard reader for Linux TTY.
    Gracefully degrades when stdin is not a TTY (e.g. pipe/redirect)."""

    def __init__(self):
        self._fd = sys.stdin.fileno()
        self._is_tty = False
        self._old = None
        try:
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
            self._is_tty = True
        except (termios.error, OSError):
            # Not a TTY — keyboard input will be unavailable
            print("[WARN] stdin is not a TTY — keyboard controls disabled.")

    def restore(self):
        if self._is_tty and self._old is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def getkey(self, timeout=0.0):
        if not self._is_tty:
            return None
        if select.select([sys.stdin], [], [], timeout)[0]:
            return sys.stdin.read(1)
        return None


# ─── IMU abstraction ───────────────────────────────────────────────────────────

class _IMUHandle:
    """Unified IMU interface over smbus2 / simulation."""

    def __init__(self):
        self._bus = None
        # Simulation state: small noise around "level on table"
        self._sim_ax = 0.0
        self._sim_ay = 0.0
        self._sim_az = G
        self._sim_gx = 0.0
        self._sim_gy = 0.0
        self._sim_gz = 0.0
        self._sim_temp = 25.0

    def init(self):
        if _BACKEND == 'smbus2':
            self._init_smbus2()
        else:
            print("[SIM] smbus2 not available — running in simulation mode.")

    def _init_smbus2(self):
        try:
            self._bus = _smbus2.SMBus(I2C_BUS)
            # Wake MPU6050: clear sleep bit in PWR_MGMT_1
            self._bus.write_byte_data(I2C_ADDR, REG_PWR_MGMT_1, 0x00)
            time.sleep(0.1)   # let sensor stabilise
        except OSError as e:
            if self._bus is not None:
                try:
                    self._bus.close()
                except Exception:
                    pass
                self._bus = None
            _fallback_to_sim(f"I2C communication failed ({e}). "
                             "Is MPU6050 connected and I2C enabled?")

    def read(self):
        """Return (ax, ay, az) m/s², (gx, gy, gz) °/s, temp °C."""
        if _BACKEND == 'smbus2':
            return self._read_smbus2()
        return self._read_sim()

    def _read_smbus2(self):
        # Burst-read 14 bytes starting at ACCEL_XOUT_H:
        #   [AX_H AX_L AY_H AY_L AZ_H AZ_L TEMP_H TEMP_L
        #    GX_H GX_L GY_H GY_L GZ_H GZ_L]
        data = self._bus.read_i2c_block_data(I2C_ADDR, REG_ACCEL_XOUT_H, 14)

        def _raw16(hi, lo):
            v = (data[hi] << 8) | data[lo]
            return v if v < 32768 else v - 65536   # signed 16-bit

        ax_raw = _raw16(0, 1)
        ay_raw = _raw16(2, 3)
        az_raw = _raw16(4, 5)
        t_raw  = _raw16(6, 7)
        gx_raw = _raw16(8, 9)
        gy_raw = _raw16(10, 11)
        gz_raw = _raw16(12, 13)

        ax = ax_raw / ACCEL_SCALE * G
        ay = ay_raw / ACCEL_SCALE * G
        az = az_raw / ACCEL_SCALE * G
        gx = gx_raw / GYRO_SCALE
        gy = gy_raw / GYRO_SCALE
        gz = gz_raw / GYRO_SCALE
        temp = t_raw / 340.0 + 36.53

        return (ax, ay, az), (gx, gy, gz), temp

    def _read_sim(self):
        """Generate realistic fake data with slight noise."""
        noise_accel = 0.04   # m/s² std dev
        noise_gyro  = 0.25   # °/s   std dev
        noise_temp  = 0.05   # °C    std dev

        ax = self._sim_ax   + random.gauss(0, noise_accel)
        ay = self._sim_ay   + random.gauss(0, noise_accel)
        az = self._sim_az   + random.gauss(0, noise_accel)
        gx = self._sim_gx   + random.gauss(0, noise_gyro)
        gy = self._sim_gy   + random.gauss(0, noise_gyro)
        gz = self._sim_gz   + random.gauss(0, noise_gyro)
        temp = self._sim_temp + random.gauss(0, noise_temp)

        return (ax, ay, az), (gx, gy, gz), temp

    def cleanup(self):
        if _BACKEND == 'smbus2' and self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass


# ─── Roll / Pitch from accelerometer ───────────────────────────────────────────

def _calc_roll_pitch(ax, ay, az):
    roll  = math.atan2(ay, az)                  * 180.0 / math.pi
    pitch = math.atan2(-ax, math.sqrt(ay**2 + az**2)) * 180.0 / math.pi
    return roll, pitch


# ─── Display helpers ───────────────────────────────────────────────────────────

def _fmt_val(v, width=6, prec=2):
    return f"{v:>{width}.{prec}f}"


def _print_line(accel, gyro, temp):
    ax, ay, az = accel
    gx, gy, gz = gyro
    print(
        f"Accel(m/s²):"
        f" X:{_fmt_val(ax)} Y:{_fmt_val(ay)} Z:{_fmt_val(az)}"
        f"  |  "
        f"Gyro(°/s):"
        f" X:{_fmt_val(gx)} Y:{_fmt_val(gy)} Z:{_fmt_val(gz)}"
        f"  |  Temp: {temp:.1f}°C"
    )


def _print_snapshot(accel, gyro, temp):
    ax, ay, az = accel
    gx, gy, gz = gyro
    roll, pitch = _calc_roll_pitch(ax, ay, az)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print()
    print("=== IMU Snapshot (R pressed) ===")
    print(f"Timestamp: {ts}")
    print(f"Accelerometer (m/s²):  X: {_fmt_val(ax, 7, 2)}"
          f"  Y: {_fmt_val(ay, 7, 2)}"
          f"  Z: {_fmt_val(az, 7, 2)}")
    print(f"Gyroscope   (°/s):     X: {_fmt_val(gx, 7, 2)}"
          f"  Y: {_fmt_val(gy, 7, 2)}"
          f"  Z: {_fmt_val(gz, 7, 2)}")
    print(f"Temperature: {temp:.1f} °C")
    print(f"Roll: {roll:.1f}°   Pitch: {pitch:.1f}°"
          f"  (calculated from accelerometer)")
    print("==================================")
    print()


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=== MPU6050 IMU Test ===")
    print(f"I2C: Bus {I2C_BUS}, Address 0x{I2C_ADDR:02X}")
    print(f"Backend: {_BACKEND}")
    print("Press R for snapshot, Q to quit")
    print()

    imu = _IMUHandle()
    imu.init()

    kb = _KeyInput()
    try:
        while True:
            accel, gyro, temp = imu.read()
            _print_line(accel, gyro, temp)

            # Wait 100 ms (10 Hz), checking for key press
            ch = kb.getkey(timeout=0.1)
            if ch is not None:
                ch = ch.upper()
                if ch == 'R':
                    accel2, gyro2, temp2 = imu.read()
                    _print_snapshot(accel2, gyro2, temp2)
                elif ch == 'Q':
                    print("\nBye.")
                    break
                else:
                    print(f"[?] Unknown key '{ch}' — press R or Q")

    except KeyboardInterrupt:
        print("\n\nInterrupted.")
    except OSError as e:
        print(f"\n[I2C Error] {e}")
        print("Check: is I2C enabled?  sudo raspi-config → Interface Options → I2C")
    finally:
        kb.restore()
        imu.cleanup()
        print("Exit.")


if __name__ == '__main__':
    main()
