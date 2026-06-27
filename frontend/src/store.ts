import { create } from "zustand";
import {
  applyScriptStoryboard,
  cancelTask,
  createProject,
  deleteAsset,
  deleteProject,
  draftScriptStoryboard,
  enqueueProjectTask,
  fetchAuthStatus,
  fetchConfig,
  fetchFirstFramePrompts,
  fetchProject,
  fetchProjects,
  fetchProjectTasks,
  fetchTask,
  fetchTemplates,
  login,
  logout,
  saveConfig,
  saveFirstFramePrompts,
  saveShots,
  saveShotRefs,
  updatePromptProfile,
  updateRemoteProfile,
  updateWorkflowSettings,
  uploadFirstFrame
} from "./api";
import type {
  ProjectDetail,
  ProjectSummary,
  AssetRef,
  AssetLibraryItem,
  FirstFramePrompt,
  PromptProfile,
  RemoteProfilePayload,
  ScriptDraftPayload,
  ScriptDraftResult,
  Shot,
  TemplateInfo,
  WebTask,
  WorkflowSettingsPayload
} from "./types";

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
  savePromptProfile: (payload: PromptProfile) => Promise<ProjectDetail>;
  draftScriptShots: (payload: ScriptDraftPayload) => Promise<ScriptDraftResult>;
  applyScriptShots: (shots: Shot[]) => Promise<ProjectDetail>;
  saveAssetRefs: (shotId: string, refs: AssetRef[]) => Promise<AssetLibraryItem[]>;
  removeAsset: (assetId: string) => Promise<AssetLibraryItem[]>;
  loadFirstFramePrompts: () => Promise<FirstFramePrompt[]>;
  saveFirstFrameDrafts: (prompts: FirstFramePrompt[]) => Promise<FirstFramePrompt[]>;
  saveWorkflowSettings: (profile: string, payload: WorkflowSettingsPayload) => Promise<ProjectDetail>;
  saveRemoteProfile: (profile: string, payload: RemoteProfilePayload) => Promise<ProjectDetail>;
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
    try {
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
      const current = get().activeProject;
      const active = projectsPayload.projects.some((project) => project.name === current) ? current : projectsPayload.projects[0]?.name;
      if (active) await get().selectProject(active);
    } catch (error) {
      set({ loading: false });
      throw error;
    }
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
    set({ loading: true });
    try {
      const [detail, configText, tasks] = await Promise.all([fetchProject(name), fetchConfig(name), fetchProjectTasks(name)]);
      set({ activeProject: name, detail, configText, tasks, loading: false, message: "" });
    } catch (error) {
      set({ loading: false });
      throw error;
    }
  },

  createNewProject: async (name: string, template: string) => {
    set({ loading: true });
    try {
      await createProject(name, template);
      const projectsPayload = await fetchProjects();
      set({ workspace: projectsPayload.workspace, projects: projectsPayload.projects, loading: false });
      await get().selectProject(name);
    } catch (error) {
      set({ loading: false });
      throw error;
    }
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

  savePromptProfile: async (payload: PromptProfile) => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    const saved = await updatePromptProfile(activeProject, payload);
    const configText = await fetchConfig(activeProject);
    set({ detail: saved, configText, message: "提示词设定已保存" });
    await get().refreshProjects();
    return saved;
  },

  draftScriptShots: async (payload: ScriptDraftPayload) => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    return draftScriptStoryboard(activeProject, payload);
  },

  applyScriptShots: async (shots: Shot[]) => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    const saved = await applyScriptStoryboard(activeProject, shots);
    set({ detail: saved, message: "脚本分镜已应用" });
    await get().refreshProjects();
    return saved;
  },

  saveAssetRefs: async (shotId: string, refs: AssetRef[]) => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    const saved = await saveShotRefs(activeProject, shotId, refs);
    set({ detail: saved.project, message: "分镜素材引用已保存" });
    return saved.assets;
  },

  removeAsset: async (assetId: string) => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    const saved = await deleteAsset(activeProject, assetId);
    set({ detail: saved.project, message: "素材已移除" });
    return saved.assets;
  },

  loadFirstFramePrompts: async () => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    return fetchFirstFramePrompts(activeProject);
  },

  saveFirstFrameDrafts: async (prompts: FirstFramePrompt[]) => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    const saved = await saveFirstFramePrompts(activeProject, prompts);
    set({ message: "首帧提示词已保存" });
    return saved;
  },

  saveWorkflowSettings: async (profile: string, payload: WorkflowSettingsPayload) => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    const saved = await updateWorkflowSettings(activeProject, profile, payload);
    const configText = await fetchConfig(activeProject);
    set({ detail: saved, configText, message: "工作流配置已保存" });
    await get().refreshProjects();
    return saved;
  },

  saveRemoteProfile: async (profile: string, payload: RemoteProfilePayload) => {
    const activeProject = get().activeProject;
    if (!activeProject) throw new Error("未选择项目");
    const saved = await updateRemoteProfile(activeProject, profile, payload);
    const configText = await fetchConfig(activeProject);
    set({ detail: saved, configText, message: "远程配置已保存" });
    await get().refreshProjects();
    return saved;
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
    const updates: Partial<AppState> = {
      tasks: exists ? current.map((item) => (item.id === id ? task : item)) : [task, ...current]
    };
    if (task.project === get().activeProject && ["succeeded", "failed", "canceled"].includes(task.status)) {
      updates.detail = await fetchProject(task.project);
    }
    set(updates);
    return task;
  },

  cancelQueuedTask: async (id: string) => {
    const task = await cancelTask(id);
    set({ tasks: get().tasks.map((item) => (item.id === id ? task : item)) });
  },

  setMessage: (message: string) => set({ message })
}));
