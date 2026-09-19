#!/usr/bin/env python3
"""
IMU Web Dashboard
=================
HTTP server that streams MPU6050 data (attitude + accel + gyro + estimated
velocity) to a browser page rendering a 3D car model and multiple rolling
time-series charts.

Endpoints
---------
GET   /                : dashboard HTML
GET   /static/<name>   : frontend assets (app.js / style.css)
GET   /api/imu         : latest sample as JSON (polled by the page)
POST  /api/calibrate   : start a zero-position calibration (~3 s window)
POST  /api/reset_yaw   : zero the heading (yaw) only

Zero-position calibration
-------------------------
The car is assumed level, still and pointing forward. We capture a short
window of samples and derive:
  * gyro_bias  = mean(gyro)        -> subtracted from every later sample
                                     (this is what stops yaw from drifting)
  * accel_bias = mean(accel)-[0,0,G]
                                   -> subtracted so this pose reads exactly
                                     (0,0,G) and therefore roll/pitch = 0
  * yaw reset to 0                 -> current heading becomes "forward"
A stability guard rejects the window if the sensor is being moved.
Biases are persisted to calibration.json and reloaded on next start.

Run
---
    python3 /home/zs/imu_web/server.py
Then open  http://<rpi-ip>:8000  on the same LAN.

Reuses the IMU abstraction from /home/zs/test_imu.py, so it also falls back
to simulation mode automatically when the sensor or smbus2 is unavailable.
"""

import json
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Make /home/zs importable so we can reuse test_imu.py
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from test_imu import (            # noqa: E402  (after sys.path tweak)
    _IMUHandle,
    _calc_roll_pitch,
    G,
    _BACKEND as _BACKEND_NAME,
)

STATIC_DIR = _HERE / 'static'

# Sensor layout / physics constants
LEAK_TAU = 1.5        # seconds; leaky-integration time constant for velocity
SAMPLE_DT = 0.02      # 50 Hz

# Calibration tuning
CAL_SAMPLES = 150     # samples per window (~3 s @ 50 Hz)
CAL_GYRO_STD_MAX = 3.0    # °/s  : reject window if gyro jitters more than this
CAL_ACCEL_STD_MAX = 0.60  # m/s² : reject window if accel jitters more than this
CAL_FILE = _HERE / 'calibration.json'


# ─── Shared state ──────────────────────────────────────────────────────────────
_LOCK = threading.Lock()

# Calibration parameters (biases) + status flags
_CAL = {
    'gyro_bias':  [0.0, 0.0, 0.0],
    'accel_bias': [0.0, 0.0, 0.0],
    'calibrated': False,   # a valid calibration has been applied
    'calibrating': False,  # a capture window is in progress
    'progress': 0.0,       # 0..1 during capture
    'samples': 0,
    'start_request': False,
    'reset_yaw': False,
    'last_result': '',     # 'ok' | 'unstable' | ''
}

_LATEST = {
    't': 0.0,
    'accel': [0.0, 0.0, G],       # m/s²   body frame (calibrated, includes gravity)
    'linear': [0.0, 0.0, 0.0],    # m/s²   body frame (gravity removed)
    'gyro':   [0.0, 0.0, 0.0],    # °/s    (calibrated)
    'velocity': [0.0, 0.0, 0.0],  # m/s    body frame estimate (leaky integral)
    'roll': 0.0,                  # °
    'pitch': 0.0,                 # °
    'yaw': 0.0,                   # °     (integrated from calibrated gyro Z)
    'temp': 25.0,                 # °C
    'backend': _BACKEND_NAME,
    # calibration status surfaced to the UI
    'calibrated': False,
    'calibrating': False,
    'cal_progress': 0.0,
}


def _gravity_in_body(roll_deg, pitch_deg):
    """Gravity vector projected into the sensor body frame (m/s²)."""
    r = math.radians(roll_deg)
    p = math.radians(pitch_deg)
    gx = -G * math.sin(p)
    gy =  G * math.sin(r) * math.cos(p)
    gz =  G * math.cos(r) * math.cos(p)
    return gx, gy, gz


def _std(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))


