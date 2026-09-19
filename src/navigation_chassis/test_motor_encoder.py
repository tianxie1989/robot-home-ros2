#!/usr/bin/env python3
"""
Motor + Encoder Hardware Test for Raspberry Pi 5
=================================================

Standalone hardware test script — NOT a ROS2 node.
Controls dual DC motors via L298N-style driver and reads quadrature encoders.

GPIO Pin Assignment (confirmed, zero-conflict):
  Left  motor: PWM=GPIO12 (Pin32), DIR=GPIO27 (Pin13)
  Right motor: PWM=GPIO13 (Pin33), DIR=GPIO23 (Pin16)
  Left  encoder: A=GPIO5 (Pin29),  B=GPIO20 (Pin38)
  Right encoder: A=GPIO6 (Pin31),  B=GPIO21 (Pin40)

Motor Truth Table:
  Forward  → PWM pin=duty, DIR pin=0
  Reverse  → PWM pin=0,    DIR pin=1  (full speed)
  Stop     → PWM pin=0,    DIR pin=0
  Brake    → PWM pin=high, DIR pin=1

Keyboard Controls (non-blocking, no Enter needed):
  W  - Forward  at 50% PWM for 2s
  S  - Reverse  at full speed for 2s
  A  - Turn left (left stop, right forward 50%) for 2s
  D  - Turn right (left forward 50%, right stop) for 2s
  P  - Pulse test: forward 1s at 50% PWM, count encoder ticks
  1  - Sweep LEFT  motor alone, PWM low→high (duty→speed mapping)
  2  - Sweep RIGHT motor alone, PWM low→high (duty→speed mapping)
  3  - Compare L vs R at identical duty (spot a reversed/dead channel)
  4  - Forward OPEN-LOOP sweep: BOTH wheels, same duty, NO PID (true straight)
  C  - Re-run the boot wiring self-check (motor<->encoder pairing + direction)
  Q  - Quit

Usage:
  python3 test_motor_encoder.py

Requirements:
  - lgpio (preferred) or gpiozero as fallback
  - Must run on Raspberry Pi 5 with direct GPIO access
  - If no GPIO library available, runs in simulation mode
"""

import sys
import time
import math
import select
import termios
import tty
import os
import threading

# ─── GPIO Pin Constants ────────────────────────────────────────────────────────
# Motor pins
L_PWM   = 12   # Left  motor PWM  (hardware PWM0)
L_DIR   = 27   # Left  motor direction
R_PWM   = 13   # Right motor PWM  (hardware PWM1)
R_DIR   = 23   # Right motor direction

# Encoder pins (pulse signal on GPIO20/21)
# ── HISTORY: 2026-09-19 the motor driven by L_PWM(GPIO12) was physically paired
# with the encoder on GPIO21 (and R_PWM/13 with GPIO20) — the motor<->encoder
# left/right pairing was CROSSED, which turned the straight-line PID into
# positive feedback (diverging to the ±trim clamp). FIXED AT THE SOURCE: the two
# encoder signal wires were physically swapped (GPIO20<->GPIO21), so the pins
# below are now the real, correct pairing. Re-run key `C` (boot self-check) any
# time to confirm the wiring stays consistent.
L_ENC   = 20   # Left  encoder pulse signal
R_ENC   = 21   # Right encoder pulse signal

# PWM parameters
PWM_FREQ  = 1000   # Hz
PWM_RANGE = 100    # duty cycle range 0–100 (percentage)
TEST_DUTY = 50     # 50% speed

# Physical constants
WHEEL_RADIUS = 0.033   # metres
TICKS_PER_REV  = 2300  # encoder ticks per wheel revolution (calibrated from test: ~2100-2500)

# ─── Backend detection ─────────────────────────────────────────────────────────
_BACKEND = 'simulation'
_lgpio   = None
_gpiozero = None


def _detect_backend():
    """Try to load lgpio → gpiozero → simulation."""
    global _BACKEND, _lgpio, _gpiozero
    try:
        import lgpio as _lg
        _lgpio = _lg
        _BACKEND = 'lgpio'
        return
    except (ImportError, OSError):
        pass
    try:
        import gpiozero as _gz
        _gpiozero = _gz
        _BACKEND = 'gpiozero'
        return
    except (ImportError, OSError):
        pass
    _BACKEND = 'simulation'


_detect_backend()

# ─── Non-blocking single-key input ─────────────────────────────────────────────

