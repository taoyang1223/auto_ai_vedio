from __future__ import annotations

import hashlib
import math
import struct
import zlib
from pathlib import Path

from auto_video.jobs import GenerationJob, ProviderResult
from auto_video.models import AssetResult, GenerationTask


class MockProvider:
    name = "mock"

    def execute_job(self, job: GenerationJob, project_root: Path) -> ProviderResult:
        output_path = project_root / job.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if job.kind == "image":
            width = max(64, int(job.controls.width if job.controls else 1080))
            height = max(64, int(job.controls.height if job.controls else 1920))
            output_path.write_bytes(_mock_png(width, height, seed=f"{job.shot_id}:{job.prompt}"))
            duration = None
        elif job.kind == "video":
            output_path.write_text(f"mock video for {job.shot_id}\n{job.prompt}\n", encoding="utf-8")
            duration = job.duration
        elif job.kind == "lipsync":
            source = next((project_root / ref.path for ref in job.refs if ref.type == "video" and ref.exists), None)
            if source and source.exists():
                output_path.write_bytes(source.read_bytes())
            else:
                output_path.write_text(f"mock lip-sync video for {job.shot_id}\n{job.prompt}\n", encoding="utf-8")
            duration = job.duration
        else:
            output_path.write_bytes(_mock_wav(duration=job.duration or 1.0, seed=f"{job.shot_id}:{job.prompt}"))
            duration = job.duration
        return ProviderResult(
            job_id=job.id,
            shot_id=job.shot_id,
            kind=job.kind,
            provider=self.name,
            status="succeeded",
            path=output_path,
            duration=duration,
            metadata={"mock": True},
        )

    def generate_image(self, task: GenerationTask) -> AssetResult:
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        width = max(64, int(task.project.width))
        height = max(64, int(task.project.height))
        task.output_path.write_bytes(_mock_png(width, height, seed=f"{task.shot.id}:{task.prompt}"))
        return AssetResult(shot_id=task.shot.id, provider=self.name, path=task.output_path, kind="image")

    def generate_video(self, task: GenerationTask) -> AssetResult:
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        task.output_path.write_text(f"mock video for {task.shot.id}\n{task.prompt}\n", encoding="utf-8")
        return AssetResult(
            shot_id=task.shot.id,
            provider=self.name,
            path=task.output_path,
            kind="clip",
            duration=task.shot.duration,
        )


def _mock_png(width: int, height: int, *, seed: str) -> bytes:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    start = (digest[0], digest[1], digest[2])
    end = (digest[3], digest[4], digest[5])
    rows = bytearray()
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3))
        rows.append(0)
        for _x in range(width):
            rows.extend(color)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _mock_wav(*, duration: float, seed: str) -> bytes:
    sample_rate = 16000
    channels = 1
    bits = 16
    frames = max(1, round(duration * sample_rate))
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    frequency = 220 + digest[0]
    samples = bytearray()
    for index in range(frames):
        envelope = min(1.0, index / max(1, sample_rate // 20), (frames - index) / max(1, sample_rate // 20))
        value = int(1800 * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
        samples.extend(struct.pack("<h", value))
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    data = bytes(samples)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )
