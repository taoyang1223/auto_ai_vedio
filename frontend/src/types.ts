export type TemplateInfo = {
  name: string;
  description: string;
};

export type ProjectSummary = {
  name: string;
  title?: string;
  path: string;
  shots?: number;
  provider?: string;
  workflows?: number;
  remote_profiles?: number;
  error?: string;
  fix?: string;
};

export type AssetRef = {
  path: string;
  type: string;
  role: string;
  usage: string;
};

export type Shot = {
  id: string;
  title: string;
  duration: number;
  intent?: string;
  provider?: string;
  visual_prompt: string;
  camera_motion: string;
  environment_motion: string;
  performance: string;
  lighting: string;
  audio_intent?: string;
  subtitle: string;
  negative_prompt: string;
  refs: AssetRef[];
  manifest?: Record<string, unknown>;
};

export type WorkflowSummary = {
  name: string;
  title: string;
  provider: string;
  kind: string;
  workflow_path?: string;
  base_url?: string;
  base_url_env: string;
  workflow_env: string;
  profile_env: string;
  tags: string[];
};

export type WorkflowSettingsPayload = {
  base_url?: string;
  workflow_path?: string;
  workflow_json?: string;
  workflow_filename?: string;
};

export type RemoteProfileSummary = {
  name: string;
  host: string;
  remote_dir: string;
  local_dir: string;
  remote_auto_video: string;
  ssh_port: string;
  ssh_options: string[];
  rsync_options: string[];
  remote_env: Record<string, string>;
};

export type RemoteProfilePayload = {
  host?: string;
  remote_dir?: string;
  local_dir?: string;
  remote_auto_video?: string;
  ssh_port?: string;
};

export type PromptProfile = {
  subject: string;
  character: string;
  setting: string;
  visual_style: string;
  camera_style: string;
  motion_style: string;
  lighting_style: string;
  continuity: string;
  negative: string;
};

export type ScriptDraftPayload = {
  script: string;
  shot_count: number;
  duration: number;
  provider?: string;
};

export type ScriptDraftResult = {
  shots: Shot[];
  source_segments: string[];
  meta: {
    shot_count: number;
    duration: number;
    provider: string;
  };
};

export type RenderSummary = {
  status?: string;
  path?: string;
  command?: string[];
};

export type ProjectDetail = ProjectSummary & {
  config: {
    aspect_ratio: string;
    width: number;
    height: number;
    fps: number;
    default_video_provider: string;
  };
  prompt_profile: PromptProfile;
  shots_detail: Shot[];
  remote_profiles_detail: RemoteProfileSummary[];
  workflows_detail: WorkflowSummary[];
  renders: Record<string, RenderSummary>;
};

export type ApiEnvelope<T> = T & {
  ok: boolean;
};

export type WebTaskLog = {
  at: string;
  message: string;
};

export type WebTaskStatus = "queued" | "running" | "succeeded" | "failed" | "canceled";

export type WebTask = {
  id: string;
  project: string;
  action: string;
  label: string;
  payload: Record<string, unknown>;
  status: WebTaskStatus;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  fix?: string | null;
  logs: WebTaskLog[];
  result?: unknown;
};

export type ComfyCheck = {
  ok: boolean;
  profile: string;
  base_url: string;
  workflow: string;
  checks: Array<{
    name: string;
    status: "ok" | "warning" | "failed";
    message: string;
    fix?: string;
    details?: Record<string, unknown>;
  }>;
};
