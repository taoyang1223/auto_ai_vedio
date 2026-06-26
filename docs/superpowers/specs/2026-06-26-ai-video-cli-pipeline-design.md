# AI Video CLI Pipeline Design

Date: 2026-06-26
Workspace: `/root/auto_ai_vedio`
Prototype reference: `/root/ai_vedio`

## Purpose

Build the first MVP of an AI video production system that productizes the working prototype in `/root/ai_vedio`.

The MVP is a CLI automation pipeline. It turns structured project files into video production artifacts:

```text
project config -> shot plan -> reference assets -> generated images -> generated clips -> audio/subtitles -> rendered final video -> manifest/reports
```

This is not a from-scratch replacement for the Seedance 2.0 model. It is a Seedance-inspired production system: multimodal, reference-driven, shot-based, provider-pluggable, and designed to support local, API, and cloud GPU generation backends.

## Seedance 2.0 Design References

The system should learn from Seedance 2.0 at the workflow and interface level:

- Multimodal inputs are first-class: text, images, videos, and audio all appear in project schema.
- Each reference asset declares a role and usage: preserve subject, preserve voice, extract style, extract camera motion, first frame, last frame, action reference, or audio reference.
- Long videos are assembled from short 4-15 second shots instead of one monolithic generation.
- Each shot carries director controls: intent, performance, camera motion, environment motion, lighting, transition, subtitle, and audio intent.
- Bridge and extension workflows are supported in schema so future providers can generate continuity shots from previous tail frames and next first frames.
- Audio-video synchronization is a product goal. The MVP aligns TTS, subtitles, BGM, and clip timing in post-production; later providers may support native joint audio-video generation.
- Compliance is explicit. The system should avoid designs that encourage celebrity imitation, unauthorized real-person cloning, protected IP replication, or generated text/logos inside video frames.

Primary references:

- https://seed.bytedance.com/en/seedance2_0
- https://arxiv.org/abs/2604.14148
- `/root/ai_vedio/Seedance 2.0 视频生成规则指南.md`
- `/root/ai_vedio/视频制作记录/视频制作记录/Seedance2.0学习总结_2026-06-08.md`

## MVP Scope

### In Scope

- Initialize a project folder with example config and shot files.
- Validate `project.yaml` and `shots.json`.
- Manage source and generated assets with a manifest.
- Generate or dry-run image tasks through mock and future real providers.
- Generate or dry-run video tasks through mock and future real providers.
- Convert structured shot fields into provider-specific prompts.
- Build an EDL from manifest data.
- Dry-run FFmpeg assembly plans.
- Support real FFmpeg assembly once clips and audio exist.
- Probe projects and generated clips for duration and basic completeness.
- Provide migration guidance from the prototype project.

### Out of Scope For MVP

- Web UI.
- Multi-user accounts.
- Payment, billing, or quota management.
- Full cloud GPU job queue.
- From-scratch video model training.
- AI visual quality scoring.
- Automatic end-to-end advertising strategy generation.
- Protected celebrity, film, anime, or trademarked IP replication workflows.

## Success Criteria

The MVP is successful when these commands work against an example project:

```bash
auto-video init demo_project
auto-video validate demo_project
auto-video images demo_project --dry-run
auto-video generate demo_project --dry-run
auto-video assemble demo_project --dry-run
auto-video probe demo_project --dry-run
```

It must also support mock output generation without API keys:

```bash
auto-video images demo_project --provider mock
auto-video generate demo_project --provider mock
```

Default tests must not require network, Seedance credentials, a cloud GPU, or FFmpeg rendering of large media.

## Architecture

```text
CLI
  -> Project Loader
  -> Schema Validator
  -> Asset Registry
  -> Prompt Planner
  -> Provider Gateway
  -> Render Pipeline
  -> QA / Probe
  -> Manifest Writer
```

### CLI

The CLI parses commands and delegates to services. It does not directly assemble prompts, call provider APIs, or build complex FFmpeg commands.

Commands:

```bash
auto-video init <project>
auto-video validate <project>
auto-video images <project>
auto-video generate <project>
auto-video assemble <project>
auto-video probe <project>
auto-video providers health
```

Useful command options:

```bash
--dry-run
--provider <name>
--only S01,S03
--failed-only
--force
--report <path>
```

### Project Loader

The loader reads project files and resolves paths safely within a project root.

It replaces repeated path helper logic from the prototype, such as `_resolve()` in multiple scripts.

Responsibilities:

- Load `project.yaml`.
- Load `shots.json`.
- Load or create `manifest.json`.
- Resolve relative paths to absolute paths.
- Reject paths that escape the project directory.
- Return typed project objects to other modules.

### Schema Validator

The validator checks project and shot definitions before generation.

Core data structures:

- `ProjectConfig`
- `ShotPlan`
- `AssetRef`
- `GenerationTask`
- `RenderEDL`
- `Manifest`

Validation rules:

- `project.yaml` has required render and provider defaults.
- `shots.json` has at least one shot.
- Each shot has `id`, `duration`, and prompt or reference data.
- `duration` is greater than zero.
- Provider names are known.
- Reference `type`, `role`, and `usage` are known enum values.
- Referenced source assets exist unless they are declared as generated outputs.
- Paths stay inside the project root.

