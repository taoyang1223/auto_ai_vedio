from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


@dataclass(frozen=True)
class ProjectTemplate:
    name: str
    description: str
    text_files: dict[str, str]
    placeholder_images: dict[str, tuple[int, int, tuple[int, int, int], tuple[int, int, int]]]


COMMON_DIRECTORIES = (
    "assets/refs",
    "assets/continuity",
    "generated/images",
    "generated/clips",
    "generated/audio",
    "renders",
    "reports",
)

DEMO_PROJECT_YAML = """name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock
prompt_profile:
  subject: A tired desk worker discovering a simple product promise
  character: Same person across the shot, natural posture and consistent clothing
  setting: Cold late-night desk with a small amount of screen glow
  visual_style: realistic commercial demo, clean composition
  camera_style: restrained camera movement, stable framing
  motion_style: subtle human motion and coherent object movement
  lighting_style: cold fluorescent light with soft practical highlights
  continuity: keep the same subject, desk layout, and understated product mood
  negative: identity drift, style drift, unreadable text
render:
  transition:
    type: fade
    duration: 0.6
  bgm_volume: 0.2
  subtitle_style: default
  brand:
    text: "Demo Brand"
    at: 1.2
  cta:
    text: "Click for more"
    at: 2.6
"""

DEMO_SHOTS_JSON = """{
  "shots": [
    {
      "id": "S01",
      "title": "Hook",
      "duration": 5,
      "intent": "Show fatigue and introduce the product need",
      "provider": "mock",
      "visual_prompt": "A tired person at a cold desk",
      "camera_motion": "slow_dolly_in",
      "environment_motion": "screen flicker, dust floats",
      "performance": "tired breathing, shoulders drop slightly",
      "lighting": "cold fluorescent light",
      "audio_intent": "quiet room tone",
      "subtitle": "Late night again",
      "negative_prompt": "text, watermark",
      "refs": [
        {
          "path": "assets/refs/S01.txt",
          "type": "text",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    }
  ]
}
"""

AUTODL_PROJECT_YAML = """name: __PROJECT_NAME__
aspect_ratio: "16:9"
width: 832
height: 544
fps: 16
default_video_provider: comfyui_wan
default_image_provider: mock
default_audio_provider: mock
prompt_profile:
  subject: 专注的 AI 视频创作者与自动化影像工作台
  character: 同一位创作者，现代简洁穿着，沉稳自信，动作自然
  setting: 现代影像工作室，故事板、显示器、生产桌面贯穿全片
  visual_style: realistic cinematic commercial film, premium tech product demo, refined materials
  camera_style: smooth controlled camera movement, stable composition, cinematic depth
  motion_style: natural hand movement, subtle parallax, coherent object motion
  lighting_style: soft key light, practical screen glow, clean rim light, controlled contrast
  continuity: preserve the same creator, workspace, color palette, and premium AI video production theme across all shots
  negative: text, watermark, logo, flicker, inconsistent character, identity drift, style drift
render:
  transition:
    type: fade
    duration: 0.4
  bgm_volume: 0.18
  subtitle_style: clean
providers:
  comfyui_wan:
    mode: external_command
    timeout_seconds: 3600
    max_attempts: 1
    command:
      - python
      - -m
      - auto_video.comfyui_wan_adapter
      - --base-url-env
      - COMFYUI_BASE_URL
      - --workflow-env
      - COMFYUI_WORKFLOW
      - --workflow-profile-env
      - COMFYUI_WORKFLOW_PROFILE
      - --timeout
      - "1800"
      - --seed
      - "42"
      - --steps
      - "20"
comfyui_workflows:
  wan2_2_smoothmix_i2v:
    title: Wan2.2 SmoothMix image-to-video
    provider: comfyui_wan
    kind: image_to_video
    base_url: http://127.0.0.1:6006
    base_url_env: COMFYUI_BASE_URL
    workflow_env: COMFYUI_WORKFLOW
    workflow_path: /root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json
    profile_env: COMFYUI_WORKFLOW_PROFILE
    tags:
      - wan2.2
      - image-to-video
      - autodl
      - rtx5090
    models:
      video: Wan2.2 SmoothMix V2
      trainer_image: wan2.2视频带工作流
    recommended_gpu:
      name: RTX 5090
      vram_gb: 32
      count: 1
    parameters:
      seed: 42
      steps: 20
    nodes:
      prompt:
        id: "257"
        input: value
      negative:
        id: "218"
        input: text
      image:
        id: "224"
        input: image
      seed:
        id: "231"
        input: seed
      duration:
        id: "238"
        input: value
      resolution:
        id: "248"
        input: value
      video:
        id: "230"
        frame_rate_input: frame_rate
        filename_prefix_input: filename_prefix
      steps:
        ids:
          - "228"
          - "229"
        steps_input: steps
        cfg_input: cfg
remote_profiles:
  autodl_5090:
    host: "root@<autodl-host>"
    remote_dir: /root/auto-video/jobs/__PROJECT_NAME__
    local_dir: /tmp/auto-video-__PROJECT_NAME__
    remote_auto_video: /opt/auto-ai-video/.venv/bin/auto-video
    ssh_options:
      - "Port=<ssh-port>"
    remote_env:
      PATH: /opt/auto-ai-video/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
      COMFYUI_BASE_URL: http://127.0.0.1:6006
      COMFYUI_WORKFLOW: /root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json
      COMFYUI_WORKFLOW_PROFILE: wan2_2_smoothmix_i2v
"""

