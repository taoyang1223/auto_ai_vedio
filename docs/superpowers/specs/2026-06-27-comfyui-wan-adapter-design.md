# ComfyUI Wan Adapter Design

## Discovery

The AutoDL application `wan2.2视频带工作流` starts ComfyUI successfully.

Observed on the rented RTX 5090 instance:

- ComfyUI process: `/root/miniconda3/bin/python main.py --port 6006 --listen 127.0.0.1`
- Control panel: port `6008`
- ComfyUI API base URL on the remote host: `http://127.0.0.1:6006`
- Health endpoints verified: `/system_stats`, `/queue`, `/object_info`
- Workflow root: `/root/zealman-app/workflows`
- Recommended first adapter workflow: `/root/zealman-app/workflows/G10-图生视频-Wan2.2SmoothMixV2.json`

G10 exposed useful API parameters:

- `224:image` uploaded image
- `257:value` positive prompt
- `218:text` negative prompt
- `231:seed`
- `238:value` duration driver
- `248:value` longest-side resolution
- `230:filename_prefix`
- `230:frame_rate`

## Goal

Add a provider adapter that translates the auto-video external command payload into a ComfyUI prompt:

1. upload the first image reference to `/upload/image`
2. load and patch a workflow JSON template
3. submit to `/prompt`
4. poll `/history/<prompt_id>`
5. download the first video output from `/view`
6. write the video to `--output`

## Entrypoints

```bash
python -m auto_video.comfyui_wan_adapter
python scripts/comfyui_wan_adapter.py
```

## Non-Goals

- Full arbitrary ComfyUI graph editing.
- Browser automation.
- Real GPU tests in the default test suite.
- T2V support in the first adapter. The first target is image-to-video because this mirrors the Seedance replacement strategy: stable first frame, controlled motion.
