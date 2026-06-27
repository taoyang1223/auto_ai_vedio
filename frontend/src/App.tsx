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
  Eye,
  Film,
  GripVertical,
  ImagePlus,
  KeyRound,
  LayoutDashboard,
  Loader2,
  LogOut,
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
import { checkComfyWorkflow } from "./api";
import { useAppStore } from "./store";
import type { ComfyCheck, ProjectDetail, RemoteProfileSummary, Shot, WebTask, WebTaskStatus, WorkflowSummary } from "./types";

type TabKey = "shots" | "workflow" | "run" | "config";

const tabItems: Array<{ key: TabKey; label: string; icon: typeof Clapperboard }> = [
  { key: "shots", label: "分镜编排", icon: Clapperboard },
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

      {tab === "shots" ? <ShotsPanel /> : null}
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
    <section className="grid grid-cols-5 gap-3 max-2xl:grid-cols-3 max-lg:grid-cols-2 max-sm:grid-cols-1">
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
      tab: "shots",
      icon: ImagePlus
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
      metric: activeTasks ? `${activeTasks} 个进行中` : failedTasks ? `${failedTasks} 个失败` : succeededTasks ? `${succeededTasks} 个完成` : "未提交",
      status: activeTasks ? "running" : failedTasks ? "warn" : succeededTasks ? "done" : "pending",
      tab: "run",
      icon: Activity
    },
    {
      key: "renders",
      label: "最终成片",
      metric: renderCount ? `${renderCount} 个结果` : "未生成",
      status: renderCount ? "done" : "pending",
      tab: "run",
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
              <SortableShotCard key={shot.id} index={index} projectName={project.name} shot={shot} updateShot={updateShot} />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </section>
  );
}

function SortableShotCard({
  index,
  projectName,
  shot,
  updateShot
}: {
  index: number;
  projectName: string;
  shot: Shot;
  updateShot: (index: number, patch: Partial<Shot>) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: shot.id });
  const { uploadFrame } = useAppStore();
  const style = { transform: CSS.Transform.toString(transform), transition };
  const firstFrame = firstFrameRef(shot);
  const generatedClip = generatedClipRef(shot);

  async function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    await uploadFrame(shot.id, file);
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
        {generatedClip ? (
          <span className="inline-flex h-7 items-center gap-1 rounded-md border border-teal-200 bg-teal-50 px-2 text-xs font-medium text-teal-700">
            <CheckCircle2 size={13} />
            已生成
          </span>
        ) : null}
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

  async function check(profile: string) {
    setChecking(profile);
    setErrors((current) => ({ ...current, [profile]: "" }));
    try {
      const result = await checkComfyWorkflow(projectName, profile);
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
            onCheck={() => check(workflow.name)}
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
    { key: "jobs-plan", label: "生成计划", icon: Clapperboard, payload: { provider: project.config.default_video_provider, kind: "video" } },
    { key: "generate", label: "提交生成", icon: Play, payload: { provider: project.config.default_video_provider, kind: "video" } },
    {
      key: "remote-plan",
      label: "远程预案",
      icon: Cloud,
      payload: { profile: firstRemoteProfile, provider: "comfyui_wan", kind: "video" },
      disabled: !firstRemoteProfile
    },
    {
      key: "remote-run",
      label: "远程执行",
      icon: Cloud,
      payload: { profile: firstRemoteProfile, provider: "comfyui_wan", kind: "video" },
      disabled: !firstRemoteProfile
    },
    { key: "probe", label: "验片", icon: Eye, payload: { dry_run: false } },
    { key: "assemble-plan", label: "合成预案", icon: Film, payload: {} }
  ];

  async function run(action: (typeof actions)[number]) {
    setBusy(action.key);
    setError("");
    try {
      const task = await enqueueTask(project.name, action.key, action.payload, action.label);
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
  if (value === "image_to_video") return "图生视频";
  if (value === "text_to_video") return "文生视频";
  if (value === "video_to_video") return "视频重绘";
  return value;
}

export default App;
