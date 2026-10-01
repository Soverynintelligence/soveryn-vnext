import * as THREE from 'three';
import { OrbitControls } from '../vendor/OrbitControls.js';
import { Chess } from '../vendor/chess.js';
import { createPiece } from './pieces.js';

// ---------- DOM ----------
const $ = (id) => document.getElementById(id);
const stage = $('stage');
const turnDot = $('turnDot');
const statusText = $('statusText');
const evalFill = $('evalFill');
const modeSel = $('modeSel');
const sideSel = $('sideSel');
const levelSel = $('levelSel');
const newBtn = $('newBtn');
const undoBtn = $('undoBtn');
const flipBtn = $('flipBtn');
const soundBtn = $('soundBtn');
const capW = $('capW');
const capB = $('capB');
const moveListEl = $('moveList');
const engineInfo = $('engineInfo');
const promoOverlay = $('promoOverlay');
const gameOverEl = $('gameOver');
const overText = $('overText');
const overNewBtn = $('overNewBtn');

// ---------- constants ----------
const FILES = 'abcdefgh';
const GLYPH = {
  w: { k: '\u2654', q: '\u2655', r: '\u2656', b: '\u2657', n: '\u2658', p: '\u2659' },
  b: { k: '\u265A', q: '\u265B', r: '\u265C', b: '\u265D', n: '\u265E', p: '\u265F' },
};
const VALUE = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };

// ---------- state ----------
let game = new Chess();
let mode = 'ai';
let playerColor = 'w';
let level = 'medium';
let selected = null;
let legalTargets = new Set();
let busy = false; // piece animation in flight
let thinking = false;
let soundOn = true;
let viewColor = 'w';
let lastMoveSquares = null;
let pendingPromo = null;
let engineToken = null;
let pendingId = null;
let reqId = 0;
let engineTurnAtReq = 'w';
let overTimer = null;

// ---------- three core ----------
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0d11);
scene.fog = new THREE.FogExp2(0x0b0d11, 0.02);

const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 0.1, 120);
camera.position.set(0, 8.6, 9.6);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
stage.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.15, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.enablePan = false;
controls.minDistance = 5;
controls.maxDistance = 20;
controls.minPolarAngle = 0.12;
controls.maxPolarAngle = 1.32;

// ---------- lights ----------
scene.add(new THREE.HemisphereLight(0xcfd8e8, 0x2a2018, 0.85));

const key = new THREE.DirectionalLight(0xfff1dc, 2.6);
key.position.set(6, 11, 5);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.left = -7;
key.shadow.camera.right = 7;
key.shadow.camera.top = 7;
key.shadow.camera.bottom = -7;
key.shadow.camera.near = 2;
key.shadow.camera.far = 26;
key.shadow.bias = -0.0004;
scene.add(key);

const fillLight = new THREE.DirectionalLight(0x8fa3c8, 0.5);
fillLight.position.set(-6, 7, -6);
scene.add(fillLight);

// ---------- board ----------
const boardRoot = new THREE.Group();
scene.add(boardRoot);

const sqGeo = new THREE.BoxGeometry(1, 0.24, 1);
const lightSqMat = new THREE.MeshStandardMaterial({ color: 0xbfa983, roughness: 0.55 });
const darkSqMat = new THREE.MeshStandardMaterial({ color: 0x5c4c3a, roughness: 0.62 });

for (let r = 0; r < 8; r++) {
  for (let f = 0; f < 8; f++) {
    const mesh = new THREE.Mesh(sqGeo, (f + r) % 2 === 0 ? darkSqMat : lightSqMat);
    mesh.position.set(f - 3.5, -0.12, 3.5 - r);
    mesh.receiveShadow = true;
    boardRoot.add(mesh);
  }
}

const slab = new THREE.Mesh(
  new THREE.BoxGeometry(9.0, 0.5, 9.0),
  new THREE.MeshStandardMaterial({ color: 0x10141b, roughness: 0.7 })
);
slab.position.y = -0.49;
slab.receiveShadow = true;
boardRoot.add(slab);