class _KeyInput:
    """Non-blocking single-keyboard reader for Linux TTY."""

    def __init__(self):
        self._fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)          # no Enter needed, echo off

    def restore(self):
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def getkey(self, timeout=0.0):
        """Return pressed character or None.  timeout=0 → poll."""
        if select.select([sys.stdin], [], [], timeout)[0]:
            return sys.stdin.read(1)
        return None


# ─── GPIO abstraction layer ────────────────────────────────────────────────────

class _GPIOHandle:
    """Unified GPIO interface over lgpio / gpiozero / simulation."""

    def __init__(self):
        self._h = None          # lgpio chip handle
        self._left_ticks  = 0
        self._right_ticks = 0
        self._poll_stop = False
        self._poll_thread = None

    # ── init / cleanup ──────────────────────────────────────────────────────

    def init(self):
        if _BACKEND == 'lgpio':
            self._init_lgpio()
        elif _BACKEND == 'gpiozero':
            self._init_gpiozero()
        else:
            print("[SIM] No GPIO hardware — running in simulation mode.")

    def _init_lgpio(self):
        self._h = _lgpio.gpiochip_open(0)
        # Motor pins → output
        for pin in (L_PWM, L_DIR, R_PWM, R_DIR):
            _lgpio.gpio_claim_output(self._h, pin, 0)
        # PWM channels
        _lgpio.tx_pwm(self._h, L_PWM, PWM_FREQ, 0)
        _lgpio.tx_pwm(self._h, R_PWM, PWM_FREQ, 0)
        # Encoder pins → input with pull-up
        _lgpio.gpio_claim_input(self._h, L_ENC, 1)  # 1=pull-up
        _lgpio.gpio_claim_input(self._h, R_ENC, 1)
        # Diagnostic: read initial GPIO levels
        l_level = _lgpio.gpio_read(self._h, L_ENC)
        r_level = _lgpio.gpio_read(self._h, R_ENC)
        print(f"[DBG] Encoder GPIO levels: Left(GPIO{L_ENC})={l_level}, Right(GPIO{R_ENC})={r_level}")
        # Start high-speed polling thread (proven to work on Pi 5, ~150kHz sampling)
        self._poll_stop = False
        self._poll_thread = threading.Thread(target=self._encoder_poller, daemon=True)
        self._poll_thread.start()
        print(f"[DBG] Encoder polling thread started (handles 1kHz+ signals)")

    def _encoder_poller(self):
        """Background thread: poll encoder GPIOs at max speed, detect rising edges.
        Proven reliable on Pi 5 at ~150kHz sampling rate (Nyquist >> 1kHz encoder)."""
        read = _lgpio.gpio_read
        h = self._h
        l_last = read(h, L_ENC)
        r_last = read(h, R_ENC)
        while not self._poll_stop:
            l_now = read(h, L_ENC)
            r_now = read(h, R_ENC)
            if l_now and not l_last:
                self._left_ticks += 1
            if r_now and not r_last:
                self._right_ticks += 1
            l_last = l_now
            r_last = r_now
            # No sleep — maximum polling speed

    def _init_gpiozero(self):
        from gpiozero import Motor, DigitalInputDevice
        self._gz_motor_l = Motor(L_PWM, L_DIR, pwm=True)
        self._gz_motor_r = Motor(R_PWM, R_DIR, pwm=True)
        self._gz_enc_la = DigitalInputDevice(L_ENC, bounce_time=None)
        self._gz_enc_ra = DigitalInputDevice(R_ENC, bounce_time=None)
        self._gz_enc_la.when_activated = lambda _: self._gz_tick('left')
        self._gz_enc_ra.when_activated = lambda _: self._gz_tick('right')

    def _gz_tick(self, side):
        if side == 'left':
            self._left_ticks += 1
        else:
            self._right_ticks += 1

    def cleanup(self):
        if _BACKEND == 'lgpio' and self._h is not None:
            try:
                self._poll_stop = True
                if self._poll_thread:
                    self._poll_thread.join(timeout=0.5)
                _lgpio.gpiochip_close(self._h)
            except Exception:
                pass
        elif _BACKEND == 'gpiozero':
            try:
                self._gz_motor_l.stop()
                self._gz_motor_r.stop()
                self._gz_enc_la.close()
                self._gz_enc_ra.close()
            except Exception:
                pass

    # ── motor primitives ────────────────────────────────────────────────────

    def _set_motor(self, pwm_pin, dir_pin, speed, direction):
        """
        speed:     0.0–1.0
        direction:  1 = forward, -1 = reverse, 0 = stop
        """
        if _BACKEND == 'lgpio':
            if direction > 0:
                _lgpio.tx_pwm(self._h, pwm_pin, PWM_FREQ, int(speed * PWM_RANGE))
                _lgpio.gpio_write(self._h, dir_pin, 0)
            elif direction < 0:
                _lgpio.tx_pwm(self._h, pwm_pin, PWM_FREQ, 0)  # stop PWM, keep freq valid
                _lgpio.gpio_write(self._h, dir_pin, 1)
            else:
                _lgpio.tx_pwm(self._h, pwm_pin, PWM_FREQ, 0)  # stop PWM, keep freq valid
                _lgpio.gpio_write(self._h, dir_pin, 0)
        elif _BACKEND == 'gpiozero':
            motor = self._gz_motor_l if pwm_pin == L_PWM else self._gz_motor_r
            if direction > 0:
                motor.forward(speed)
            elif direction < 0:
                motor.backward(1.0)   # reverse always full speed
            else:
                motor.stop()
        else:
            tag = 'L' if pwm_pin == L_PWM else 'R'
            action = {1: 'FWD', '-1': 'REV', 0: 'STOP'}[direction]
            print(f"[SIM] Motor-{tag}: {action}  speed={speed:.0%}")

    def left_fwd(self, speed):   self._set_motor(L_PWM, L_DIR, speed,  1)
    def left_rev(self):          self._set_motor(L_PWM, L_DIR, 1.0,   -1)
    def left_stop(self):         self._set_motor(L_PWM, L_DIR, 0.0,    0)
    def right_fwd(self, speed):  self._set_motor(R_PWM, R_DIR, speed,  1)
    def right_rev(self):         self._set_motor(R_PWM, R_DIR, 1.0,   -1)
    def right_stop(self):        self._set_motor(R_PWM, R_DIR, 0.0,    0)
    def all_stop(self):
        self.left_stop(); self.right_stop()

    # ── encoder access ──────────────────────────────────────────────────────

    @property
    def left_ticks(self):  return self._left_ticks
    @property
    def right_ticks(self): return self._right_ticks
    def reset_ticks(self):
        self._left_ticks = self._right_ticks = 0


