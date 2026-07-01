# AGENTS.md

本文件给后续 Codex / 开发 Agent 使用，概括当前 `auto_ai_vedio` 项目的产品目标、代码结构、常用命令和开发注意事项。

## 项目定位

`auto_ai_vedio` 是一个受 Seedance 类视频生成体验启发的 AI 视频生产系统。当前重点不是做单次玩具 Demo，而是把“小说章节 -> 可审查的分镜生产档案 -> 云端 GPU 生成 -> 配音/口型同步 -> 成片”做成可重复、可恢复、可管理的流水线。

目标场景：

- 用户每天粘贴一本原创小说的一章。
- 系统自动判断合适的视频时长和分镜数量，默认上限目标约 20 分钟。
- 自动管理人物、音色、场景、服装、首帧、提示词、配音、口型同步和最终成片。
- 后续章节复用人物与场景档案，保持外貌、声音、服装逻辑、场景风格一致。
- 使用本机 Codex/GPT 能力做章节理解、角色/场景抽取、分镜规划和提示词生成。
- 使用 AutoDL/ComfyUI/Wan 等云端 GPU 资源执行视频、首帧、口型同步等重型生成任务。

## 技术栈

后端 / CLI：

- Python 3.12+
- 包入口：`auto-video = auto_video.cli:entrypoint`
- 主要依赖：`PyYAML`
- 测试：`pytest`

前端：

- React 18 + TypeScript
- Vite 5
- Zustand
- React Router v6
- Tailwind CSS
- `@dnd-kit`
- Lucide React
- Axios

静态前端构建结果会被打包进 Python 包：

- 前端源码：`frontend/src`
- 构建产物：`src/auto_video/web_static`

修改前端后需要运行 `npm run build`，并提交更新后的 `web_static` 产物。

## 重要目录

- `src/auto_video/`：Python 包主体。
- `frontend/`：React 控制台源码。
- `tests/`：后端测试。
- `src/auto_video/web_static/`：前端构建后的静态资源，由 Python Web 服务直接托管。
- `/tmp/auto-video-web-mvp/`：当前常用 Web 工作区，里面放运行时项目，不属于源码仓库。

典型项目目录结构：

- `project.yaml`：项目配置、provider、workflow、remote profile。
- `shots.json`：分镜内容。
- `manifest.json`：生成结果、任务状态、资产引用。
- `assets/refs/`：首帧、参考图等输入资产。
- `generated/`：视频、音频、口型同步等中间产物。
- `renders/final.mp4`：最终合成视频。

## 核心模块

- `models.py`：项目、分镜、provider 等数据结构。
- `project.py`：项目加载、保存和路径处理。
- `templates.py`：项目模板，包括 AutoDL ComfyUI Wan 模板。
- `novel.py`：小说章节生产档案生成、人物/场景/分镜草稿生成。
- `novel_analyzer.py`：调用 Codex/GPT 进行章节理解与结构化规划。
- `script_storyboard.py`：脚本到分镜的转换逻辑。
- `prompts.py` / `first_frame_prompt.py`：提示词与首帧提示词构建。
- `first_frame_generation.py`：首帧生成任务。
- `asset_library.py`：素材库和素材引用。
- `job_builder.py`：根据项目生成 video/audio/lipsync 等 provider job。
- `job_store.py` / `jobs.py`：任务记录、提交和状态管理。
- `providers/`：mock、external command、local TTS 等 provider 实现。
- `comfyui_wan_adapter.py`：AutoDL/ComfyUI Wan 视频生成适配器。
- `comfyui_lipsync_adapter.py`：ComfyUI 口型同步适配器。
- `comfyui_image_adapter.py`：ComfyUI 图片/首帧适配器。
- `render.py`：最终视频合成。
- `probe.py` / `media_quality.py`：媒体探测和质量检查。
- `shot_policy.py`：分镜媒体选择策略。当前关键规则：只有对白/人物说话镜头才优先使用 lipsync 输出，旁白和动作镜头应使用原始视频，避免被 4 秒口型同步结果截断。
- `web.py`：Web API 和静态服务。
- `web_tasks.py`：Web 任务状态、进度、暂停/恢复等持久化任务逻辑。
- `workflow_registry.py`：ComfyUI workflow 注册和节点映射。
- `remote_*` / `worker_*`：远程 GPU 执行、worker bundle、导出/导入和诊断。

## 常用命令

初始化开发环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

运行测试：

```bash
.venv/bin/python -m pytest -q
```

前端构建：

```bash
cd frontend
npm install
npm run build
```

启动 Web 控制台：

