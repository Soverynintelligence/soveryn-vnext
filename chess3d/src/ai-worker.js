import { Chess } from '../vendor/chess.js';

const PIECE_VALUE = { p: 100, n: 320, b: 330, r: 500, q: 900, k: 0 };
const MATE = 100000;

// PSTs are written rank-8-first, matching chess.js board() rows for WHITE
// ([r][f], r=0 is rank 8, f=0 is file a). Black mirrors rank via 7-r.
const PST = {
  p: [
    [0, 0, 0, 0, 0, 0, 0, 0],
    [50, 50, 50, 50, 50, 50, 50, 50],
    [10, 10, 20, 30, 30, 20, 10, 10],
    [5, 5, 10, 25, 25, 10, 5, 5],
    [0, 0, 0, 20, 20, 0, 0, 0],
    [5, -5, -10, 0, 0, -10, -5, 5],
    [5, 10, 10, -20, -20, 10, 10, 5],
    [0, 0, 0, 0, 0, 0, 0, 0],
  ],
  n: [
    [-50, -40, -30, -30, -30, -30, -40, -50],
    [-40, -20, 0, 0, 0, 0, -20, -40],
    [-30, 0, 10, 15, 15, 10, 0, -30],
    [-30, 5, 15, 20, 20, 15, 5, -30],
    [-30, 0, 15, 20, 20, 15, 0, -30],
    [-30, 5, 10, 15, 15, 10, 5, -30],
    [-40, -20, 0, 5, 5, 0, -20, -40],
    [-50, -40, -30, -30, -30, -30, -40, -50],
  ],
  b: [
    [-20, -10, -10, -10, -10, -10, -10, -20],
    [-10, 0, 0, 0, 0, 0, 0, -10],
    [-10, 0, 5, 10, 10, 5, 0, -10],
    [-10, 5, 5, 10, 10, 5, 5, -10],
    [-10, 0, 10, 10, 10, 10, 0, -10],
    [-10, 10, 10, 10, 10, 10, 10, -10],
    [-10, 5, 0, 0, 0, 0, 5, -10],
    [-20, -10, -10, -10, -10, -10, -10, -20],
  ],
  r: [
    [0, 0, 0, 0, 0, 0, 0, 0],
    [5, 10, 10, 10, 10, 10, 10, 5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [0, 0, 0, 5, 5, 0, 0, 0],
  ],
  q: [
    [-20, -10, -10, -5, -5, -10, -10, -20],
    [-10, 0, 0, 0, 0, 0, 0, -10],
    [-10, 0, 5, 5, 5, 5, 0, -10],
    [-5, 0, 5, 5, 5, 5, 0, -5],
    [0, 0, 5, 5, 5, 5, 0, -5],
    [-10, 5, 5, 5, 5, 5, 0, -10],
    [-10, 0, 5, 0, 0, 0, 0, -10],
    [-20, -10, -10, -5, -5, -10, -10, -20],
  ],
};

const KING_MID = [
  [-30, -40, -40, -50, -50, -40, -40, -30],
  [-30, -40, -40, -50, -50, -40, -40, -30],
  [-30, -40, -40, -50, -50, -40, -40, -30],
  [-30, -40, -40, -50, -50, -40, -40, -30],
  [-20, -30, -30, -40, -40, -30, -30, -20],
  [-10, -20, -20, -20, -20, -20, -20, -10],
  [20, 20, 0, 0, 0, 0, 20, 20],
  [20, 30, 10, 0, 0, 10, 30, 20],
];

const KING_END = [
  [-50, -40, -30, -20, -20, -30, -40, -50],
  [-30, -20, -10, 0, 0, -10, -20, -30],
  [-30, -10, 20, 30, 30, 20, -10, -30],
  [-30, -10, 30, 40, 40, 30, -10, -30],
  [-30, -10, 30, 40, 40, 30, -10, -30],
  [-30, -10, 20, 30, 30, 20, -10, -30],
  [-30, -30, 0, 0, 0, 0, -30, -30],
  [-50, -30, -30, -30, -30, -30, -30, -50],
];

const LEVELS = {
  easy: { depth: 2, timeMs: 400, jitter: 60 },
  medium: { depth: 3, timeMs: 1600, jitter: 12 },
  hard: { depth: 5, timeMs: 5000, jitter: 0 },
};

let nodeCount = 0;
let aborted = false;
let deadline = 0;
let jitter = 0;

function evalWhite(game) {
  const board = game.board();
  let score = 0;
  let npm = 0;
  let wBishops = 0;
  let bBishops = 0;
  const list = [];
  for (let r = 0; r < 8; r++) {
    const row = board[r];
    for (let f = 0; f < 8; f++) {
      const sq = row[f];
      if (!sq) continue;
      const v = PIECE_VALUE[sq.type];
      list.push(sq, r, f, v);
      if (sq.type !== 'k' && sq.type !== 'p') npm += v;
      if (sq.type === 'b') sq.color === 'w' ? wBishops++ : bBishops++;
    }
  }
  const w = Math.min(1, npm / 6400);
  for (let i = 0; i < list.length; i += 4) {
    const sq = list[i];
    const r = list[i + 1];
    const f = list[i + 2];
    const v = list[i + 3];
    const rr = sq.color === 'w' ? r : 7 - r;
    const sign = sq.color === 'w' ? 1 : -1;
    if (sq.type === 'k') {
      score += (KING_MID[rr][f] * w + KING_END[rr][f] * (1 - w)) * sign;
    } else {
      score += (v + PST[sq.type][rr][f]) * sign;
    }
  }
  if (wBishops >= 2) score += 30;
  if (bBishops >= 2) score -= 30;
  return score;
}

function evalSide(game) {
  const ev = evalWhite(game);
  let s = game.turn() === 'w' ? ev : -ev;
  if (jitter > 0) s += (Math.random() - 0.5) * 2 * jitter;
  return s;
}

function orderMoves(moves) {
  for (const m of moves) {
    let s = 0;
    if (m.captured) s += 10 * PIECE_VALUE[m.captured] - PIECE_VALUE[m.piece];
    if (m.promotion) s += PIECE_VALUE[m.promotion];
    if (m.san.includes('+')) s += 50;
    m._s = s;
  }
  moves.sort((a, b) => b._s - a._s);
}

function quiesce(game, alpha, beta, qd) {
  nodeCount++;
  if ((nodeCount & 2047) === 0 && Date.now() > deadline) aborted = true;
  if (aborted) return 0;
  const standPat = evalSide(game);
  if (standPat >= beta) return beta;
  if (standPat > alpha) alpha = standPat;
  if (qd <= 0) return alpha;
  const caps = game.moves({ verbose: true }).filter((m) => m.captured || m.promotion);
  orderMoves(caps);
  for (const m of caps) {
    game.move(m);
    const score = -quiesce(game, -beta, -alpha, qd - 1);
    game.undo();
    if (aborted) return 0;
    if (score >= beta) return beta;
    if (score > alpha) alpha = score;
  }
  return alpha;
}

function search(game, depth, alpha, beta, ply) {
  nodeCount++;
  if ((nodeCount & 1023) === 0 && Date.now() > deadline) aborted = true;
  if (aborted) return 0;
  if (game.isGameOver()) {
    return game.isCheckmate() ? -MATE + ply : 0;
  }
  if (depth <= 0) return quiesce(game, alpha, beta, 4);
  const moves = game.moves({ verbose: true });
  orderMoves(moves);
  let best = -Infinity;
  for (const m of moves) {
    game.move(m);
    const s = -search(game, depth - 1, -beta, -alpha, ply + 1);
    game.undo();
    if (aborted) return 0;
    if (s > best) best = s;
    if (best > alpha) alpha = best;
    if (alpha >= beta) break;
  }
  return best;
}

function findBestMove(fen, level = 'medium') {
  const cfg = LEVELS[level] || LEVELS.medium;
  const game = new Chess(fen);
  const moves = game.moves({ verbose: true });
  if (moves.length === 0) return null;
  nodeCount = 0;
  aborted = false;
  jitter = cfg.jitter;
  deadline = Date.now() + cfg.timeMs;
  orderMoves(moves);
  let best = null;
  let bestScore = -Infinity;
  let completedDepth = 0;
  for (let d = 1; d <= cfg.depth; d++) {
    let iterBest = null;
    let iterScore = -Infinity;
    let alpha = -Infinity;
    for (const m of moves) {
      game.move(m);
      const s = -search(game, d - 1, -Infinity, -alpha, 1);
      game.undo();
      if (aborted) break;
      if (s > iterScore) {
        iterScore = s;
        iterBest = m;
      }
      if (s > alpha) alpha = s;
    }
    if (aborted) break;
    best = iterBest;
    bestScore = iterScore;
    completedDepth = d;
    const idx = moves.indexOf(best);
    if (idx > 0) {
      moves.splice(idx, 1);
      moves.unshift(best);
    }
    if (bestScore > MATE - 1000) break;
  }
  if (!best) best = moves[0];
  return {
    move: { from: best.from, to: best.to, promotion: best.promotion || undefined },
    san: best.san,
    score: bestScore,
    depth: completedDepth,
    nodes: nodeCount,
  };
}

if (typeof self !== 'undefined') {
  self.onmessage = (e) => {
    const { id, fen, level } = e.data;
    const t0 = Date.now();
    const res = findBestMove(fen, level);
    self.postMessage({ id, ...res, timeMs: Date.now() - t0 });
  };
}

export { findBestMove, LEVELS };
