# Chess 3D

Browser chess with a 3D board (three.js), a minimax engine with alpha-beta + quiescence
running in a Web Worker (chess.js rules), promotion picker, undo, eval bar, sounds.

## Run

Module worker + import maps need HTTP, not `file://`:

```sh
cd chess3d
python3 -m http.server 8020
# open http://localhost:8020
```

## Layout

- `index.html` — markup, import map (`three` -> `vendor/three.module.js`)
- `src/main.js` — scene, board, input, move animation, UI, engine wiring
- `src/pieces.js` — lathe/extrude piece geometry builders
- `src/ai-worker.js` — search (iterative deepening, MVV-LVA ordering, PST eval)
- `vendor/` — three.js r160, OrbitControls, chess.js v1 (ESM, no build step)
