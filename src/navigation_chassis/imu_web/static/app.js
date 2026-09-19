// IMU Web Dashboard — 3D car + multi-window rolling charts
// Zero deps besides Three.js (loaded via importmap in index.html).

import * as THREE from 'three';

// ══════════════════════════════════════════════════════════════════════════
//  Global state
// ══════════════════════════════════════════════════════════════════════════
const state = {
    latest: {
        t: 0, accel: [0, 0, 9.81], linear: [0, 0, 0],
        gyro: [0, 0, 0], velocity: [0, 0, 0],
        roll: 0, pitch: 0, yaw: 0, temp: 25,
    },
    paused: false,
    demo: false,
    yawOffset: 0,       // subtract from raw yaw so reset makes current = 0
    lastRxTime: 0,
    // Display sign multipliers learned by the pose self-test wizard. They
    // absorb the sensor's physical mounting so the on-screen car mirrors the
    // real car. Persisted to localStorage under 'imu_disp_sign'.
    sign: { roll: 1, pitch: 1, yaw: 1 },
    _raw: null,
};
try {
    const _saved = JSON.parse(localStorage.getItem('imu_disp_sign') || 'null');
    if (_saved && typeof _saved === 'object') Object.assign(state.sign, _saved);
} catch (_) { /* ignore corrupt storage */ }

// ══════════════════════════════════════════════════════════════════════════
//  Three.js scene — car model, ground, lights, camera orbit
// ══════════════════════════════════════════════════════════════════════════
const stage = document.getElementById('stage');

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0e1220);
scene.fog = new THREE.Fog(0x0e1220, 22, 70);

const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 200);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
stage.appendChild(renderer.domElement);

// ─── Lights ──────────────────────────────────────────────
scene.add(new THREE.AmbientLight(0xffffff, 0.35));
const key = new THREE.DirectionalLight(0xffffff, 0.95);
key.position.set(8, 12, 6);
key.castShadow = true;
key.shadow.mapSize.set(1024, 1024);
key.shadow.camera.left = -10; key.shadow.camera.right = 10;
key.shadow.camera.top  =  10; key.shadow.camera.bottom = -10;
scene.add(key);
const rim = new THREE.DirectionalLight(0x4a7bff, 0.4);
rim.position.set(-6, 4, -8);
scene.add(rim);

// ─── Ground + grid + axes ────────────────────────────────
const groundMat = new THREE.MeshStandardMaterial({
    color: 0x141a35, roughness: 0.95, metalness: 0.05,
});
const ground = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), groundMat);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

const grid = new THREE.GridHelper(60, 30, 0x2f6dfc, 0x1e2540);
grid.position.y = 0.005;
scene.add(grid);

// World axes helper for orientation reference
scene.add(new THREE.AxesHelper(2.5));