const rim = new THREE.Mesh(
  new THREE.BoxGeometry(9.06, 0.07, 9.06),
  new THREE.MeshStandardMaterial({ color: 0xe3b25c, roughness: 0.35, metalness: 0.5 })
);
rim.position.y = -0.275;
boardRoot.add(rim);

// ---------- highlights ----------
const hlRoot = new THREE.Group();
scene.add(hlRoot);

function hlBox(size, color, opacity) {
  const m = new THREE.Mesh(
    new THREE.BoxGeometry(size, 0.05, size),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false })
  );
  m.visible = false;
  m.renderOrder = 1;
  hlRoot.add(m);
  return m;
}

const selMesh = hlBox(1.04, 0xe3b25c, 0.4);
selMesh.position.y = 0.035;
const lastFromMesh = hlBox(1.0, 0xe3b25c, 0.16);
lastFromMesh.position.y = 0.028;
const lastToMesh = hlBox(1.0, 0xe3b25c, 0.16);
lastToMesh.position.y = 0.028;

const targetRoot = new THREE.Group();
scene.add(targetRoot);

const discGeo = new THREE.CylinderGeometry(0.12, 0.12, 0.035, 20);
const ringGeo = new THREE.TorusGeometry(0.37, 0.05, 10, 36);
const discMat = new THREE.MeshBasicMaterial({ color: 0xe3b25c, transparent: true, opacity: 0.85, depthWrite: false });
const ringMat = new THREE.MeshBasicMaterial({ color: 0xe05c5c, transparent: true, opacity: 0.8, depthWrite: false });

// ---------- pieces ----------
const piecesRoot = new THREE.Group();
scene.add(piecesRoot);
const pieces = new Map(); // square name -> group

function squareToVec(name) {
  return new THREE.Vector3(FILES.indexOf(name[0]) - 3.5, 0, 3.5 - (Number(name[1]) - 1));
}

function placePiece(group, name) {
  group.position.copy(squareToVec(name));
  group.userData.isPieceRoot = true;
  group.userData.square = name;
  pieces.set(name, group);
  piecesRoot.add(group);
}

function syncFromBoard() {
  for (const g of pieces.values()) piecesRoot.remove(g);
  pieces.clear();
  const board = game.board();
  for (let r = 0; r < 8; r++) {
    for (let f = 0; f < 8; f++) {
      const sq = board[r][f];
      if (!sq) continue;
      placePiece(createPiece(sq.type, sq.color), FILES[f] + (8 - r));
    }
  }
}

// ---------- tweens ----------
const tweens = new Set();

function addTween(dur, step, done) {
  const tw = { start: performance.now(), dur, step, done };
  tweens.add(tw);
  return tw;
}

