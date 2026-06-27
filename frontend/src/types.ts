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

export type ProjectDetail = ProjectSummary & {
  config: {
    aspect_ratio: string;
    width: number;
    height: number;
    fps: number;
    default_video_provider: string;
  };
  shots_detail: Shot[];
  remote_profiles_detail: string[];
  workflows_detail: WorkflowSummary[];
  renders: Record<string, unknown>;
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