### Asset Registry

The registry tracks source assets and generated artifacts.

Asset categories:

- source images
- source video references
- source audio references
- generated first-frame images
- generated clips
- generated TTS
- rendered outputs
- contact sheets
- probe reports

Every generated artifact gets a stable asset id, file path, provider name, status, and optional error summary in `manifest.json`.

### Prompt Planner

The prompt planner transforms structured shot fields into provider-specific prompts.

It enforces the Seedance-inspired shot model:

```text
subject action
performance and micro-motion
camera motion
environment motion
lighting
audio intent
negative constraints
reference asset usage
```

Provider behavior:

- Seedance prompt includes time slices, multimodal reference roles, audio intent, and continuity guidance.
- Wan prompt focuses on image-to-video motion, strong camera movement, environment motion, and negative prompts.
- Slideshow prompt only needs image order, duration, and transition details.
- Mock prompt is deterministic for tests.

### Provider Gateway

All generation backends implement a small interface:

```text
ImageProvider.generate_image(task) -> AssetResult
VideoProvider.generate_video(task) -> AssetResult
AudioProvider.generate_audio(task) -> AssetResult
```

MVP providers:

- `mock` for offline tests and demo workflows.
- `seedream` adapter planned from `/root/ai_vedio/tools/providers/seedream.py`.
- `seedance` adapter planned from `/root/ai_vedio/tools/providers/seedance.py`.
- `wan` adapter planned from `/root/ai_vedio/tools/providers/wan.py`.

Real providers are not required for default tests.

### Render Pipeline

The render pipeline modularizes the prototype's `assemble2.py` behavior.

Capabilities:

- Build an EDL from manifest and project config.
- Retime clips.
- Apply xfade transitions.
- Burn ASS subtitles.
- Align per-shot TTS with timeline offsets.
- Loop and mix BGM.
- Support overlays such as particles.
- Add brand and CTA text.
- Output `renders/final.mp4`.

MVP render mode starts with `--dry-run` support and command planning. Real FFmpeg execution is supported once sample media exists.

### QA / Probe

QA starts with objective checks:

- Required files exist.
- Clip durations are readable.
- Target duration divided by source duration is calculated.
- High stretch ratios are reported.
- Manifest entries are complete.
- Optional contact sheet generation is available when FFmpeg is installed.

The prototype guidance says long slowdowns create "PPT-like" video. The MVP should report stretch ratio warnings so users regenerate clips instead of hiding weak motion with slow motion.

### Manifest Writer

The manifest records project state and generation outcomes.

Rules:

- `--dry-run` does not modify `manifest.json`.
- A real generation command updates only affected assets and shots.
- Failed tasks record provider, error summary, and `retryable`.
- `--failed-only` reruns only failed shots.
- `--force` overwrites successful generated assets for selected shots.

## Project Structure

Generated projects use this layout:

```text
demo_project/
  project.yaml
  shots.json
  assets/
    source/
    refs/
    audio_refs/
    video_refs/
  generated/
    images/
    clips/
    audio/
  renders/
    final.mp4
    contact_sheet.jpg
  reports/
    probe.json
    validation.json
  manifest.json
```

## Project Config

Example `project.yaml`:

```yaml
name: demo_ad
aspect_ratio: "9:16"
width: 1080
height: 1920
fps: 30
default_video_provider: mock
default_image_provider: mock
default_audio_provider: mock

render:
  transition:
    type: fade
    duration: 0.6
  bgm: assets/audio_refs/bgm.mp3
  bgm_volume: 0.2
  subtitle_style: default
  brand:
    text: "Demo Brand"
    at: 1.2
  cta:
    text: "点击主页了解更多"
    at: 2.6
```

## Shot Plan

Example `shots.json`:

```json
{
  "shots": [
    {
      "id": "S01",
      "title": "痛点钩子",
      "duration": 5,
      "intent": "展示深夜疲惫状态，引出产品解决方案",
      "provider": "mock",
      "visual_prompt": "冷白灯下的深夜书桌，人物疲惫地揉太阳穴",
      "camera_motion": "slow_dolly_in",
      "environment_motion": "screen light flickers, dust floats",
      "performance": "tired breathing, shoulders drop slightly",
      "lighting": "cold fluorescent light",
      "audio_intent": "quiet room tone, soft sigh",
      "subtitle": "又是被 deadline 填满的深夜",
      "negative_prompt": "text, watermark, distorted hands",
      "refs": [
        {
          "path": "assets/refs/s01_first.png",
          "type": "image",
          "role": "first_frame",
          "usage": "preserve_subject"
        }
      ]
    }
  ]
}
```

Reference roles:

- `first_frame`
- `last_frame`
- `style_reference`
- `camera_reference`
- `motion_reference`
- `voice_reference`
- `bgm_reference`
- `environment_reference`

Reference usages:

- `preserve_subject`
- `preserve_voice`
- `extract_style`
- `extract_camera_motion`
- `extract_action`
- `extract_audio_rhythm`
- `provide_context`