def _load_calibration():
    """Restore persisted biases; return whether one existed."""
    if not CAL_FILE.exists():
        return False
    try:
        data = json.loads(CAL_FILE.read_text())
        with _LOCK:
            _CAL['gyro_bias']  = list(data['gyro_bias'])
            _CAL['accel_bias'] = list(data['accel_bias'])
            _CAL['calibrated'] = True
            _LATEST['calibrated'] = True
        print(f'[calib] loaded from {CAL_FILE.name}')
        return True
    except Exception as e:
        print(f'[calib] failed to load ({e})')
        return False


def _save_calibration():
    try:
        with _LOCK:
            payload = {
                'gyro_bias': _CAL['gyro_bias'],
                'accel_bias': _CAL['accel_bias'],
                'saved_at': time.time(),
            }
        CAL_FILE.write_text(json.dumps(payload, indent=2))
    except Exception as e:
        print(f'[calib] failed to save ({e})')


def _imu_loop(imu):
    """Background reader: sample ~50 Hz, apply calibration, integrate."""
    prev = time.time()
    yaw = 0.0
    vx = vy = vz = 0.0

    # Calibration capture buffers (loop-local)
    cal_accel, cal_gyro = [], []
    calibrating = not _load_calibration()   # auto-cal if nothing was saved
    if calibrating:
        with _LOCK:
            _CAL['calibrating'] = True

    while True:
        try:
            accel, gyro, temp = imu.read()
            now = time.time()
            dt = max(1e-3, min(0.2, now - prev))
            prev = now

            # ── handle on-demand start / yaw-reset requests ──
            with _LOCK:
                start_req = _CAL['start_request']
                reset_req = _CAL['reset_yaw']
            if start_req:
                cal_accel, cal_gyro = [], []
                calibrating = True
                with _LOCK:
                    _CAL['start_request'] = False
                    _CAL['calibrating'] = True
                    _CAL['progress'] = 0.0
                    _CAL['samples'] = 0
                    _CAL['last_result'] = ''
            if reset_req:
                yaw = 0.0
                with _LOCK:
                    _CAL['reset_yaw'] = False

            # ── calibration capture window ──
            if calibrating:
                cal_accel.append(accel)
                cal_gyro.append(gyro)
                n = len(cal_accel)
                with _LOCK:
                    _CAL['progress'] = min(1.0, n / CAL_SAMPLES)
                    _CAL['samples'] = n
                if n >= CAL_SAMPLES:
                    # stability guard: reject if the sensor was moved
                    gstd = max(_std([g[i] for g in cal_gyro]) for i in range(3))
                    astd = max(_std([a[i] for a in cal_accel]) for i in range(3))
                    if gstd > CAL_GYRO_STD_MAX or astd > CAL_ACCEL_STD_MAX:
                        print(f'[calib] unstable (gyroσ={gstd:.2f} '
                              f'accelσ={astd:.2f}) — retrying')
                        cal_accel, cal_gyro = [], []
                        with _LOCK:
                            _CAL['last_result'] = 'unstable'
                    else:
                        gb = [sum(g[i] for g in cal_gyro) / n for i in range(3)]
                        ab = [sum(a[i] for a in cal_accel) / n
                              - (G if i == 2 else 0.0) for i in range(3)]
                        with _LOCK:
                            _CAL['gyro_bias'] = gb
                            _CAL['accel_bias'] = ab
                            _CAL['calibrated'] = True
                            _CAL['calibrating'] = False
                            _CAL['progress'] = 1.0
                            _CAL['last_result'] = 'ok'
                            _LATEST['calibrated'] = True
                        calibrating = False
                        yaw = 0.0
                        vx = vy = vz = 0.0
                        _save_calibration()
                        print(f'[calib] done  gyro_bias='
                              f'{tuple(round(x, 3) for x in gb)}  accel_bias='
                              f'{tuple(round(x, 4) for x in ab)}')

            # ── apply calibration to this sample ──
            with _LOCK:
                ab = tuple(_CAL['accel_bias'])
                gb = tuple(_CAL['gyro_bias'])
            ax, ay, az = accel[0] - ab[0], accel[1] - ab[1], accel[2] - ab[2]
            gx, gy, gz = gyro[0] - gb[0], gyro[1] - gb[1], gyro[2] - gb[2]

            roll, pitch = _calc_roll_pitch(ax, ay, az)
            yaw += gz * dt
            while yaw > 180.0:  yaw -= 360.0
            while yaw < -180.0: yaw += 360.0

            # Gravity removal, then leaky integration for a stable velocity
            # estimate (pure integration would diverge on any bias/noise).
            bx, by, bz = _gravity_in_body(roll, pitch)
            lx, ly, lz = ax - bx, ay - by, az - bz
            leak = math.exp(-dt / LEAK_TAU)
            vx = vx * leak + lx * dt
            vy = vy * leak + ly * dt
            vz = vz * leak + lz * dt

            with _LOCK:
                _LATEST.update({
                    't': now,
                    'accel': [ax, ay, az],
                    'linear': [lx, ly, lz],
                    'gyro':   [gx, gy, gz],
                    'velocity': [vx, vy, vz],
                    'roll': roll,
                    'pitch': pitch,
                    'yaw': yaw,
                    'temp': temp,
                    'calibrated': _CAL['calibrated'],
                    'calibrating': _CAL['calibrating'],
                    'cal_progress': _CAL['progress'],
                })
            elapsed = time.time() - now
            if elapsed < SAMPLE_DT:
                time.sleep(SAMPLE_DT - elapsed)
        except Exception as e:      # keep the loop alive no matter what
            print(f'[imu_loop] error: {e}')
            time.sleep(0.5)


