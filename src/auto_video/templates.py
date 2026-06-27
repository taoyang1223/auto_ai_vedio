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
    "generated/lipsync",
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
default_lipsync_provider: mock
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
default_image_provider: comfyui_image
default_audio_provider: local_tts
default_lipsync_provider: comfyui_lipsync
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
  comfyui_image:
    mode: external_command
    timeout_seconds: 1800
    max_attempts: 1
    command:
      - python
      - -m
      - auto_video.comfyui_image_adapter
      - --base-url-env
      - COMFYUI_IMAGE_BASE_URL
      - --workflow-env
      - COMFYUI_IMAGE_WORKFLOW
      - --workflow-profile-env
      - COMFYUI_IMAGE_WORKFLOW_PROFILE
      - --timeout
      - "1200"
      - --seed
      - "42"
      - --steps
      - "8"
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
  comfyui_lipsync:
    mode: external_command
    timeout_seconds: 3600
    max_attempts: 1
    command:
      - python
      - -m
      - auto_video.comfyui_lipsync_adapter
      - --base-url-env
      - COMFYUI_LIPSYNC_BASE_URL
      - --workflow-env
      - COMFYUI_LIPSYNC_WORKFLOW
      - --workflow-profile-env
      - COMFYUI_LIPSYNC_WORKFLOW_PROFILE
      - --timeout
      - "1800"
      - --seed
      - "42"
  local_tts:
    mode: local_tts
    timeout_seconds: 240
    engine: edge_tts
    command: edge-tts
    voice: zh-CN-XiaoxiaoNeural
    rate: +0%
    volume: +0%
    sample_rate: 48000
    channels: 2
    text_source: subtitle
comfyui_workflows:
  qwen2512_first_frame:
    title: Qwen2512 首帧文生图
    provider: comfyui_image
    kind: text_to_image
    base_url: http://127.0.0.1:6006
    base_url_env: COMFYUI_IMAGE_BASE_URL
    workflow_env: COMFYUI_IMAGE_WORKFLOW
    workflow_path: /root/zealman-app/workflows/A01-文生图-Qwen2512高清放大.json
    profile_env: COMFYUI_IMAGE_WORKFLOW_PROFILE
    tags:
      - qwen2512
      - text-to-image
      - first-frame
      - autodl
      - rtx5090
    models:
      image: Qwen Image 2512
      trainer_image: A01-文生图-Qwen2512高清放大
    recommended_gpu:
      name: RTX 5090
      vram_gb: 32
      count: 1
    parameters:
      seed: 42
      steps: 8
      guidance_scale: 1
    nodes:
      prompt:
        id: "187"
        input: text
      negative:
        id: "437"
        input: text
      seed:
        id: "3"
        input: seed
      size:
        id: "118"
        width_input: width
        height_input: height
      output:
        id: "499"
        filename_prefix_input: filename_prefix
      steps:
        ids:
          - "3"
        steps_input: steps
        cfg_input: cfg
  wan2_2_smoothmix_i2v:
    title: Wan2.2 SmoothMix 图生视频
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
  lipsync_video_audio:
    title: 视频配音口型同步
    provider: comfyui_lipsync
    kind: lipsync
    base_url: http://127.0.0.1:6006
    base_url_env: COMFYUI_LIPSYNC_BASE_URL
    workflow_env: COMFYUI_LIPSYNC_WORKFLOW
    workflow_path: /root/zealman-app/workflows/L20-视频配音口型同步.json
    profile_env: COMFYUI_LIPSYNC_WORKFLOW_PROFILE
    tags:
      - lipsync
      - video-audio
      - autodl
      - rtx5090
    models:
      lipsync: ComfyUI 口型驱动工作流
    recommended_gpu:
      name: RTX 5090
      vram_gb: 32
      count: 1
    parameters:
      seed: 42
    uploads:
      endpoint: /upload/image
      video_field: image
      audio_field: image
      type: input
    nodes:
      video:
        id: "video"
        input: video
      audio:
        id: "audio"
        input: audio
      output:
        id: "output"
        filename_prefix_input: filename_prefix
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
      COMFYUI_IMAGE_BASE_URL: http://127.0.0.1:6006
      COMFYUI_IMAGE_WORKFLOW: /root/zealman-app/workflows/A01-文生图-Qwen2512高清放大.json
      COMFYUI_IMAGE_WORKFLOW_PROFILE: qwen2512_first_frame
      COMFYUI_BASE_URL: http://127.0.0.1:6006
      COMFYUI_WORKFLOW: /root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json
      COMFYUI_WORKFLOW_PROFILE: wan2_2_smoothmix_i2v
      COMFYUI_LIPSYNC_BASE_URL: http://127.0.0.1:6006
      COMFYUI_LIPSYNC_WORKFLOW: /root/zealman-app/workflows/L20-视频配音口型同步.json
      COMFYUI_LIPSYNC_WORKFLOW_PROFILE: lipsync_video_audio
