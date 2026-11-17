export interface StressMLResult {
  enabled: boolean;
  applied: {word: string; stressed: string; confidence: number}[];
  skippedKnown: number;
  /** OmniVoice local pipeline: counts of added accents per stage. */
  stageCounts?: {usual: number; dictionary: number; statistical: number; ml: number};
}
export interface FrontendResult { normalized: string; phonemes: string; stressML: StressMLResult; }
export interface SynthesisOptions {
  /** Optional accents; OmniVoice receives stressed text, not BelG2P phonemes. */
  useStressML?: boolean;
  /** 0.5–2, default 1. GlowTTS/OmniVoice: duration conditioning; MOSS: pitch-preserving WSOLA. Never playbackRate. */
  speed?: number;
  /** OmniVoice only: iterative generation steps, default 16. */
  omniSteps?: 8 | 16 | 32;
  /** MOSS only: safety limit, 1–375 frames (12.5 frames/s), default 375. */
  mossMaxFrames?: number;
}
export interface BelVoiceOptions {
  /** Each engine owns one voice. Dispose it before switching to limit memory. */
  voice?: 'default' | 'female-1' | 'omnivoice' | 'moss';
  /** Experimental OmniVoice only. No automatic larger-download fallback. */
  backend?: 'wasm' | 'webgpu';
  /** Required explicit opt-in before OmniVoice can load large model files. */
  allowModelDownload?: boolean;
  /** Optional OmniVoice model mirror; defaults to a pinned Hugging Face revision. */
  modelBaseUrl?: string | URL;
  /** Same-origin static runtime directory; defaults to this module's directory. */
  assetsUrl?: string | URL;
  /** 0 = auto (up to 4 threads); without cross-origin isolation falls back to 1. */
  numThreads?: number;
  onLog?: (message: string) => void;
  onStatus?: (message: string) => void;
  onFrontend?: (result: FrontendResult) => void;
}
export interface RuntimeInfo {
  voice: 'default' | 'female-1' | 'omnivoice' | 'moss';
  engine?: 'omnivoice' | 'moss';
  backend?: 'wasm' | 'webgpu';
  requestedThreads: number;
  numThreads: number;
  crossOriginIsolated: boolean;
  hardwareConcurrency: number;
  sampleRate: number;
  runtimeVersion: string;
  /** Initial Worker setup: asset fetching/decoding and model initialization; excludes lazy StressML. */
  loadMs: number;
  /** ONNX session initialization, including WASM startup; part of loadMs. */
  modelInitMs: number;
}
export interface SynthesisMetrics {
  speed: number;
  steps?: number;
  diffusionMs?: number;
  generationMs?: number;
  frontendMs: number; stressMlMs: number; encoderMs: number; decoderMs: number; vocoderMs: number;
  totalMs: number; duration: number; tokens: number; frames: number; sampleRate: number;
}
export interface SynthesisResult extends FrontendResult {
  /** Mono floating-point PCM; the caller owns this buffer. No automatic playback. */
  samples: Float32Array;
  sampleRate: number;
  /** PCM16 mono WAV, peak-normalized in the same way as the demo. */
  wav: ArrayBuffer;
  warnings: string[];
  metrics: SynthesisMetrics;
  runtime: Readonly<RuntimeInfo>;
}
export interface BelVoice {
  readonly info: Readonly<RuntimeInfo> | null;
  /** Optional preload. Concurrent calls share one initialization. */
  load(): Promise<Readonly<RuntimeInfo>>;
  /** Lazily loads models. Concurrent synthesis rejects with code BUSY; no queue. */
  synthesize(text: string, options?: SynthesisOptions): Promise<SynthesisResult>;
  /** Terminates the Worker and rejects pending operations. Idempotent. */
  dispose(): void;
}
export class BelVoiceError extends Error { readonly code: string; constructor(code: string, message: string); }
export function createBelVoice(options?: BelVoiceOptions): BelVoice;