AUTODL_SHOTS_JSON = """{
  "shots": [
    {
      "id": "S01",
      "title": "Opening subject",
      "duration": 4,
      "intent": "Establish the main character and visual style",
      "provider": "comfyui_wan",
      "visual_prompt": "cinematic close shot of a focused creator reviewing a storyboard wall, modern studio, refined commercial lighting, detailed hands, natural motion",
      "camera_motion": "slow dolly in with a gentle parallax shift",
      "environment_motion": "soft monitor glow, paper notes moving slightly in the air",
      "performance": "the creator turns from the board toward the camera with calm confidence",
      "lighting": "soft key light, practical screen highlights, controlled contrast",
      "audio_intent": "quiet studio texture and subtle cinematic pulse",
      "subtitle": "A story starts with one clear frame",
      "negative_prompt": "text, watermark, logo, bad hands, extra fingers, duplicated face, distorted body, low quality, blurry",
      "refs": [
        {
          "path": "assets/refs/S01_first_frame.png",
          "type": "image",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    },
    {
      "id": "S02",
      "title": "Workflow motion",
      "duration": 4,
      "intent": "Show the production process becoming alive",
      "provider": "comfyui_wan",
      "visual_prompt": "wide cinematic shot of a production desk where storyboard cards transform into glowing video thumbnails, realistic materials, elegant tech ambience",
      "camera_motion": "sideways tracking shot across the desk",
      "environment_motion": "cards lift slightly, light reflections travel across glass and metal surfaces",
      "performance": "hands arrange the cards with precise deliberate movement",
      "lighting": "warm practical desk light mixed with cool display light",
      "audio_intent": "soft mechanical clicks and rising musical texture",
      "subtitle": "Shots become a sequence",
      "negative_prompt": "text, watermark, logo, unreadable UI, bad hands, extra fingers, flicker, low quality, blurry",
      "refs": [
        {
          "path": "assets/refs/S02_first_frame.png",
          "type": "image",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    },
    {
      "id": "S03",
      "title": "Final reveal",
      "duration": 4,
      "intent": "Deliver a polished final result",
      "provider": "comfyui_wan",
      "visual_prompt": "hero shot of a finished AI video playing on a large studio screen, satisfied creator silhouette, cinematic reveal, premium product-demo feeling",
      "camera_motion": "slow crane up and subtle push forward",
      "environment_motion": "screen reflections ripple gently, room lights brighten with the reveal",
      "performance": "the creator steps back and watches the finished film with a small smile",
      "lighting": "clean cinematic backlight, soft rim light, high-end studio finish",
      "audio_intent": "resolved musical hit with clean room ambience",
      "subtitle": "Then the film is ready",
      "negative_prompt": "text, watermark, logo, broken screen, bad hands, distorted body, duplicate person, low quality, blurry",
      "refs": [
        {
          "path": "assets/refs/S03_first_frame.png",
          "type": "image",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    }
  ]
}
"""