# ─── Simple PID controller for closed-loop straight driving ───────────────────

class _SimplePID:
    """PI controller on the wheel-RATE error (ticks/s).

    No derivative (the rate signal is already noisy); a small integral removes
    the steady-state offset. Output is a symmetric ±out_max PWM trim.
    Open-loop testing showed L/R match within ~1% at equal duty, so gentle
    gains are all that's needed once the base is symmetric.
    """
    def __init__(self, kp=0.0005, ki=0.002, out_max=0.25):
        self.kp, self.ki, self.out_max = kp, ki, out_max
        self._integral = 0.0

    def update(self, error, dt):
        """error = right_rate - left_rate (ticks/s). dt = seconds since last call."""
        self._integral += error * dt
        # anti-windup: cap the integral so its share alone can't exceed the clamp
        max_i = (self.out_max / self.ki) if self.ki else self.out_max
        self._integral = max(-max_i, min(max_i, self._integral))
        out = self.kp * error + self.ki * self._integral
        return max(-self.out_max, min(self.out_max, out))

    def reset(self):
        self._integral = 0.0


def _forward_pid(gpio: _GPIOHandle, duration=5.0, base=0.50, trim_max=0.25):
    """Drive straight with a rate-matching PI trim around an EQUAL base.

    Open-loop testing showed the two wheels match within ~1% at identical duty,
    so the base is symmetric (not 45/55) and a single PI acts on the L/R *rate*
    difference (not accumulated position), applying an opposing ±trim to each
    wheel. This removes the old position-error integrator wind-up that saturated
    both wheels to the clamp and made the car drift worse over time.
    """
    WINDOW = 0.15           # s — rate measurement / control period (~7 Hz)
    pid = _SimplePID(out_max=trim_max)
    gpio.reset_ticks()

    lt0, rt0 = gpio.left_ticks, gpio.right_ticks
    print(f"[FWD-PID] Forward {duration}s (equal base={base*100:.0f}%, "
          f"PI on L/R rate, trim±{trim_max*100:.0f}%) ...")

    gpio.left_fwd(base)
    gpio.right_fwd(base)

    t_start = time.time()
    prev_l = prev_r = 0
    prev_t = t_start
    next_print = t_start + 0.5
    duty_l = duty_r = base

    while True:
        now = time.time()
        remaining = duration - (now - t_start)
        if remaining <= 0:
            break
        time.sleep(min(WINDOW, remaining))
        now = time.time()
        dt = now - prev_t
        if dt <= 1e-4:
            continue

        lt_now = gpio.left_ticks - lt0
        rt_now = gpio.right_ticks - rt0
        l_rate = (lt_now - prev_l) / dt
        r_rate = (rt_now - prev_r) / dt
        prev_l, prev_r, prev_t = lt_now, rt_now, now

        # error > 0 → right faster → raise left, lower right (opposing trim)
        trim = pid.update(r_rate - l_rate, dt)
        duty_l = max(0.1, min(1.0, base + trim))
        duty_r = max(0.1, min(1.0, base - trim))
        gpio.left_fwd(duty_l)
        gpio.right_fwd(duty_r)

        if now >= next_print:
            next_print += 0.5
            print(f"  [{now - t_start:.1f}s] L={lt_now} R={rt_now} "
                  f"diff={abs(lt_now - rt_now)} | rate L={l_rate:.0f} R={r_rate:.0f} "
                  f"trim={trim*100:+.1f}% | PWM: L={duty_l*100:.0f}% R={duty_r*100:.0f}%")

    gpio.all_stop()
    lt_final = gpio.left_ticks - lt0
    rt_final = gpio.right_ticks - rt0
    _print_motion_stats('FWD-PID', lt0, rt0, gpio.left_ticks, gpio.right_ticks, duration)
    diff = abs(lt_final - rt_final)
    ratio_match = min(lt_final, rt_final) / max(lt_final, 1) * 100
    print(f"  [RESULT] Tick difference: {diff}  (match ratio: {ratio_match:.1f}%)")
    if diff < 50:
        print(f"  [RESULT] Straight line achieved!")
    else:
        print(f"  [RESULT] Still drifting — mechanical friction asymmetry too large.")
    print("[FWD-PID] Stopped.")


# ─── Encoder stats helper ─────────────────────────────────────────────────────

def _print_motion_stats(label, lt_before, rt_before, lt_after, rt_after, duration):
    """Print encoder pulse count, frequency and estimated speed after a motion."""
    lt_delta = lt_after - lt_before
    rt_delta = rt_after - rt_before
    lt_freq = abs(lt_delta) / duration   # ticks per second
    rt_freq = abs(rt_delta) / duration
    # distance = ticks * (2*pi*R) / ticks_per_rev
    lt_dist = abs(lt_delta) * WHEEL_RADIUS * 2 * 3.14159 / TICKS_PER_REV
    rt_dist = abs(rt_delta) * WHEEL_RADIUS * 2 * 3.14159 / TICKS_PER_REV
    lt_speed = lt_dist / duration
    rt_speed = rt_dist / duration
    print(f"  [{label}] Encoder stats ({duration:.1f}s):")
    print(f"    Left  ticks: {lt_delta:+d}  ({lt_freq:.1f} Hz)  ~{lt_speed:.3f} m/s  ({lt_dist*100:.1f} cm)")
    print(f"    Right ticks: {rt_delta:+d}  ({rt_freq:.1f} Hz)  ~{rt_speed:.3f} m/s  ({rt_dist*100:.1f} cm)")
    print(f"    * Distance assumes {TICKS_PER_REV} ticks/rev (calibrated)")


# ─── Pulse test ────────────────────────────────────────────────────────────────

def _run_pulse_test(gpio: _GPIOHandle):
    gpio.reset_ticks()
    print("\n[Pulse Test] Moving forward 1 second...")
    gpio.left_fwd(TEST_DUTY / PWM_RANGE)
    gpio.right_fwd(TEST_DUTY / PWM_RANGE)
    time.sleep(1.0)
    gpio.all_stop()

    lt = gpio.left_ticks
    rt = gpio.right_ticks
    dist_l = abs(lt) * WHEEL_RADIUS   # placeholder: assumes 1 tick = radius (rad)
    dist_r = abs(rt) * WHEEL_RADIUS
    avg_dist = (dist_l + dist_r) / 2.0
    tpr = max(abs(lt), abs(rt)) or 1  # ticks per revolution estimate

    print(f"[Pulse Test] Left  encoder: {lt} ticks")
    print(f"[Pulse Test] Right encoder: {rt} ticks")
    print(f"[Pulse Test] Distance per wheel: {avg_dist:.3f} m  (wheel radius={WHEEL_RADIUS} m)")
    print(f"[Pulse Test] Estimated ticks/revolution: {tpr}")
    print()


# ─── Single-side duty sweep / L-vs-R comparison ────────────────────────────────
# Purpose: verify the PWM-duty → wheel-speed mapping for EACH motor on its own,
# and compare both sides at identical duty. This exposes a channel whose speed
# does NOT rise with duty (inverted / saturated / dead) — e.g. a right motor
# that stays slow even at high PWM.
# SAFETY: lift the drive wheels off the ground — each side runs ALONE, so the
# car will spin/turn in place if it is on the floor.