// ─── Car model (procedural, low-poly) ────────────────────
// Local convention:  +X = forward,  +Y = up,  +Z = right
function buildCar() {
    const group = new THREE.Group();

    const bodyMat = new THREE.MeshStandardMaterial({
        color: 0xff4f4f, metalness: 0.55, roughness: 0.4,
    });
    const darkMat = new THREE.MeshStandardMaterial({
        color: 0x222b4a, metalness: 0.7, roughness: 0.35,
    });
    const glassMat = new THREE.MeshStandardMaterial({
        color: 0x8ec5ff, metalness: 0.9, roughness: 0.15,
        transparent: true, opacity: 0.55,
    });
    const tireMat = new THREE.MeshStandardMaterial({
        color: 0x141414, roughness: 0.95,
    });
    const rimMat = new THREE.MeshStandardMaterial({
        color: 0xb0b8cc, metalness: 0.9, roughness: 0.25,
    });

    // Chassis (main body)
    const chassis = new THREE.Mesh(new THREE.BoxGeometry(4.2, 0.55, 2.1), bodyMat);
    chassis.position.y = 0.72;
    chassis.castShadow = true;
    group.add(chassis);

    // Hood slope (front wedge)
    const hood = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.28, 1.95), bodyMat);
    hood.position.set(1.35, 0.98, 0);
    hood.castShadow = true;
    group.add(hood);

    // Trunk slope (rear wedge)
    const trunk = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.28, 1.95), bodyMat);
    trunk.position.set(-1.55, 0.98, 0);
    trunk.castShadow = true;
    group.add(trunk);

    // Cabin
    const cabin = new THREE.Mesh(new THREE.BoxGeometry(1.9, 0.65, 1.85), darkMat);
    cabin.position.set(-0.15, 1.35, 0);
    cabin.castShadow = true;
    group.add(cabin);

    // Windows (glass slab on each side + top)
    const glassTop = new THREE.Mesh(new THREE.BoxGeometry(1.75, 0.02, 1.7), glassMat);
    glassTop.position.set(-0.15, 1.69, 0);
    group.add(glassTop);
    const glassFront = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.55, 1.7), glassMat);
    glassFront.position.set(0.83, 1.35, 0);
    group.add(glassFront);
    const glassBack = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.55, 1.7), glassMat);
    glassBack.position.set(-1.13, 1.35, 0);
    group.add(glassBack);

    // Head / tail lights (glow)
    const headMat = new THREE.MeshStandardMaterial({
        color: 0xfff5a3, emissive: 0xfff5a3, emissiveIntensity: 1.0,
    });
    const tailMat = new THREE.MeshStandardMaterial({
        color: 0xff2a2a, emissive: 0xff2a2a, emissiveIntensity: 0.9,
    });
    [-0.7, 0.7].forEach(z => {
        const hl = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.18, 0.4), headMat);
        hl.position.set(2.12, 0.85, z);
        group.add(hl);
        const tl = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.18, 0.4), tailMat);
        tl.position.set(-2.12, 0.85, z);
        group.add(tl);
    });

    // Wheels — 4, cylinder with visible rim
    const wheels = [];
    const wheelGeo = new THREE.CylinderGeometry(0.52, 0.52, 0.32, 28);
    const rimGeo   = new THREE.CylinderGeometry(0.30, 0.30, 0.34, 20);
    // A tiny bright "lug" bolted off-center on each wheel, so when the wheel
    // rolls you can actually see it — a plain smooth cylinder looks static.
    const lugGeo   = new THREE.BoxGeometry(0.10, 0.10, 0.36);
    const lugMat   = new THREE.MeshStandardMaterial({
        color: 0xf2f5ff, metalness: 0.6, roughness: 0.35,
    });
    const positions = [
        [ 1.35, 0.52,  1.02],
        [ 1.35, 0.52, -1.02],
        [-1.35, 0.52,  1.02],
        [-1.35, 0.52, -1.02],
    ];
    for (const [x, y, z] of positions) {
        const wGroup = new THREE.Group();
        const tire = new THREE.Mesh(wheelGeo, tireMat);
        tire.rotation.x = Math.PI / 2;   // axle along local Z (car's lateral axis)
        tire.castShadow = true;
        wGroup.add(tire);
        const wRim = new THREE.Mesh(rimGeo, rimMat);
        wRim.rotation.x = Math.PI / 2;
        wGroup.add(wRim);
        // Off-center lug (forward side of the wheel); rotates with the group.
        const lug = new THREE.Mesh(lugGeo, lugMat);
        lug.position.set(0.28, 0, 0);
        wGroup.add(lug);
        wGroup.position.set(x, y, z);
        group.add(wGroup);
        wheels.push(wGroup);
    }

    // Forward arrow (body +X) so users see heading clearly
    const arrow = new THREE.ArrowHelper(
        new THREE.Vector3(1, 0, 0),
        new THREE.Vector3(0, 2.2, 0),
        1.6, 0x44ff88, 0.4, 0.25,
    );
    group.add(arrow);

    // "Top" marker (small block on cabin roof, so flips are readable)
    const marker = new THREE.Mesh(
        new THREE.BoxGeometry(0.15, 0.05, 0.15),
        new THREE.MeshStandardMaterial({ color: 0xffd54f, emissive: 0xffd54f,
                                          emissiveIntensity: 0.6 }),
    );
    marker.position.set(-0.15, 1.72, 0.6);
    group.add(marker);

    return { group, wheels };
}

const { group: carGroup, wheels: carWheels } = buildCar();
carGroup.rotation.order = 'YXZ';
scene.add(carGroup);

// A shadow-catcher "ghost" (thin dark rectangle on the ground under the car)
// that grows when the car tilts — makes the attitude change easier to read.
const shadowPlane = new THREE.Mesh(
    new THREE.CircleGeometry(3.2, 48),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.25 }),
);
shadowPlane.rotation.x = -Math.PI / 2;
shadowPlane.position.y = 0.01;
scene.add(shadowPlane);

