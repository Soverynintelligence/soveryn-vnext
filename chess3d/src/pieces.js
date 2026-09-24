import * as THREE from 'three';

const M = THREE.MathUtils;

function lathePoints(pts) {
  return pts.map((p) => new THREE.Vector2(Math.max(p[0], 0.0001), p[1]));
}

// Points along a circular arc centered (cx, cy), radius r. Angles in degrees, 0 = +x, 90 = up.
function arc(cx, cy, r, degStart, degEnd, n = 8) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const a = M.degToRad(degStart + ((degEnd - degStart) * i) / n);
    pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
  }
  return pts;
}

const PROFILES = {
  pawn: {
    body: [
      [0, 0], [0.30, 0], [0.30, 0.05], [0.27, 0.09], [0.22, 0.12], [0.17, 0.20],
      [0.15, 0.30], [0.16, 0.36], [0.19, 0.40], [0.16, 0.44],
      ...arc(0, 0.63, 0.17, -90, 90, 10),
    ],
  },
  rook: {
    body: [
      [0, 0], [0.32, 0], [0.32, 0.05], [0.28, 0.09], [0.24, 0.13], [0.22, 0.20],
      [0.21, 0.40], [0.22, 0.55], [0.25, 0.60], [0.30, 0.62], [0.30, 0.72],
      [0.24, 0.72], [0.24, 0.66], [0, 0.66],
    ],
  },
  bishop: {
    body: [
      [0, 0], [0.30, 0], [0.30, 0.05], [0.26, 0.09], [0.20, 0.13], [0.15, 0.22],
      [0.13, 0.34], [0.14, 0.44], [0.17, 0.50], [0.14, 0.54],
      ...arc(0, 0.82, 0.165, -75, 90, 12),
    ],
  },
  queen: {
    body: [
      [0, 0], [0.33, 0], [0.33, 0.05], [0.29, 0.09], [0.23, 0.13], [0.18, 0.22],
      [0.15, 0.36], [0.14, 0.52], [0.16, 0.66], [0.20, 0.78], [0.25, 0.86],
      [0.27, 0.90], [0.21, 0.92], [0.15, 0.94], [0.20, 1.02], [0.26, 1.08],
      [0.20, 1.10], [0.10, 1.11], [0, 1.11],
    ],
  },
  king: {
    body: [
      [0, 0], [0.34, 0], [0.34, 0.05], [0.30, 0.09], [0.24, 0.13], [0.19, 0.22],
      [0.16, 0.38], [0.15, 0.56], [0.17, 0.72], [0.21, 0.84], [0.25, 0.92],
      [0.27, 0.97], [0.21, 0.99], [0.15, 1.01], [0.18, 1.08], [0.22, 1.14],
      [0.16, 1.16], ...arc(0, 1.18, 0.14, -70, 90, 10),
    ],
  },
  knightBase: {
    body: [
      [0, 0], [0.31, 0], [0.31, 0.05], [0.27, 0.09], [0.22, 0.13],
      [0.19, 0.18], [0.21, 0.22], [0, 0.22],
    ],
  },
};

// Knight head silhouette (2D, x = forward, y = up), extruded.
const KNIGHT_SHAPE = [
  [-0.16, 0.00], [-0.20, 0.14], [-0.16, 0.30], [-0.06, 0.44], [-0.04, 0.58],
  [0.02, 0.66], [0.07, 0.54], [0.14, 0.50], [0.22, 0.42], [0.26, 0.34],
  [0.28, 0.26], [0.27, 0.18], [0.20, 0.14], [0.12, 0.12], [0.10, 0.00],
];

const geoCache = new Map();

function cached(key, build) {
  if (!geoCache.has(key)) geoCache.set(key, build());
  return geoCache.get(key);
}

function latheGeo(type) {
  return cached(`lathe:${type}`, () => {
    const g = new THREE.LatheGeometry(lathePoints(PROFILES[type].body), 40);
    g.computeVertexNormals();
    return g;
  });
}

