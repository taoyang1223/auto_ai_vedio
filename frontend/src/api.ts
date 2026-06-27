import axios from "axios";
import type {
  ApiEnvelope,
  AssetLibraryItem,
  AssetRef,
  AssetUploadPayload,
  ComfyCheck,
  FirstFramePrompt,
  PromptProfile,
  ProjectDetail,
  ProjectSummary,
  RemoteProfilePayload,
  ScriptDraftPayload,
  ScriptDraftResult,
  Shot,
  TemplateInfo,
  WebTask,
  WorkflowSettingsPayload
} from "./types";

const client = axios.create({
  headers: { "Content-Type": "application/json" },
  withCredentials: true
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const payload = error.response?.data;
    const message = payload?.fix ? `${payload.error}\n${payload.fix}` : payload?.error || error.message;
    throw new Error(message);
  }
);

export async function fetchTemplates(): Promise<TemplateInfo[]> {
  const { data } = await client.get<ApiEnvelope<{ templates: TemplateInfo[] }>>("/api/templates");
  return data.templates;
}

export async function fetchAuthStatus(): Promise<{ enabled: boolean; authenticated: boolean }> {
  const { data } = await client.get<ApiEnvelope<{ enabled: boolean; authenticated: boolean }>>("/api/auth/status");
  return { enabled: data.enabled, authenticated: data.authenticated };
}

export async function login(token: string): Promise<{ enabled: boolean; authenticated: boolean }> {
  const { data } = await client.post<ApiEnvelope<{ enabled: boolean; authenticated: boolean }>>("/api/auth/login", { token });
  return { enabled: data.enabled, authenticated: data.authenticated };
}

export async function logout(): Promise<void> {
  await client.post("/api/auth/logout", {});
}

export async function fetchProjects(): Promise<{ workspace: string; projects: ProjectSummary[] }> {
  const { data } = await client.get<ApiEnvelope<{ workspace: string; projects: ProjectSummary[] }>>("/api/projects");
  return { workspace: data.workspace, projects: data.projects };
}

export async function createProject(name: string, template: string): Promise<ProjectSummary> {
  const { data } = await client.post<ApiEnvelope<{ project: ProjectSummary }>>("/api/projects", { name, template });
  return data.project;
}

export async function deleteProject(name: string): Promise<string> {
  const { data } = await client.delete<ApiEnvelope<{ deleted: string }>>(`/api/projects/${encodeURIComponent(name)}`);
  return data.deleted;
}

export async function fetchProject(name: string): Promise<ProjectDetail> {
  const { data } = await client.get<ApiEnvelope<{ project: ProjectDetail }>>(`/api/projects/${encodeURIComponent(name)}`);
  return data.project;
}

export async function fetchConfig(name: string): Promise<string> {
  const { data } = await client.get<ApiEnvelope<{ text: string }>>(`/api/projects/${encodeURIComponent(name)}/config`);
  return data.text;
}

export async function saveConfig(name: string, text: string): Promise<ProjectDetail> {
  const { data } = await client.put<ApiEnvelope<{ project: ProjectDetail }>>(`/api/projects/${encodeURIComponent(name)}/config`, { text });
  return data.project;
}

export async function saveShots(name: string, shots: unknown[]): Promise<ProjectDetail> {
  const { data } = await client.put<ApiEnvelope<{ project: ProjectDetail }>>(`/api/projects/${encodeURIComponent(name)}/shots`, { shots });
  return data.project;
}

export async function fetchAssets(name: string): Promise<AssetLibraryItem[]> {
  const { data } = await client.get<ApiEnvelope<{ assets: AssetLibraryItem[] }>>(`/api/projects/${encodeURIComponent(name)}/assets`);
  return data.assets;
}

export async function uploadAsset(name: string, payload: AssetUploadPayload): Promise<AssetLibraryItem[]> {
  const { data } = await client.post<ApiEnvelope<{ assets: AssetLibraryItem[] }>>(`/api/projects/${encodeURIComponent(name)}/assets`, payload);
  return data.assets;
}

export async function saveShotRefs(name: string, shotId: string, refs: AssetRef[]): Promise<{ project: ProjectDetail; assets: AssetLibraryItem[] }> {
  const { data } = await client.put<ApiEnvelope<{ project: ProjectDetail; assets: AssetLibraryItem[] }>>(
    `/api/projects/${encodeURIComponent(name)}/shot-refs`,
    { shot_id: shotId, refs }
  );
  return { project: data.project, assets: data.assets };
}

