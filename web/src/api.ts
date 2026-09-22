// Types and calls for the Lanternist API (src/lanternist/api/app.py).

export type Mode = "still" | "video";
export type Camera = "auto" | "push_in" | "pull_out" | "pan_left" | "pan_right" | "static";

export interface CastMember {
  id: string;
  name: string;
  look: string;
}

export interface Line {
  speaker: string;
  text: string;
}

export interface Scene {
  n: number;
  narration: Line[];
  visual: string;
  motion: string;
  sound: string;
  cast: string[];
  camera: Camera;
  mode: Mode;
  seed: number | null;
}

export interface Storyboard {
  title: string;
  language: string;
  audience: string;
  kind: string;
  style: string;
  voice: string;
  seed: number;
  subtitles: "off" | "sidecar" | "burned";
  cast: CastMember[];
  cast_sheet_prompt: string | null;
  models?: { writer: string; writer_effort: Effort | null };
  scenes: Scene[];
}

export interface StageState {
  status: "running" | "done";
  done: number;
  total: number;
  assets?: Record<string, string>;
  asset?: string;
}

export interface Progress {
  stages?: Record<string, StageState>;
  log?: string[];
  message?: string;
}

export type Effort = "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

/** What a write or rewrite job reports: which model wrote it and what OpenRouter charged. */
export interface WriterResult {
  writer?: string | null;
  cost_usd?: number | null;
  calls?: number;
  tokens_in?: number;
  tokens_out?: number;
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type JobKind = "write" | "rewrite" | "cast" | "board" | "render";

export interface FilmResult {
  film: string;
  srt: string | null;
  vtt: string | null;
  duration: number;
  path: string;
}

export interface Job {
  id: string;
  story_id: string;
  version: number | null;
  kind: JobKind;
  status: JobStatus;
  params: Record<string, unknown>;
  progress: Progress;
  result:
    | (Partial<FilmResult> & WriterResult & { version?: number; cast?: string | null; keyframes?: string[] })
    | null;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface StoryMeta {
  id: string;
  slug: string;
  title: string;
  language: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface StoryListItem extends StoryMeta {
  scenes: number;
  active_jobs: number;
  film: FilmResult | null;
  film_version: number | null;
  poster: string | null;
}

export interface BoardScene {
  n: number;
  audio: string | null;
  duration: number | null;
  keyframe: string | null;
  motion: string | null;
}

export interface BoardPeek {
  cast: string | null;
  scenes: BoardScene[];
  total: number | null;
  voice_ok: boolean;
}

export interface StoryDetail {
  story: StoryMeta;
  version: number;
  storyboard: Storyboard | null;
  board: BoardPeek | null;
  jobs: Job[];
  versions: { version: number; note: string; created_at: string }[];
  film: Job | null;
  writer: StoryWriter | null;
}

/** Who wrote a story, and what writing and rewriting it has cost, failed attempts included. */
export interface StoryWriter {
  id: string;
  model: string;
  local: boolean;
  cost_usd: number;
}

export interface Voice {
  name: string;
  path: string;
  has_transcript: boolean;
}

export interface Options {
  languages: { id: string; name: string }[];
  audiences: { id: string; name: string }[];
  kinds: { id: string; name: string }[];
  styles: { id: string; name: string; prompt: string }[];
  cameras: Camera[];
  voices: Voice[];
  fake_engines: boolean;
}

export interface Brief {
  idea: string;
  language: string;
  audience: string;
  kind: string;
  minutes: number;
  style: string;
  notes: string;
  mode: "still" | "hybrid" | "video";
  voice: string;
  writer: string;
  effort: Effort | null;
}

export interface WriterModel {
  id: string;
  label: string;
  provider: "ollama" | "openrouter";
  /** The provider's own id for it, e.g. "openai/gpt-5.6-luna". */
  model: string;
  local: boolean;
  recommended: boolean;
  /** Estimated cost per minute of story; 0 for local models, null when unknown. */
  usd_per_minute: number | null;
  /** Where the token counts behind the estimate come from: your stories, our trials, or a median. */
  basis: "free" | "measured" | "trial" | "typical" | "unknown";
  efforts: { id: Effort; name: string }[] | null;
  default_effort: Effort | null;
  price_in: number | null;
  price_out: number | null;
  /** The default writer, though neither Ollama nor OpenRouter offers it right now. */
  unavailable: boolean;
}

export interface WriterCatalog {
  default: string;
  models: WriterModel[];
  providers: {
    ollama: { ok: boolean; error: string | null };
    openrouter: { ok: boolean; error: string | null; configured: boolean };
  };
}

export interface Check {
  name: string;
  status: "ok" | "warn" | "fail";
  detail: string;
}

export type ProviderName = "openrouter" | "fal";

export interface Provider {
  name: ProviderName;
  label: string;
  configured: boolean;
  source: "env" | "keychain" | "file" | "fake" | null;
  last4: string | null;
  ok: boolean | null;
  detail: string;
  needed: boolean;
  usage: { usage: number | null; limit: number | null; limit_remaining: number | null } | null;
}

export interface SettingRow {
  key: string;
  label: string;
  value: unknown;
  source: "app" | "file" | "default";
}

/** The message to show for anything a promise rejected with. */
export const errorMessage = (e: unknown): string => (e instanceof Error ? e.message : String(e));

interface ErrorBody {
  detail?: string | { loc?: unknown[]; msg: string }[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const { detail } = (await res.json()) as ErrorBody;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail))
        message = detail.map((d) => `${(d.loc ?? []).join(".")}: ${d.msg}`).join("; ");
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => call<{ ok: boolean; fake_engines: boolean }>("GET", "/api/health"),
  options: () => call<Options>("GET", "/api/options"),
  doctor: () => call<Check[]>("GET", "/api/doctor"),
  stories: () => call<StoryListItem[]>("GET", "/api/stories"),
  story: (id: string) => call<StoryDetail>("GET", `/api/stories/${id}`),
  write: (brief: Brief) => call<{ story: StoryMeta; job: Job }>("POST", "/api/stories", { brief }),
  importStoryboard: (storyboard: unknown) =>
    call<{ story: StoryMeta; job: null }>("POST", "/api/stories", { storyboard }),
  save: (id: string, storyboard: Storyboard, base_version: number, note = "edited") =>
    call<{ story: StoryMeta; version: number }>("PUT", `/api/stories/${id}`, {
      storyboard,
      base_version,
      note,
    }),
  remove: (id: string) => call<void>("DELETE", `/api/stories/${id}`),
  rewrite: (id: string, n: number, instruction: string) =>
    call<Job>("POST", `/api/stories/${id}/scenes/${n}/rewrite`, { instruction }),
  reroll: (id: string, n: number) =>
    call<{ version: number; job: Job }>("POST", `/api/stories/${id}/scenes/${n}/reroll`),
  rerollCast: (id: string) => call<{ version: number; job: Job }>("POST", `/api/stories/${id}/cast/reroll`),
  run: (id: string, kind: "cast" | "board" | "render") => call<Job>("POST", `/api/stories/${id}/${kind}`),
  job: (id: string) => call<Job>("GET", `/api/jobs/${id}`),
  cancel: (id: string) => call<{ cancelled: boolean }>("POST", `/api/jobs/${id}/cancel`),
  providers: () => call<Provider[]>("GET", "/api/providers"),
  setKey: (name: ProviderName, key: string) =>
    call<Provider & { stored_in: string }>("PUT", `/api/providers/${name}/key`, { key }),
  clearKey: (name: ProviderName) => call<void>("DELETE", `/api/providers/${name}/key`),
  settings: () => call<SettingRow[]>("GET", "/api/settings"),
  saveSettings: (changes: Record<string, unknown>) => call<SettingRow[]>("PUT", "/api/settings", { changes }),
  writers: () => call<WriterCatalog>("GET", "/api/models?capability=writer.chat"),
  voices: () => call<Voice[]>("GET", "/api/voices"),
  addVoice: (form: FormData) => call<Voice>("POST", "/api/voices", form),
};

export const asset = (id: string | null | undefined, download?: string) =>
  id ? `/api/assets/${id}${download ? `?download=${encodeURIComponent(download)}` : ""}` : undefined;

export const isActive = (j: Job) => j.status === "queued" || j.status === "running";

export const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  es: "Spanish",
  pt: "Portuguese",
  fr: "French",
  de: "German",
  it: "Italian",
  ru: "Russian",
  zh: "Chinese",
  ja: "Japanese",
  ko: "Korean",
};

export const STYLE_NAMES: Record<string, string> = {
  watercolour: "Watercolour",
  "3d_film": "3D film",
  paper_cutout: "Paper cut-out",
  clay: "Clay",
  ink_pencil: "Ink and pencil",
  anime: "Anime",
};

/** Dollars as people read them: cents for small amounts, never "$0.00" for something that cost money. */
export function fmtUsd(usd: number | null | undefined): string {
  if (usd == null) return "";
  if (usd === 0) return "free";
  if (usd < 0.01) return `$${usd.toFixed(usd < 0.001 ? 4 : 3)}`;
  return `$${usd.toFixed(2)}`;
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return m ? `${m}:${String(r).padStart(2, "0")}` : `${s.toFixed(1)} s`;
}