// ─── Minimal orbit camera (drag to rotate, wheel to zoom) ─
const orbit = {
    theta: Math.PI / 4,   // azimuth
    phi:   Math.PI / 5,   // elevation
    dist:  10,
    target: new THREE.Vector3(0, 1, 0),
};
function updateCamera() {
    const s = Math.sin(orbit.phi), c = Math.cos(orbit.phi);
    camera.position.set(
        orbit.target.x + orbit.dist * c * Math.cos(orbit.theta),
        orbit.target.y + orbit.dist * s,
        orbit.target.z + orbit.dist * c * Math.sin(orbit.theta),
    );
    camera.lookAt(orbit.target);
}
let dragging = false, lastX = 0, lastY = 0;
renderer.domElement.addEventListener('pointerdown', e => {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    renderer.domElement.setPointerCapture(e.pointerId);
});
renderer.domElement.addEventListener('pointermove', e => {
    if (!dragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    orbit.theta -= dx * 0.008;
    orbit.phi = Math.max(0.08, Math.min(1.4, orbit.phi + dy * 0.008));
});
renderer.domElement.addEventListener('pointerup',   e => {
    dragging = false;
    try { renderer.domElement.releasePointerCapture(e.pointerId); } catch (_) {}
});
renderer.domElement.addEventListener('wheel', e => {
    e.preventDefault();
    orbit.dist = Math.max(4, Math.min(40, orbit.dist * (1 + e.deltaY * 0.001)));
}, { passive: false });
updateCamera();

// ─── Resize ─────────────────────────────────────────────
function resizeRenderer() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (w === 0 || h === 0) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
}
new ResizeObserver(resizeRenderer).observe(stage);
resizeRenderer();

// ══════════════════════════════════════════════════════════════════════════
//  Rolling chart renderer (pure canvas 2D)
// ══════════════════════════════════════════════════════════════════════════
class RollingChart {
    constructor(canvasId, opts) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.window = opts.window ?? 10;     // seconds visible
        this.series = opts.series;           // [{key, label, color}, ...]
        this.title  = opts.title ?? '';
        this.unit   = opts.unit ?? '';
        this.data   = [];                    // [{t, v: {key: value}}]
        new ResizeObserver(() => this._resize()).observe(this.canvas.parentElement);
        this._resize();
    }
    _resize() {
        const dpr = window.devicePixelRatio || 1;
        const r = this.canvas.getBoundingClientRect();
        this.canvas.width  = Math.max(1, Math.floor(r.width  * dpr));
        this.canvas.height = Math.max(1, Math.floor(r.height * dpr));
        this._dpr = dpr;
        this._w = r.width;
        this._h = r.height;
    }
    clear() { this.data.length = 0; }
    push(t, values) {
        const v = {};
        for (const s of this.series) v[s.key] = values[s.key];
        this.data.push({ t, v });
        while (this.data.length && t - this.data[0].t > this.window) this.data.shift();
    }
    draw() {
        const c = this.ctx, w = this._w, h = this._h, dpr = this._dpr;
        c.setTransform(dpr, 0, 0, dpr, 0, 0);
        c.fillStyle = '#0e1220';
        c.fillRect(0, 0, w, h);

        const padL = 42, padR = 10, padT = 26, padB = 18;
        const pw = Math.max(10, w - padL - padR);
        const ph = Math.max(10, h - padT - padB);

        // Determine time window
        const tmax = this.data.length ? this.data[this.data.length - 1].t : 0;
        const tmin = tmax - this.window;

        // Y range: include 0 so it's always visible
        let ymin = 0, ymax = 0;
        for (const p of this.data) {
            if (p.t < tmin) continue;
            for (const s of this.series) {
                const v = p.v[s.key];
                if (!isFinite(v)) continue;
                if (v < ymin) ymin = v;
                if (v > ymax) ymax = v;
            }
        }
        if (ymax - ymin < 1e-6) { ymin -= 1; ymax += 1; }
        const padY = (ymax - ymin) * 0.15;
        ymin -= padY; ymax += padY;

        const X = t => padL + ((t - tmin) / this.window) * pw;
        const Y = v => padT + (1 - (v - ymin) / (ymax - ymin)) * ph;

        // Background grid
        c.strokeStyle = '#1a2244';
        c.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const yy = Math.round(padT + (i / 4) * ph) + 0.5;
            c.beginPath(); c.moveTo(padL, yy); c.lineTo(padL + pw, yy); c.stroke();
        }
        for (let i = 0; i <= 4; i++) {
            const xx = Math.round(padL + (i / 4) * pw) + 0.5;
            c.beginPath(); c.moveTo(xx, padT); c.lineTo(xx, padT + ph); c.stroke();
        }

        // Zero line
        if (ymin < 0 && ymax > 0) {
            c.strokeStyle = '#3a4a7a';
            c.setLineDash([3, 3]);
            c.beginPath();
            c.moveTo(padL, Y(0)); c.lineTo(padL + pw, Y(0));
            c.stroke();
            c.setLineDash([]);
        }

        // Y labels
        c.fillStyle = '#8fa1d8';
        c.font = '10px ui-monospace, Menlo, monospace';
        c.textAlign = 'right';
        c.textBaseline = 'middle';
        for (let i = 0; i <= 4; i++) {
            const v = ymax - (i / 4) * (ymax - ymin);
            c.fillText(v.toFixed(1), padL - 4, padT + (i / 4) * ph);
        }

        // Title (top-left)
        c.textAlign = 'left';
        c.textBaseline = 'top';
        c.fillStyle = '#c9d4ff';
        c.font = 'bold 11px sans-serif';
        c.fillText(`${this.title}  [${this.unit}]`, padL, 6);

        // Legend (top-right)
        c.font = '10px sans-serif';
        c.textBaseline = 'top';
        let lx = w - padR;
        for (let i = this.series.length - 1; i >= 0; i--) {
            const s = this.series[i];
            c.textAlign = 'right';
            c.fillStyle = '#c9d4ff';
            const tw = c.measureText(s.label).width;
            c.fillText(s.label, lx, 7);
            lx -= tw + 3;
            c.fillStyle = s.color;
            c.fillRect(lx - 10, 10, 10, 3);
            lx -= 14;
        }

        // Series lines
        c.lineWidth = 1.7;
        for (const s of this.series) {
            c.strokeStyle = s.color;
            c.beginPath();
            let started = false;
            for (const p of this.data) {
                if (p.t < tmin) continue;
                const v = p.v[s.key];
                if (!isFinite(v)) continue;
                const px = X(p.t), py = Y(v);
                if (!started) { c.moveTo(px, py); started = true; }
                else c.lineTo(px, py);
            }
            c.stroke();
        }

        // Border
        c.strokeStyle = '#2b3457';
        c.lineWidth = 1;
        c.strokeRect(padL + 0.5, padT + 0.5, pw - 1, ph - 1);
    }
}