function easeInOut(t) {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

function stepTweens(now) {
  for (const tw of [...tweens]) {
    const k = Math.min(1, (now - tw.start) / tw.dur);
    tw.step(easeInOut(k), k);
    if (k >= 1) {
      tweens.delete(tw);
      if (tw.done) tw.done();
    }
  }
}

function flyPiece(group, fromSq, toSq, { dur = 300, hop = 0.3, onDone } = {}) {
  const a = squareToVec(fromSq);
  const b = squareToVec(toSq);
  addTween(dur, (e) => {
    group.position.set(a.x + (b.x - a.x) * e, Math.sin(e * Math.PI) * hop, a.z + (b.z - a.z) * e);
  }, onDone);
}

function sinkPiece(group) {
  addTween(280, (e) => {
    const s = Math.max(0.001, 1 - e);
    group.scale.set(s, s, s);
    group.position.y = -0.45 * e;
  }, () => piecesRoot.remove(group));
}

// ---------- camera views ----------
function sideView(color, animate) {
  if (viewColor === color) return;
  viewColor = color;
  const pos = color === 'w' ? new THREE.Vector3(0, 8.6, 9.6) : new THREE.Vector3(0, 8.6, -9.6);
  if (!animate) {
    camera.position.copy(pos);
    return;
  }
  const from = camera.position.clone();
  addTween(650, (e) => camera.position.lerpVectors(from, pos, e));
}

// ---------- sound ----------
let actx = null;

function sound(kind) {
  if (!soundOn) return;
  try {
    actx ??= new (window.AudioContext || window.webkitAudioContext)();
  } catch {
    return;
  }
  if (actx.state === 'suspended') actx.resume();
  const t = actx.currentTime;
  const tone = (freq, at, dur, type = 'sine', vol = 0.12, slideTo = null) => {
    const o = actx.createOscillator();
    const g = actx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t + at);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + at + dur);
    g.gain.setValueAtTime(vol, t + at);
    g.gain.exponentialRampToValueAtTime(0.0008, t + at + dur);
    o.connect(g).connect(actx.destination);
    o.start(t + at);
    o.stop(t + at + dur + 0.02);
  };
  switch (kind) {
    case 'select': tone(950, 0, 0.045, 'sine', 0.04); break;
    case 'move': tone(190, 0, 0.09, 'triangle', 0.14, 120); break;
    case 'capture': tone(140, 0, 0.14, 'triangle', 0.2, 70); tone(340, 0.01, 0.05, 'square', 0.05); break;
    case 'promote': tone(420, 0, 0.09, 'sine', 0.1, 640); tone(640, 0.09, 0.12, 'sine', 0.1, 880); break;
    case 'check': tone(660, 0, 0.09, 'square', 0.055); tone(880, 0.1, 0.12, 'square', 0.055); break;
    case 'end': tone(392, 0, 0.16, 'sine', 0.1); tone(494, 0.14, 0.16, 'sine', 0.1); tone(587, 0.28, 0.3, 'sine', 0.1); break;
  }
}

// ---------- engine ----------
let worker = null;
try {
  worker = new Worker(new URL('./ai-worker.js', import.meta.url), { type: 'module' });
  worker.onmessage = onEngineMessage;
  worker.onerror = () => {
    thinking = false;
    updateStatus();
    engineInfo.textContent = 'engine error \u2014 serve over http';
  };
} catch {
  engineInfo.textContent = 'worker unavailable \u2014 serve over http';
}

function humanTurn() {
  return mode === 'human' || game.turn() === playerColor;
}

function askEngine() {
  if (!worker || game.isGameOver()) return;
  thinking = true;
  updateStatus();
  engineInfo.textContent = 'thinking\u2026';
  engineToken = {};
  engineTurnAtReq = game.turn();
  const id = ++reqId;
  pendingId = id;
  worker.postMessage({ id, fen: game.fen(), level });
}

function onEngineMessage(e) {
  const d = e.data;
  if (d.id !== pendingId || (engineToken && engineToken.cancelled)) return;
  thinking = false;
  engineToken = null;
  pendingId = null;
  if (Number.isFinite(d.score)) {
    const whiteCp = engineTurnAtReq === 'w' ? d.score : -d.score;
    setEval(whiteCp);
  }
  if (d.depth != null) {
    engineInfo.textContent = `depth ${d.depth} \u00b7 ${Number(d.nodes).toLocaleString()} nodes \u00b7 ${(d.timeMs / 1000).toFixed(1)}s`;
  }
  if (d.move) doMove(d.move);
}

function setEval(whiteCp) {
  let pct;
  if (Math.abs(whiteCp) > 90000) {
    pct = whiteCp > 0 ? 100 : 0;
  } else {
    pct = 50 + 50 * Math.tanh(whiteCp / 400);
  }
  evalFill.style.width = pct + '%';
}

// ---------- selection ----------
function clearSelection() {
  selected = null;
  legalTargets.clear();
  selMesh.visible = false;
  targetRoot.clear();
}