export async function deleteAsset(name: string, assetId: string): Promise<{ project: ProjectDetail; assets: AssetLibraryItem[] }> {
  const { data } = await client.delete<ApiEnvelope<{ project: ProjectDetail; assets: AssetLibraryItem[] }>>(
    `/api/projects/${encodeURIComponent(name)}/assets/${encodeURIComponent(assetId)}`
  );
  return { project: data.project, assets: data.assets };
}

export async function fetchFirstFramePrompts(name: string): Promise<FirstFramePrompt[]> {
  const { data } = await client.get<ApiEnvelope<{ prompts: FirstFramePrompt[] }>>(
    `/api/projects/${encodeURIComponent(name)}/first-frame-prompts`
  );
  return data.prompts;
}

export async function saveFirstFramePrompts(name: string, prompts: FirstFramePrompt[]): Promise<FirstFramePrompt[]> {
  const { data } = await client.put<ApiEnvelope<{ prompts: FirstFramePrompt[] }>>(
    `/api/projects/${encodeURIComponent(name)}/first-frame-prompts`,
    {
      prompts: prompts.map((prompt) => ({
        shot_id: prompt.shot_id,
        prompt: prompt.prompt,
        negative_prompt: prompt.negative_prompt
      }))
    }
  );
  return data.prompts;
}

export async function updatePromptProfile(name: string, payload: PromptProfile): Promise<ProjectDetail> {
  const { data } = await client.put<ApiEnvelope<{ project: ProjectDetail }>>(
    `/api/projects/${encodeURIComponent(name)}/prompt-profile`,
    payload
  );
  return data.project;
}

export async function draftScriptStoryboard(name: string, payload: ScriptDraftPayload): Promise<ScriptDraftResult> {
  const { data } = await client.post<ApiEnvelope<ScriptDraftResult>>(
    `/api/projects/${encodeURIComponent(name)}/script-draft`,
    payload
  );
  return { shots: data.shots, source_segments: data.source_segments, meta: data.meta };
}

export async function applyScriptStoryboard(name: string, shots: Shot[]): Promise<ProjectDetail> {
  const { data } = await client.post<ApiEnvelope<{ project: ProjectDetail }>>(
    `/api/projects/${encodeURIComponent(name)}/script-apply`,
    { shots }
  );
  return data.project;
}

export async function uploadFirstFrame(name: string, shotId: string, file: File): Promise<ProjectDetail> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
  const { data } = await client.post<ApiEnvelope<{ project: ProjectDetail }>>(`/api/projects/${encodeURIComponent(name)}/first-frame`, {
    shot_id: shotId,
    filename: file.name,
    data_url: dataUrl
  });
  return data.project;
}

export async function checkComfyWorkflow(name: string, profile: string, kind?: string): Promise<ComfyCheck> {
  const { data } = await client.post<ApiEnvelope<{ result: ComfyCheck }>>(`/api/projects/${encodeURIComponent(name)}/workflow-check`, {
    profile,
    kind,
    require_idle: false,
    require_gpu: true
  });
  return data.result;
}

export async function updateWorkflowSettings(name: string, profile: string, payload: WorkflowSettingsPayload): Promise<ProjectDetail> {
  const { data } = await client.put<ApiEnvelope<{ project: ProjectDetail }>>(
    `/api/projects/${encodeURIComponent(name)}/workflows/${encodeURIComponent(profile)}`,
    payload
  );
  return data.project;
}

export async function updateRemoteProfile(name: string, profile: string, payload: RemoteProfilePayload): Promise<ProjectDetail> {
  const { data } = await client.put<ApiEnvelope<{ project: ProjectDetail }>>(
    `/api/projects/${encodeURIComponent(name)}/remote-profiles/${encodeURIComponent(profile)}`,
    payload
  );
  return data.project;
}

export async function enqueueProjectTask(
  name: string,
  action: string,
  payload: Record<string, unknown> = {},
  label?: string
): Promise<WebTask> {
  const { data } = await client.post<ApiEnvelope<{ task: WebTask }>>(`/api/projects/${encodeURIComponent(name)}/tasks`, {
    action,
    label,
    payload
  });
  return data.task;
}

export async function fetchProjectTasks(name: string): Promise<WebTask[]> {
  const { data } = await client.get<ApiEnvelope<{ tasks: WebTask[] }>>(`/api/projects/${encodeURIComponent(name)}/tasks`);
  return data.tasks;
}

export async function fetchTask(id: string): Promise<WebTask> {
  const { data } = await client.get<ApiEnvelope<{ task: WebTask }>>(`/api/tasks/${encodeURIComponent(id)}`);
  return data.task;
}

export async function cancelTask(id: string): Promise<WebTask> {
  const { data } = await client.post<ApiEnvelope<{ task: WebTask }>>(`/api/tasks/${encodeURIComponent(id)}/cancel`, {});
  return data.task;
}
