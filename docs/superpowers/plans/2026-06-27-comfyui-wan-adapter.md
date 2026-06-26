# ComfyUI Wan Adapter Implementation Plan

> **For agentic workers:** Tests must stay offline. Use a fake ComfyUI HTTP server.

**Goal:** Add `auto_video.comfyui_wan_adapter` for AutoDL ComfyUI Wan2.2 workflows.

---

## Task 1: Tests

- [x] Fake `/upload/image`, `/prompt`, `/history/<id>`, and `/view`.
- [x] Assert workflow nodes are patched from provider job payload.
- [x] Assert module entrypoint works.
- [x] Assert missing image reference fails clearly.
- [x] Assert external command provider can run the adapter.

## Task 2: Adapter

- [x] Add CLI parser with base URL, workflow path, timeout, polling, and node IDs.
- [x] Resolve base URL from argument or env.
- [x] Upload the first image reference.
- [x] Load workflow JSON and strip metadata keys.
- [x] Patch prompt, negative prompt, image, seed, duration, resolution, frame rate, steps, and filename prefix where nodes exist.
- [x] Submit prompt and poll history.
- [x] Download first video/media output and write `--output`.

## Task 3: Docs

- [x] Add script wrapper.
- [x] Document AutoDL ComfyUI Wan2.2 provider config in README.

## Verification Commands

```bash
.venv/bin/python -m pytest tests/test_comfyui_wan_adapter.py -v
.venv/bin/python -m pytest -v
```
