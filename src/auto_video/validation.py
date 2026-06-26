from __future__ import annotations

from .errors import AssetError, ConfigError
from .models import BUILTIN_PROVIDERS, Project
from .project import resolve_project_path


def validate_project(project: Project) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    if project.config.width <= 0 or project.config.height <= 0:
        raise ConfigError("width and height must be positive", fix="Set positive render dimensions.")
    if project.config.fps <= 0:
        raise ConfigError("fps must be positive", fix="Set fps to a positive integer.")
    configured_providers = BUILTIN_PROVIDERS | set(project.config.providers)
    for shot in project.shots:
        if shot.id in seen:
            raise ConfigError(f"duplicate shot id {shot.id}", fix="Use unique shot ids.")
        seen.add(shot.id)
        if not shot.visual_prompt and not shot.refs:
            raise ConfigError(
                f"shot {shot.id} needs visual_prompt or refs",
                fix="Add a visual_prompt or at least one reference asset.",
            )
        if shot.provider and shot.provider not in configured_providers:
            allowed_list = ", ".join(sorted(configured_providers))
            raise ConfigError(
                f"shot {shot.id} provider has unsupported provider {shot.provider!r}",
                fix=f"Use one of: {allowed_list}.",
            )
        for index, ref in enumerate(shot.refs):
            path = resolve_project_path(project.config.root, ref.path)
            if not path.exists():
                raise AssetError(
                    f"shot {shot.id} refs[{index}].path not found: {ref.path}",
                    fix="Place the file at that path or update shots.json.",
                )
    return warnings