"""

AUTODL_SHOTS_JSON = """{
  "shots": [
    {
      "id": "S01",
      "title": "建立主角",
      "duration": 4,
      "intent": "建立主角、场景和整片影像气质",
      "provider": "comfyui_wan",
      "visual_prompt": "电影感近景，一位专注的 AI 视频创作者正在检查故事板墙，现代影像工作室，精致商业灯光，手部细节自然，realistic cinematic commercial film",
      "camera_motion": "缓慢向前推进，带轻微视差",
      "environment_motion": "显示器柔和发光，纸质便签轻微晃动",
      "performance": "创作者从故事板转向镜头，神情沉稳自信",
      "lighting": "柔和主光，屏幕实践光，高级克制的对比度",
      "audio_intent": "安静工作室氛围，轻微电影脉冲",
      "subtitle": "一个清晰首帧，启动整条故事线",
      "negative_prompt": "文字，水印，logo，坏手，多余手指，重复人脸，肢体变形，低质量，模糊",
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
      "title": "流程运转",
      "duration": 4,
      "intent": "展示分镜、素材和视频生成流程被自动串联",
      "provider": "comfyui_wan",
      "visual_prompt": "电影感广角，制作桌上的故事板卡片逐渐变成发光的视频缩略图，真实材质，优雅科技氛围，premium tech product demo",
      "camera_motion": "镜头沿桌面横向平移",
      "environment_motion": "卡片轻微升起，玻璃和金属表面有流动反光",
      "performance": "双手精准整理卡片，动作克制明确",
      "lighting": "温暖桌灯与冷色屏幕光混合",
      "audio_intent": "轻柔机械点击声，音乐能量逐步上升",
      "subtitle": "分镜开始自动连成序列",
      "negative_prompt": "文字，水印，logo，不可读界面，坏手，多余手指，闪烁，低质量，模糊",
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
      "title": "成片揭示",
      "duration": 4,
      "intent": "呈现最终成片和完成感",
      "provider": "comfyui_wan",
      "visual_prompt": "英雄镜头，大型工作室屏幕正在播放完成的 AI 视频，创作者满意地站在屏幕前，电影感揭示，高级产品演示气质",
      "camera_motion": "缓慢升镜并轻微向前推进",
      "environment_motion": "屏幕反光轻微波动，空间灯光随揭示逐渐变亮",
      "performance": "创作者后退一步观看成片，露出克制微笑",
      "lighting": "干净电影背光，柔和轮廓光，高级工作室收束",
      "audio_intent": "收束的音乐重音，干净空间氛围",
      "subtitle": "成片准备完成",
      "negative_prompt": "文字，水印，logo，破损屏幕，坏手，肢体变形，重复人物，低质量，模糊",
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

AutoDL ComfyUI Wan 视频生成模板，适用于 `auto-video` 控制台。

## 运行前检查

1. 在控制台的“首帧设计”里生成或替换 `assets/refs/` 下的占位 PNG。
2. 编辑 `project.yaml`，把 `remote_profiles.autodl_5090` 里的 `<autodl-host>` 和 `<ssh-port>` 换成 AutoDL 实例信息。
3. 确认 `COMFYUI_WORKFLOW` 指向 GPU 实例上的真实工作流。
4. 在 AutoDL 上启动 ComfyUI，确保 GPU 主机能访问 `http://127.0.0.1:6006`。

## 常用命令

```bash
auto-video validate .
auto-video workflows list .
auto-video workflows show . wan2_2_smoothmix_i2v
auto-video workflows show . qwen2512_first_frame
auto-video remote run . --profile autodl_5090 --provider comfyui_image --kind image
auto-video remote profiles .
auto-video remote run . --profile autodl_5090 --provider comfyui_wan --kind video
auto-video audio . --provider local_tts --skip-succeeded
auto-video probe . --strict
auto-video continuity extract-tail-frames .
auto-video assemble .
auto-video remote wrapup --host root@<autodl-host> --remote-dir /root/auto-video/jobs/__PROJECT_NAME__ --ssh-option Port=<ssh-port>
```

模板自带的占位图只用于让项目能稳定通过校验。真实 Wan 视频质量主要取决于首帧质量、主体一致性提示词和工作流参数。
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
        description="三分镜 AutoDL ComfyUI Wan 图生视频模板。",
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