```bash
.venv/bin/python -m auto_video web --workspace /tmp/auto-video-web-mvp --host 0.0.0.0 --port 8765
```

创建 AutoDL ComfyUI Wan 项目：

```bash
.venv/bin/python -m auto_video init wan_story --template autodl_comfyui_wan
```

典型生产流程：

```bash
.venv/bin/python -m auto_video validate /tmp/auto-video-web-mvp/wan_story
.venv/bin/python -m auto_video remote run /tmp/auto-video-web-mvp/wan_story --profile autodl_5090 --provider comfyui_wan --kind video --skip-succeeded
.venv/bin/python -m auto_video audio /tmp/auto-video-web-mvp/wan_story --provider local_tts --skip-succeeded
.venv/bin/python -m auto_video remote run /tmp/auto-video-web-mvp/wan_story --profile autodl_5090 --provider comfyui_lipsync --kind lipsync --skip-succeeded
.venv/bin/python -m auto_video probe /tmp/auto-video-web-mvp/wan_story --strict
.venv/bin/python -m auto_video assemble /tmp/auto-video-web-mvp/wan_story
```

## 当前产品流程

Web 控制台面向中文使用，主流程大致为：

1. 新建项目或选择已有项目。
2. 在“小说章节”粘贴本章正文。
3. 让 Codex 自动分析章节，生成章节生产档案。
4. 检查人物与音色、场景风格、分镜数量、提示词设定。
5. 应用为项目分镜。
6. 生成首帧素材。
7. 提交视频生成任务。
8. 生成配音。
9. 执行口型同步。
10. 探测媒体质量。
11. 合成最终视频。
12. 在成片审看/分镜审查里查看并重做不满意镜头。

任务进度必须能跨刷新保留。新增长耗时功能时，应接入 `web_tasks.py` 或现有任务状态机制，不要只放在 React 本地状态里。

## 关键设计约束

- 不要把 AutoDL SSH 密码、Token、Cookie 写入仓库。
- Web UI 应优先使用中文，操作状态要明确展示“当前模块、当前步骤、进度、是否可暂停、是否可查看已生成结果”。
- 生成任务必须支持断点续跑，优先使用 `--skip-succeeded` 或 manifest 中已有结果。
- 对真实视频质量敏感的改动，应同时更新 probe/render/job tests。
- 不要让 lipsync 输出覆盖所有镜头。旁白镜头、纯场景镜头、无口型需求镜头应保留原始视频时长。
- 前端改动后必须构建，并提交 `src/auto_video/web_static`。
- 运行时项目通常在 `/tmp/auto-video-web-mvp`，不要误把大型生成视频、音频、中间素材加入 Git。
- 如果需要云端 GPU，优先走 remote/worker/provider 机制，而不是在业务代码里硬编码机器地址。

## 测试建议

后端通用检查：

```bash
.venv/bin/python -m pytest -q
```

改动分镜、渲染、口型策略时至少跑：

```bash
.venv/bin/python -m pytest tests/test_job_builder.py tests/test_render_probe.py tests/test_novel.py tests/test_web.py -q
```

改动前端时至少跑：

```bash
cd frontend
npm run build
```

## 当前已知质量短板

当前系统已经能完成“章节 -> 分镜 -> 任务 -> 合成”的链路，但成片质量还需要继续提高：

- 首帧质量门禁不足，可能出现灰墙、空场景、低信息量首帧。
- 人物一致性还需要更强的参考图、角色卡、LoRA/IP-Adapter/FaceID 类方案。
- 场景一致性需要场景参考图和风格档案，而不只是文字描述。
- 服装需要和场景、时间、人物身份绑定，后续章节复用时不能漂移。
- 分镜提示词需要更明确地绑定人物、场景、动作、表情、镜头、服装、对白对象。
- 像素级口型同步依赖具体 ComfyUI 口型驱动 workflow，当前项目只提供适配层和任务链路。
- 成片审看还应继续加强：每个分镜可查看首帧、原视频、配音、口型结果、最终片段，并支持单镜头重做。

## 推荐下一阶段

优先做“质量门禁 + 单镜头重做”：

1. 为首帧和视频增加自动 QC 分数。
2. 低分镜头自动标记为待重做，不直接进入最终合成。
3. 在 Web UI 中展示每个分镜的首帧、视频、配音、口型同步结果。
4. 支持对单个分镜重新生成首帧、视频、配音或口型同步。
5. 把人物参考图和场景参考图纳入每个镜头的生成输入。

这比继续盲目跑整章视频更重要，因为它能把不可控的生成结果变成可审查、可修复的生产流程。