function selectSquare(sq) {
  selected = sq;
  const moves = game.moves({ square: sq, verbose: true });
  legalTargets = new Set(moves.map((m) => m.to));
  const v = squareToVec(sq);
  selMesh.position.set(v.x, 0.035, v.z);
  selMesh.visible = true;
  targetRoot.clear();
  const seen = new Set();
  for (const m of moves) {
    if (seen.has(m.to)) continue;
    seen.add(m.to);
    const tv = squareToVec(m.to);
    const isCap = !!m.captured || m.flags.includes('e');
    const marker = new THREE.Mesh(isCap ? ringGeo : discGeo, isCap ? ringMat : discMat);
    if (isCap) {
      marker.rotation.x = -Math.PI / 2;
      marker.position.set(tv.x, 0.06, tv.z);
    } else {
      marker.position.set(tv.x, 0.03, tv.z);
    }
    marker.renderOrder = 1;
    targetRoot.add(marker);
  }
  sound('select');
}

function handleSquareClick(sq) {
  if (!sq || busy) return;
  if (!humanTurn()) {
    clearSelection();
    return;
  }
  if (selected) {
    if (sq === selected) {
      clearSelection();
      return;
    }
    if (legalTargets.has(sq)) {
      tryMove(selected, sq);
      return;
    }
  }
  const p = game.get(sq);
  if (p && p.color === game.turn()) {
    selectSquare(sq);
  } else {
    clearSelection();
  }
}

function tryMove(from, to) {
  const cands = game.moves({ square: from, verbose: true }).filter((m) => m.to === to);
  if (!cands.length) return false;
  if (cands[0].promotion) {
    pendingPromo = { from, to };
    promoOverlay.hidden = false;
    return true;
  }
  doMove({ from, to });
  return true;
}

// ---------- moving ----------
function doMove(mv) {
  const ret = game.move(mv);
  if (!ret) return;
  pendingPromo = null;
  promoOverlay.hidden = true;
  animateMove(ret);
}

function animateMove(ret) {
  busy = true;
  clearSelection();
  const primary = pieces.get(ret.from);
  pieces.delete(ret.from);

  let capSq = null;
  if (ret.captured) {
    capSq = ret.flags.includes('e') ? ret.to[0] + ret.from[1] : ret.to;
  }
  const victim = capSq ? pieces.get(capSq) : null;
  if (victim) pieces.delete(capSq);

  pieces.set(ret.to, primary);
  if (primary) primary.userData.square = ret.to;
  if (victim) sinkPiece(victim);

  if (ret.flags.includes('k') || ret.flags.includes('q')) {
    const rank = ret.from[1];
    const rookFrom = (ret.flags.includes('k') ? 'h' : 'a') + rank;
    const rookTo = (ret.flags.includes('k') ? 'f' : 'd') + rank;
    const rook = pieces.get(rookFrom);
    if (rook) {
      pieces.delete(rookFrom);
      pieces.set(rookTo, rook);
      rook.userData.square = rookTo;
      flyPiece(rook, rookFrom, rookTo, { dur: 320, hop: 0.12 });
    }
  }

  const finish = () => {
    if (ret.promotion && primary) {
      piecesRoot.remove(primary);
      placePiece(createPiece(ret.promotion, ret.color), ret.to);
    }
    busy = false;
    postMove(ret);
  };

  if (primary) {
    const isN = ret.piece === 'n';
    flyPiece(primary, ret.from, ret.to, { dur: isN ? 400 : 300, hop: isN ? 0.85 : 0.28, onDone: finish });
  } else {
    busy = false;
    postMove(ret);
  }
}

function postMove(ret) {
  lastMoveSquares = [ret.from, ret.to];
  updateLastMove();
  updateMoveList();
  updateCaptured();
  undoBtn.disabled = game.history().length === 0;

  if (game.isGameOver()) sound('end');
  else if (game.isCheck()) sound('check');
  else if (ret.captured) sound('capture');
  else if (ret.promotion) sound('promote');
  else sound('move');

  updateStatus();

  if (game.isGameOver()) {
    overTimer = setTimeout(showGameOver, 650);
    return;
  }
  if (mode === 'ai' && game.turn() !== playerColor) askEngine();
}