const charts = {
    accel: new RollingChart('c-accel', {
        title: '线性加速度 Linear Accel', unit: 'm/s²', window: 10,
        series: [
            { key: 'ax', label: 'X 前', color: '#ff5f5f' },
            { key: 'ay', label: 'Y 左', color: '#4ade80' },
            { key: 'az', label: 'Z 上', color: '#60a5fa' },
        ],
    }),
    gyro: new RollingChart('c-gyro', {
        title: '角速度 Gyro', unit: '°/s', window: 10,
        series: [
            { key: 'gx', label: 'roll  rate', color: '#f97316' },
            { key: 'gy', label: 'pitch rate', color: '#a78bfa' },
            { key: 'gz', label: 'yaw   rate', color: '#22d3ee' },
        ],
    }),
    velocity: new RollingChart('c-velocity', {
        title: '速度估计 Velocity', unit: 'm/s', window: 10,
        series: [
            { key: 'vx', label: 'Vx', color: '#ff5f5f' },
            { key: 'vy', label: 'Vy', color: '#4ade80' },
            { key: 'vz', label: 'Vz', color: '#60a5fa' },
            { key: 'vabs', label: '|v|', color: '#ffd166' },
        ],
    }),
    angle: new RollingChart('c-angle', {
        title: '姿态角 Attitude', unit: '°', window: 10,
        series: [
            { key: 'roll',  label: 'Roll',  color: '#ff5f5f' },
            { key: 'pitch', label: 'Pitch', color: '#4ade80' },
            { key: 'yaw',   label: 'Yaw',   color: '#22d3ee' },
        ],
    }),
};

