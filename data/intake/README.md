# Intake

Drop **md / txt / PDF** here (PDF must have a text layer — scans need OCR later).

Then:

```bash
cd ~/soveryn_vnext
python -m scripts.kb_ingest
```

Originals stay in this folder. Chunks + embeddings go to `data/kb/` (not the lattice). Eve and Aetheria pick them up on the next recall turn after vNext restart.

No video. No passwords.
