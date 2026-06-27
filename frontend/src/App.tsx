import {
  closestCenter,
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors
} from "@dnd-kit/core";
import {
  arrayMove,
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  Activity,
  AlertCircle,
  Boxes,
  CheckCircle2,
  ChevronRight,
  Clapperboard,
  Clock,
  Cloud,
  Copy,
  Eye,
  Film,
  GripVertical,
  ImagePlus,
  KeyRound,
  LayoutDashboard,
  Loader2,
  LogOut,
  Mic2,
  Play,
  Plus,
  RefreshCw,
  Save,
  Settings,
  ShieldCheck,
  Sparkles,
  Terminal,
  Trash2,
  UploadCloud,
  Wand2,
  XCircle
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { checkComfyWorkflow, fetchAssets, uploadAsset } from "./api";
import { useAppStore } from "./store";
import type {
  AssetLibraryItem,
  AssetRef,
  ComfyCheck,
  FirstFramePrompt,
  ProjectDetail,
  PromptProfile,
  ScriptDraftResult,
  Shot,
  RemoteProfileSummary,
  WebTask,
  WebTaskStatus,
  WorkflowSummary
} from "./types";

type TabKey = "script" | "assets" | "first_frames" | "shots" | "voice" | "prompt" | "review" | "workflow" | "run" | "config";

const tabItems: Array<{ key: TabKey; label: string; icon: typeof Clapperboard }> = [
  { key: "script", label: "脚本拆镜", icon: Sparkles },
  { key: "assets", label: "素材库", icon: ImagePlus },
  { key: "first_frames", label: "首帧设计", icon: ImagePlus },
  { key: "shots", label: "分镜编排", icon: Clapperboard },
  { key: "voice", label: "配音", icon: Mic2 },
  { key: "prompt", label: "提示词", icon: Wand2 },
  { key: "review", label: "成片审看", icon: Eye },
  { key: "workflow", label: "工作流配置", icon: Boxes },
  { key: "run", label: "任务运行", icon: Play },
  { key: "config", label: "项目配置", icon: Settings }
];

function App() {
  return (
    <Routes>
      <Route path="/projects/:projectName" element={<ConsoleShell />} />
      <Route path="*" element={<ConsoleShell />} />
    </Routes>
  );
}

function ConsoleShell() {
  const navigate = useNavigate();
  const { projectName } = useParams();
  const {
    activeProject,
    authEnabled,
    authenticated,
    boot,
    detail,
    loading,
    message,
    projects,
    selectProject,
    templates,
    workspace
  } = useAppStore();
  const [bootError, setBootError] = useState("");

  useEffect(() => {
    boot()
      .then(() => setBootError(""))
      .catch((error) => setBootError(friendlyError(error)));
  }, [boot]);

  useEffect(() => {
    if (!authenticated || !projectName || !projects.length) return;
    if (!projects.some((project) => project.name === projectName)) {
      const fallback = activeProject && projects.some((project) => project.name === activeProject) ? activeProject : projects[0].name;
      setBootError("");
      navigate(`/projects/${encodeURIComponent(fallback)}`, { replace: true });
      return;
    }
    if (projectName !== activeProject) {
      selectProject(projectName)
        .then(() => setBootError(""))
        .catch((error) => {
          const fallback = activeProject && projects.some((project) => project.name === activeProject) ? activeProject : projects[0]?.name;
          if (fallback && fallback !== projectName) {
            navigate(`/projects/${encodeURIComponent(fallback)}`, { replace: true });
          }
          setBootError(friendlyError(error));
        });
    }
  }, [authenticated, projectName, activeProject, projects, selectProject, navigate]);

  useEffect(() => {
    if (authenticated && !projectName && activeProject) {
      navigate(`/projects/${encodeURIComponent(activeProject)}`, { replace: true });
    }
  }, [authenticated, activeProject, navigate, projectName]);

  const currentName = projectName || activeProject || "";

  if (authEnabled && !authenticated) {
    return (
      <div className="min-h-screen bg-mist text-ink">
        <TopBar />
        <main className="grid min-h-[calc(100vh-72px)] place-items-center px-4 py-10">
          <LoginScreen />
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-mist text-ink">
      <TopBar />
      <div className="grid min-h-[calc(100vh-72px)] grid-cols-[304px_1fr] max-lg:grid-cols-1">
        <ProjectSidebar active={currentName} projects={projects} workspace={workspace} />
        <main className="min-w-0 px-6 py-5 max-lg:px-4">
          {bootError ? <Notice tone="bad" title="启动失败" body={bootError} /> : null}
          {message ? <Notice tone="ok" title="状态" body={message} /> : null}
          {loading && !detail ? <LoadingState /> : null}
          {!loading && !detail ? <EmptyState hasTemplates={templates.length > 0} /> : null}
          {detail ? <ProjectConsole /> : null}
        </main>
      </div>
    </div>
  );
}

function TopBar() {
  const { authenticated, authEnabled, createNewProject, logoutSession, templates } = useAppStore();
  const navigate = useNavigate();
  const [name, setName] = useState("new_project");
  const [template, setTemplate] = useState("autodl_comfyui_wan");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (templates.length && !templates.some((item) => item.name === template)) {
      setTemplate(templates[0].name);
    }
  }, [template, templates]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await createNewProject(name.trim(), template);
      navigate(`/projects/${encodeURIComponent(name.trim())}`);
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    await logoutSession();
    navigate("/");
  }

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="flex h-[72px] items-center justify-between gap-4 px-6 max-lg:h-auto max-lg:flex-col max-lg:items-stretch max-lg:py-4">
        <Link to="/" className="flex min-w-0 items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-teal-700 text-white">
            <Wand2 size={22} />
          </div>
          <div className="min-w-0">
            <div className="text-lg font-semibold">自动影像工厂</div>
            <div className="truncate text-xs text-slate-500">Auto AI Video 控制台</div>
          </div>
        </Link>
        {authenticated ? (
          <div className="flex items-center gap-2 max-md:flex-wrap">
            <form className="flex items-center gap-2 max-md:flex-wrap" onSubmit={handleCreate}>
              <label className="grid gap-1">
                <span className="text-xs font-medium text-slate-500">项目名</span>
                <input
                  className="control w-48"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  aria-label="项目名称"
                />
              </label>
              <label className="grid gap-1">
                <span className="text-xs font-medium text-slate-500">模板</span>
                <select className="control w-56" value={template} onChange={(event) => setTemplate(event.target.value)}>
                  {templates.map((item) => (
                    <option key={item.name} value={item.name}>
                      {templateLabel(item.name)}
                    </option>
                  ))}
                </select>
              </label>
              <button className="btn btn-primary" disabled={busy} type="submit" title="新建项目">
                {busy ? <Loader2 className="animate-spin" size={17} /> : <Plus size={17} />}
                新建
              </button>
            </form>
            {authEnabled ? (
              <button className="btn" onClick={handleLogout} type="button" title="退出登录">
                <LogOut size={17} />
                退出
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      {error ? <div className="border-t border-red-100 bg-red-50 px-6 py-2 text-sm text-red-700">{error}</div> : null}
    </header>
  );
}

function LoginScreen() {
  const { loginWithToken } = useAppStore();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await loginWithToken(token);
    } catch (err) {
      setError(String((err as Error).message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-panel">
      <div className="grid h-12 w-12 place-items-center rounded-lg bg-teal-50 text-teal-700">
        <ShieldCheck size={24} />
      </div>
      <h1 className="mt-5 text-2xl font-semibold text-slate-950">访问控制台</h1>
      <p className="mt-2 text-sm leading-6 text-slate-500">
        请输入服务启动时配置的访问口令。登录后才能查看项目、上传素材和执行生产动作。
      </p>
      <form className="mt-6 grid gap-3" onSubmit={submit}>
        <label className="grid gap-1">
          <span className="label">访问口令</span>
          <div className="relative">
            <KeyRound className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={17} />
            <input
              className="control w-full pl-10"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              autoFocus
            />
          </div>
        </label>
        <button className="btn btn-primary w-full" disabled={busy || !token} type="submit">
          {busy ? <Loader2 className="animate-spin" size={17} /> : <ShieldCheck size={17} />}
          登录
        </button>
      </form>
      {error ? (
        <div className="mt-4 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
    </section>
  );
}

function ProjectSidebar({ active, projects, workspace }: { active: string; projects: ReturnType<typeof useAppStore.getState>["projects"]; workspace: string }) {
  return (
    <aside className="border-r border-slate-200 bg-white max-lg:border-b max-lg:border-r-0">
      <div className="flex h-full flex-col">
        <div className="border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <LayoutDashboard size={17} />
            项目
          </div>
          <div className="mt-1 truncate text-xs text-slate-500">{workspace}</div>
        </div>
        <div className="grid gap-2 overflow-auto p-3 max-lg:max-h-56">
          {projects.map((project) => (
            <Link
              key={project.name}
              to={`/projects/${encodeURIComponent(project.name)}`}
              className={`group rounded-lg border p-3 transition ${
                project.name === active
                  ? "border-teal-300 bg-teal-50"
                  : "border-transparent bg-white hover:border-slate-200 hover:bg-slate-50"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-900">{project.title || project.name}</div>
                  <div className="mt-1 truncate text-xs text-slate-500">
                    {project.shots || 0} 个分镜 · {project.provider || "未配置"}
                  </div>
                </div>
                <ChevronRight className="mt-0.5 text-slate-400 transition group-hover:translate-x-0.5" size={16} />
              </div>
            </Link>
          ))}
        </div>
      </div>
    </aside>
  );
}

function ProjectConsole() {
  const { deleteExistingProject, detail, setMessage, tasks } = useAppStore();
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabKey>("shots");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [deleting, setDeleting] = useState(false);
  if (!detail) return null;
  const project = detail;

  const metrics = [
    { label: "分镜", value: project.shots_detail.length },
    { label: "尺寸", value: `${project.config.width}x${project.config.height}` },
    { label: "帧率", value: project.config.fps },
    { label: "工作流", value: project.workflows_detail.length },
    { label: "远程", value: project.remote_profiles_detail.length }
  ];

  async function confirmDelete() {
    setDeleting(true);
    setDeleteError("");
    try {
      const next = await deleteExistingProject(project.name);
      setMessage("项目已删除");
      navigate(next ? `/projects/${encodeURIComponent(next)}` : "/", { replace: true });
    } catch (error) {
      setDeleteError(String((error as Error).message || error));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="grid gap-5">
      <section className="panel overflow-hidden">
        <div className="flex items-center justify-between gap-5 px-5 py-5 max-xl:flex-col max-xl:items-stretch">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs font-medium text-teal-700">
              <Sparkles size={15} />
              项目工作台
            </div>
            <h1 className="mt-2 truncate text-2xl font-semibold text-slate-950">{project.title || project.name}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-500">
              <span>{project.config.default_video_provider}</span>
              <span className="h-1 w-1 rounded-full bg-slate-300" />
              <span>{project.config.aspect_ratio}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-3">
            <div className="grid grid-cols-5 gap-2 max-md:grid-cols-2">
              {metrics.map((metric) => (
                <div key={metric.label} className="h-[76px] min-w-[112px] rounded-lg border border-slate-200 bg-slate-50 px-3 py-3">
                  <div className="truncate text-xl font-semibold text-slate-950">{metric.value}</div>
                  <div className="mt-1 text-xs text-slate-500">{metric.label}</div>
                </div>
              ))}
            </div>
            <button className="btn border-red-200 text-red-700 hover:border-red-300 hover:bg-red-50" onClick={() => setDeleteOpen(true)} type="button">
              <Trash2 size={17} />
              删除项目
            </button>
          </div>
        </div>
      </section>

      <ProductionStatus detail={project} onSelectTab={setTab} tasks={tasks} />
      <FinalRenderPreview detail={project} />

      <nav className="flex flex-wrap gap-2">
        {tabItems.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.key}
              className={`btn ${tab === item.key ? "btn-soft" : ""}`}
              onClick={() => setTab(item.key)}
              type="button"
            >
              <Icon size={17} />
              {item.label}
            </button>
          );
        })}
      </nav>

      {tab === "script" ? <ScriptStoryboardPanel /> : null}
      {tab === "assets" ? <AssetLibraryPanel /> : null}
      {tab === "first_frames" ? <FirstFramePanel /> : null}
      {tab === "shots" ? <ShotsPanel /> : null}
      {tab === "voice" ? <VoicePanel /> : null}
      {tab === "prompt" ? <PromptProfilePanel /> : null}
      {tab === "review" ? <ReviewPanel /> : null}
      {tab === "workflow" ? <WorkflowPanel /> : null}
      {tab === "run" ? <RunPanel /> : null}
      {tab === "config" ? <ConfigPanel /> : null}
      {deleteOpen ? (
        <DeleteProjectDialog
          busy={deleting}
          error={deleteError}
          projectName={project.name}
          title={project.title || project.name}
          onCancel={() => {
            setDeleteOpen(false);
            setDeleteError("");
          }}
          onConfirm={confirmDelete}
        />
      ) : null}
    </div>
  );
}

function FinalRenderPreview({ detail }: { detail: ProjectDetail }) {
  const finalRender = detail.renders.final;
  if (!finalRender?.path) return null;

  return (
    <section className="panel overflow-hidden">
      <div className="grid grid-cols-[minmax(280px,520px)_1fr] gap-0 max-xl:grid-cols-1">
        <video
          className="aspect-video h-full w-full bg-slate-950 object-contain"
          controls
          preload="metadata"
          src={mediaUrl(detail.name, finalRender.path)}
        />
        <div className="flex flex-col justify-between gap-5 p-5">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-teal-700">
              <Film size={15} />
              最终成片
            </div>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">{detail.title || detail.name}</h2>
            <div className="mt-2 flex flex-wrap gap-2 text-sm text-slate-500">
              <span>{detail.shots_detail.length} 个分镜</span>
              <span>{detail.config.width}x{detail.config.height}</span>
              <span>{detail.config.fps} FPS</span>
              {finalRender.versions?.length ? <span>{finalRender.versions.length} 个历史版本</span> : null}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <a className="btn btn-primary" href={mediaUrl(detail.name, finalRender.path)} target="_blank" rel="noreferrer">
              <Eye size={17} />
              打开成片
            </a>
            {finalRender.subtitle ? (
              <a className="btn" href={mediaUrl(detail.name, finalRender.subtitle)} target="_blank" rel="noreferrer">
                <Film size={17} />
                字幕 {finalRender.subtitle_entries || ""}
              </a>
            ) : null}
            {finalRender.voiceover ? (
              <a className="btn" href={mediaUrl(detail.name, finalRender.voiceover)} target="_blank" rel="noreferrer">
                <Mic2 size={17} />
                旁白 {finalRender.voiceover_segments || ""}
              </a>
            ) : null}
            {finalRender.versions?.slice(-3).map((version, index) => (
              <a
                key={version.path}
                className="btn"
                href={mediaUrl(detail.name, version.path)}
                target="_blank"
                rel="noreferrer"
                title={version.archived_at || version.path}
              >
                <Clock size={17} />
                版本 {Math.max(1, (finalRender.versions?.length || 0) - 2 + index)}
              </a>
            ))}
            <span className="inline-flex h-10 items-center rounded-md border border-teal-200 bg-teal-50 px-3 text-sm font-medium text-teal-700">
              {finalRender.status === "generated" ? "已生成" : finalRender.status || "已保存"}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

function DeleteProjectDialog({
  busy,
  error,
  onCancel,
  onConfirm,
  projectName,
  title
}: {
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: () => void;
  projectName: string;
  title: string;
}) {
  const [typed, setTyped] = useState("");
  const canDelete = typed === projectName;
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-slate-950/30 px-4 backdrop-blur-sm">
      <section className="w-full max-w-md rounded-xl border border-red-100 bg-white p-5 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-red-50 text-red-700">
            <Trash2 size={20} />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-slate-950">删除项目</h2>
            <div className="mt-1 break-words text-sm text-slate-500">{title}</div>
          </div>
        </div>
        <label className="mt-5 grid gap-1">
          <span className="label">输入项目名确认</span>
          <input className="control w-full" value={typed} onChange={(event) => setTyped(event.target.value)} autoFocus />
        </label>
        {error ? <div className="mt-3 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn" onClick={onCancel} type="button">
            取消
          </button>
          <button className="btn border-red-200 bg-red-600 text-white hover:bg-red-700" disabled={busy || !canDelete} onClick={onConfirm} type="button">
            {busy ? <Loader2 className="animate-spin" size={17} /> : <Trash2 size={17} />}
            确认删除
          </button>
        </div>
      </section>
    </div>
  );
}

type ProductionStep = {
  key: string;
  label: string;
  metric: string;
  status: "done" | "running" | "warn" | "pending";
  tab: TabKey;
  icon: typeof Clapperboard;
};

function ProductionStatus({
  detail,
  onSelectTab,
  tasks
}: {
  detail: ProjectDetail;
  onSelectTab: (tab: TabKey) => void;
  tasks: WebTask[];
}) {
  const steps = productionSteps(detail, tasks);
  return (
    <section className="grid grid-cols-8 gap-3 max-2xl:grid-cols-4 max-lg:grid-cols-2 max-sm:grid-cols-1">
      {steps.map((step) => {
        const Icon = step.icon;
        return (
          <button
            key={step.key}
            className="panel min-h-[88px] p-4 text-left transition hover:border-teal-200 hover:bg-teal-50/40"
            onClick={() => onSelectTab(step.tab)}
            type="button"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-50 text-teal-700">
                <Icon size={18} />
              </div>
              <ProductionStatusPill status={step.status} />
            </div>
            <div className="mt-3 min-w-0">
              <div className="truncate text-sm font-semibold text-slate-900">{step.label}</div>
              <div className="mt-1 truncate text-xs text-slate-500">{step.metric}</div>
            </div>
          </button>
        );
      })}
    </section>
  );
}

function productionSteps(detail: ProjectDetail, tasks: WebTask[]): ProductionStep[] {
  const totalShots = detail.shots_detail.length;
  const readyShots = detail.shots_detail.filter((shot) => shot.visual_prompt.trim() && Number(shot.duration) > 0).length;
  const firstFrames = detail.shots_detail.filter((shot) => Boolean(firstFrameRef(shot))).length;
  const staticRefs = detail.shots_detail.reduce((count, shot) => count + shot.refs.length, 0);
  const generatedShots = detail.shots_detail.filter((shot) => Boolean(generatedClipRef(shot))).length;
  const generatedVoice = detail.shots_detail.filter((shot) => Boolean(generatedAudioRef(shot))).length;
  const staleVoice = detail.shots_detail.filter((shot) => shot.voice_freshness?.status === "stale").length;
  const profileFilled = Object.values(detail.prompt_profile || {}).filter((value) => String(value || "").trim()).length;
  const activeTasks = tasks.filter((task) => task.status === "queued" || task.status === "running").length;
  const succeededTasks = tasks.filter((task) => task.status === "succeeded").length;
  const failedTasks = tasks.filter((task) => task.status === "failed").length;
  const renderCount = Object.keys(detail.renders || {}).length;
  return [
    {
      key: "shots",
      label: "分镜内容",
      metric: `${readyShots}/${totalShots} 已填写`,
      status: totalShots > 0 && readyShots === totalShots ? "done" : "warn",
      tab: "shots",
      icon: Clapperboard
    },
    {
      key: "first_frames",
      label: "首帧素材",
      metric: `${firstFrames}/${totalShots} 已关联`,
      status: totalShots > 0 && firstFrames === totalShots ? "done" : firstFrames > 0 ? "warn" : "pending",
      tab: "first_frames",
      icon: ImagePlus
    },
    {
      key: "assets",
      label: "素材引用",
      metric: staticRefs ? `${staticRefs} 个引用` : "未绑定",
      status: staticRefs ? "done" : "pending",
      tab: "assets",
      icon: ImagePlus
    },
    {
      key: "prompt",
      label: "提示词设定",
      metric: profileFilled ? `${profileFilled}/9 项已填写` : "未填写一致性",
      status: profileFilled >= 5 ? "done" : profileFilled > 0 ? "warn" : "pending",
      tab: "prompt",
      icon: Wand2
    },
    {
      key: "voice",
      label: "分镜配音",
      metric: staleVoice ? `${staleVoice} 条需更新` : generatedVoice ? `${generatedVoice}/${totalShots} 已生成` : "未生成",
      status: staleVoice ? "warn" : totalShots > 0 && generatedVoice === totalShots ? "done" : generatedVoice > 0 ? "warn" : "pending",
      tab: "voice",
      icon: Mic2
    },
    {
      key: "workflow",
      label: "工作流",
      metric: detail.workflows_detail.length ? `${detail.workflows_detail.length} 个可用` : "未配置",
      status: detail.workflows_detail.length ? "done" : "warn",
      tab: "workflow",
      icon: Boxes
    },
    {
      key: "tasks",
      label: "任务运行",
      metric: activeTasks ? `${activeTasks} 个进行中` : generatedShots ? `${generatedShots}/${totalShots} 已生成` : failedTasks ? `${failedTasks} 个失败` : succeededTasks ? `${succeededTasks} 个完成` : "未提交",
      status: activeTasks ? "running" : failedTasks ? "warn" : succeededTasks ? "done" : "pending",
      tab: "run",
      icon: Activity
    },
    {
      key: "renders",
      label: "最终成片",
      metric: renderCount ? `${renderCount} 个结果` : "未生成",
      status: renderCount ? "done" : "pending",
      tab: "review",
      icon: Film
    }
  ];
}

function ProductionStatusPill({ status }: { status: ProductionStep["status"] }) {
  const className = {
    done: "border-teal-200 bg-teal-50 text-teal-700",
    running: "border-blue-200 bg-blue-50 text-blue-700",
    warn: "border-amber-200 bg-amber-50 text-amber-700",
    pending: "border-slate-200 bg-slate-50 text-slate-500"
  }[status];
  const label = {
    done: "就绪",
    running: "进行中",
    warn: "待处理",
    pending: "未开始"
  }[status];
  const icon = status === "running" ? <Loader2 className="animate-spin" size={13} /> : status === "done" ? <CheckCircle2 size={13} /> : null;
  return (
    <span className={`inline-flex h-6 items-center gap-1 rounded-md border px-2 text-xs ${className}`}>
      {icon}
      {label}
    </span>
  );
}

function ScriptStoryboardPanel() {
  const { applyScriptShots, detail, draftScriptShots, setMessage } = useAppStore();
  const [script, setScript] = useState("");
  const [shotCount, setShotCount] = useState("3");
  const [duration, setDuration] = useState("4");
  const [provider, setProvider] = useState("");
  const [draft, setDraft] = useState<ScriptDraftResult | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!detail) return;
    setShotCount(String(detail.shots_detail.length || 3));
    setDuration(String(detail.shots_detail[0]?.duration || 4));
    setProvider(detail.config.default_video_provider);
    setScript(defaultScriptFromProject(detail));
    setDraft(null);
    setError("");
  }, [detail?.name]);

  if (!detail) return null;
  const project = detail;

  async function generateDraft() {
    setBusy("draft");
    setError("");
    try {
      const result = await draftScriptShots({
        script,
        shot_count: Number(shotCount),
        duration: Number(duration),
        provider: provider.trim() || project.config.default_video_provider
      });
      setDraft(result);
      setMessage("分镜草稿已生成");
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  async function applyDraft() {
    if (!draft?.shots.length) return;
    setBusy("apply");
    setError("");
    try {
      await applyScriptShots(draft.shots);
      setMessage("脚本分镜已应用，旧生成记录已清空");
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="grid grid-cols-[minmax(360px,0.9fr)_minmax(0,1.1fr)] gap-4 max-2xl:grid-cols-1">
      <article className="panel p-5">
        <div className="mb-5 flex items-center gap-2 text-sm font-semibold text-slate-900">
          <Sparkles size={18} className="text-teal-700" />
          中文脚本
        </div>
        <div className="grid gap-3">
          <label className="grid gap-1">
            <span className="label">脚本内容</span>
            <textarea
              className="control h-auto min-h-[280px] w-full resize-y py-3 leading-7"
              value={script}
              onChange={(event) => setScript(event.target.value)}
            />
          </label>
          <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
            <LabeledInput label="分镜数量" type="number" value={shotCount} onChange={setShotCount} />
            <LabeledInput label="单镜时长" type="number" value={duration} onChange={setDuration} />
            <LabeledInput label="生成服务" value={provider} onChange={setProvider} />
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-primary" disabled={busy === "draft" || !script.trim()} onClick={generateDraft} type="button">
              {busy === "draft" ? <Loader2 className="animate-spin" size={17} /> : <Sparkles size={17} />}
              生成分镜草稿
            </button>
            <button className="btn" disabled={busy === "apply" || !draft?.shots.length} onClick={applyDraft} type="button">
              {busy === "apply" ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
              应用到项目
            </button>
          </div>
          {error ? <div className="whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
        </div>
      </article>

      <aside className="panel p-5">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Clapperboard size={18} className="text-teal-700" />
              草稿预览
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {draft ? `${draft.meta.shot_count} 个分镜 · ${draft.meta.duration}s · ${draft.meta.provider}` : "等待草稿"}
            </div>
          </div>
          {draft?.shots.length ? (
            <button className="btn btn-primary" disabled={busy === "apply"} onClick={applyDraft} type="button">
              {busy === "apply" ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
              应用草稿
            </button>
          ) : null}
        </div>

        {draft?.shots.length ? (
          <div className="grid max-h-[780px] gap-3 overflow-auto pr-1">
            {draft.shots.map((shot, index) => (
              <article key={shot.id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="text-lg font-bold text-teal-700">{shot.id}</span>
                    <span className="truncate text-sm font-semibold text-slate-950">{shot.title}</span>
                  </div>
                  <span className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-500">
                    {shot.duration}s
                  </span>
                </div>
                <div className="mt-3 grid gap-2 text-sm leading-6 text-slate-600">
                  <div className="font-medium text-slate-800">{draft.source_segments[index]}</div>
                  <div>{shot.visual_prompt}</div>
                  <div className="grid grid-cols-2 gap-2 max-lg:grid-cols-1">
                    <span className="rounded-md bg-slate-50 px-2 py-1">镜头：{shot.camera_motion}</span>
                    <span className="rounded-md bg-slate-50 px-2 py-1">灯光：{shot.lighting}</span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="grid min-h-[420px] place-items-center rounded-lg border border-dashed border-slate-200 text-sm text-slate-500">
            暂无草稿
          </div>
        )}
      </aside>
    </section>
  );
}

function defaultScriptFromProject(detail: ProjectDetail) {
  return detail.shots_detail
    .map((shot) => shot.subtitle || shot.intent || shot.visual_prompt)
    .filter(Boolean)
    .join("。");
}

const assetTypeOptions = [
  { value: "image", label: "图片" },
  { value: "video", label: "视频" },
  { value: "audio", label: "音频" },
  { value: "text", label: "文本" }
];

const assetRoleOptions = [
  { value: "first_frame", label: "首帧" },
  { value: "last_frame", label: "尾帧" },
  { value: "style_reference", label: "风格" },
  { value: "camera_reference", label: "镜头" },
  { value: "motion_reference", label: "动作" },
  { value: "environment_reference", label: "场景" },
  { value: "voice_reference", label: "声音" },
  { value: "bgm_reference", label: "配乐" }
];

const assetUsageOptions = [
  { value: "preserve_subject", label: "保持主体" },
  { value: "extract_style", label: "提取风格" },
  { value: "extract_camera_motion", label: "提取镜头" },
  { value: "extract_action", label: "提取动作" },
  { value: "provide_context", label: "提供上下文" },
  { value: "preserve_voice", label: "保持声音" },
  { value: "extract_audio_rhythm", label: "提取节奏" }
];

function AssetLibraryPanel() {
  const { detail, removeAsset, saveAssetRefs, setMessage } = useAppStore();
  const [assets, setAssets] = useState<AssetLibraryItem[]>([]);
  const [selectedShotId, setSelectedShotId] = useState("");
  const [draftRefs, setDraftRefs] = useState<AssetRef[]>([]);
  const [label, setLabel] = useState("");
  const [assetType, setAssetType] = useState("image");
  const [role, setRole] = useState("style_reference");
  const [usage, setUsage] = useState("extract_style");
  const [textAsset, setTextAsset] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!detail) return;
    setSelectedShotId((current) => {
      if (detail.shots_detail.some((shot) => shot.id === current)) return current;
      return detail.shots_detail[0]?.id || "";
    });
    fetchAssets(detail.name)
      .then(setAssets)
      .catch((failure) => setError(friendlyError(failure)));
  }, [detail?.name]);

  const selectedShot = detail?.shots_detail.find((shot) => shot.id === selectedShotId) || detail?.shots_detail[0];

  useEffect(() => {
    setDraftRefs(selectedShot?.refs ? selectedShot.refs.map((ref) => ({ ...ref })) : []);
  }, [selectedShot?.id, detail?.shots_detail]);

  if (!detail) return null;
  const project = detail;

  async function refreshAssets() {
    setAssets(await fetchAssets(project.name));
  }

  async function upload() {
    setBusy("upload");
    setError("");
    try {
      const dataUrl = file ? await fileToDataUrl(file) : undefined;
      const nextAssets = await uploadAsset(project.name, {
        label: label.trim() || file?.name || "素材",
        type: assetType,
        role,
        usage,
        filename: file?.name,
        data_url: dataUrl,
        text: assetType === "text" && !file ? textAsset : undefined
      });
      setAssets(nextAssets);
      setLabel("");
      setTextAsset("");
      setFile(null);
      setMessage("素材已上传");
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  async function saveBindings() {
    if (!selectedShot) return;
    setBusy("bind");
    setError("");
    try {
      const nextAssets = await saveAssetRefs(selectedShot.id, draftRefs);
      setAssets(nextAssets);
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  async function deleteOne(asset: AssetLibraryItem) {
    setBusy(asset.id);
    setError("");
    try {
      const nextAssets = await removeAsset(asset.id);
      setAssets(nextAssets);
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  function toggleAsset(asset: AssetLibraryItem) {
    setDraftRefs((current) => {
      if (current.some((ref) => ref.path === asset.path)) {
        return current.filter((ref) => ref.path !== asset.path);
      }
      return [
        ...current,
        {
          path: asset.path,
          type: asset.type,
          role: asset.role,
          usage: asset.usage
        }
      ];
    });
  }

  return (
    <section className="grid grid-cols-[minmax(320px,0.72fr)_minmax(0,1.28fr)] gap-4 max-2xl:grid-cols-1">
      <article className="panel p-5">
        <div className="mb-5 flex items-center gap-2 text-sm font-semibold text-slate-900">
          <UploadCloud size={18} className="text-teal-700" />
          上传素材
        </div>
        <div className="grid gap-3">
          <LabeledInput label="素材名称" value={label} onChange={setLabel} />
          <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
            <LabeledSelect label="类型" value={assetType} options={assetTypeOptions} onChange={setAssetType} />
            <LabeledSelect label="角色" value={role} options={assetRoleOptions} onChange={setRole} />
            <LabeledSelect label="用途" value={usage} options={assetUsageOptions} onChange={setUsage} />
          </div>
          {assetType === "text" ? (
            <LabeledTextarea label="文本内容" rows={5} value={textAsset} onChange={setTextAsset} />
          ) : null}
          <label className="btn justify-start">
            <UploadCloud size={17} />
            选择文件
            <input
              className="hidden"
              type="file"
              accept="image/*,video/*,audio/*,.txt,.md,.json"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </label>
          {file ? <div className="truncate text-xs text-slate-500">{file.name}</div> : null}
          <button className="btn btn-primary" disabled={busy === "upload" || (!file && !textAsset.trim())} onClick={upload} type="button">
            {busy === "upload" ? <Loader2 className="animate-spin" size={17} /> : <UploadCloud size={17} />}
            上传到素材库
          </button>
          {error ? <div className="whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
        </div>
      </article>

      <div className="grid gap-4">
        <article className="panel p-5">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <ImagePlus size={18} className="text-teal-700" />
                素材列表
              </div>
              <div className="mt-1 text-xs text-slate-500">{assets.length} 个素材</div>
            </div>
            <button className="btn" onClick={() => refreshAssets().catch((failure) => setError(friendlyError(failure)))} type="button">
              <RefreshCw size={17} />
              刷新
            </button>
          </div>
          <div className="grid grid-cols-3 gap-3 max-2xl:grid-cols-2 max-lg:grid-cols-1">
            {assets.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                checked={draftRefs.some((ref) => ref.path === asset.path)}
                projectName={detail.name}
                busy={busy === asset.id}
                onDelete={() => deleteOne(asset)}
                onToggle={() => toggleAsset(asset)}
              />
            ))}
            {!assets.length ? (
              <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-sm text-slate-500">
                暂无素材
              </div>
            ) : null}
          </div>
        </article>

        <article className="panel p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Clapperboard size={18} className="text-teal-700" />
              分镜绑定
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select className="control h-10 w-40" value={selectedShot?.id || ""} onChange={(event) => setSelectedShotId(event.target.value)}>
                {detail.shots_detail.map((shot) => (
                  <option key={shot.id} value={shot.id}>
                    {shot.id}
                  </option>
                ))}
              </select>
              <button className="btn btn-primary" disabled={busy === "bind" || !selectedShot} onClick={saveBindings} type="button">
                {busy === "bind" ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
                保存绑定
              </button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {draftRefs.map((ref) => (
              <span key={ref.path} className="max-w-full truncate rounded-md border border-teal-200 bg-teal-50 px-2 py-1 text-xs text-teal-700">
                {ref.path}
              </span>
            ))}
            {!draftRefs.length ? <span className="text-sm text-slate-500">未绑定素材</span> : null}
          </div>
        </article>
      </div>
    </section>
  );
}

function AssetCard({
  asset,
  busy,
  checked,
  onDelete,
  onToggle,
  projectName
}: {
  asset: AssetLibraryItem;
  busy: boolean;
  checked: boolean;
  onDelete: () => void;
  onToggle: () => void;
  projectName: string;
}) {
  return (
    <article className={`overflow-hidden rounded-lg border ${checked ? "border-teal-300 bg-teal-50" : "border-slate-200 bg-white"}`}>
      <button className="block aspect-video w-full bg-slate-100 text-left" onClick={onToggle} type="button">
        <AssetPreview asset={asset} projectName={projectName} />
      </button>
      <div className="grid gap-3 p-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-950">{asset.label}</div>
          <div className="mt-1 truncate text-xs text-slate-500">{assetRoleLabel(asset.role)} · {assetUsageLabel(asset.usage)}</div>
        </div>
        <div className="flex flex-wrap gap-1">
          {asset.bound_shots.map((shotId) => (
            <span key={shotId} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
              {shotId}
            </span>
          ))}
        </div>
        <div className="flex items-center justify-between gap-2">
          <button className={`btn h-8 px-2 text-xs ${checked ? "btn-soft" : ""}`} onClick={onToggle} type="button">
            {checked ? "已选" : "绑定"}
          </button>
          <button className="btn h-8 border-red-200 px-2 text-xs text-red-700" disabled={busy} onClick={onDelete} type="button">
            {busy ? <Loader2 className="animate-spin" size={14} /> : <Trash2 size={14} />}
            移除
          </button>
        </div>
      </div>
    </article>
  );
}

function AssetPreview({ asset, projectName }: { asset: AssetLibraryItem; projectName: string }) {
  if (!asset.exists) {
    return <div className="grid h-full place-items-center text-sm text-slate-400">文件缺失</div>;
  }
  const url = mediaUrl(projectName, asset.path);
  if (asset.type === "image") {
    return <img className="h-full w-full object-cover" src={url} alt={asset.label} />;
  }
  if (asset.type === "video") {
    return <video className="h-full w-full object-cover" src={url} muted preload="metadata" />;
  }
  if (asset.type === "audio") {
    return (
      <div className="grid h-full place-items-center p-3">
        <audio className="w-full" src={url} controls />
      </div>
    );
  }
  return (
    <div className="grid h-full place-items-center px-4 text-center text-sm text-slate-500">
      {asset.path}
    </div>
  );
}

function LabeledSelect({
  label,
  onChange,
  options,
  value
}: {
  label: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  value: string;
}) {
  return (
    <label className="grid gap-1">
      <span className="label">{label}</span>
      <select className="control w-full" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function fileToDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function copyToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  const ok = document.execCommand("copy");
  textarea.remove();
  if (!ok) {
    throw new Error("复制失败，请手动选中提示词复制。");
  }
}

function assetRoleLabel(value: string) {
  return assetRoleOptions.find((option) => option.value === value)?.label || value;
}

function assetUsageLabel(value: string) {
  return assetUsageOptions.find((option) => option.value === value)?.label || value;
}

function FirstFramePanel() {
  const { detail, enqueueTask, loadFirstFramePrompts, loadTask, saveFirstFrameDrafts, setMessage, uploadFrame } = useAppStore();
  const [prompts, setPrompts] = useState<FirstFramePrompt[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [watchTaskId, setWatchTaskId] = useState("");

  useEffect(() => {
    if (!detail) return;
    reloadPrompts();
  }, [detail?.name]);

  useEffect(() => {
    if (!watchTaskId) return;
    const tick = async () => {
      try {
        const task = await loadTask(watchTaskId);
        if (["succeeded", "failed", "canceled"].includes(task.status)) {
          setWatchTaskId("");
          await reloadPrompts();
        }
      } catch (failure) {
        setError(friendlyError(failure));
      }
    };
    tick();
    const timer = window.setInterval(tick, 1500);
    return () => window.clearInterval(timer);
  }, [watchTaskId, loadTask]);

  if (!detail) return null;
  const projectName = detail.name;
  const total = detail.shots_detail.length;
  const ready = detail.shots_detail.filter((shot) => Boolean(firstFrameRef(shot))).length;
  const customized = prompts.filter((prompt) => prompt.prompt !== prompt.generated_prompt || prompt.negative_prompt !== prompt.generated_negative_prompt).length;
  const missingShotIds = detail.shots_detail.filter((shot) => !firstFrameRef(shot)).map((shot) => shot.id);
  const imageProvider = detail.config.default_image_provider || "mock";
  const remoteProfile = detail.remote_profiles_detail[0]?.name || "";

  async function reloadPrompts() {
    setBusy("load");
    setError("");
    try {
      setPrompts(await loadFirstFramePrompts());
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  async function saveAll() {
    setBusy("save");
    setError("");
    try {
      setPrompts(await saveFirstFrameDrafts(prompts));
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  function updatePrompt(shotId: string, key: "prompt" | "negative_prompt", value: string) {
    setPrompts((current) => current.map((item) => (item.shot_id === shotId ? { ...item, [key]: value } : item)));
  }

  function restoreGenerated(shotId: string) {
    setPrompts((current) =>
      current.map((item) =>
        item.shot_id === shotId
          ? {
              ...item,
              prompt: item.generated_prompt,
              negative_prompt: item.generated_negative_prompt
            }
          : item
      )
    );
  }

  async function copyPrompt(prompt: FirstFramePrompt) {
    const body = `${prompt.prompt}\n\nNegative prompt:\n${prompt.negative_prompt}`;
    try {
      await copyToClipboard(body);
      setMessage(`${prompt.shot_id} 首帧提示词已复制`);
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    }
  }

  async function uploadShotFrame(shotId: string, file: File) {
    setBusy(`upload-${shotId}`);
    setError("");
    try {
      await uploadFrame(shotId, file);
      setMessage(`${shotId} 首帧已上传`);
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  async function enqueueFirstFrameGeneration(shotIds: string[], label: string) {
    if (!shotIds.length) return;
    const useRemote = Boolean(remoteProfile) && imageProvider !== "mock";
    const action = useRemote ? "remote-first-frame" : "first-frame-generate";
    setBusy(`generate-${shotIds.join(",")}`);
    setError("");
    try {
      const task = await enqueueTask(
        projectName,
        action,
        {
          profile: remoteProfile || undefined,
          provider: imageProvider,
          only: shotIds,
          skip_succeeded: false
        },
        label
      );
      setWatchTaskId(task.id);
      setMessage(`${label}已加入队列`);
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="grid gap-4">
      <article className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <ImagePlus size={18} className="text-teal-700" />
              首帧设计
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {ready}/{total} 已上传 · {customized} 个自定义提示词
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="btn"
              disabled={Boolean(watchTaskId) || Boolean(busy) || !missingShotIds.length}
              onClick={() => enqueueFirstFrameGeneration(missingShotIds, "生成缺失首帧")}
              type="button"
            >
              {watchTaskId || busy.startsWith("generate-") ? <Loader2 className="animate-spin" size={17} /> : <Wand2 size={17} />}
              生成缺失首帧
            </button>
            <button className="btn" disabled={busy === "load"} onClick={reloadPrompts} type="button">
              {busy === "load" ? <Loader2 className="animate-spin" size={17} /> : <RefreshCw size={17} />}
              刷新
            </button>
            <button className="btn btn-primary" disabled={busy === "save" || !prompts.length} onClick={saveAll} type="button">
              {busy === "save" ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
              保存全部
            </button>
          </div>
        </div>
        {error ? <div className="mt-4 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      </article>

      <div className="grid grid-cols-2 gap-4 max-2xl:grid-cols-1">
        {prompts.map((prompt) => {
          const shot = detail.shots_detail.find((item) => item.id === prompt.shot_id);
          return (
            <FirstFrameCard
              key={prompt.shot_id}
              busy={busy}
              prompt={prompt}
              projectName={detail.name}
              shot={shot}
              taskRunning={Boolean(watchTaskId)}
              onCopy={() => copyPrompt(prompt)}
              onGenerate={() => enqueueFirstFrameGeneration([prompt.shot_id], `${prompt.shot_id} 生成首帧`)}
              onRestore={() => restoreGenerated(prompt.shot_id)}
              onUpdate={(key, value) => updatePrompt(prompt.shot_id, key, value)}
              onUpload={(file) => uploadShotFrame(prompt.shot_id, file)}
            />
          );
        })}
      </div>
    </section>
  );
}

function FirstFrameCard({
  busy,
  onCopy,
  onGenerate,
  onRestore,
  onUpdate,
  onUpload,
  projectName,
  prompt,
  shot,
  taskRunning
}: {
  busy: string;
  onCopy: () => void;
  onGenerate: () => void;
  onRestore: () => void;
  onUpdate: (key: "prompt" | "negative_prompt", value: string) => void;
  onUpload: (file: File) => void;
  projectName: string;
  prompt: FirstFramePrompt;
  shot?: Shot;
  taskRunning: boolean;
}) {
  const firstFrame = shot ? firstFrameRef(shot) : prompt.first_frame_path;
  const isCustom = prompt.prompt !== prompt.generated_prompt || prompt.negative_prompt !== prompt.generated_negative_prompt;
  const uploadBusy = busy === `upload-${prompt.shot_id}`;

  function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    onUpload(file);
    event.currentTarget.value = "";
  }

  return (
    <article className="panel overflow-hidden">
      <div className="flex min-h-16 items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className="text-lg font-bold text-teal-700">{prompt.shot_id}</div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-950">{prompt.title || shot?.title || "未命名分镜"}</div>
            <div className="mt-0.5 text-xs text-slate-500">{prompt.duration}s · {prompt.provider}</div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <span className={`inline-flex h-7 items-center rounded-md border px-2 text-xs ${firstFrame ? "border-teal-200 bg-teal-50 text-teal-700" : "border-amber-200 bg-amber-50 text-amber-700"}`}>
            {firstFrame ? "已有首帧" : "待上传"}
          </span>
          <span className={`inline-flex h-7 items-center rounded-md border px-2 text-xs ${isCustom ? "border-blue-200 bg-blue-50 text-blue-700" : "border-slate-200 bg-slate-50 text-slate-500"}`}>
            {isCustom ? "自定义" : "自动草稿"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-[188px_1fr] gap-4 p-4 max-md:grid-cols-1">
        <div className="grid gap-3">
          <div className="aspect-video overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
            {firstFrame ? (
              <img className="h-full w-full object-cover" src={mediaUrl(projectName, firstFrame)} alt={`${prompt.shot_id} 首帧`} />
            ) : (
              <div className="grid h-full place-items-center bg-gradient-to-br from-slate-100 to-teal-50 text-slate-400">
                <ImagePlus size={30} />
              </div>
            )}
          </div>
          <label className={`btn justify-start ${uploadBusy ? "opacity-70" : ""}`}>
            {uploadBusy ? <Loader2 className="animate-spin" size={17} /> : <UploadCloud size={17} />}
            上传首帧
            <input className="hidden" type="file" accept="image/png,image/jpeg,image/webp" disabled={uploadBusy} onChange={handleUpload} />
          </label>
          <button className="btn justify-start" disabled={taskRunning || busy.startsWith("generate-")} onClick={onGenerate} type="button">
            {busy === `generate-${prompt.shot_id}` ? <Loader2 className="animate-spin" size={17} /> : <Wand2 size={17} />}
            生成首帧
          </button>
          {prompt.refs.length ? (
            <div className="flex flex-wrap gap-1">
              {prompt.refs.map((ref) => (
                <span key={`${prompt.shot_id}-${ref.path}`} className="max-w-full truncate rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">
                  {ref.role_label || ref.role} · {ref.usage_label || ref.usage}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        <div className="grid gap-3">
          <LabeledTextarea
            label="首帧提示词"
            rows={9}
            value={prompt.prompt}
            onChange={(value) => onUpdate("prompt", value)}
          />
          <LabeledTextarea
            label="负面提示词"
            rows={3}
            value={prompt.negative_prompt}
            onChange={(value) => onUpdate("negative_prompt", value)}
          />
          <div className="flex flex-wrap justify-end gap-2">
            <button className="btn" onClick={onRestore} type="button">
              <RefreshCw size={17} />
              恢复自动草稿
            </button>
            <button className="btn btn-primary" onClick={onCopy} type="button">
              <Copy size={17} />
              复制提示词
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}

function ShotsPanel() {
  const { detail, persistShots, setMessage, setShots } = useAppStore();
  const [saving, setSaving] = useState(false);
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  if (!detail) return null;
  const project = detail;

  function updateShot(index: number, patch: Partial<Shot>) {
    const next = project.shots_detail.map((shot, itemIndex) => (itemIndex === index ? { ...shot, ...patch } : shot));
    setShots(next);
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = project.shots_detail.findIndex((shot) => shot.id === active.id);
    const newIndex = project.shots_detail.findIndex((shot) => shot.id === over.id);
    setShots(arrayMove(project.shots_detail, oldIndex, newIndex));
  }

  async function save() {
    setSaving(true);
    try {
      await persistShots();
    } catch (error) {
      setMessage(String((error as Error).message || error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm font-medium text-slate-700">分镜列表</div>
        <button className="btn btn-primary" disabled={saving} onClick={save} type="button">
          {saving ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
          保存分镜
        </button>
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={project.shots_detail.map((shot) => shot.id)} strategy={rectSortingStrategy}>
          <div className="grid grid-cols-3 gap-4 max-2xl:grid-cols-2 max-lg:grid-cols-1">
            {project.shots_detail.map((shot, index) => (
              <SortableShotCard
                key={shot.id}
                defaultProvider={project.config.default_video_provider}
                index={index}
                projectName={project.name}
                remoteProfile={project.remote_profiles_detail[0]?.name || ""}
                shot={shot}
                updateShot={updateShot}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </section>
  );
}

function VoicePanel() {
  const { detail, enqueueTask, persistShots, setMessage, setShots } = useAppStore();
  const [busy, setBusy] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  if (!detail) return null;
  const project = detail;

  const generated = project.shots_detail.filter((shot) => Boolean(generatedAudioRef(shot))).length;
  const stale = project.shots_detail.filter((shot) => shot.voice_freshness?.status === "stale").length;
  const provider = project.config.default_audio_provider || "local_tts";

  function updateShot(index: number, patch: Partial<Shot>) {
    const next = project.shots_detail.map((shot, itemIndex) => (itemIndex === index ? { ...shot, ...patch } : shot));
    setShots(next);
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      await persistShots();
    } catch (failure) {
      setError(friendlyError(failure));
    } finally {
      setSaving(false);
    }
  }

  async function enqueue(action: string, label: string, payload: Record<string, unknown>) {
    setBusy(label);
    setError("");
    try {
      await enqueueTask(project.name, action, payload, label);
      setMessage(`${label}已加入队列`);
    } catch (failure) {
      setError(friendlyError(failure));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="grid gap-4">
      <div className="panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Mic2 size={18} className="text-teal-700" />
              配音工作台
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {provider} · {generated}/{project.shots_detail.length} 已生成{stale ? ` · ${stale} 条需更新` : ""}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="btn"
              disabled={Boolean(busy)}
              onClick={() => enqueue("jobs-plan", "配音计划", { provider, kind: "audio", skip_succeeded: true })}
              type="button"
            >
              {busy === "配音计划" ? <Loader2 className="animate-spin" size={17} /> : <Clapperboard size={17} />}
              配音计划
            </button>
            <button
              className="btn btn-primary"
              disabled={Boolean(busy)}
              onClick={() => enqueue("generate", "生成/更新配音", { provider, kind: "audio", skip_succeeded: true })}
              type="button"
            >
              {busy === "生成/更新配音" ? <Loader2 className="animate-spin" size={17} /> : <Mic2 size={17} />}
              生成/更新配音
            </button>
            <button className="btn" disabled={saving} onClick={save} type="button">
              {saving ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
              保存台词
            </button>
            <button className="btn" disabled={Boolean(busy)} onClick={() => enqueue("assemble", "合成带配音成片", {})} type="button">
              {busy === "合成带配音成片" ? <Loader2 className="animate-spin" size={17} /> : <Film size={17} />}
              合成成片
            </button>
          </div>
        </div>
        {error ? <div className="mt-3 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      </div>

      <div className="grid grid-cols-3 gap-4 max-2xl:grid-cols-2 max-lg:grid-cols-1">
        {project.shots_detail.map((shot, index) => (
          <VoiceShotCard
            key={shot.id}
            index={index}
            projectName={project.name}
            provider={provider}
            shot={shot}
            updateShot={updateShot}
            onGenerate={(shotId) => enqueue("generate", `${shotId} 重配`, { provider, kind: "audio", only: [shotId] })}
            busy={busy}
          />
        ))}
      </div>
    </section>
  );
}

function VoiceShotCard({
  busy,
  index,
  onGenerate,
  projectName,
  provider,
  shot,
  updateShot
}: {
  busy: string;
  index: number;
  onGenerate: (shotId: string) => void;
  projectName: string;
  provider: string;
  shot: Shot;
  updateShot: (index: number, patch: Partial<Shot>) => void;
}) {
  const audio = generatedAudioRef(shot);
  const status = voiceGenerationStatus(shot);
  return (
    <article className="panel overflow-hidden">
      <div className="flex h-14 items-center justify-between gap-3 border-b border-slate-100 px-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-teal-700">{shot.id}</span>
            <span className="truncate text-sm font-semibold text-slate-900">{shot.title}</span>
          </div>
          <div className="mt-0.5 truncate text-xs text-slate-500">{shot.voice_freshness?.message || voiceGenerationLabel(status)}</div>
        </div>
        <VoiceStatusPill status={status} />
      </div>
      <div className="grid gap-3 p-4">
        {audio ? (
          <audio className="w-full" src={mediaUrl(projectName, audio)} controls />
        ) : (
          <div className="grid h-12 place-items-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500">
            尚未生成音频
          </div>
        )}
        <LabeledTextarea label="配音台词" rows={4} value={shot.subtitle} onChange={(value) => updateShot(index, { subtitle: value })} />
        <LabeledInput label="声音意图" value={shot.audio_intent || ""} onChange={(value) => updateShot(index, { audio_intent: value })} />
        <div className="grid grid-cols-[1fr_auto] items-end gap-3">
          <label className="grid gap-1">
            <span className="label">配音服务</span>
            <input className="control w-full bg-slate-50 text-slate-500" value={provider} readOnly />
          </label>
          <button className="btn h-10" disabled={Boolean(busy)} onClick={() => onGenerate(shot.id)} type="button">
            {busy === `${shot.id} 重配` ? <Loader2 className="animate-spin" size={17} /> : <RefreshCw size={17} />}
            重配
          </button>
        </div>
      </div>
    </article>
  );
}

const promptProfileFields: Array<{ key: keyof PromptProfile; label: string; rows?: number; compact?: boolean }> = [
  { key: "subject", label: "主体", compact: true },
  { key: "character", label: "角色一致性" },
  { key: "setting", label: "场景一致性" },
  { key: "visual_style", label: "视觉风格" },
  { key: "camera_style", label: "镜头语言" },
  { key: "motion_style", label: "运动风格" },
  { key: "lighting_style", label: "灯光" },
  { key: "continuity", label: "连续性规则" },
  { key: "negative", label: "全局负面词" }
];

function emptyPromptProfile(): PromptProfile {
  return {
    subject: "",
    character: "",
    setting: "",
    visual_style: "",
    camera_style: "",
    motion_style: "",
    lighting_style: "",
    continuity: "",
    negative: ""
  };
}

function normalizePromptProfile(profile?: Partial<PromptProfile>): PromptProfile {
  const empty = emptyPromptProfile();
  return Object.fromEntries(
    Object.keys(empty).map((key) => [key, String(profile?.[key as keyof PromptProfile] || "")])
  ) as PromptProfile;
}

function PromptProfilePanel() {
  const { detail, savePromptProfile, setMessage } = useAppStore();
  const [profile, setProfile] = useState<PromptProfile>(emptyPromptProfile);
  const [selectedShotId, setSelectedShotId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!detail) return;
    setProfile(normalizePromptProfile(detail.prompt_profile));
    setSelectedShotId((current) => {
      if (detail.shots_detail.some((shot) => shot.id === current)) return current;
      return detail.shots_detail[0]?.id || "";
    });
  }, [detail]);

  if (!detail) return null;
  const selectedShot = detail.shots_detail.find((shot) => shot.id === selectedShotId) || detail.shots_detail[0];
  const filled = Object.values(profile).filter((value) => value.trim()).length;
  const preview = selectedShot ? buildPromptPreview(profile, selectedShot) : "";

  function updateField(key: keyof PromptProfile, value: string) {
    setProfile((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    setSaving(true);
    setError("");
    try {
      await savePromptProfile(profile);
    } catch (failure) {
      const message = friendlyError(failure);
      setError(message);
      setMessage(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="grid grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)] gap-4 max-2xl:grid-cols-1">
      <article className="panel p-5">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Wand2 size={18} className="text-teal-700" />
              提示词一致性
            </div>
            <div className="mt-1 text-xs text-slate-500">{filled}/9 项已填写</div>
          </div>
          <button className="btn btn-primary" disabled={saving} onClick={save} type="button">
            {saving ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
            保存提示词设定
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3 max-xl:grid-cols-1">
          {promptProfileFields.map((field) =>
            field.compact ? (
              <LabeledInput
                key={field.key}
                label={field.label}
                value={profile[field.key]}
                onChange={(value) => updateField(field.key, value)}
              />
            ) : (
              <LabeledTextarea
                key={field.key}
                label={field.label}
                rows={field.rows || 3}
                value={profile[field.key]}
                onChange={(value) => updateField(field.key, value)}
              />
            )
          )}
        </div>
        {error ? <div className="mt-4 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      </article>

      <aside className="panel p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Clapperboard size={18} className="text-teal-700" />
              生成提示词预览
            </div>
            <div className="mt-1 text-xs text-slate-500">{selectedShot?.id || "未选择分镜"}</div>
          </div>
          <select className="control h-10 w-36" value={selectedShotId} onChange={(event) => setSelectedShotId(event.target.value)}>
            {detail.shots_detail.map((shot) => (
              <option key={shot.id} value={shot.id}>
                {shot.id}
              </option>
            ))}
          </select>
        </div>
        <pre className="mt-5 max-h-[720px] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-4 text-sm leading-6 text-slate-100">
          {preview}
        </pre>
      </aside>
    </section>
  );
}

function buildPromptPreview(profile: PromptProfile, shot: Shot) {
  const profileLines = [
    ["Subject", profile.subject],
    ["Character continuity", profile.character],
    ["Setting continuity", profile.setting],
    ["Visual style", profile.visual_style],
    ["Camera style", profile.camera_style],
    ["Motion style", profile.motion_style],
    ["Lighting style", profile.lighting_style],
    ["Continuity rules", profile.continuity]
  ]
    .filter(([, value]) => value.trim())
    .map(([label, value]) => `${label}: ${value}`);
  const negative = combineNegativeTerms([shot.negative_prompt, profile.negative]);
  return [
    ...profileLines,
    shot.visual_prompt,
    `Performance: ${shot.performance}`,
    `Camera: ${shot.camera_motion}`,
    `Environment motion: ${shot.environment_motion}`,
    `Lighting: ${shot.lighting}`,
    "continuous smooth cinematic motion, no text, no watermark",
    `Negative: ${negative}`
  ]
    .filter((line) => line.trim() && !line.endsWith(": "))
    .join("\n");
}

function combineNegativeTerms(values: string[]) {
  const seen = new Set<string>();
  const terms: string[] = [];
  values.forEach((value) => {
    value.split(",").forEach((part) => {
      const term = part.trim();
      const key = term.toLocaleLowerCase();
      if (!term || seen.has(key)) return;
      seen.add(key);
      terms.push(term);
    });
  });
  return terms.join(", ");
}

function SortableShotCard({
  defaultProvider,
  index,
  projectName,
  remoteProfile,
  shot,
  updateShot
}: {
  defaultProvider: string;
  index: number;
  projectName: string;
  remoteProfile: string;
  shot: Shot;
  updateShot: (index: number, patch: Partial<Shot>) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: shot.id });
  const { enqueueTask, setMessage, uploadFrame } = useAppStore();
  const style = { transform: CSS.Transform.toString(transform), transition };
  const firstFrame = firstFrameRef(shot);
  const generatedClip = generatedClipRef(shot);
  const generationStatus = shotGenerationStatus(shot);
  const [rerunning, setRerunning] = useState(false);
  const [rerunError, setRerunError] = useState("");

  async function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    await uploadFrame(shot.id, file);
  }

  async function rerunShot() {
    if (!remoteProfile) {
      setRerunError("请先在工作流配置里填写远程机器");
      return;
    }
    setRerunning(true);
    setRerunError("");
    try {
      await enqueueTask(
        projectName,
        "remote-run",
        { profile: remoteProfile, provider: shot.provider || defaultProvider, kind: "video", only: [shot.id] },
        `${shot.id} 重跑`
      );
      setMessage(`${shot.id} 重跑已加入队列`);
    } catch (error) {
      setRerunError(String((error as Error).message || error));
    } finally {
      setRerunning(false);
    }
  }

  return (
    <article
      ref={setNodeRef}
      style={style}
      className={`panel overflow-hidden ${isDragging ? "opacity-70 shadow-xl" : ""}`}
    >
      <div className="flex h-14 items-center gap-3 border-b border-slate-100 px-4">
        <button className="grid h-9 w-9 place-items-center rounded-md border border-slate-200 text-slate-400" type="button" {...attributes} {...listeners} title="拖拽排序">
          <GripVertical size={18} />
        </button>
        <div className="text-lg font-bold text-teal-700">{shot.id}</div>
        <input
          className="control h-9 min-w-0 flex-1 font-medium"
          value={shot.title}
          onChange={(event) => updateShot(index, { title: event.target.value })}
          aria-label="分镜标题"
        />
        {generatedClip ? <ShotGenerationPill status={generationStatus} /> : null}
      </div>
      <div className="grid gap-4 p-4">
        {generatedClip ? (
          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                <Film size={17} className="text-teal-700" />
                生成结果
              </div>
              <a className="btn h-8 px-2 text-xs" href={mediaUrl(projectName, generatedClip)} target="_blank" rel="noreferrer">
                <Eye size={14} />
                打开
              </a>
            </div>
            <video
              className="aspect-video w-full rounded-lg border border-slate-200 bg-slate-950 object-contain"
              controls
              preload="metadata"
              poster={firstFrame ? mediaUrl(projectName, firstFrame) : undefined}
              src={mediaUrl(projectName, generatedClip)}
            />
          </div>
        ) : null}
        <div className="grid grid-cols-[132px_1fr] gap-3">
          <div className="h-[118px] overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
            {firstFrame ? (
              <img className="h-full w-full object-cover" src={mediaUrl(projectName, firstFrame)} alt={`${shot.id} 首帧`} />
            ) : (
              <div className="grid h-full place-items-center text-slate-400">
                <ImagePlus size={28} />
              </div>
            )}
          </div>
          <div className="grid gap-3">
            <LabeledInput label="生成服务" value={shot.provider || ""} onChange={(value) => updateShot(index, { provider: value })} />
            <LabeledInput
              label="时长"
              type="number"
              value={String(shot.duration)}
              onChange={(value) => updateShot(index, { duration: Number(value) })}
            />
          </div>
        </div>
        <LabeledTextarea label="画面提示词" value={shot.visual_prompt} onChange={(value) => updateShot(index, { visual_prompt: value })} />
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          <LabeledInput label="镜头运动" value={shot.camera_motion} onChange={(value) => updateShot(index, { camera_motion: value })} />
          <LabeledInput label="环境运动" value={shot.environment_motion} onChange={(value) => updateShot(index, { environment_motion: value })} />
          <LabeledInput label="表演状态" value={shot.performance} onChange={(value) => updateShot(index, { performance: value })} />
          <LabeledInput label="灯光" value={shot.lighting} onChange={(value) => updateShot(index, { lighting: value })} />
        </div>
        <LabeledInput label="字幕" value={shot.subtitle} onChange={(value) => updateShot(index, { subtitle: value })} />
        <LabeledTextarea label="负面提示词" value={shot.negative_prompt} rows={3} onChange={(value) => updateShot(index, { negative_prompt: value })} />
        <label className="btn justify-start">
          <UploadCloud size={17} />
          上传首帧
          <input className="hidden" type="file" accept="image/png,image/jpeg,image/webp" onChange={handleUpload} />
        </label>
        <button className="btn justify-start" disabled={rerunning} onClick={rerunShot} type="button">
          {rerunning ? <Loader2 className="animate-spin" size={17} /> : <RefreshCw size={17} />}
          重跑此镜头
        </button>
        {rerunError ? <div className="whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{rerunError}</div> : null}
      </div>
    </article>
  );
}

function ReviewPanel() {
  const { detail, enqueueTask, setMessage } = useAppStore();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  if (!detail) return null;

  const remoteProfile = detail.remote_profiles_detail[0]?.name || "";
  const projectName = detail.name;
  const generatedShots = detail.shots_detail.filter((shot) => Boolean(generatedClipRef(shot))).length;
  const finalRender = detail.renders.final;

  async function enqueue(action: string, label: string, payload: Record<string, unknown>) {
    setBusy(action);
    setError("");
    try {
      await enqueueTask(projectName, action, payload, label);
      setMessage(`${label}已加入队列`);
    } catch (failure) {
      setError(String((failure as Error).message || failure));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="grid gap-4">
      <div className="panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Eye size={18} className="text-teal-700" />
              成片审看
            </div>
            <div className="mt-1 text-xs text-slate-500">
              {generatedShots}/{detail.shots_detail.length} 分镜已生成 · {finalRender?.path ? "成片已生成" : "未合成"}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="btn btn-primary"
              disabled={Boolean(busy) || !remoteProfile}
              onClick={() =>
                enqueue("produce-all", "一键完整生产", {
                  profile: remoteProfile,
                  provider: detail.config.default_video_provider,
                  kind: "video"
                })
              }
              type="button"
            >
              {busy === "produce-all" ? <Loader2 className="animate-spin" size={17} /> : <Wand2 size={17} />}
              一键完整生产
            </button>
            <button
              className="btn"
              disabled={Boolean(busy) || !remoteProfile}
              onClick={() =>
                enqueue("remote-run", "生成剩余分镜", {
                  profile: remoteProfile,
                  provider: detail.config.default_video_provider,
                  kind: "video",
                  skip_succeeded: true
                })
              }
              type="button"
            >
              {busy === "remote-run" ? <Loader2 className="animate-spin" size={17} /> : <Cloud size={17} />}
              生成剩余分镜
            </button>
            <button className="btn" disabled={Boolean(busy)} onClick={() => enqueue("probe", "自动验片", { blackdetect: true })} type="button">
              {busy === "probe" ? <Loader2 className="animate-spin" size={17} /> : <Eye size={17} />}
              自动验片
            </button>
            <button
              className="btn"
              disabled={Boolean(busy)}
              onClick={() =>
                enqueue("generate", "生成配音", {
                  provider: detail.config.default_audio_provider,
                  kind: "audio",
                  skip_succeeded: true
                })
              }
              type="button"
            >
              {busy === "generate" ? <Loader2 className="animate-spin" size={17} /> : <Mic2 size={17} />}
              生成配音
            </button>
            <button className="btn" disabled={Boolean(busy)} onClick={() => enqueue("continuity", "提取连续性", { force: true })} type="button">
              {busy === "continuity" ? <Loader2 className="animate-spin" size={17} /> : <Copy size={17} />}
              提取连续性
            </button>
            <button className="btn" disabled={Boolean(busy)} onClick={() => enqueue("assemble", "合成成片", {})} type="button">
              {busy === "assemble" ? <Loader2 className="animate-spin" size={17} /> : <Film size={17} />}
              合成成片
            </button>
          </div>
        </div>
        {error ? <div className="mt-3 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      </div>

      {finalRender?.path ? (
        <article className="panel overflow-hidden">
          <video className="aspect-video w-full bg-slate-950 object-contain" controls preload="metadata" src={mediaUrl(detail.name, finalRender.path)} />
        </article>
      ) : null}

      <div className="grid grid-cols-3 gap-4 max-2xl:grid-cols-2 max-lg:grid-cols-1">
        {detail.shots_detail.map((shot) => (
          <ReviewShotCard
            key={shot.id}
            defaultProvider={detail.config.default_video_provider}
            projectName={detail.name}
            remoteProfile={remoteProfile}
            shot={shot}
          />
        ))}
      </div>
    </section>
  );
}

function ReviewShotCard({
  defaultProvider,
  projectName,
  remoteProfile,
  shot
}: {
  defaultProvider: string;
  projectName: string;
  remoteProfile: string;
  shot: Shot;
}) {
  const { enqueueTask, setMessage } = useAppStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const firstFrame = firstFrameRef(shot);
  const generatedClip = generatedClipRef(shot);
  const generatedAudio = generatedAudioRef(shot);
  const generationStatus = shotGenerationStatus(shot);

  async function rerunShot() {
    if (!remoteProfile) {
      setError("请先在工作流配置里填写远程机器");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await enqueueTask(
        projectName,
        "remote-run",
        { profile: remoteProfile, provider: shot.provider || defaultProvider, kind: "video", only: [shot.id] },
        `${shot.id} 重跑`
      );
      setMessage(`${shot.id} 重跑已加入队列`);
    } catch (failure) {
      setError(String((failure as Error).message || failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="panel overflow-hidden">
      <div className="flex h-14 items-center justify-between gap-3 border-b border-slate-100 px-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-teal-700">{shot.id}</span>
            <span className="truncate text-sm font-semibold text-slate-900">{shot.title}</span>
          </div>
          <div className="mt-0.5 text-xs text-slate-500">{shotGenerationLabel(generationStatus, Boolean(generatedClip))}</div>
        </div>
        <button className="btn h-9 px-2 text-xs" disabled={busy} onClick={rerunShot} type="button">
          {busy ? <Loader2 className="animate-spin" size={15} /> : <RefreshCw size={15} />}
          重跑
        </button>
      </div>
      <div className="grid gap-3 p-4">
        {generatedClip ? (
          <video
            className="aspect-video w-full rounded-lg border border-slate-200 bg-slate-950 object-contain"
            controls
            preload="metadata"
            poster={firstFrame ? mediaUrl(projectName, firstFrame) : undefined}
            src={mediaUrl(projectName, generatedClip)}
          />
        ) : (
          <div className="aspect-video overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
            {firstFrame ? (
              <img className="h-full w-full object-cover" src={mediaUrl(projectName, firstFrame)} alt={`${shot.id} 首帧`} />
            ) : (
              <div className="grid h-full place-items-center text-slate-400">
                <ImagePlus size={28} />
              </div>
            )}
          </div>
        )}
        {generatedAudio ? <audio className="w-full" src={mediaUrl(projectName, generatedAudio)} controls /> : null}
        <div className="line-clamp-3 text-sm leading-6 text-slate-600">{shot.visual_prompt}</div>
        {error ? <div className="whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      </div>
    </article>
  );
}

function WorkflowPanel() {
  const { detail } = useAppStore();
  const [checking, setChecking] = useState("");
  const [results, setResults] = useState<Record<string, ComfyCheck>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  if (!detail) return null;
  const projectName = detail.name;

  async function check(profile: string, kind: string) {
    setChecking(profile);
    setErrors((current) => ({ ...current, [profile]: "" }));
    try {
      const result = await checkComfyWorkflow(projectName, profile, kind);
      setResults((current) => ({ ...current, [profile]: result }));
    } catch (error) {
      setErrors((current) => ({ ...current, [profile]: friendlyError(error) }));
    } finally {
      setChecking("");
    }
  }

  return (
    <section className="grid gap-4">
      <div className="grid grid-cols-2 gap-4 max-xl:grid-cols-1">
        {detail.workflows_detail.map((workflow) => (
          <WorkflowCard
            key={workflow.name}
            checking={checking === workflow.name}
            error={errors[workflow.name]}
            onCheck={() => check(workflow.name, workflow.kind)}
            result={results[workflow.name]}
            workflow={workflow}
          />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-4 max-xl:grid-cols-1">
        {detail.remote_profiles_detail.map((profile) => (
          <RemoteProfileCard key={profile.name} profile={profile} />
        ))}
      </div>
    </section>
  );
}

function WorkflowCard({
  checking,
  error,
  onCheck,
  result,
  workflow
}: {
  checking: boolean;
  error?: string;
  onCheck: () => void;
  result?: ComfyCheck;
  workflow: WorkflowSummary;
}) {
  const { saveWorkflowSettings, setMessage } = useAppStore();
  const [baseUrl, setBaseUrl] = useState(workflow.base_url || "");
  const [workflowPath, setWorkflowPath] = useState(workflow.workflow_path || "");
  const [workflowJson, setWorkflowJson] = useState("");
  const [workflowFilename, setWorkflowFilename] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    setBaseUrl(workflow.base_url || "");
    setWorkflowPath(workflow.workflow_path || "");
    setWorkflowJson("");
    setWorkflowFilename("");
  }, [workflow.base_url, workflow.workflow_path, workflow.name]);

  async function save() {
    setSaving(true);
    setSaveError("");
    try {
      await saveWorkflowSettings(workflow.name, {
        base_url: baseUrl,
        workflow_path: workflowPath,
        workflow_json: workflowJson || undefined,
        workflow_filename: workflowFilename || undefined
      });
      setWorkflowJson("");
      setWorkflowFilename("");
    } catch (saveFailure) {
      setSaveError(friendlyError(saveFailure));
    } finally {
      setSaving(false);
    }
  }

  async function upload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setWorkflowJson(text);
      setWorkflowFilename(file.name);
      setWorkflowPath(`保存为 workflows/${file.name.replace(/[^A-Za-z0-9_.-]/g, "_")}`);
    } catch (uploadFailure) {
      setMessage(String((uploadFailure as Error).message || uploadFailure));
    } finally {
      event.target.value = "";
    }
  }

  return (
    <article className="panel p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-teal-700">
            <Boxes size={15} />
            {workflowKindLabel(workflow.kind)}
          </div>
          <h2 className="mt-2 text-lg font-semibold text-slate-950">{workflow.title}</h2>
        </div>
        <span className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-500">{workflow.provider}</span>
      </div>

      <dl className="mt-5 grid gap-3 text-sm">
        <InfoRow label="配置档" value={workflow.name} />
        <InfoRow label="配置变量" value={`${workflow.base_url_env} / ${workflow.workflow_env} / ${workflow.profile_env}`} />
      </dl>

      <div className="mt-5 grid gap-3">
        <LabeledInput label="ComfyUI 地址" value={baseUrl} onChange={setBaseUrl} />
        <LabeledInput label="工作流路径" value={workflowPath} onChange={setWorkflowPath} />
        <div className="flex flex-wrap items-center gap-2">
          <label className="btn">
            <UploadCloud size={17} />
            上传 JSON
            <input className="hidden" type="file" accept="application/json,.json" onChange={upload} />
          </label>
          <button className="btn btn-primary" disabled={saving} onClick={save} type="button">
            {saving ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
            保存配置
          </button>
          <button className="btn" disabled={checking} onClick={onCheck} type="button">
            {checking ? <Loader2 className="animate-spin" size={17} /> : <CheckCircle2 size={17} />}
            检查连接
          </button>
        </div>
        {workflowFilename ? <div className="truncate text-xs text-slate-500">已选择：{workflowFilename}</div> : null}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {workflow.tags.map((tag) => (
          <span key={tag} className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">
            {tag}
          </span>
        ))}
      </div>
      {saveError ? <div className="mt-4 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{saveError}</div> : null}
      {error ? <div className="mt-4 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      {result ? <ComfyCheckResult result={result} /> : null}
    </article>
  );
}

function RemoteProfileCard({ profile }: { profile: RemoteProfileSummary }) {
  const { saveRemoteProfile } = useAppStore();
  const [host, setHost] = useState(profile.host || "");
  const [sshPort, setSshPort] = useState(profile.ssh_port || "");
  const [remoteDir, setRemoteDir] = useState(profile.remote_dir || "");
  const [localDir, setLocalDir] = useState(profile.local_dir || "");
  const [remoteAutoVideo, setRemoteAutoVideo] = useState(profile.remote_auto_video || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setHost(profile.host || "");
    setSshPort(profile.ssh_port || "");
    setRemoteDir(profile.remote_dir || "");
    setLocalDir(profile.local_dir || "");
    setRemoteAutoVideo(profile.remote_auto_video || "");
  }, [profile.host, profile.local_dir, profile.name, profile.remote_auto_video, profile.remote_dir, profile.ssh_port]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      await saveRemoteProfile(profile.name, {
        host,
        ssh_port: sshPort,
        remote_dir: remoteDir,
        local_dir: localDir,
        remote_auto_video: remoteAutoVideo
      });
    } catch (saveFailure) {
      setError(friendlyError(saveFailure));
    } finally {
      setSaving(false);
    }
  }

  const envEntries = Object.entries(profile.remote_env || {});

  return (
    <article className="panel p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-teal-700">
            <Cloud size={15} />
            远程机器
          </div>
          <h2 className="mt-2 text-lg font-semibold text-slate-950">{profile.name}</h2>
        </div>
        <span className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-500">AutoDL</span>
      </div>

      <div className="mt-5 grid grid-cols-[1fr_140px] gap-3 max-md:grid-cols-1">
        <LabeledInput label="SSH 主机" value={host} onChange={setHost} />
        <LabeledInput label="SSH 端口" type="number" value={sshPort} onChange={setSshPort} />
      </div>
      <div className="mt-3 grid gap-3">
        <LabeledInput label="远程目录" value={remoteDir} onChange={setRemoteDir} />
        <LabeledInput label="本地缓存目录" value={localDir} onChange={setLocalDir} />
        <LabeledInput label="远端 auto-video 命令" value={remoteAutoVideo} onChange={setRemoteAutoVideo} />
      </div>

      {envEntries.length ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {envEntries.map(([name, value]) => (
            <span key={name} className="max-w-full truncate rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600">
              {name}={value}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-5 flex justify-end">
        <button className="btn btn-primary" disabled={saving} onClick={save} type="button">
          {saving ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
          保存远程配置
        </button>
      </div>
      {error ? <div className="mt-4 whitespace-pre-wrap rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
    </article>
  );
}

function ComfyCheckResult({ result }: { result: ComfyCheck }) {
  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-800">连接检查结果</div>
        <TaskStatusBadge status={result.ok ? "succeeded" : "failed"} />
      </div>
      <div className="mb-3 grid gap-1 text-xs text-slate-500">
        <div className="break-words">地址：{result.base_url || "未解析"}</div>
        <div className="break-words">工作流：{result.workflow || "未解析"}</div>
      </div>
      <div className="grid gap-2">
        {result.checks.map((check) => (
          <div key={check.name} className="rounded-md border border-white bg-white px-3 py-2 text-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="font-medium text-slate-800">{comfyCheckLabel(check.name)}</div>
              <ComfyCheckBadge status={check.status} />
            </div>
            <div className="mt-1 whitespace-pre-wrap break-words text-xs text-slate-500">{check.message}</div>
            {check.fix ? <div className="mt-1 whitespace-pre-wrap break-words text-xs text-amber-700">{check.fix}</div> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function ComfyCheckBadge({ status }: { status: ComfyCheck["checks"][number]["status"] }) {
  const className = {
    ok: "border-teal-200 bg-teal-50 text-teal-700",
    warning: "border-amber-200 bg-amber-50 text-amber-700",
    failed: "border-red-200 bg-red-50 text-red-700"
  }[status];
  const label = { ok: "正常", warning: "注意", failed: "失败" }[status];
  return <span className={`rounded-md border px-2 py-0.5 text-xs ${className}`}>{label}</span>;
}

function comfyCheckLabel(value: string) {
  return {
    base_url: "服务地址",
    system_stats: "系统状态",
    gpu: "显卡状态",
    queue: "队列状态",
    queue_idle: "空闲状态",
    workflow_path: "工作流路径",
    workflow: "工作流结构"
  }[value] || value;
}

function RunPanel() {
  const { cancelQueuedTask, detail, enqueueTask, loadTask, refreshTasks, setMessage, tasks } = useAppStore();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");

  useEffect(() => {
    if (!detail) return;
    refreshTasks(detail.name).catch((err) => setError(String((err as Error).message || err)));
    const timer = window.setInterval(() => {
      refreshTasks(detail.name).catch((err) => setError(String((err as Error).message || err)));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [detail, refreshTasks]);

  useEffect(() => {
    if (!selectedTaskId && tasks[0]) {
      setSelectedTaskId(tasks[0].id);
    }
  }, [selectedTaskId, tasks]);

  useEffect(() => {
    if (!selectedTaskId) return;
    loadTask(selectedTaskId).catch((err) => setError(String((err as Error).message || err)));
    const timer = window.setInterval(() => {
      loadTask(selectedTaskId).catch((err) => setError(String((err as Error).message || err)));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [loadTask, selectedTaskId]);

  if (!detail) return null;
  const project = detail;
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) || tasks[0] || null;
  const firstRemoteProfile = project.remote_profiles_detail[0]?.name || "";

  const actions = [
    { key: "validate", label: "校验项目", icon: CheckCircle2, payload: {} },
    {
      key: "first-frame-generate",
      label: "生成首帧",
      icon: ImagePlus,
      payload: { provider: project.config.default_image_provider || "mock", skip_succeeded: true }
    },
    { key: "jobs-plan", label: "生成计划", icon: Clapperboard, payload: { provider: project.config.default_video_provider, kind: "video" } },
    { key: "generate", label: "提交生成", icon: Play, payload: { provider: project.config.default_video_provider, kind: "video" } },
    { key: "voice-plan", label: "配音计划", icon: Mic2, action: "jobs-plan", payload: { provider: project.config.default_audio_provider, kind: "audio", skip_succeeded: true } },
    { key: "voice-generate", label: "生成配音", icon: Mic2, action: "generate", payload: { provider: project.config.default_audio_provider, kind: "audio", skip_succeeded: true } },
    {
      key: "remote-plan",
      label: "远程预案",
      icon: Cloud,
      payload: { profile: firstRemoteProfile, provider: "comfyui_wan", kind: "video" },
      disabled: !firstRemoteProfile
    },
    {
      key: "remote-first-frame",
      label: "远程首帧",
      icon: Cloud,
      payload: { profile: firstRemoteProfile, provider: project.config.default_image_provider || "mock" },
      disabled: !firstRemoteProfile
    },
    {
      key: "produce-all",
      label: "一键完整生产",
      icon: Wand2,
      payload: { profile: firstRemoteProfile, provider: "comfyui_wan", kind: "video" },
      disabled: !firstRemoteProfile
    },
    {
      key: "remote-run",
      label: "生成剩余分镜",
      icon: Cloud,
      payload: { profile: firstRemoteProfile, provider: "comfyui_wan", kind: "video", skip_succeeded: true },
      disabled: !firstRemoteProfile
    },
    { key: "probe", label: "验片", icon: Eye, payload: { dry_run: false } },
    { key: "continuity", label: "提取连续性", icon: Copy, payload: { force: true } },
    { key: "assemble-plan", label: "合成预案", icon: Film, payload: {} },
    { key: "assemble", label: "合成成片", icon: Film, payload: {} },
    {
      key: "remote-wrapup",
      label: "远程收尾检查",
      icon: Terminal,
      payload: { profile: firstRemoteProfile },
      disabled: !firstRemoteProfile
    }
  ];

  async function run(action: (typeof actions)[number]) {
    setBusy(action.key);
    setError("");
    try {
      const taskAction = "action" in action && action.action ? action.action : action.key;
      const task = await enqueueTask(project.name, taskAction, action.payload, action.label);
      setSelectedTaskId(task.id);
      setMessage(`${action.label}已加入队列`);
    } catch (error) {
      setError(String((error as Error).message || error));
    } finally {
      setBusy("");
    }
  }

  async function refreshNow() {
    setError("");
    try {
      await refreshTasks(project.name);
      if (selectedTaskId) await loadTask(selectedTaskId);
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  }

  async function cancelSelected() {
    if (!selectedTask) return;
    await cancelQueuedTask(selectedTask.id);
  }

  return (
    <section className="grid grid-cols-[360px_1fr] gap-4 max-xl:grid-cols-1">
      <div className="grid gap-4">
        <div className="panel p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-semibold">
              <Activity size={18} />
              生产动作
            </div>
            <button className="btn h-9 px-3" onClick={refreshNow} type="button" title="刷新任务">
              <RefreshCw size={16} />
            </button>
          </div>
          {error ? <Notice tone="bad" title="任务错误" body={error} /> : null}
          <div className="grid gap-2">
            {actions.map((action) => {
              const Icon = action.icon;
              return (
                <button
                  key={action.key}
                  className="btn justify-start"
                  disabled={Boolean(busy) || action.disabled}
                  onClick={() => run(action)}
                  title={action.disabled ? "请先配置远程机器" : action.label}
                  type="button"
                >
                  {busy === action.key ? <Loader2 className="animate-spin" size={17} /> : <Icon size={17} />}
                  {action.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="panel p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <Clock size={18} />
            任务队列
          </div>
          <div className="grid max-h-[420px] gap-2 overflow-auto pr-1">
            {tasks.length ? (
              tasks.map((task) => (
                <button
                  key={task.id}
                  className={`rounded-lg border px-3 py-2 text-left transition ${
                    selectedTask?.id === task.id ? "border-teal-300 bg-teal-50" : "border-slate-200 bg-white hover:bg-slate-50"
                  }`}
                  onClick={() => setSelectedTaskId(task.id)}
                  type="button"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium text-slate-900">{task.label}</span>
                    <TaskStatusBadge status={task.status} />
                  </div>
                  <div className="mt-1 truncate text-xs text-slate-500">
                    {task.id} · {formatTaskTime(task.created_at)}
                  </div>
                </button>
              ))
            ) : (
              <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-sm text-slate-500">
                暂无任务
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="panel overflow-hidden">
        {selectedTask ? (
          <div className="grid gap-0">
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Terminal size={18} className="text-teal-700" />
                  <h2 className="truncate text-lg font-semibold text-slate-950">{selectedTask.label}</h2>
                </div>
                <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
                  <span>{selectedTask.id}</span>
                  <span>创建 {formatTaskTime(selectedTask.created_at)}</span>
                  {selectedTask.finished_at ? <span>完成 {formatTaskTime(selectedTask.finished_at)}</span> : null}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <TaskStatusBadge status={selectedTask.status} />
                {selectedTask.status === "queued" ? (
                  <button className="btn h-9 px-3" onClick={cancelSelected} type="button" title="取消任务">
                    <XCircle size={16} />
                  </button>
                ) : null}
              </div>
            </div>
            {selectedTask.error ? (
              <div className="border-b border-red-100 bg-red-50 px-5 py-3 text-sm text-red-800">
                <div className="font-medium">{selectedTask.error}</div>
                {selectedTask.fix ? <div className="mt-1 whitespace-pre-wrap">{selectedTask.fix}</div> : null}
              </div>
            ) : null}
            <div className="grid grid-cols-[minmax(260px,0.82fr)_1fr] gap-0 max-2xl:grid-cols-1">
              <div className="border-r border-slate-100 p-5 max-2xl:border-b max-2xl:border-r-0">
                <div className="mb-3 text-sm font-semibold text-slate-800">执行日志</div>
                <div className="grid max-h-[520px] gap-2 overflow-auto pr-1">
                  {selectedTask.logs.length ? (
                    selectedTask.logs.map((log, index) => (
                      <div key={`${log.at}-${index}`} className="rounded-lg bg-slate-50 px-3 py-2 text-sm">
                        <div className="text-xs text-slate-400">{formatTaskTime(log.at)}</div>
                        <div className="mt-1 whitespace-pre-wrap break-words text-slate-700">{log.message}</div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-sm text-slate-500">
                      等待日志
                    </div>
                  )}
                </div>
              </div>
              <div className="p-5">
                <div className="mb-3 text-sm font-semibold text-slate-800">任务结果</div>
                <pre className="min-h-[520px] overflow-auto rounded-lg bg-slate-950 p-4 text-sm leading-6 text-slate-100">
                  {taskResultText(selectedTask)}
                </pre>
              </div>
            </div>
          </div>
        ) : (
          <div className="grid min-h-[520px] place-items-center text-slate-500">
            <div className="text-center">
              <Clock className="mx-auto text-teal-700" size={28} />
              <div className="mt-3 text-sm">提交一个生产动作后，这里会显示日志和结果</div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function TaskStatusBadge({ status }: { status: WebTaskStatus }) {
  const className = {
    queued: "border-slate-200 bg-slate-50 text-slate-600",
    running: "border-blue-200 bg-blue-50 text-blue-700",
    succeeded: "border-teal-200 bg-teal-50 text-teal-700",
    failed: "border-red-200 bg-red-50 text-red-700",
    canceled: "border-amber-200 bg-amber-50 text-amber-700"
  }[status];
  const icon = status === "running" ? <Loader2 className="animate-spin" size={13} /> : status === "failed" ? <AlertCircle size={13} /> : null;
  return (
    <span className={`inline-flex h-6 items-center gap-1 rounded-md border px-2 text-xs ${className}`}>
      {icon}
      {taskStatusLabel(status)}
    </span>
  );
}

function taskStatusLabel(status: WebTaskStatus) {
  return {
    queued: "排队",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
    canceled: "已取消"
  }[status];
}

function formatTaskTime(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function taskResultText(task: WebTask) {
  if (task.result !== undefined && task.result !== null) {
    return JSON.stringify(task.result, null, 2);
  }
  if (task.status === "failed") {
    return JSON.stringify({ error: task.error, fix: task.fix }, null, 2);
  }
  return "任务尚未产生结果";
}

function friendlyError(error: unknown) {
  const message = String((error as Error)?.message || error || "");
  if (message.includes("missing project.yaml") || message.includes("Create project.yaml")) {
    return "项目不存在或配置文件缺失\n请从左侧选择现有项目，或重新新建项目。";
  }
  if (message.includes("project not found")) {
    return "项目不存在\n请从左侧选择现有项目，或重新新建项目。";
  }
  return message;
}

function ConfigPanel() {
  const { configText, persistConfig, setMessage } = useAppStore();
  const [text, setText] = useState(configText);
  const [saving, setSaving] = useState(false);

  useEffect(() => setText(configText), [configText]);

  async function save() {
    setSaving(true);
    try {
      await persistConfig(text);
    } catch (error) {
      setMessage(String((error as Error).message || error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="grid gap-3">
      <div className="flex justify-end">
        <button className="btn btn-primary" disabled={saving} onClick={save} type="button">
          {saving ? <Loader2 className="animate-spin" size={17} /> : <Save size={17} />}
          保存配置
        </button>
      </div>
      <textarea
        className="min-h-[620px] w-full rounded-lg border border-slate-200 bg-slate-950 p-4 font-mono text-sm leading-6 text-slate-100 outline-none focus:border-teal-500"
        value={text}
        onChange={(event) => setText(event.target.value)}
        spellCheck={false}
      />
    </section>
  );
}

function LabeledInput({
  label,
  onChange,
  type = "text",
  value
}: {
  label: string;
  onChange: (value: string) => void;
  type?: string;
  value: string;
}) {
  return (
    <label className="grid gap-1">
      <span className="label">{label}</span>
      <input className="control w-full" type={type} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function LabeledTextarea({
  label,
  onChange,
  rows = 5,
  value
}: {
  label: string;
  onChange: (value: string) => void;
  rows?: number;
  value: string;
}) {
  return (
    <label className="grid gap-1">
      <span className="label">{label}</span>
      <textarea className="control h-auto min-h-[112px] w-full resize-y py-2" rows={rows} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[96px_1fr] gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words text-slate-800">{value}</dd>
    </div>
  );
}

function Notice({ body, title, tone }: { body: string; title: string; tone: "bad" | "ok" }) {
  return (
    <div className={`mb-4 rounded-lg border px-4 py-3 ${tone === "bad" ? "border-red-200 bg-red-50 text-red-800" : "border-teal-200 bg-teal-50 text-teal-800"}`}>
      <div className="flex items-start gap-2">
        {tone === "bad" ? <AlertCircle className="mt-0.5" size={17} /> : <CheckCircle2 className="mt-0.5" size={17} />}
        <div>
          <div className="font-medium">{title}</div>
          <div className="mt-1 whitespace-pre-wrap text-sm">{body}</div>
        </div>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="grid min-h-[520px] place-items-center">
      <div className="flex items-center gap-2 text-slate-500">
        <Loader2 className="animate-spin" size={18} />
        加载中
      </div>
    </div>
  );
}

function EmptyState({ hasTemplates }: { hasTemplates: boolean }) {
  return (
    <div className="grid min-h-[560px] place-items-center rounded-lg border border-dashed border-slate-300 bg-white">
      <div className="text-center">
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-lg bg-teal-50 text-teal-700">
          <Plus size={24} />
        </div>
        <div className="mt-4 text-lg font-semibold">暂无项目</div>
        <div className="mt-1 text-sm text-slate-500">{hasTemplates ? "从右上角新建一个项目" : "模板加载中"}</div>
      </div>
    </div>
  );
}

function firstFrameRef(shot: Shot) {
  return shot.refs.find((ref) => ref.type === "image" && ref.role === "first_frame")?.path;
}

function generatedClipRef(shot: Shot) {
  const clip = shot.manifest?.clip;
  return typeof clip === "string" ? clip : "";
}

function generatedAudioRef(shot: Shot) {
  const audio = shot.manifest?.audio;
  return typeof audio === "string" ? audio : "";
}

function shotGenerationStatus(shot: Shot) {
  return shot.freshness?.status || (generatedClipRef(shot) ? "generated" : "pending");
}

function shotGenerationLabel(status: ReturnType<typeof shotGenerationStatus>, hasClip: boolean) {
  if (status === "stale") return "首帧已更新，需重跑";
  if (status === "generated") return "已生成";
  return hasClip ? "需检查" : "未生成";
}

function ShotGenerationPill({ status }: { status: ReturnType<typeof shotGenerationStatus> }) {
  const stale = status === "stale";
  const className = stale ? "border-amber-200 bg-amber-50 text-amber-700" : "border-teal-200 bg-teal-50 text-teal-700";
  const Icon = stale ? AlertCircle : CheckCircle2;
  return (
    <span className={`inline-flex h-7 items-center gap-1 rounded-md border px-2 text-xs font-medium ${className}`}>
      <Icon size={13} />
      {stale ? "需重跑" : "已生成"}
    </span>
  );
}

function voiceGenerationStatus(shot: Shot) {
  return shot.voice_freshness?.status || (generatedAudioRef(shot) ? "generated" : "pending");
}

function voiceGenerationLabel(status: ReturnType<typeof voiceGenerationStatus>) {
  return {
    generated: "配音已同步",
    stale: "台词变化，需重配",
    pending: "未生成配音"
  }[status];
}

function VoiceStatusPill({ status }: { status: ReturnType<typeof voiceGenerationStatus> }) {
  const className = {
    generated: "border-teal-200 bg-teal-50 text-teal-700",
    stale: "border-amber-200 bg-amber-50 text-amber-700",
    pending: "border-slate-200 bg-slate-50 text-slate-500"
  }[status];
  return <span className={`shrink-0 rounded-md border px-2 py-0.5 text-xs ${className}`}>{voiceGenerationLabel(status)}</span>;
}

function mediaUrl(projectName: string, path: string) {
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `/media/${encodeURIComponent(projectName)}/${encoded}`;
}

function templateLabel(value: string) {
  if (value === "autodl_comfyui_wan") return "AutoDL 视频生成模板";
  if (value === "demo") return "本地演示模板";
  return value;
}

function workflowKindLabel(value: string) {
  if (value === "text_to_image") return "文生首帧";
  if (value === "image") return "图像生成";
  if (value === "image_to_video") return "图生视频";
  if (value === "text_to_video") return "文生视频";
  if (value === "video_to_video") return "视频重绘";
  return value;
}

export default App;