// ══════════════════════════════════════════════════════════════════════════
//  Data source — poll server (real IMU) or run in-browser demo synthesizer
// ══════════════════════════════════════════════════════════════════════════
async function pollIMU() {
    if (state.paused || state.demo) return;
    try {
        const r = await fetch('/api/imu', { cache: 'no-store' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const j = await r.json();
        state.latest = j;
        state.lastRxTime = performance.now();
        setStatus(true);
        setBackendTag(j.backend || '—');
    } catch (_) {
        setStatus(false);
    }
}
setInterval(pollIMU, 60);   // ~16 Hz polling is plenty for a smooth chart

// Demo-mode generator (used when no hardware / user hits "演示模式")
function demoSample(now) {
    const t = now / 1000;
    // Compose a nice choreography: tilt → 360° roll → pitch wobble → yaw spin
    const cycle = (t % 20);
    let roll, pitch, yaw, ax, ay, az, gx = 0, gy = 0, gz = 0;
    if (cycle < 4) {
        // gentle sway
        roll  = 15 * Math.sin(t * 1.4);
        pitch = 10 * Math.sin(t * 1.1);
        yaw   = 20 * Math.sin(t * 0.4);
    } else if (cycle < 8) {
        // 360° roll flip
        const k = (cycle - 4) / 4;
        roll = k * 360;
        pitch = 8 * Math.sin(k * Math.PI * 4);
        yaw = 30 * Math.sin(k * Math.PI * 2);
    } else if (cycle < 12) {
        // pitch loop
        const k = (cycle - 8) / 4;
        pitch = k * 360;
        roll = 12 * Math.sin(k * Math.PI * 3);
        yaw = 15 * Math.sin(k * Math.PI * 2 + 1);
    } else if (cycle < 16) {
        // yaw spin
        const k = (cycle - 12) / 4;
        yaw = k * 720;
        roll = 8 * Math.sin(k * Math.PI * 4);
        pitch = 6 * Math.sin(k * Math.PI * 3);
    } else {
        // shake + translation
        roll  = 5 * Math.sin(t * 20);
        pitch = 4 * Math.sin(t * 17);
        yaw   = 180 * Math.sin(t * 0.6);
    }
    // Fake accelerometers from angles (static gravity projection + a bit of
    // centripetal / translational "motion")
    const g = 9.81;
    const rr = Math.radians ? 0 : 0;   // noop
    const d2r = Math.PI / 180;
    const rp = roll * d2r, pp = pitch * d2r;
    ax = -g * Math.sin(pp) + 0.8 * Math.sin(t * 3);
    ay =  g * Math.sin(rp) * Math.cos(pp) + 0.5 * Math.sin(t * 2.4);
    az =  g * Math.cos(rp) * Math.cos(pp) + 0.4 * Math.sin(t * 1.8);
    gx = (roll  - (demoSample._lr || 0)) * 30;
    gy = (pitch - (demoSample._lp || 0)) * 30;
    gz = (yaw   - (demoSample._ly || 0)) * 30;
    demoSample._lr = roll; demoSample._lp = pitch; demoSample._ly = yaw;
    const vabs = Math.hypot(Math.sin(t * 1.2), Math.cos(t * 0.9), 0) * 3.0;
    return {
        t: Date.now() / 1000,
        accel: [ax, ay, az],
        linear: [ax - (-g * Math.sin(pp)),
                 ay - ( g * Math.sin(rp) * Math.cos(pp)),
                 az - ( g * Math.cos(rp) * Math.cos(pp))],
        gyro: [gx, gy, gz],
        velocity: [
            Math.sin(t * 1.2) * 3,
            Math.cos(t * 0.9) * 3,
            Math.sin(t * 0.7) * 1.5,
        ],
        roll, pitch, yaw,
        temp: 25 + Math.sin(t * 0.5) * 1.2,
        backend: 'demo',
        vabs,
    };
}

// ══════════════════════════════════════════════════════════════════════════
//  HUD wiring
// ══════════════════════════════════════════════════════════════════════════
const elStatus    = document.getElementById('status');
const elBackend   = document.getElementById('backend-tag');
const elCalibTag  = document.getElementById('calib-tag');
const elBtnCalib  = document.getElementById('btn-calib');
const elBtnDemo   = document.getElementById('btn-demo');
const elBtnYaw    = document.getElementById('btn-yaw');
const elBtnPause  = document.getElementById('btn-pause');
const elBtnClear  = document.getElementById('btn-clear');

function setStatus(ok) {
    elStatus.textContent = ok ? 'connected' : 'disconnected';
    elStatus.classList.toggle('off', !ok);
}
function setBackendTag(name) {
    elBackend.textContent = 'backend: ' + name;
}

// Reflect calibration state (from the polled /api/imu payload) onto the tag.
let _wasCalibrating = false;
function updateCalibTag(s) {
    if (!s) return;
    elCalibTag.classList.remove('ok', 'busy', 'warn');
    if (s.calibrating) {
        const pct = Math.round((s.cal_progress || 0) * 100);
        elCalibTag.textContent = `标定中 ${pct}%`;
        elCalibTag.classList.add('busy');
        elBtnCalib.disabled = true;
    } else {
        elBtnCalib.disabled = false;
        if (s.calibrated) {
            elCalibTag.textContent = '已标定';
            elCalibTag.classList.add('ok');
        } else {
            elCalibTag.textContent = '未标定';
        }
    }
    // When a capture window just finished, the server reset yaw to 0, so drop
    // any stale client-side heading offset to keep a single source of truth.
    if (_wasCalibrating && !s.calibrating) state.yawOffset = 0;
    _wasCalibrating = !!s.calibrating;
}

async function requestCalibrate() {
    if (state.demo) return;               // calibration is meaningless in demo
    try {
        await fetch('/api/calibrate', { method: 'POST' });
        state.yawOffset = 0;              // optimistic; server zeroes yaw too
    } catch (_) { /* pollIMU will surface the disconnect */ }
}

elBtnCalib.addEventListener('click', requestCalibrate);
elBtnDemo.addEventListener('click', () => {
    state.demo = !state.demo;
    elBtnDemo.classList.toggle('active', state.demo);
    elBtnDemo.textContent = state.demo ? '退出演示' : '演示模式';
    elBtnCalib.disabled = state.demo;
    elBtnWizard.disabled = state.demo;
    if (state.demo && wzActive) wizClose(false);
    if (state.demo) {
        setBackendTag('backend: demo');
        elCalibTag.classList.remove('ok', 'busy', 'warn');
        elCalibTag.textContent = '演示';
    }
});
elBtnYaw.addEventListener('click', () => {
    const rawYaw = (state._raw && state._raw.yaw) || 0;
    if (state.demo) { state.yawOffset = state.sign.yaw * rawYaw; return; }
    fetch('/api/reset_yaw', { method: 'POST' }).catch(() => {});
    state.yawOffset = 0;
});
elBtnPause.addEventListener('click', () => {
    state.paused = !state.paused;
    elBtnPause.classList.toggle('active', state.paused);
    elBtnPause.textContent = state.paused ? '继续' : '暂停';
});
elBtnClear.addEventListener('click', () => {
    for (const ch of Object.values(charts)) ch.clear();
});
window.addEventListener('keydown', e => {
    if (e.code === 'Space') { e.preventDefault(); elBtnDemo.click(); }
    else if (e.key === 'c' || e.key === 'C') { requestCalibrate(); }
    else if (e.key === 't' || e.key === 'T') { elBtnWizard.click(); }
});

// ══════════════════════════════════════════════════════════════════════════
//  Pose self-test wizard  (drone-style guided attitude orientation check)
//  Walks the user through known physical poses; a single "纠正" click mirrors
//  that axis so the on-screen car matches the real one. Learned signs persist.
// ══════════════════════════════════════════════════════════════════════════
const elBtnWizard = document.getElementById('btn-wizard');
const wizardEl    = document.getElementById('wizard');
const wzStep      = document.getElementById('wz-step');
const wzTitle     = document.getElementById('wz-title');
const wzDesc      = document.getElementById('wz-desc');
const wzAxis      = document.getElementById('wz-axis');
const wzVal       = document.getElementById('wz-val');
const wzFlip      = document.getElementById('wz-flip');
const wzNext      = document.getElementById('wz-next');
const wzExit      = document.getElementById('wz-exit');

const WIZ_STEPS = [
  { title: '① 保持水平静止',       desc: '把小车平放在桌面、保持不动。屏幕上的小车应当水平、不歪斜。',        axis: null,    label: '' },
  { title: '② 车头向下压（车尾翘起）', desc: '屏幕上的小车应「车头朝下」俯仰。若屏幕反而抬头，点下面「纠正」。', axis: 'pitch', label: 'Pitch 前后' },
  { title: '③ 车头上抬（车尾下压）',   desc: '屏幕小车应「车头朝上」。若相反，点「纠正」。',                 axis: 'pitch', label: 'Pitch 前后' },
  { title: '④ 向左倾斜（左侧离地）',   desc: '屏幕小车应「向左倒」，与手中实物一致。若相反，点「纠正」。',   axis: 'roll',  label: 'Roll 左右' },
  { title: '⑤ 向右倾斜（右侧离地）',   desc: '屏幕小车应「向右倒」。若相反，点「纠正」。',                   axis: 'roll',  label: 'Roll 左右' },
  { title: '⑥ 机头向右转（俯视顺时针）', desc: '屏幕小车应「向右转向」。若相反，点「纠正」。',                 axis: 'yaw',   label: 'Yaw 航向' },
];
let wzActive = false, wzIndex = 0;

function wizSaveSign() {
    try { localStorage.setItem('imu_disp_sign', JSON.stringify(state.sign)); }
    catch (_) { /* ignore */ }
}
function wizRender() {
    const st = WIZ_STEPS[wzIndex];
    wzStep.textContent = (wzIndex + 1) + ' / ' + WIZ_STEPS.length;
    wzTitle.textContent = st.title;
    wzDesc.textContent  = st.desc;
    if (st.axis) {
        wzAxis.textContent = st.label;
        wzFlip.style.display = '';
        wzFlip.textContent = '🔄 屏幕与实物反了（纠正 ' + st.label + '）';
    } else {
        wzAxis.textContent = 'Roll / Pitch';
        wzFlip.style.display = 'none';
    }
    wzNext.textContent = (wzIndex === WIZ_STEPS.length - 1) ? '完成 ✅' : '下一步 ▶';
}
function wizOpen() {
    if (state.demo) return;
    wzActive = true; wzIndex = 0;
    wizardEl.classList.remove('hidden');
    elBtnWizard.classList.add('active');
    wizRender();
}
function wizClose() {
    wzActive = false;
    wizardEl.classList.add('hidden');
    elBtnWizard.classList.remove('active');
    wizSaveSign();
}
wzFlip.addEventListener('click', () => {
    const ax = WIZ_STEPS[wzIndex].axis;
    if (!ax) return;
    state.sign[ax] *= -1;        // mirror this axis; car flips on next frame
    wizSaveSign();
});
wzNext.addEventListener('click', () => {
    if (wzIndex < WIZ_STEPS.length - 1) { wzIndex++; wizRender(); }
    else wizClose();
});
wzExit.addEventListener('click', () => wizClose());

// Live readout inside the wizard card, fed with the display sample each frame.
function wizUpdate(s) {
    if (!wzActive) return;
    const ax = WIZ_STEPS[wzIndex].axis;
    if (ax === 'roll')            wzVal.textContent = (s.roll  ?? 0).toFixed(1) + '°';
    else if (ax === 'pitch')      wzVal.textContent = (s.pitch ?? 0).toFixed(1) + '°';
    else if (ax === 'yaw')        wzVal.textContent = (s.yaw   ?? 0).toFixed(1) + '°';
    else wzVal.textContent = (s.roll ?? 0).toFixed(1) + '° / ' + (s.pitch ?? 0).toFixed(1) + '°';
}
elBtnWizard.addEventListener('click', () => { wzActive ? wizClose() : wizOpen(); });

// ══════════════════════════════════════════════════════════════════════════
//  Main loop: sample → update car → push charts → draw
// ══════════════════════════════════════════════════════════════════════════
const target = { roll: 0, pitch: 0, yaw: 0 };
let   smooth = { roll: 0, pitch: 0, yaw: 0 };

function pushCharts(s) {
    const t = (performance.now() / 1000);
    const [ax, ay, az]   = s.linear || [0, 0, 0];
    const [gx, gy, gz]   = s.gyro   || [0, 0, 0];
    const [vx, vy, vz]   = s.velocity || [0, 0, 0];
    charts.accel.push(t, { ax, ay, az });
    charts.gyro.push(t, { gx, gy, gz });
    charts.velocity.push(t, { vx, vy, vz, vabs: Math.hypot(vx, vy, vz) });
    // s is already the display sample (sign-corrected, yaw-offset applied)
    charts.angle.push(t, {
        roll:  s.roll  ?? 0,
        pitch: s.pitch ?? 0,
        yaw:   s.yaw   ?? 0,
    });
}

function normalizeAngle(a) {
    a = a % 360;
    if (a >  180) a -= 360;
    if (a < -180) a += 360;
    return a;
}

function updateHUD(s) {
    const set = (id, v) => document.getElementById(id).textContent = v;
    set('v-roll',  (s.roll  ?? 0).toFixed(1) + '°');
    set('v-pitch', (s.pitch ?? 0).toFixed(1) + '°');
    set('v-yaw',   (s.yaw ?? 0).toFixed(1) + '°');
    const [ax, ay, az] = s.accel   || [0, 0, 0];
    const [gx, gy, gz] = s.gyro    || [0, 0, 0];
    const [vx, vy, vz] = s.velocity || [0, 0, 0];
    set('v-ax', ax.toFixed(2)); set('v-ay', ay.toFixed(2)); set('v-az', az.toFixed(2));
    set('v-amag', Math.hypot(ax, ay, az).toFixed(2));
    set('v-gx', gx.toFixed(2)); set('v-gy', gy.toFixed(2)); set('v-gz', gz.toFixed(2));
    set('v-vx', vx.toFixed(2)); set('v-vy', vy.toFixed(2)); set('v-vz', vz.toFixed(2));
    set('v-vspeed', Math.hypot(vx, vy, vz).toFixed(2));
    set('v-temp', (s.temp ?? 0).toFixed(1) + ' °C');
}

let lastFrame = performance.now();
function tick() {
    requestAnimationFrame(tick);
    const now = performance.now();
    const dt = Math.min(0.1, (now - lastFrame) / 1000);
    lastFrame = now;

    const raw = state.demo ? demoSample(now) : state.latest;
    state._raw = raw;
    // Apply learned display signs + heading offset ONCE, into a single
    // "display sample" that drives the model, the HUD and the charts, so all
    // three agree with what the user sees. sign absorbs sensor-mounting flips;
    // yawOffset is the current-heading-zero from the 重置航向 button.
    const S = state.sign;
    const sample = Object.assign({}, raw, {
        roll:  S.roll  * (raw.roll  ?? 0),
        pitch: S.pitch * (raw.pitch ?? 0),
        yaw:   normalizeAngle(S.yaw * (raw.yaw ?? 0) - state.yawOffset),
    });

    // Target angles = display values. The model axis mapping below is fixed to
    // the car geometry (+X fwd, +Y up, +Z right); sensor-mounting quirks are
    // already folded into S via the pose self-test.
    target.roll  = sample.roll;
    target.pitch = sample.pitch;
    target.yaw   = sample.yaw;

    // Shortest-path angular lerp (deg)
    const k = state.demo ? 0.15 : 0.25;
    for (const key of ['roll', 'pitch', 'yaw']) {
        let d = target[key] - smooth[key];
        while (d >  180) d -= 360;
        while (d < -180) d += 360;
        smooth[key] += d * k;
    }

    // Apply attitude to the car.  Model axes: +X forward, +Y up, +Z right.
    //   roll  = tilt about the FORWARD axis  -> rotation.x
    //   pitch = tilt about the LATERAL axis  -> rotation.z
    //   yaw   = turn about the VERTICAL axis -> rotation.y
    // (order 'YXZ' keeps yaw as the primary/world rotation)
    const d2r = Math.PI / 180;
    carGroup.rotation.x =  smooth.roll  * d2r;
    carGroup.rotation.z =  smooth.pitch * d2r;
    carGroup.rotation.y = -smooth.yaw   * d2r;

    // Ground shadow follows car roll/pitch footprint (shrink when airborne-look)
    const flatness = Math.max(0.15, Math.cos(smooth.roll * d2r) * Math.cos(smooth.pitch * d2r));
    shadowPlane.scale.setScalar(0.8 + 0.4 * flatness);
    shadowPlane.material.opacity = 0.10 + 0.20 * flatness;

    // Wheels roll ONLY when the sensor is genuinely moving forward/backward.
    // Notes on the previous bug:
    //   • We were rotating around `x` — the wrong axis (that tilts the wheel
    //     forward/back instead of rolling it). The tire mesh inside each
    //     group was pre-rotated by π/2 so its cylinder axis aligns with the
    //     group's local **Z**, which is the car's lateral (axle) direction.
    //     Rolling therefore has to be `rotation.z`.
    //   • The old code accumulated `+= |v|·0.08` every frame, so any IMU
    //     noise > 0 kept spinning the wheels forever.
    // Now: use forward velocity vx with a hard deadzone (0.35 m/s) and clamp
    // per-frame delta. Stationary sensor ⇒ wheels stay perfectly still.
    const vx = (sample.velocity && sample.velocity[0]) || 0;
    if (Math.abs(vx) > 0.35) {
        const step = Math.max(-0.35, Math.min(0.35, vx * 0.09));   // rad / frame
        // Positive vx (car moving forward) should roll wheels so the top of
        // the wheel moves toward the front — that is NEGATIVE rotation about
        // the +Z (right-hand-rule around axle pointing right).
        for (const w of carWheels) w.rotation.z -= step;
    }

    pushCharts(sample);
    updateHUD(sample);
    wizUpdate(sample);
    if (!state.demo) updateCalibTag(state.latest);

    for (const ch of Object.values(charts)) ch.draw();

    updateCamera();
    renderer.render(scene, camera);
}
tick();
