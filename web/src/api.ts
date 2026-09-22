// Types and calls for the Lanternist API (src/lanternist/api/app.py).

export type Mode = "still" | "video";
export type Camera = "auto" | "push_in" | "pull_out" | "pan_left" | "pan_right" | "static";

export interface CastMember {
  id: string;
  name: string;
  look: string;
  /** An object the story turns on is locked by its look alone, off the cast sheet. */
  kind: "character" | "object";
}

/** A setting seen in more than one scene, restated in every picture set there. */
export interface Place {
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
  /** The id of the place it's set in, or empty. */
  place: string;
  camera: Camera;
  mode: Mode;
  seed: number | null;
  /** A new take of the scene's video; null follows `seed`. */
  video_seed: number | null;
  /** Another shot of the same paragraph as the scene before: a short pause and a cut, not a fade. */
  continues: boolean;
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
  /** Each character drawn alone from the cast sheet, and each picture given only who is in it. */
  portraits: boolean;
  places: Place[];
  models: Models;
  scenes: Scene[];
}

/** Which model makes each stage of a story; an empty id means the default from Settings. */
export interface Models {
  writer: string;
  writer_effort: Effort | null;
  tts: string;
  image: string;
  image_quality: string | null;
  video: string;
  video_quality: string | null;
  /** A registry id, "none" to leave silent video scenes silent, or empty for the default. */
  ambience: string;
}

export interface StageState {
  /** What the progress row is called; the backend names every stage. */
  label?: string;
  /** What the stage is doing, in plain words: "Painting the scenes". */
  doing?: string;
  status: "running" | "done";
  done: number;
  total: number;
  /** What a row of one item made: the cast sheet, or the film. */
  asset?: string;
  /** What the stage has paid for so far, when it runs on a paid model. */
  spent_usd?: number;
  /** How long it has worked, from starting on its first item. */
  secs?: number;
  /** How far through its one item it is, 0 to 1, when it says: the mix, from ffmpeg. */
  at?: number;
  /** The passes a stage of one item goes through, in order (the writer's); `done` counts those ended. */
  passes?: string[];
  /** What makes its items: a model's name, or ffmpeg; and whether that's on this machine. */
  model?: string;
  local?: boolean;
}

/** Where one scene's step in a stage, or one character's portrait, has got to in a job. */
export interface Step {
  /** `failed`: the picture check failed its picture, and says why in `note`. */
  state: "queued" | "cached" | "waiting" | "working" | "done" | "failed";
  /** Kept while it's made again, until the new one lands. */
  asset?: string;
  /** How long it took, from starting on it to its output landing. */
  secs?: number;
  /** How many times the job made it: 2 once the picture check had it drawn again. */
  tries?: number;
  /** Waiting: how many requests are ahead of it in the provider's queue. */
  ahead?: number;
  note?: string;
  /** What the provider billed for it, when it bills by scene: a portrait's and a check's count only in their stage. */
  cost_usd?: number;
}