## Manifest

Example `manifest.json`:

```json
{
  "project": "demo_ad",
  "schema_version": "0.1",
  "assets": {},
  "shots": {
    "S01": {
      "status": "generated",
      "provider": "mock",
      "image": "generated/images/S01.png",
      "clip": "generated/clips/S01.mp4",
      "duration": 5.0
    }
  },
  "renders": {
    "final": "renders/final.mp4"
  }
}
```

## Data Flow

```text
auto-video validate demo_project
  -> read project.yaml and shots.json
  -> validate fields, paths, durations, providers

auto-video images demo_project
  -> find shots needing generated first-frame images
  -> call ImageProvider
  -> write generated/images and manifest

auto-video generate demo_project
  -> read shot refs and prompt fields
  -> create provider-specific generation task
  -> call VideoProvider
  -> write generated/clips and manifest

auto-video assemble demo_project
  -> collect clips, subtitles, audio, render settings
  -> build EDL
  -> plan or run FFmpeg
  -> write renders/final.mp4 and manifest

auto-video probe demo_project
  -> inspect generated files
  -> calculate duration and stretch ratio
  -> write reports/probe.json unless dry-run
```

## Dry-Run Rules

Dry-run is read-only by default.

Rules:

- `--dry-run` does not write generated media.
- `--dry-run` does not modify `manifest.json`.
- `--dry-run` prints planned actions.
- `--dry-run --report <path>` may write an explicit report file.
- Validation may write a report only when `--report` is set.

This fixes a prototype issue where `batch-generate --dry-run` still attempted to write a manifest.

## Error Handling

Error categories:

```text
ConfigError
AssetError
ProviderError
RenderError
ProbeError
```

Every user-facing error includes:

- project path
- shot id when applicable
- field path when applicable
- concise failure reason
- repair guidance

Example:

```text
ConfigError: shot S03 refs[0].path not found: assets/refs/s03.png
Fix: place the file at that path or update shots.json.
```

Provider failures are recorded in manifest:

```json
{
  "shots": {
    "S03": {
      "status": "failed",
      "provider": "seedance",
      "error": "SetLimitExceeded",
      "retryable": true
    }
  }
}
```

## Testing Strategy

### Unit Tests

Schema tests:

- required project fields
- required shot fields
- valid provider names
- valid reference roles and usages
- positive shot durations
- path containment inside project root

Prompt planner tests:

- Seedance prompt includes multimodal reference roles and time-slice intent.
- Wan prompt includes action, camera motion, environment motion, and negative prompt.
- Mock prompt is deterministic.

Manifest tests:

- successful asset update
- failed task update
- no manifest write during dry-run
- rerun selection for `--only`, `--failed-only`, and `--force`

### CLI Tests

Commands tested with temporary projects:

```bash
auto-video init <tmp>/demo
auto-video validate <tmp>/demo
auto-video images <tmp>/demo --dry-run
auto-video generate <tmp>/demo --dry-run
auto-video assemble <tmp>/demo --dry-run
auto-video probe <tmp>/demo --dry-run
```

### End-To-End Mock Test

An `examples/demo_project` should run without credentials:

```bash
auto-video validate examples/demo_project
auto-video images examples/demo_project --provider mock
auto-video generate examples/demo_project --provider mock
auto-video assemble examples/demo_project --dry-run
auto-video probe examples/demo_project --dry-run
```

### Real Provider Checks

Real providers are opt-in and not part of default tests:

```bash
auto-video providers health
auto-video images demo_project --provider seedream --only S01
auto-video generate demo_project --provider seedance --only S01
auto-video generate demo_project --provider wan --only S01
```

Missing credentials or unavailable cloud GPU services must return clear configuration errors.

## Migration From `/root/ai_vedio`

Prototype assets map to MVP concepts:

```text
/root/ai_vedio/config.toml.example        -> config documentation
/root/ai_vedio/batch_plans/*.json         -> shots.json examples
/root/ai_vedio/edl/*.json                 -> render EDL examples
/root/ai_vedio/tools/providers/*.py       -> provider adapters
/root/ai_vedio/tools/assemble2.py         -> render pipeline behavior
/root/ai_vedio/tools/slideshow.py         -> fallback renderer/provider idea
/root/ai_vedio/tools/parallax_render.py   -> future GPU utility
/root/ai_vedio/视频制作记录/...            -> production SOP and QA rules
```

The migration should copy behavior, not blindly copy file shape. The new system should centralize schema, path resolution, manifest updates, and dry-run behavior.

## Future Extensions

These are intentionally outside MVP but supported by the architecture:

- cloud GPU worker
- remote AutoDL execution and artifact sync
- Web control panel
- HyperFrames rendering backend
- automated storyboard planning
- cost estimation
- provider benchmarking
- AI-assisted visual QA
- bridge-shot generation from tail and first frames
- video extension workflow

## Approval Gate

Implementation should not start until this design is reviewed and approved. After approval, create an implementation plan in:

```text
docs/superpowers/plans/YYYY-MM-DD-ai-video-cli-pipeline.md
```

The implementation plan should use task-sized, test-first steps.