SWEEP_DUTIES = (20, 30, 40, 50, 60, 70, 80, 90, 100)   # % — low → high


def _measure_side(gpio: _GPIOHandle, side, duty, dwell=1.0, settle=0.3):
    """Run one side forward at `duty` (0.0–1.0); return (ticks, Hz, cm/s).

    The first `settle` seconds are discarded so we measure steady-state speed,
    not the start-up ramp. The other side stays stopped.
    """
    gpio.all_stop()
    gpio.reset_ticks()
    if side == 'left':
        gpio.left_fwd(duty)
    else:
        gpio.right_fwd(duty)
    time.sleep(settle)
    gpio.reset_ticks()                     # zero after transient
    t0 = time.perf_counter()
    time.sleep(dwell)
    dt = (time.perf_counter() - t0) or 1e-6
    gpio.all_stop()
    ticks = gpio.left_ticks if side == 'left' else gpio.right_ticks
    hz = abs(ticks) / dt
    cm_s = hz / TICKS_PER_REV * 2 * math.pi * WHEEL_RADIUS * 100.0
    return ticks, hz, cm_s


def _sweep_verdict(label, rows):
    """Interpret a (duty%, Hz) ramp: monotonic? reversed? dead?"""
    hzs = [r[1] for r in rows]
    if len(hzs) < 2:
        return
    rise = hzs[-1] - hzs[0]
    nonmono = [rows[i][0] for i in range(1, len(hzs))
               if hzs[i] < hzs[i - 1] - max(2.0, 0.10 * hzs[i - 1])]
    print(f"  [{label}] {rows[0][0]}%→{rows[-1][0]}%  Hz {hzs[0]:.0f}→{hzs[-1]:.0f} "
          f"(Δ{rise:+.0f})")
    if rise <= 0:
        print(f"  [{label}] ⚠ REVERSED / DEAD — higher duty does NOT increase speed. "
              f"Check {label} PWM/DIR wiring or inverted duty mapping.")
    elif nonmono:
        print(f"  [{label}] ⚠ non-monotonic at {nonmono}% — unstable drive or "
              f"missed encoder edges (polling saturation?).")
    else:
        print(f"  [{label}] ✓ monotonic — duty→speed mapping looks normal.")


def _run_duty_sweep(gpio: _GPIOHandle, side, duties=SWEEP_DUTIES,
                    dwell=1.0, settle=0.3):
    """Sweep a single motor's PWM low→high and log its encoder speed."""
    label = side.upper()
    print(f"\n[Sweep:{label}] single-side PWM sweep low→high "
          f"(the other wheel is stopped — lift wheels off ground!)")
    if _BACKEND == 'simulation':
        print("  [SIM] no encoder hardware — run this on the Pi for real numbers.")
    print("  duty%   ticks      Hz    ~cm/s")
    print("  " + "-" * 40)
    rows = []
    for d in duties:
        ticks, hz, cm_s = _measure_side(gpio, side, d / 100.0, dwell, settle)
        print(f"  {d:3d}%   {ticks:6d}  {hz:7.1f}  {cm_s:6.1f}")
        rows.append((d, hz))
        time.sleep(0.15)
    _sweep_verdict(label, rows)
    gpio.all_stop()


def _run_duty_compare(gpio: _GPIOHandle, duties=SWEEP_DUTIES,
                      dwell=1.0, settle=0.3):
    """Run L and R separately at each identical duty and compare their speed.

    If the right wheel is slower at EVERY duty (ratio L/R > 1 throughout), the
    right side needs a much larger base — i.e. mechanical loss or a weak/dead
    PWM channel, NOT a PID issue. If R sometimes beats L and sometimes loses,
    suspect wiring / signal integrity on the right channel.
    """
    print("\n[Compare] Left vs Right at identical duty (each side runs alone)")
    if _BACKEND == 'simulation':
        print("  [SIM] no encoder hardware — run this on the Pi for real numbers.")
    print("  duty%    L_Hz    R_Hz   L/R    Lcm/s  Rcm/s")
    print("  " + "-" * 50)
    lfast = rfast = 0
    for d in duties:
        _, lhz, lcm = _measure_side(gpio, 'left',  d / 100.0, dwell, settle)
        _, rhz, rcm = _measure_side(gpio, 'right', d / 100.0, dwell, settle)
        if lhz > rhz:
            lfast += 1
        elif rhz > lhz:
            rfast += 1
        ratio = (lhz / rhz) if rhz > 0 else float('inf')
        rs = f"{ratio:4.2f}" if rhz > 0 else "  inf"
        print(f"  {d:3d}%   {lhz:6.1f}  {rhz:6.1f}  {rs}   {lcm:5.1f}  {rcm:5.1f}")
        time.sleep(0.15)
    n = len(duties)
    print(f"  [Compare] Left faster at {lfast}/{n} steps, "
          f"Right faster at {rfast}/{n} steps.")
    if rfast == 0 and lfast == n:
        print("  [Compare] ⚠ Right is slower at EVERY duty → the R channel is NOT "
              "inverted (it still responds), it is just weak: check R drive "
              "strength / friction / supply, or R duty→speed curve.")
    elif lfast == 0 and rfast == n:
        print("  [Compare] ⚠ Left is slower at EVERY duty → investigate L channel.")
    else:
        print("  [Compare] ✓ No fixed side wins → speed mapping is broadly "
              "consistent; drift is from PID base/clamp tuning, not wiring.")
    gpio.all_stop()