// ---------- UI updates ----------
function resultText() {
  if (game.isCheckmate()) return `${game.turn() === 'w' ? 'Black' : 'White'} wins \u00b7 checkmate`;
  if (game.isStalemate()) return 'Draw \u00b7 stalemate';
  if (game.isInsufficientMaterial()) return 'Draw \u00b7 insufficient material';
  if (game.isThreefoldRepetition()) return 'Draw \u00b7 threefold repetition';
  if (game.isDrawByFiftyMoves()) return 'Draw \u00b7 fifty-move rule';
  return 'Draw';
}

function updateStatus() {
  turnDot.className = 'dot ' + game.turn();
  if (game.isGameOver()) {
    statusText.textContent = resultText();
  } else if (thinking) {
    statusText.textContent = 'Engine thinking\u2026';
  } else {
    statusText.textContent = `${game.turn() === 'w' ? 'White' : 'Black'} to move${game.isCheck() ? ' \u00b7 check' : ''}`;
  }
}

function showGameOver() {
  overTimer = null;
  overText.textContent = resultText();
  gameOverEl.hidden = false;
}

function updateLastMove() {
  if (!lastMoveSquares) {
    lastFromMesh.visible = false;
    lastToMesh.visible = false;
    return;
  }
  const a = squareToVec(lastMoveSquares[0]);
  const b = squareToVec(lastMoveSquares[1]);
  lastFromMesh.position.set(a.x, 0.028, a.z);
  lastToMesh.position.set(b.x, 0.028, b.z);
  lastFromMesh.visible = true;
  lastToMesh.visible = true;
}

function updateMoveList() {
  const h = game.history();
  let html = '';
  for (let i = 0; i < h.length; i += 2) {
    html += `<li><span class="num">${i / 2 + 1}.</span><span>${h[i]}</span><span>${h[i + 1] || ''}</span></li>`;
  }
  moveListEl.innerHTML = html;
  moveListEl.scrollTop = moveListEl.scrollHeight;
}

function updateCaptured() {
  const h = game.history({ verbose: true });
  const wTook = [];
  const bTook = [];
  for (const m of h) {
    if (m.captured) (m.color === 'w' ? wTook : bTook).push(m.captured);
  }
  const byValue = (a, b) => VALUE[b] - VALUE[a];
  wTook.sort(byValue);
  bTook.sort(byValue);
  capW.textContent = wTook.map((t) => GLYPH.b[t]).join('');
  capB.textContent = bTook.map((t) => GLYPH.w[t]).join('');
}

function updateAll() {
  updateStatus();
  updateMoveList();
  updateCaptured();
  updateLastMove();
  undoBtn.disabled = game.history().length === 0;
}

// ---------- actions ----------
function newGame() {
  if (overTimer) {
    clearTimeout(overTimer);
    overTimer = null;
  }
  if (engineToken) engineToken.cancelled = true;
  engineToken = null;
  pendingId = null;
  thinking = false;
  busy = false;
  game = new Chess();
  pendingPromo = null;
  promoOverlay.hidden = true;
  gameOverEl.hidden = true;
  clearSelection();
  lastMoveSquares = null;
  syncFromBoard();
  updateAll();
  evalFill.style.width = '50%';
  engineInfo.innerHTML = '&nbsp;';
  sideView(playerColor, true);
  if (mode === 'ai' && playerColor === 'b') askEngine();
}

function undo() {
  if (!game.history().length) return;
  if (overTimer) {
    clearTimeout(overTimer);
    overTimer = null;
  }
  if (engineToken) engineToken.cancelled = true;
  engineToken = null;
  pendingId = null;
  thinking = false;
  gameOverEl.hidden = true;
  game.undo();
  if (mode === 'ai' && game.turn() !== playerColor && game.history().length) game.undo();
  clearSelection();
  pendingPromo = null;
  promoOverlay.hidden = true;
  syncFromBoard();
  const h = game.history({ verbose: true });
  lastMoveSquares = h.length ? [h[h.length - 1].from, h[h.length - 1].to] : null;
  updateAll();
  evalFill.style.width = '50%';
  engineInfo.innerHTML = '&nbsp;';
  if (mode === 'ai' && !game.isGameOver() && game.turn() !== playerColor) askEngine();
}

