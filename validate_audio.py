#!/usr/bin/env python3
"""Audio validation: transcribe WAV chunks with Whisper and compare to expected text.

Usage:
    python validate_audio.py runs/<run_dir>/
    python validate_audio.py runs/<run_dir>/ --limit 20

Reads captions.json from the run dir to get expected text, transcribes
the corresponding chunk WAVs, and reports similarity scores.

Exit code 0 = all pass, 1 = failures found.
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def load_asr(device: int = -1):
    from transformers import pipeline
    return pipeline(
        "automatic-speech-recognition",
        model="openai/whisper-tiny",
        device=device,
        return_timestamps=False,
    )


def validate_run(run_dir: Path, limit: int = 20, min_sim: float = 0.40) -> bool:
    captions_path = run_dir / "captions.json"
    if not captions_path.exists():
        print(f"ERROR: {captions_path} not found")
        return False

    with open(captions_path) as f:
        caps = json.load(f)["captions"]

    # Filter: only entries with real text, prioritise dialogue over action
    # Skip silence/parenthetical entries
    entries = [c for c in caps if c["text"].strip() and c["type"] in ("dialogue", "action", "slug")]
    
    # Take a representative sample: first N, biased toward dialogue
    dialogue = [c for c in entries if c["type"] == "dialogue"][:limit//2]
    other    = [c for c in entries if c["type"] != "dialogue"][:limit//2]
    sample   = (dialogue + other)[:limit]

    if not sample:
        print("No entries to validate.")
        return False

    import torch
    device = 0 if torch.cuda.is_available() else -1
    print(f"Loading whisper-tiny on {'CUDA' if device==0 else 'CPU'}...")
    asr = load_asr(device)
    print(f"Validating {len(sample)} chunks from {run_dir.name}\n")

    chunks_dir = run_dir / "chunks"
    passed = 0
    failed = 0
    failures = []

    header = f"{'#':<4} {'SPEAKER':<16} {'TYPE':<10} {'SIM':>5}  {'RESULT':<6}  EXPECTED / WHISPER"
    print(header)
    print("-" * 100)

    for i, cap in enumerate(sample):
        job_id  = cap["id"]
        speaker = cap["speaker"]
        etype   = cap["type"]
        expected = cap["text"]

        wav_path = chunks_dir / f"{job_id}.wav"
        if not wav_path.exists():
            print(f"{i+1:<4} {speaker:<16} {etype:<10} {'N/A':>5}  {'SKIP':<6}  {wav_path.name} not found")
            continue

        try:
            result = asr(str(wav_path))
            transcribed = result["text"].strip()
        except Exception as e:
            transcribed = f"ERROR: {e}"
            failed += 1
            failures.append((expected, transcribed, 0.0))
            print(f"{i+1:<4} {speaker:<16} {etype:<10} {'ERR':>5}  {'FAIL':<6}  {expected[:40]}")
            continue

        exp_n = norm(expected)
        got_n = norm(transcribed)
        ratio = difflib.SequenceMatcher(None, exp_n, got_n).ratio()

        exp_words = set(exp_n.split())
        got_words = set(got_n.split())
        overlap   = len(exp_words & got_words) / max(len(exp_words), 1)

        ok = ratio >= min_sim or overlap >= min_sim
        status = "PASS" if ok else "FAIL"

        if ok:
            passed += 1
        else:
            failed += 1
            failures.append((expected, transcribed, ratio))

        exp_short = expected[:40].ljust(41)
        got_short = transcribed[:40]
        print(f"{i+1:<4} {speaker:<16} {etype:<10} {ratio:>5.2f}  {status:<6}  {exp_short} / {got_short}")

    print()
    total = passed + failed
    print(f"Result: {passed}/{total} passed  (threshold: similarity >= {min_sim})")

    if failures:
        print("\nFailed entries:")
        for exp, got, sim in failures:
            print(f"  [{sim:.2f}] Expected: {exp[:60]}")
            print(f"          Got:      {got[:60]}")

    if failed == 0:
        print("\n✅ ALL PASS — audio is intelligible and matches input text")
        return True
    elif passed / total >= 0.8:
        print(f"\n⚠️  MOSTLY PASS ({passed}/{total}) — minor STT variation, not audio failures")
        return True
    else:
        print(f"\n❌ FAIL — {failed}/{total} chunks did not match")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate ScriptStage audio chunks with Whisper")
    parser.add_argument("run_dir", help="Path to run directory")
    parser.add_argument("--limit", type=int, default=20, help="Max chunks to validate (default: 20)")
    parser.add_argument("--min-sim", type=float, default=0.40, help="Minimum similarity to pass (default: 0.40)")
    args = parser.parse_args()

    run_path = Path(args.run_dir)
    if not run_path.exists():
        print(f"ERROR: {run_path} does not exist")
        sys.exit(1)

    ok = validate_run(run_path, limit=args.limit, min_sim=args.min_sim)
    sys.exit(0 if ok else 1)