def _run_forward_openloop(gpio: _GPIOHandle, duties=(30, 40, 50, 60, 70, 80, 90, 100),
                          dwell=1.0, settle=0.3):
    """Drive BOTH wheels forward at the SAME fixed duty, NO PID, and compare
    their tick rates.

    Unlike the single-side sweep (which pivots the car and adds large, asymmetric
    scrub friction), this reproduces real straight-line rolling, so the L/R Hz
    ratio here is the true open-loop mismatch that the forward PID has to fight.
    Use it to pick DUTY_L_BASE / DUTY_R_BASE and a sane PID clamp.
    """
    print("\n[FWD-Open] Both wheels FORWARD at identical duty, NO PID")
    print("  (rolls straight — keep a clear path or support the chassis)")
    if _BACKEND == 'simulation':
        print("  [SIM] no encoder hardware — run this on the Pi for real numbers.")
    print("  duty%    L_Hz    R_Hz   L/R    Lcm/s  Rcm/s")
    print("  " + "-" * 50)
    rows = []
    for d in duties:
        gpio.all_stop()
        gpio.reset_ticks()
        gpio.left_fwd(d / 100.0)
        gpio.right_fwd(d / 100.0)
        time.sleep(settle)
        gpio.reset_ticks()                     # zero after start-up transient
        t0 = time.perf_counter()
        time.sleep(dwell)
        dt = (time.perf_counter() - t0) or 1e-6
        gpio.all_stop()
        lt = gpio.left_ticks
        rt = gpio.right_ticks
        lhz = abs(lt) / dt
        rhz = abs(rt) / dt
        lcm = lhz / TICKS_PER_REV * 2 * math.pi * WHEEL_RADIUS * 100.0
        rcm = rhz / TICKS_PER_REV * 2 * math.pi * WHEEL_RADIUS * 100.0
        ratio = (lhz / rhz) if rhz > 0 else float('inf')
        rs = f"{ratio:4.2f}" if rhz > 0 else "  inf"
        print(f"  {d:3d}%   {lhz:6.1f}  {rhz:6.1f}  {rs}   {lcm:5.1f}  {rcm:5.1f}")
        rows.append((d, lhz, rhz))
        time.sleep(0.15)
    valid = [(d, l, r) for (d, l, r) in rows if l > 0 and r > 0]
    if valid:
        avg = sum(l / r for _, l, r in valid) / len(valid)
        faster = 'RIGHT' if avg < 1 else ('LEFT' if avg > 1 else 'neither')
        print(f"  [FWD-Open] mean L/R ratio = {avg:.2f} → {faster} runs "
              f"faster at equal duty (straight, open-loop).")
        if avg > 1.05:
            print("     → R is the slower wheel: RAISE DUTY_R_BASE and/or widen "
                  "the PID clamp so it can compensate.")
        elif avg < 0.95:
            print("     → L is the slower wheel: RAISE DUTY_L_BASE and/or widen "
                  "the PID clamp.")
        else:
            print("     ✓ wheels are well matched open-loop → the forward drift is "
                  "from PID base/clamp tuning, not the motors themselves.")
    else:
        print("  [FWD-Open] not enough valid data (check encoder wiring / dead-zone).")
    gpio.all_stop()


# ─── Boot wiring self-check (motor<->encoder pairing + spin direction) ────────

def _measure_signed_window(gpio: _GPIOHandle, duty_l, duty_r, dur=0.8, settle=0.25):
    """Both wheels forward at the given duties; return SIGNED (lt, rt, lrate, rrate)."""
    gpio.all_stop()
    gpio.reset_ticks()
    gpio.left_fwd(duty_l)
    gpio.right_fwd(duty_r)
    time.sleep(settle)
    gpio.reset_ticks()
    t0 = time.perf_counter()
    time.sleep(dur)
    dt = (time.perf_counter() - t0) or 1e-6
    gpio.all_stop()
    lt = gpio.left_ticks
    rt = gpio.right_ticks
    return lt, rt, lt / dt, rt / dt


