"""Standalone Whisper transcription for analysis_ai.

Deliberately independent of the notes app's server/worker code and database:
it takes a media file path and writes a JSON file, nothing else. The media
file is only ever opened for reading.

Language is always passed explicitly. Left to auto-detect, Whisper guesses
from the first 30 seconds -- and for recordings that open with silence or
small talk it has labelled English lectures as Welsh ("cy") and then
transcribed the whole thing as Welsh-looking gibberish.
"""
import argparse
import json
import os
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", help="audio/video file to transcribe (opened read-only)")
    parser.add_argument("out", help="output .json path (refuses to overwrite unless --force)")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--language", default="en", help="ISO code; auto-detect is intentionally not the default")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    args = parser.parse_args()

    if os.path.exists(args.out) and not args.force:
        print(f"refusing to overwrite {args.out} (use --force)", file=sys.stderr)
        return 1

    from faster_whisper import WhisperModel

    started = time.time()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print(f"model loaded in {time.time() - started:.0f}s", flush=True)

    # Same decoding choices the notes app settled on (see server/app/jobs/transcribe.py):
    # VAD off (it discarded real speech on quiet recordings) and no conditioning on
    # previous text (avoids repetition loops on long recordings).
    segments_iter, info = model.transcribe(
        args.media,
        language=args.language,
        word_timestamps=False,
        vad_filter=False,
        condition_on_previous_text=False,
    )

    segments = []
    for seg in segments_iter:
        segments.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
        if len(segments) % 100 == 0:
            print(f"  {len(segments)} segments, {seg.end / 60:.1f} min transcribed", flush=True)

    result = {
        "source": os.path.basename(args.media),
        "model": args.model,
        "language": info.language,
        "language_forced": args.language,
        "duration_seconds": info.duration,
        "full_text": " ".join(s["text"] for s in segments),
        "segments": segments,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, args.out)
    print(f"done: {len(segments)} segments, {len(result['full_text'])} chars, {time.time() - started:.0f}s total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
