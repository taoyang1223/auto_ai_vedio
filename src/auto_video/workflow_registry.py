from __future__ import annotations

from typing import Any

from .errors import ConfigError
from .models import Project


WORKFLOW_PROFILE_ENV = "COMFYUI_WORKFLOW_PROFILE"


def list_workflows(project: Project) -> list[dict[str, Any]]:
    return [_summary(name, raw) for name, raw in sorted(project.config.comfyui_workflows.items())]


def get_workflow(project: Project, name: str) -> dict[str, Any]:
    workflows = project.config.comfyui_workflows
    if name in workflows:
        return workflows[name]
    allowed = ", ".join(sorted(workflows)) or "(none configured)"
    raise ConfigError(f"unknown ComfyUI workflow profile {name!r}", fix=f"Use one of: {allowed}.")


def show_workflow(project: Project, name: str) -> dict[str, Any]:
    raw = get_workflow(project, name)
    return {"name": name, **raw}


def workflow_env(project: Project, name: str) -> dict[str, str]:
    raw = get_workflow(project, name)
    env: dict[str, str] = {}
    base_url_env = str(raw.get("base_url_env") or "COMFYUI_BASE_URL")
    workflow_env_name = str(raw.get("workflow_env") or "COMFYUI_WORKFLOW")
    profile_env_name = str(raw.get("profile_env") or WORKFLOW_PROFILE_ENV)
    if raw.get("base_url"):
        env[base_url_env] = str(raw["base_url"])
    if raw.get("workflow_path"):
        env[workflow_env_name] = str(raw["workflow_path"])
    env[profile_env_name] = name
    extra_env = raw.get("env") or {}
    if not isinstance(extra_env, dict):
        raise ConfigError(f"workflow {name} env must be a mapping", fix="Use NAME: value pairs under env.")
    for key, value in extra_env.items():
        env[str(key)] = str(value)
    return env


def workflow_env_exports(project: Project, name: str) -> list[str]:
    return [f"{key}={value}" for key, value in workflow_env(project, name).items()]


def comfyui_wan_adapter_options(project: Project, name: str) -> dict[str, Any]:
    raw = get_workflow(project, name)
    options = _base_adapter_options(raw)

    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ConfigError(f"workflow {name} parameters must be a mapping", fix="Use key/value parameters.")
    _copy(parameters, options, "seed", "seed")
    _copy(parameters, options, "steps", "steps")
    _copy(parameters, options, "guidance_scale", "guidance_scale")
    _copy(parameters, options, "resolution", "resolution")

    nodes = raw.get("nodes") or {}
    if not isinstance(nodes, dict):
        raise ConfigError(f"workflow {name} nodes must be a mapping", fix="Use named node mappings.")
    _node(nodes, options, "prompt", "prompt_node", "prompt_input")
    _node(nodes, options, "negative", "negative_node", "negative_input")
    _node(nodes, options, "image", "image_node", "image_input")
    _node(nodes, options, "seed", "seed_node", "seed_input")
    _node(nodes, options, "duration", "duration_node", "duration_input")
    _node(nodes, options, "resolution", "resolution_node", "resolution_input")
    _video_node(nodes, options)
    _steps_node(nodes, options)
    return options


def comfyui_image_adapter_options(project: Project, name: str) -> dict[str, Any]:
    raw = get_workflow(project, name)
    options = _base_adapter_options(raw)

    parameters = raw.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ConfigError(f"workflow {name} parameters must be a mapping", fix="Use key/value parameters.")
    _copy(parameters, options, "seed", "seed")
    _copy(parameters, options, "steps", "steps")
    _copy(parameters, options, "guidance_scale", "guidance_scale")

    nodes = raw.get("nodes") or {}
    if not isinstance(nodes, dict):
        raise ConfigError(f"workflow {name} nodes must be a mapping", fix="Use named node mappings.")
    _node(nodes, options, "prompt", "prompt_node", "prompt_input")
    _node(nodes, options, "negative", "negative_node", "negative_input")
    _node(nodes, options, "seed", "seed_node", "seed_input")
    _size_node(nodes, options)
    _output_node(nodes, options)
    _steps_node(nodes, options)
    return options


