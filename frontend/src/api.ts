import axios from "axios";
import type { ApiEnvelope, ProjectDetail, ProjectSummary, TemplateInfo, WebTask } from "./types";

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