def _pairing_selfcheck(gpio: _GPIOHandle, verbose=True):
    """One-shot wiring self-check (like a drone pre-flight).

    Phase 1 · direction : equal duty straight — both encoders must count the SAME
      sign; opposite signs mean one wheel or encoder is reversed.
    Phase 2 · pairing   : asymmetric duty — whichever PWM channel is pushed HIGH,
      the encoder on the SAME name must speed up. If the OPPOSITE encoder speeds
      up, the motor<->encoder left/right pairing is CROSSED. A crossed pairing
      turns any closed-loop speed controller into POSITIVE FEEDBACK (it lowers a
      side's PWM yet that side's encoder accelerates) and the car drifts worse
      over time instead of correcting.

    Returns a dict; prints a human verdict unless verbose=False.
    """
    result = {'backend': _BACKEND, 'skipped': _BACKEND == 'simulation',
              'direction_ok': True, 'verdict': 'n/a',
              'crossed': False, 'ambiguous': False}
    if _BACKEND == 'simulation':
        if verbose:
            print("[SelfCheck] simulation mode — wiring self-check skipped.")
        return result

    if verbose:
        print("\n[SelfCheck] Motor<->encoder wiring self-check — keep the WHEELS "
              "CLEAR, the car will creep/turn for a few seconds ...")

    # Phase 1 — spin direction (equal duty, straight)
    lt, rt, lr, rr = _measure_signed_window(gpio, 0.60, 0.60)
    same_dir = (lt >= 0) == (rt >= 0)
    result['direction_ok'] = same_dir
    if verbose:
        mark = 'same sign \u2713' if same_dir else \
            'OPPOSITE SIGN \u26a0 one wheel/encoder reversed'
        print(f"  [dir]  L={lt:+d} ({lr:+.0f} Hz)   R={rt:+d} ({rr:+.0f} Hz)   \u2192 {mark}")
    time.sleep(0.4)

    # Phase 2 — pairing (asymmetric duty)
    _, _, aL, aR = _measure_signed_window(gpio, 0.85, 0.35)
    time.sleep(0.4)
    _, _, bL, bR = _measure_signed_window(gpio, 0.35, 0.85)
    a_tracks = aL > aR          # left PWM high  -> left encoder should win
    b_tracks = bR > bL          # right PWM high -> right encoder should win
    if a_tracks and b_tracks:
        verdict = 'correct'
    elif (not a_tracks) and (not b_tracks):
        verdict = 'crossed'
    else:
        verdict = 'ambiguous'
    result['verdict'] = verdict
    result['crossed'] = (verdict == 'crossed')
    result['ambiguous'] = (verdict == 'ambiguous')
    if verbose:
        print(f"  [pair] L_pwm=85% \u2192 L={aL:+.0f} R={aR:+.0f} Hz   "
              f"L_pwm=35% \u2192 L={bL:+.0f} R={bR:+.0f} Hz")
        if verdict == 'crossed':
            print("  [pair] \u26a0 CROSSED — left_fwd drives the wheel read by "
                  "right_ticks (and vice-versa). Straight-line PID will diverge. "
                  "Fix: swap the two encoder wires (or the two motor wires), or "
                  "exchange L_ENC/R_ENC in software.")
        elif verdict == 'ambiguous':
            print("  [pair] ~ AMBIGUOUS — the two phases disagree; check supply / "
                  "that the wheels roll freely, then re-run with key C.")
        else:
            print("  [pair] \u2713 CORRECT — each side's actuation matches its own encoder.")
    gpio.all_stop()
    ok = result['direction_ok'] and verdict == 'correct'
    if verbose:
        print(f"  [SelfCheck] {'PASS \u2713 — wiring OK' if ok else 'REVIEW — see flags above'}")
    return result


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("========================================")
    print("  Motor + Encoder Test (Raspberry Pi 5)")
    print("========================================")
    print(f"GPIO:   Left PWM={L_PWM}, Left DIR={L_DIR}, "
          f"Right PWM={R_PWM}, Right DIR={R_DIR}")
    print(f"Encoder: Left={L_ENC} (GPIO{L_ENC}), Right={R_ENC} (GPIO{R_ENC})")
    print(f"PWM:    {PWM_FREQ} Hz, Range {PWM_RANGE}, Test Speed {TEST_DUTY}%")
    print(f"Backend: {_BACKEND}")
    print()
    print("Controls:")
    print("  W - Forward 2s (PID closed-loop, equalize ticks)")
    print("  S - Backward (2 s)     A - Turn Left (2 s)")
    print("  D - Turn Right (2 s)   P - Pulse Test (1 s)")
    print("  1 - Sweep LEFT duty    2 - Sweep RIGHT duty (low→high, alone)")
    print("  3 - Compare L vs R at same duty  (lift wheels off ground!)")
    print("  4 - Forward OPEN-LOOP: both wheels, same duty, no PID (straight)")
    print("  C - Re-run wiring self-check (pairing+direction)  I - GPIO levels")
    print("  Q - Quit")
    print()

    gpio = _GPIOHandle()
    gpio.init()

    # ── Boot wiring self-check: confirm motor<->encoder pairing + spin direction.
    #    Auto-skips in simulation mode. Suppress with `--no-selfcheck`.
    if '--no-selfcheck' in sys.argv:
        print("[SelfCheck] skipped (--no-selfcheck).")
    else:
        _pairing_selfcheck(gpio)
        print()

    kb = _KeyInput()
    try:
        while True:
            print(
                f"Left ticks: {gpio.left_ticks:<6}  Right ticks: {gpio.right_ticks:<6}",
                end='', flush=True
            )
            ch = kb.getkey(timeout=0.5)

            # erase status line
            sys.stdout.write('\r' + ' ' * 60 + '\r')
            sys.stdout.flush()

            if ch is None:
                continue

            ch = ch.upper()

            if ch == 'W':
                _forward_pid(gpio, duration=5.0)

            elif ch == 'S':
                print("[REV] Reverse at full speed for 2 s ...")
                lt0, rt0 = gpio.left_ticks, gpio.right_ticks
                gpio.left_rev()
                gpio.right_rev()
                time.sleep(2.0)
                gpio.all_stop()
                _print_motion_stats('REV', lt0, rt0, gpio.left_ticks, gpio.right_ticks, 2.0)
                print("[REV] Stopped.")

            elif ch == 'A':
                print("[LEFT] Turn left for 2 s (right stop, left fwd 50%) ...")
                lt0, rt0 = gpio.left_ticks, gpio.right_ticks
                gpio.right_stop()
                gpio.left_fwd(TEST_DUTY / PWM_RANGE)
                time.sleep(2.0)
                gpio.all_stop()
                _print_motion_stats('LEFT', lt0, rt0, gpio.left_ticks, gpio.right_ticks, 2.0)
                print("[LEFT] Stopped.")

            elif ch == 'D':
                print("[RIGHT] Turn right for 2 s (left stop, right fwd 50%) ...")
                lt0, rt0 = gpio.left_ticks, gpio.right_ticks
                gpio.left_stop()
                gpio.right_fwd(TEST_DUTY / PWM_RANGE)
                time.sleep(2.0)
                gpio.all_stop()
                _print_motion_stats('RIGHT', lt0, rt0, gpio.left_ticks, gpio.right_ticks, 2.0)
                print("[RIGHT] Stopped.")

            elif ch == 'P':
                _run_pulse_test(gpio)

            elif ch == '1':
                _run_duty_sweep(gpio, 'left')

            elif ch == '2':
                _run_duty_sweep(gpio, 'right')

            elif ch == '3':
                _run_duty_compare(gpio)

            elif ch == '4':
                _run_forward_openloop(gpio)

            elif ch == 'C':
                _pairing_selfcheck(gpio)

            elif ch == 'I':
                if _BACKEND == 'lgpio' and gpio._h is not None:
                    for pin, name in [(L_ENC, f'LeftEnc(GPIO{L_ENC})'),
                                      (R_ENC, f'RightEnc(GPIO{R_ENC})'),
                                      (L_PWM, f'LeftPWM(GPIO{L_PWM})'),
                                      (R_PWM, f'RightPWM(GPIO{R_PWM})')]:
                        level = _lgpio.gpio_read(gpio._h, pin)
                        print(f"  [DBG] {name} = {level}")
                else:
                    print("  [DBG] GPIO not available")

            elif ch == 'Q':
                print("Bye.")
                break

            else:
                print(f"[?] Unknown key '{ch}' — press W/S/A/D/P/1/2/3/4/C/Q")

    except KeyboardInterrupt:
        print("\n\nInterrupted.")
    finally:
        kb.restore()
        gpio.all_stop()
        gpio.cleanup()
        print("GPIO cleaned up. Exit.")


if __name__ == '__main__':
    main()
