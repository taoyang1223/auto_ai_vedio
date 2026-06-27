import { create } from "zustand";
import {
  createProject,
  fetchConfig,
  fetchProject,
  fetchProjects,
  fetchTemplates,
  saveConfig,
  saveShots,
  uploadFirstFrame
} from "./api";
import type { ProjectDetail, ProjectSummary, Shot, TemplateInfo } from "./types";

type AppState = {
  workspace: string;
  templates: TemplateInfo[];
  projects: ProjectSummary[];
  activeProject: string | null;
  detail: ProjectDetail | null;
  configText: string;
  loading: boolean;
  message: string;
  boot: () => Promise<void>;
  selectProject: (name: string) => Promise<void>;
  createNewProject: (name: string, template: string) => Promise<void>;
  setShots: (shots: Shot[]) => void;
  persistShots: () => Promise<void>;
  persistConfig: (text: string) => Promise<void>;
  uploadFrame: (shotId: string, file: File) => Promise<void>;
  refreshProjects: () => Promise<void>;
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

  boot: async () => {
    set({ loading: true });
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

  refreshProjects: async () => {
    const payload = await fetchProjects();
    set({ workspace: payload.workspace, projects: payload.projects });
  },

  selectProject: async (name: string) => {
    set({ loading: true, activeProject: name });
    const [detail, configText] = await Promise.all([fetchProject(name), fetchConfig(name)]);
    set({ detail, configText, loading: false, message: "" });
  },

  createNewProject: async (name: string, template: string) => {
    set({ loading: true });
    await createProject(name, template);
    const projectsPayload = await fetchProjects();
    set({ workspace: projectsPayload.workspace, projects: projectsPayload.projects, activeProject: name, loading: false });
    await get().selectProject(name);
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

  setMessage: (message: string) => set({ message })
}));