def _base_adapter_options(raw: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    _copy(raw, options, "base_url", "base_url")
    _copy(raw, options, "base_url_env", "base_url_env")
    _copy(raw, options, "workflow_path", "workflow")
    _copy(raw, options, "workflow_env", "workflow_env")
    return options


def _summary(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "title": str(raw.get("title") or name),
        "provider": str(raw.get("provider") or "comfyui_wan"),
        "kind": str(raw.get("kind") or "image_to_video"),
        "workflow_path": raw.get("workflow_path"),
        "base_url": raw.get("base_url"),
        "base_url_env": str(raw.get("base_url_env") or "COMFYUI_BASE_URL"),
        "workflow_env": str(raw.get("workflow_env") or "COMFYUI_WORKFLOW"),
        "profile_env": str(raw.get("profile_env") or WORKFLOW_PROFILE_ENV),
        "tags": _string_list(raw.get("tags")),
    }


def _copy(source: dict[str, Any], target: dict[str, Any], source_key: str, target_key: str) -> None:
    value = source.get(source_key)
    if value is not None:
        target[target_key] = value


def _node(
    nodes: dict[str, Any],
    options: dict[str, Any],
    name: str,
    node_arg: str,
    input_arg: str,
) -> None:
    raw = nodes.get(name)
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ConfigError(f"workflow node {name} must be a mapping", fix="Use id and input fields.")
    if raw.get("id") is not None:
        options[node_arg] = str(raw["id"])
    if raw.get("input") is not None:
        options[input_arg] = str(raw["input"])


def _video_node(nodes: dict[str, Any], options: dict[str, Any]) -> None:
    raw = nodes.get("video")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ConfigError("workflow node video must be a mapping", fix="Use id and input fields.")
    if raw.get("id") is not None:
        options["video_node"] = str(raw["id"])
    if raw.get("frame_rate_input") is not None:
        options["frame_rate_input"] = str(raw["frame_rate_input"])
    if raw.get("filename_prefix_input") is not None:
        options["filename_prefix_input"] = str(raw["filename_prefix_input"])


def _steps_node(nodes: dict[str, Any], options: dict[str, Any]) -> None:
    raw = nodes.get("steps")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ConfigError("workflow node steps must be a mapping", fix="Use ids and input fields.")
    if raw.get("ids") is not None:
        values = raw["ids"]
        if not isinstance(values, list) or not all(isinstance(value, str | int) for value in values):
            raise ConfigError("workflow steps.ids must be a list", fix="Use a list of ComfyUI node ids.")
        options["steps_node"] = [str(value) for value in values]
    if raw.get("steps_input") is not None:
        options["steps_input"] = str(raw["steps_input"])
    if raw.get("cfg_input") is not None:
        options["cfg_input"] = str(raw["cfg_input"])


def _size_node(nodes: dict[str, Any], options: dict[str, Any]) -> None:
    raw = nodes.get("size")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ConfigError("workflow node size must be a mapping", fix="Use id, width_input, and height_input fields.")
    if raw.get("id") is not None:
        options["size_node"] = str(raw["id"])
    if raw.get("width_input") is not None:
        options["width_input"] = str(raw["width_input"])
    if raw.get("height_input") is not None:
        options["height_input"] = str(raw["height_input"])


def _output_node(nodes: dict[str, Any], options: dict[str, Any]) -> None:
    raw = nodes.get("output")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ConfigError("workflow node output must be a mapping", fix="Use id and filename_prefix_input fields.")
    if raw.get("id") is not None:
        options["output_node"] = str(raw["id"])
    if raw.get("filename_prefix_input") is not None:
        options["filename_prefix_input"] = str(raw["filename_prefix_input"])


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError("workflow tags must be a list", fix="Use a YAML list of tags.")
    return [str(item) for item in value]