export interface Progress {
  stages?: Record<string, StageState>;
  /** By scene number, then by stage. */
  scenes?: Record<string, Record<string, Step>>;
  /** Each character's portrait, by character id: a board's or render's are here from its start. */
  cast?: Record<string, Step>;
  /** A board or render draws the story's cast sheet. */
  sheet?: boolean;
  /** What the job has paid for so far. */
  spent_usd?: number;
  /** A board's or render's time left, in seconds, as a range: never a countdown. */
  eta_s?: [number, number];
  /** Each stage's share of the job's time, in the order they run, so a long stage is drawn long. */
  phases?: { stage: string; label: string; share: number }[];
  /** How far through the job it is, 0 to 1, by time. */
  fraction?: number;
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
export type JobKind = "write" | "rewrite" | "cast" | "board" | "render" | "sample";

export interface FilmResult {
  film: string;
  srt: string | null;
  vtt: string | null;
  duration: number;
  path: string;
}

/** Why a job stopped before a remote stage: it would have gone past the story's budget. */
export interface BudgetStop {
  stage: string;
  need_usd: number;
  spent_usd: number;
  budget_usd: number;
  short_usd: number;
}

export interface EstimateLine {
  stage: string;
  label: string;
  model: string;
  model_label: string;
  local: boolean;
  steps: number;
  todo: number;
  cost_usd: number;
  gpu_seconds: number;
  paid_seconds: number;
  waste_seconds: number;
}

/** What a board or render would cost now: cached steps are free, local ones cost GPU time. */
export interface Estimate {
  kind: "board" | "render";
  lines: EstimateLine[];
  total_usd: number;
  gpu_seconds: number;
  waste_seconds: number;
  /** Scene lengths come from recorded narration, not from the words. */
  measured: boolean;
  price_date: string | null;
  /** What a new take of each video scene would cost. */
  retakes: { scene: number; cost_usd: number }[];
  budget_usd?: number;
  spent_usd?: number;
  short_usd?: number;
  /** The budget that fits all of it: what "raise the budget and carry on" asks for. */
  raise_to_usd?: number;
}

export interface Budget {
  usd: number;
  /** The story has no budget of its own and follows Settings. */
  default: boolean;
  spent_usd: number;
}

export interface Job {
  id: string;
  /** None for a job that belongs to no story: a voice sample. */
  story_id: string | null;
  version: number | null;
  kind: JobKind;
  status: JobStatus;
  params: Record<string, unknown>;
  progress: Progress;
  result:
    | (Partial<FilmResult> &
        WriterResult & {
          version?: number;
          cast?: string | null;
          keyframes?: string[];
          budget?: BudgetStop;
          /** By scene, why the picture check had its picture drawn again (saved as `version`). */
          redrawn?: Record<string, string>;
          /** By scene, why its picture still fails the check. */
          flagged?: Record<string, string>;
          /** A voice sample job's line. */
          audio?: string;
        })
    | null;
  error: string | null;
  /** The estimate shown before the job ran. */
  estimate: Estimate | null;
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
  /** How far through its running job is, 0 to 1, by time; null when nothing's running or it can't say. */
  progress: number | null;
  film: FilmResult | null;
  film_version: number | null;
  poster: string | null;
  spent_usd: number;
}

export interface BoardScene {
  n: number;
  /** The first sentence of its narration. */
  line: string;
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
  budget: Budget;
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

/** A voice a narration model offers, with its sample line once one was made. */
export interface PresetVoice {
  id: string;
  label: string;
  sample: string | null;
}

/** The voices of one narration model: its presets, and the recordings it clones. */
export interface VoiceCatalog {
  model: string;
  label: string;
  local: boolean;
  clone: boolean;
  /** It speaks the language asked about. */
  speaks: boolean;
  presets: PresetVoice[];
  recordings: (Voice & { sample: string | null })[];
  /** What making one sample costs; null for a model on this machine. */
  sample_usd: number | null;
}

export interface Options {
  languages: { id: string; name: string }[];
  audiences: { id: string; name: string }[];
  kinds: { id: string; name: string }[];
  styles: { id: string; name: string; prompt: string }[];
  cameras: Camera[];
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

export type Capability = "tts.speak" | "image.keyframe" | "video.image_to_video" | "audio.ambience";

export interface MediaPrice {
  /** List price per `per` (a picture, a second of video); null for models on this machine. */
  usd: number | null;
  /** GPU time per `per`, for models on this machine. */
  gpu_seconds: number | null;
}

/** A model a media stage can use, from the registry, with its price at each quality it offers. */
export interface MediaModel extends MediaPrice {
  id: string;
  label: string;
  provider: "local" | "fal";
  local: boolean;
  /** Runs here now: a local model, or a remote one whose provider has a key. */
  available: boolean;
  status: string;
  notes: string;
  licence: string;
  commercial_use: boolean | "below_10m_revenue";
  per: string;
  /** Video: the model makes its own sound bed, so no ambience model is needed. */
  sound?: boolean;
  quality: {
    param: string;
    default: string;
    options: (MediaPrice & { id: string; label: string })[];
  } | null;
}

export interface MediaCatalog {
  default: string;
  models: MediaModel[];
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
  /** For a default-model setting: the stage it picks for. */
  capability: Capability | null;
  /** For a model setting that may be "none": what that means. */
  off: string | null;
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
  retake: (id: string, n: number) =>
    call<{ version: number; job: Job }>("POST", `/api/stories/${id}/scenes/${n}/retake`),
  run: (id: string, kind: "cast" | "board" | "render") => call<Job>("POST", `/api/stories/${id}/${kind}`),
  estimate: (id: string, kind: "board" | "render") =>
    call<Estimate>("GET", `/api/stories/${id}/estimate?kind=${kind}`),
  setBudget: (id: string, usd: number | null) => call<Budget>("PUT", `/api/stories/${id}/budget`, { usd }),
  job: (id: string) => call<Job>("GET", `/api/jobs/${id}`),
  cancel: (id: string) => call<{ cancelled: boolean }>("POST", `/api/jobs/${id}/cancel`),
  providers: () => call<Provider[]>("GET", "/api/providers"),
  setKey: (name: ProviderName, key: string) =>
    call<Provider & { stored_in: string }>("PUT", `/api/providers/${name}/key`, { key }),
  clearKey: (name: ProviderName) => call<void>("DELETE", `/api/providers/${name}/key`),
  settings: () => call<SettingRow[]>("GET", "/api/settings"),
  saveSettings: (changes: Record<string, unknown>) => call<SettingRow[]>("PUT", "/api/settings", { changes }),
  writers: () => call<WriterCatalog>("GET", "/api/models?capability=writer.chat"),
  models: (capability: Capability) => call<MediaCatalog>("GET", `/api/models?capability=${capability}`),
  voiceCatalog: (tts: string, language: string) =>
    call<VoiceCatalog>(
      "GET",
      `/api/voices/catalog?tts=${encodeURIComponent(tts)}&language=${encodeURIComponent(language)}`,
    ),
  sample: (tts: string, voice: string, language: string) =>
    call<{ audio: string | null; job: Job | null }>("POST", "/api/voices/sample", { tts, voice, language }),
  addVoice: (form: FormData) => call<Voice>("POST", "/api/voices", form),
};

/** Where a recording in the voices folder plays from. */
export const recording = (name: string) => `/api/voices/${encodeURIComponent(name)}/audio`;

export const asset = (id: string | null | undefined, download?: string) =>
  id ? `/api/assets/${id}${download ? `?download=${encodeURIComponent(download)}` : ""}` : undefined;

/** A picture about as wide as it's shown: the server makes a small JPEG of it once and keeps it. */
export const thumb = (id: string | null | undefined, width: number) =>
  id ? `/api/assets/${id}?w=${width}` : undefined;

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

/** How a still scene's camera moves, as the Script step and the reel's cards name it. */
export const CAMERA_NAMES: Record<Camera, string> = {
  auto: "Auto",
  push_in: "Push in",
  pull_out: "Pull out",
  pan_left: "Pan left",
  pan_right: "Pan right",
  static: "Static",
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

/** A button's label with what pressing it costs, when it costs money. */
export function withPrice(label: string, usd: number | null | undefined): string {
  return usd ? `${label} · ${fmtUsd(usd)}` : label;
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s == null) return "";
  const m = Math.floor(s / 60);
  const r = Math.round(s - m * 60);
  return m ? `${m}:${String(r).padStart(2, "0")}` : `${s.toFixed(1)} s`;
}

/** A price per unit: fractions of a cent matter here ($0.0125 a second), unlike in a total. */
function fmtRate(usd: number): string {
  return usd >= 0.1 ? `$${usd.toFixed(2)}` : `$${Number(usd.toPrecision(3))}`;
}

/** What a model costs for one unit of its output, as people read it. */
export function priceOf(p: MediaPrice | undefined, per: string): string {
  if (p?.usd != null) return `${fmtRate(p.usd)} a ${per}`;
  if (p?.gpu_seconds != null) return `free, about ${Math.round(p.gpu_seconds)} s of GPU a ${per}`;
  return "free, on this machine";
}

/** The chosen model of a catalog, and the price at the chosen quality. */
export function chosenModel(catalog: MediaCatalog | null, value: string, quality: string | null) {
  const model = catalog?.models.find((m) => m.id === (value || catalog.default));
  const q = model?.quality;
  const qualityId = q ? (q.options.some((o) => o.id === quality) ? quality : q.default) : null;
  const price: MediaPrice | undefined = q ? q.options.find((o) => o.id === qualityId) : model;
  return { model, qualityId, price };
}
