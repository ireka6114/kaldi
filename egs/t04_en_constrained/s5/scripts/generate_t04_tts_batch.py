#!/usr/bin/env python3

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def load_items(input_path: Path, text_col: str, utt_col: str | None) -> list[tuple[str, str]]:
    suffix = input_path.suffix.lower()
    rows: list[tuple[str, str]] = []

    if suffix in {".csv", ".tsv"}:
        delim = "," if suffix == ".csv" else "\t"
        with input_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delim)
            if text_col not in (reader.fieldnames or []):
                raise ValueError(f"missing text column '{text_col}' in {input_path}")
            if utt_col and utt_col not in (reader.fieldnames or []):
                raise ValueError(f"missing utt_id column '{utt_col}' in {input_path}")

            for i, row in enumerate(reader, start=1):
                text = (row.get(text_col) or "").strip()
                if not text:
                    continue
                utt_id = (row.get(utt_col) or "").strip() if utt_col else ""
                if not utt_id:
                    utt_id = f"utt_{i:04d}"
                rows.append((utt_id, text))
        return rows

    with input_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            rows.append((f"utt_{i:04d}", text))
    return rows


def sanitize_id(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "utt"


def require_sox() -> None:
    try:
        subprocess.run(["sox", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        raise RuntimeError("sox is required but not found") from exc


def openai_tts_to_wav_bytes(
    text: str,
    model: str,
    voice: str,
    api_key: str,
    timeout_sec: int,
) -> bytes:
    url = "https://api.openai.com/v1/audio/speech"
    payload_candidates = [
        {
            "model": model,
            "voice": voice,
            "input": text,
            "format": "wav",
        },
        {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": "wav",
        },
    ]

    last_error: Exception | None = None
    for payload in payload_candidates:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            last_error = RuntimeError(f"OpenAI HTTP {exc.code}: {body[:400]}")
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"OpenAI TTS failed: {last_error}")


def convert_to_16k_mono(src_wav: Path, dst_wav: Path, sample_rate: int) -> None:
    dst_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "sox",
            str(src_wav),
            "-r",
            str(sample_rate),
            "-c",
            "1",
            str(dst_wav),
        ],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch-generate T04 wavs using OpenAI TTS, normalized to 16k mono.")
    ap.add_argument("--input-list", required=True, help="txt/csv list file")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--text-column", default="target_word")
    ap.add_argument("--utt-id-column", default="utt_id")
    ap.add_argument("--provider", default="openai", choices=["openai"])
    ap.add_argument("--openai-model", default="gpt-4o-mini-tts")
    ap.add_argument("--openai-voice", default="alloy")
    ap.add_argument("--api-key-env", default="OPENAI_API_KEY")
    ap.add_argument("--sample-rate", type=int, default=16000)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--timeout-sec", type=int, default=60)
    ap.add_argument("--manifest-json", default="")
    args = ap.parse_args()

    require_sox()

    input_path = Path(args.input_list).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_items(input_path, args.text_column, args.utt_id_column)
    if not rows:
        raise RuntimeError(f"no items loaded from {input_path}")

    api_key = os.environ.get(args.api_key_env, "")
    if args.provider == "openai" and not api_key:
        raise RuntimeError(f"missing API key env: {args.api_key_env}")

    done = []
    for raw_utt_id, text in rows:
        utt_id = sanitize_id(raw_utt_id)
        out_wav = output_dir / f"{utt_id}.wav"
        if out_wav.exists() and not args.overwrite:
            done.append({"utt_id": utt_id, "text": text, "wav_path": str(out_wav), "status": "exists"})
            continue

        with tempfile.TemporaryDirectory() as td:
            raw_wav = Path(td) / "raw.wav"
            if args.provider == "openai":
                wav_bytes = openai_tts_to_wav_bytes(
                    text=text,
                    model=args.openai_model,
                    voice=args.openai_voice,
                    api_key=api_key,
                    timeout_sec=args.timeout_sec,
                )
                raw_wav.write_bytes(wav_bytes)
            else:
                raise RuntimeError(f"unsupported provider: {args.provider}")

            convert_to_16k_mono(raw_wav, out_wav, args.sample_rate)

        done.append({"utt_id": utt_id, "text": text, "wav_path": str(out_wav), "status": "generated"})
        print(f"generated: {utt_id} -> {out_wav}")

    if args.manifest_json:
        mpath = Path(args.manifest_json).resolve()
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps({"items": done}, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(f"wrote manifest: {mpath}")

    print(f"done: {len(done)} items, output_dir={output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