AUTODL_README = """# __PROJECT_NAME__

AutoDL ComfyUI Wan starter project for `auto-video`.

## Before running

1. Replace the placeholder PNG files in `assets/refs/` with real first-frame images.
2. Edit `project.yaml` and replace `<autodl-host>` and `<ssh-port>` in `remote_profiles.autodl_5090`.
3. Confirm the workflow path in `COMFYUI_WORKFLOW` matches the workflow on the GPU instance.
4. Start ComfyUI on AutoDL and make sure `http://127.0.0.1:6006` is reachable from the GPU host.

## Useful commands

```bash
auto-video validate .
auto-video workflows list .
auto-video workflows show . wan2_2_smoothmix_i2v
auto-video remote profiles .
auto-video remote run . --profile autodl_5090 --provider comfyui_wan --kind video
auto-video probe . --strict
auto-video continuity extract-tail-frames .
auto-video assemble .
auto-video remote wrapup --host root@<autodl-host> --remote-dir /root/auto-video/jobs/__PROJECT_NAME__ --ssh-option Port=<ssh-port>
```

The generated placeholder images are only scaffolding. They keep validation deterministic, but real Wan output depends on high-quality first frames.
"""


TEMPLATES = {
    "demo": ProjectTemplate(
        name="demo",
        description="Offline mock project for local development and tests.",
        text_files={
            "project.yaml": DEMO_PROJECT_YAML,
            "shots.json": DEMO_SHOTS_JSON,
            "assets/refs/S01.txt": "mock first-frame reference\n",
        },
        placeholder_images={},
    ),
    "autodl_comfyui_wan": ProjectTemplate(
        name="autodl_comfyui_wan",
        description="Three-shot AutoDL ComfyUI Wan image-to-video starter project.",
        text_files={
            "project.yaml": AUTODL_PROJECT_YAML,
            "shots.json": AUTODL_SHOTS_JSON,
            "README.md": AUTODL_README,
        },
        placeholder_images={
            "assets/refs/S01_first_frame.png": (832, 544, (31, 44, 79), (97, 174, 147)),
            "assets/refs/S02_first_frame.png": (832, 544, (54, 46, 79), (214, 176, 91)),
            "assets/refs/S03_first_frame.png": (832, 544, (24, 61, 73), (202, 103, 112)),
        },
    ),
}

TEMPLATE_ALIASES = {
    "default": "demo",
    "mock": "demo",
    "autodl-wan": "autodl_comfyui_wan",
    "comfyui-wan": "autodl_comfyui_wan",
    "wan": "autodl_comfyui_wan",
}


def list_templates() -> list[dict[str, str]]:
    return [
        {"name": template.name, "description": template.description}
        for template in sorted(TEMPLATES.values(), key=lambda item: item.name)
    ]


def init_project(path: Path, *, template_name: str = "demo", force: bool = False) -> None:
    template = _resolve_template(template_name)
    project_name = _project_name(path)
    _ensure_can_write(path, force=force)
    for directory in COMMON_DIRECTORIES:
        (path / directory).mkdir(parents=True, exist_ok=True)
    for relative_path, content in template.text_files.items():
        _write_text(path / relative_path, _render(content, project_name), force=force)
    for relative_path, image in template.placeholder_images.items():
        width, height, start, end = image
        _write_bytes(path / relative_path, _gradient_png(width, height, start, end), force=force)


def _resolve_template(value: str) -> ProjectTemplate:
    key = TEMPLATE_ALIASES.get(value, value)
    if key in TEMPLATES:
        return TEMPLATES[key]
    allowed = ", ".join(sorted(set(TEMPLATES) | set(TEMPLATE_ALIASES)))
    raise ConfigError(f"unknown init template {value!r}", fix=f"Use one of: {allowed}.")


def _project_name(path: Path) -> str:
    name = path.name or "auto_video_project"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-")
    return safe or "auto_video_project"


def _ensure_can_write(path: Path, *, force: bool) -> None:
    if force:
        return
    conflicts = [name for name in ("project.yaml", "shots.json") if (path / name).exists()]
    if conflicts:
        raise ConfigError(
            f"project already contains {', '.join(conflicts)}",
            fix="Choose a new directory or pass --force to overwrite template files.",
        )


def _render(content: str, project_name: str) -> str:
    return content.replace("__PROJECT_NAME__", project_name)


def _write_text(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise ConfigError(f"file already exists: {path}", fix="Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, content: bytes, *, force: bool) -> None:
    if path.exists() and not force:
        raise ConfigError(f"file already exists: {path}", fix="Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _gradient_png(
    width: int,
    height: int,
    start: tuple[int, int, int],
    end: tuple[int, int, int],
) -> bytes:
    rows = []
    for y in range(height):
        ratio = y / max(1, height - 1)
        base = tuple(round(start[index] + (end[index] - start[index]) * ratio) for index in range(3))
        row = bytearray([0])
        for x in range(width):
            shimmer = round(18 * x / max(1, width - 1))
            row.extend(min(255, channel + shimmer) for channel in base)
        rows.append(bytes(row))
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, level=9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)
