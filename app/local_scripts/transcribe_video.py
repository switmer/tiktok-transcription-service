#!/usr/bin/env python3
"""Simple CLI: any video/audio file → transcript.txt

Usage
-----
python transcribe_video.py /path/to/video.mp4 --model small --language en

Dependencies
------------
1. FFmpeg (for audio extraction) – `brew install ffmpeg` on macOS.
2. openai-whisper – `pip install -U openai-whisper`

The script loads the requested Whisper model locally (no OpenAI API key needed),
transcribes the media file, and writes `<basename>_transcript.txt` next to it.
"""

import argparse
import os
import sys
from pathlib import Path
import shutil
import tempfile
import subprocess

try:
    import whisper  # type: ignore
except ImportError:
    whisper = None  # Optional when faster-whisper is available

try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception:
    WhisperModel = None  # Optional


def ensure_ffmpeg() -> None:
    """Exit early if ffmpeg is not available."""
    if shutil.which("ffmpeg") is None:
        print("[!] ffmpeg not found on PATH. Install it and try again.")
        sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe any video/audio file to text using Whisper")
    parser.add_argument("input", help="Path to the video or audio file")
    parser.add_argument("--model", default="small", help="Whisper model size (tiny|base|small|medium|large)")
    parser.add_argument("--language", default=None, help="ISO language code (e.g. 'en'). Auto-detect if omitted")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Device to run the model on")
    # Output format toggles
    parser.add_argument("--txt", action="store_true", help="Write plain-text transcript (default)")
    parser.add_argument("--srt", action="store_true", help="Write .srt subtitles")
    parser.add_argument("--vtt", action="store_true", help="Write .vtt subtitles")
    parser.set_defaults(txt=True)
    return parser.parse_args()


# ------------------------- helpers -------------------------

def progress(p: float) -> None:
    """Emit a progress line for GUI wrappers (0-1)."""
    p = max(0.0, min(1.0, p))
    sys.stderr.write(f"PROGRESS: {p:.2f}\n")
    sys.stderr.flush()


def probe_duration_seconds(path: Path) -> float:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)
        ], capture_output=True, text=True, check=True)
        return max(0.0, float(result.stdout.strip()))
    except Exception:
        return 0.0


def main() -> None:
    args = parse_args()
    infile = Path(args.input).expanduser().resolve()

    if not infile.exists():
        print(f"[!] File not found: {infile}")
        sys.exit(1)

    ensure_ffmpeg()

    progress(0.0)

    duration = probe_duration_seconds(infile)

    # Prefer faster-whisper for streaming progress if available
    text = ""
    if WhisperModel is not None:
        print(f"[+] Loading faster-whisper '{args.model}' on {args.device}…")
        model = WhisperModel(args.model, device=args.device, compute_type="int8" if args.device == "cpu" else "float16")
        print(f"[+] Transcribing {infile} …")
        progress(0.05)
        collected_segments = []
        segments, info = model.transcribe(str(infile), language=args.language, vad_filter=True)
        for seg in segments:
            collected_segments.append(seg)
            if duration > 0:
                progress(min(max(seg.end / duration, 0.0), 0.99))
        # Build text
        text = "".join(s.text or "" for s in collected_segments).strip()
        # For srt/vtt we need segment-like dicts
        result_segments = [{"start": s.start or 0.0, "end": s.end or 0.0, "text": s.text or ""} for s in collected_segments]
    else:
        if whisper is None:
            print("[!] Neither faster-whisper nor openai-whisper is available.")
            sys.exit(1)
        print(f"[+] Loading Whisper model '{args.model}' on {args.device}… (first time can be slow)")
        model = whisper.load_model(args.model, device=args.device)
        print(f"[+] Transcribing {infile} …")
        progress(0.05)
        result = model.transcribe(str(infile), language=args.language)
        text = result.get("text", "").strip()
        result_segments = result.get("segments", [])
        if not text:
            print("[!] Transcription produced empty text.")
            sys.exit(1)

    basename = infile.with_suffix("")

    if args.txt:
        txt_path = basename.with_name(basename.name + "_transcript.txt")
        txt_path.write_text(text, encoding="utf-8")
        print(f"[✓] TXT → {txt_path}")

    # For srt/vtt we can use whisper's built-in writers
    if args.srt or args.vtt:
        # Try to use whisper.utils if available; otherwise write minimal SRT/VTT
        try:
            from whisper.utils import write_srt, write_vtt  # type: ignore
        except Exception:
            write_srt = write_vtt = None  # type: ignore
        segments = result_segments
        if args.srt:
            srt_path = basename.with_name(basename.name + "_transcript.srt")
            if write_srt:
                with srt_path.open("w", encoding="utf-8") as f:
                    write_srt(segments, file=f)
            else:
                with srt_path.open("w", encoding="utf-8") as f:
                    for i, s in enumerate(segments, start=1):
                        f.write(f"{i}\n")
                        f.write(f"{int(s['start']//3600):02d}:{int(s['start']%3600//60):02d}:{int(s['start']%60):02d},000 --> {int(s['end']//3600):02d}:{int(s['end']%3600//60):02d}:{int(s['end']%60):02d},000\n")
                        f.write((s.get('text') or '').strip() + "\n\n")
            print(f"[✓] SRT → {srt_path}")
        if args.vtt:
            vtt_path = basename.with_name(basename.name + "_transcript.vtt")
            if write_vtt:
                with vtt_path.open("w", encoding="utf-8") as f:
                    write_vtt(segments, file=f)
            else:
                with vtt_path.open("w", encoding="utf-8") as f:
                    f.write("WEBVTT\n\n")
                    for s in segments:
                        f.write(f"{int(s['start']//3600):02d}:{int(s['start']%3600//60):02d}:{int(s['start']%60):02d}.000 --> {int(s['end']//3600):02d}:{int(s['end']%3600//60):02d}:{int(s['end']%60):02d}.000\n")
                        f.write((s.get('text') or '').strip() + "\n\n")
            print(f"[✓] VTT → {vtt_path}")

    progress(1.0)


if __name__ == "__main__":
    main()