# ─── HTTP handler ──────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):       # silence per-request access log
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _json(self, code, obj):
        self._send(code, 'application/json', json.dumps(obj).encode('utf-8'))

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path in ('/', '/index.html'):
            f = STATIC_DIR / 'index.html'
            if f.exists():
                self._send(200, 'text/html; charset=utf-8', f.read_bytes())
            else:
                self._send(404, 'text/plain', b'index.html missing')
        elif path == '/api/imu':
            with _LOCK:
                payload = dict(_LATEST)
            self._json(200, payload)
        elif path.startswith('/static/'):
            name = path[len('/static/'):].lstrip('/')
            allowed = {'app.js', 'style.css', 'index.html'}
            if name in allowed:
                f = STATIC_DIR / name
                if f.exists():
                    if name.endswith('.js'):
                        ct = 'text/javascript; charset=utf-8'
                    elif name.endswith('.css'):
                        ct = 'text/css; charset=utf-8'
                    else:
                        ct = 'text/html; charset=utf-8'
                    self._send(200, ct, f.read_bytes())
                    return
            self._send(404, 'text/plain', b'not found')
        else:
            self._send(404, 'text/plain', b'not found')

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/calibrate':
            with _LOCK:
                _CAL['start_request'] = True
            self._json(202, {'status': 'calibrating',
                             'message': '请保持小车静止水平'})
        elif path == '/api/reset_yaw':
            with _LOCK:
                _CAL['reset_yaw'] = True
            self._json(200, {'status': 'ok'})
        else:
            self._send(404, 'text/plain', b'not found')


# ─── Entry ─────────────────────────────────────────────────────────────────────
def main():
    port = int(os.environ.get('PORT', '8000'))
    host = os.environ.get('HOST', '0.0.0.0')

    print('=== IMU Web Dashboard ===')
    print(f'Backend: {_BACKEND_NAME}')

    imu = _IMUHandle()
    imu.init()                       # may fall back to simulation automatically

    # Refresh backend tag in shared state (init may have flipped it)
    import test_imu as _t
    with _LOCK:
        _LATEST['backend'] = _t._BACKEND

    threading.Thread(target=_imu_loop, args=(imu,), daemon=True).start()

    server = ThreadingHTTPServer((host, port), _Handler)
    print(f'Serving on  http://{host}:{port}   (Ctrl+C to stop)')
    print(f'Open in browser: http://{"<rpi-ip>" if host == "0.0.0.0" else host}:{port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down.')
    finally:
        imu.cleanup()
        server.server_close()


if __name__ == '__main__':
    main()