// ---------- picking ----------
const raycaster = new THREE.Raycaster();
const ndc = new THREE.Vector2();
const boardPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
const planeHit = new THREE.Vector3();

function pickSquare(e) {
  const rect = renderer.domElement.getBoundingClientRect();
  ndc.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);

  const hits = raycaster.intersectObjects(piecesRoot.children, true);
  if (hits.length) {
    let o = hits[0].object;
    while (o && !(o.userData && o.userData.isPieceRoot)) o = o.parent;
    if (o && o.userData.square) return o.userData.square;
  }

  if (raycaster.ray.intersectPlane(boardPlane, planeHit)) {
    if (Math.abs(planeHit.x) <= 4.01 && Math.abs(planeHit.z) <= 4.01) {
      const f = Math.min(7, Math.max(0, Math.floor(planeHit.x + 4)));
      const rIdx = Math.min(7, Math.max(0, Math.floor(4 - planeHit.z)));
      return FILES[f] + (rIdx + 1);
    }
  }
  return null;
}

let downId = null;
let downX = 0;
let downY = 0;

renderer.domElement.addEventListener('pointerdown', (e) => {
  downId = e.pointerId;
  downX = e.clientX;
  downY = e.clientY;
});

renderer.domElement.addEventListener('pointerup', (e) => {
  if (e.pointerId !== downId) return;
  downId = null;
  if (Math.hypot(e.clientX - downX, e.clientY - downY) > 6) return; // was a drag/orbit
  handleSquareClick(pickSquare(e));
});

renderer.domElement.addEventListener('pointermove', (e) => {
  if (busy) return;
  const sq = pickSquare(e);
  let can = false;
  if (sq && humanTurn()) {
    if (selected && legalTargets.has(sq)) {
      can = true;
    } else {
      const p = game.get(sq);
      can = !!(p && p.color === game.turn());
    }
  }
  renderer.domElement.style.cursor = can ? 'pointer' : 'grab';
});

// ---------- controls wiring ----------
newBtn.addEventListener('click', newGame);
overNewBtn.addEventListener('click', newGame);
undoBtn.addEventListener('click', undo);
flipBtn.addEventListener('click', () => sideView(viewColor === 'w' ? 'b' : 'w', true));
soundBtn.addEventListener('click', () => {
  soundOn = !soundOn;
  soundBtn.textContent = soundOn ? 'Sound on' : 'Sound off';
});
modeSel.addEventListener('change', () => {
  mode = modeSel.value;
  newGame();
});
sideSel.addEventListener('change', () => {
  playerColor = sideSel.value;
  newGame();
});
levelSel.addEventListener('change', () => {
  level = levelSel.value;
});

for (const btn of promoOverlay.querySelectorAll('.promo-choices button')) {
  btn.addEventListener('click', () => {
    if (!pendingPromo) {
      promoOverlay.hidden = true;
      return;
    }
    doMove({ from: pendingPromo.from, to: pendingPromo.to, promotion: btn.dataset.p });
  });
}

promoOverlay.addEventListener('click', (e) => {
  if (e.target === promoOverlay) {
    pendingPromo = null;
    promoOverlay.hidden = true;
    clearSelection();
  }
});

addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    pendingPromo = null;
    promoOverlay.hidden = true;
    clearSelection();
  }
});

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

// ---------- boot ----------
syncFromBoard();
updateAll();
evalFill.style.width = '50%';

function loop(now) {
  requestAnimationFrame(loop);
  stepTweens(now);
  controls.update();
  renderer.render(scene, camera);
}
requestAnimationFrame(loop);