function knightHeadGeo() {
  return cached('knightHead', () => {
    const shape = new THREE.Shape();
    shape.moveTo(KNIGHT_SHAPE[0][0], KNIGHT_SHAPE[0][1]);
    for (let i = 1; i < KNIGHT_SHAPE.length; i++) {
      shape.lineTo(KNIGHT_SHAPE[i][0], KNIGHT_SHAPE[i][1]);
    }
    shape.closePath();
    const g = new THREE.ExtrudeGeometry(shape, {
      depth: 0.16, bevelEnabled: true, bevelThickness: 0.035,
      bevelSize: 0.035, bevelSegments: 3, curveSegments: 8,
    });
    g.computeVertexNormals();
    g.center();
    return g;
  });
}

const PIECE_MATS = {
  w: new THREE.MeshStandardMaterial({ color: 0xe8e2d0, roughness: 0.35, metalness: 0.08 }),
  b: new THREE.MeshStandardMaterial({ color: 0x2c2f36, roughness: 0.42, metalness: 0.28 }),
};

function addMesh(group, geo, mat, pos = [0, 0, 0]) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(...pos);
  m.castShadow = true;
  m.receiveShadow = true;
  group.add(m);
  return m;
}

function buildKnight(group, mat) {
  addMesh(group, latheGeo('knightBase'), mat);
  const head = addMesh(group, knightHeadGeo(), mat, [0, 0.55, 0]);
  return head;
}

function buildRook(group, mat) {
  addMesh(group, latheGeo('rook'), mat);
  const turretGeo = cached('rookTurret', () => new THREE.BoxGeometry(0.15, 0.14, 0.13));
  for (let i = 0; i < 5; i++) {
    const a = (i / 5) * Math.PI * 2;
    const x = Math.cos(a) * 0.255;
    const z = Math.sin(a) * 0.255;
    const m = addMesh(group, turretGeo, mat, [x, 0.79, z]);
    m.rotation.y = -a;
  }
}

function buildBishop(group, mat) {
  addMesh(group, latheGeo('bishop'), mat);
  const finial = cached('bishopFinial', () => new THREE.SphereGeometry(0.05, 14, 10));
  addMesh(group, finial, mat, [0, 1.035, 0]);
}

function buildQueen(group, mat) {
  addMesh(group, latheGeo('queen'), mat);
  const pearl = cached('queenPearl', () => new THREE.SphereGeometry(0.038, 12, 9));
  for (let i = 0; i < 8; i++) {
    const a = (i / 8) * Math.PI * 2;
    addMesh(group, pearl, mat, [Math.cos(a) * 0.185, 1.135, Math.sin(a) * 0.185]);
  }
  const orb = cached('queenOrb', () => new THREE.SphereGeometry(0.062, 14, 11));
  addMesh(group, orb, mat, [0, 1.175, 0]);
}

function buildKing(group, mat) {
  addMesh(group, latheGeo('king'), mat);
  const vBar = cached('kingCrossV', () => new THREE.BoxGeometry(0.05, 0.13, 0.05));
  const hBar = cached('kingCrossH', () => new THREE.BoxGeometry(0.12, 0.05, 0.05));
  addMesh(group, vBar, mat, [0, 1.345, 0]);
  addMesh(group, hBar, mat, [0, 1.36, 0]);
}

const BUILDERS = {
  p: (g, m) => addMesh(g, latheGeo('pawn'), m),
  r: buildRook,
  n: buildKnight,
  b: buildBishop,
  q: buildQueen,
  k: buildKing,
};

function createPiece(type, color) {
  const group = new THREE.Group();
  const mat = PIECE_MATS[color];
  BUILDERS[type](group, mat);
  if (type === 'n') {
    group.rotation.y = color === 'w' ? Math.PI / 2 : -Math.PI / 2;
  }
  return group;
}

export { createPiece, PIECE_MATS };
