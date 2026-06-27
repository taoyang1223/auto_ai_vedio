import { create } from "zustand";
import {
  cancelTask,
  createProject,
  deleteProject,
  enqueueProjectTask,
  fetchAuthStatus,
  fetchConfig,
  fetchProject,
  fetchProjects,
  fetchProjectTasks,
  fetchTask,
  fetchTemplates,
  login,
  logout,
  saveConfig,
  saveShots,
  uploadFirstFrame
} from "./api";
import type { ProjectDetail, ProjectSummary, Shot, TemplateInfo, WebTask } from "./types";

type AppState = {
  workspace: string;
  templates: TemplateInfo[];
  projects: ProjectSummary[];
  activeProject: string | null;
  detail: ProjectDetail | null;
  configText: string;
  loading: boolean;
  message: string;
  tasks: WebTask[];
  authEnabled: boolean;
  authenticated: boolean;
  boot: () => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logoutSession: () => Promise<void>;
  selectProject: (name: string) => Promise<void>;
  createNewProject: (name: string, template: string) => Promise<void>;
  deleteExistingProject: (name: string) => Promise<string | null>;
  setShots: (shots: Shot[]) => void;
  persistShots: () => Promise<void>;
  persistConfig: (text: string) => Promise<void>;
  uploadFrame: (shotId: string, file: File) => Promise<void>;
  refreshProjects: () => Promise<void>;
  refreshTasks: (project?: string) => Promise<void>;
  enqueueTask: (project: string, action: string, payload?: Record<string, unknown>, label?: string) => Promise<WebTask>;
  loadTask: (id: string) => Promise<WebTask>;
  cancelQueuedTask: (id: string) => Promise<void>;
  setMessage: (message: string) => void;
};

export const useAppStore = create<AppState>((set, get) => ({
  workspace: "",
  templates: [],
  projects: [],
  activeProject: null,
  detail: null,
  configText: "",
  loading: false,
  message: "",
  tasks: [],
  authEnabled: false,
  authenticated: true,

  boot: async () => {
    set({ loading: true });
    const auth = await fetchAuthStatus();
    set({ authEnabled: auth.enabled, authenticated: auth.authenticated });
    if (auth.enabled && !auth.authenticated) {
      set({ loading: false });
      return;
    }
    const [templates, projectsPayload] = await Promise.all([fetchTemplates(), fetchProjects()]);
    set({
      templates,
      workspace: projectsPayload.workspace,
      projects: projectsPayload.projects,
      loading: false
    });
    const active = get().activeProject || projectsPayload.projects[0]?.name;
    if (active) await get().selectProject(active);
  },

  loginWithToken: async (token: string) => {
    set({ loading: true });
    try {
      const auth = await login(token);
      set({ authEnabled: auth.enabled, authenticated: auth.authenticated });
      await get().boot();
    } finally {
      set({ loading: false });
    }
  },

  logoutSession: async () => {
    await logout();
    set({
      activeProject: null,
      authenticated: false,
      configText: "",
      detail: null,
      projects: [],
      tasks: [],
      templates: [],
      workspace: ""
    });
  },

  refreshProjects: async () => {
    const payload = await fetchProjects();
    set({ workspace: payload.workspace, projects: payload.projects });
  },

  selectProject: async (name: string) => {
    set({ loading: true, activeProject: name });
    const [detail, configText, tasks] = await Promise.all([fetchProject(name), fetchConfig(name), fetchProjectTasks(name)]);
    set({ detail, configText, tasks, loading: false, message: "" });
  },

  createNewProject: async (name: string, template: string) => {
    set({ loading: true });
    await createProject(name, template);
    const projectsPayload = await fetchProjects();
    set({ workspace: projectsPayload.workspace, projects: projectsPayload.projects, activeProject: name, loading: false });
    await get().selectProject(name);
  },

  deleteExistingProject: async (name: string) => {
    set({ loading: true });
    try {
      await deleteProject(name);
      const projectsPayload = await fetchProjects();
      const next = projectsPayload.projects.find((project) => project.name !== name)?.name || null;
      set({
        activeProject: next,
        configText: "",
        detail: null,
        loading: false,
        projects: projectsPayload.projects,
        tasks: [],
        workspace: projectsPayload.workspace
      });
      if (next) {
        await get().selectProject(next);
      }
      return next;
    } catch (error) {
      set({ loading: false });
      throw error;
    }
  },

  setShots: (shots: Shot[]) => {
    const detail = get().detail;
    if (!detail) return;
    set({ detail: { ...detail, shots_detail: shots } });
  },

  persistShots: async () => {
    const { activeProject, detail } = get();
    if (!activeProject || !detail) return;
    const clean = detail.shots_detail.map(({ manifest, ...shot }) => shot);
    const saved = await saveShots(activeProject, clean);
    set({ detail: saved, message: "分镜已保存" });
    await get().refreshProjects();
  },

  persistConfig: async (text: string) => {
    const activeProject = get().activeProject;
    if (!activeProject) return;
    const saved = await saveConfig(activeProject, text);
    set({ detail: saved, configText: text, message: "配置已保存" });
    await get().refreshProjects();
  },

  uploadFrame: async (shotId: string, file: File) => {
    const activeProject = get().activeProject;
    if (!activeProject) return;
    const saved = await uploadFirstFrame(activeProject, shotId, file);
    set({ detail: saved, message: "首帧已更新" });
  },

  refreshTasks: async (project?: string) => {
    const name = project || get().activeProject;
    if (!name) return;
    const tasks = await fetchProjectTasks(name);
    set({ tasks });
  },

  enqueueTask: async (project: string, action: string, payload: Record<string, unknown> = {}, label?: string) => {
    const task = await enqueueProjectTask(project, action, payload, label);
    set({ tasks: [task, ...get().tasks.filter((item) => item.id !== task.id)] });
    return task;
  },

  loadTask: async (id: string) => {
    const task = await fetchTask(id);
    const current = get().tasks;
    const exists = current.some((item) => item.id === id);
    set({ tasks: exists ? current.map((item) => (item.id === id ? task : item)) : [task, ...current] });
    return task;
  },

  cancelQueuedTask: async (id: string) => {
    const task = await cancelTask(id);
    set({ tasks: get().tasks.map((item) => (item.id === id ? task : item)) });
  },

  setMessage: (message: string) => set({ message })
}));
