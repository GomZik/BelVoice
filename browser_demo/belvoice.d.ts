export interface StressMLResult {
  enabled: boolean;
  applied: {word: string; stressed: string; confidence: number}[];
  skippedKnown: number;
}
export interface FrontendResult { normalized: string; phonemes: string; stressML: StressMLResult; }
export interface SynthesisOptions {
  useStressML?: boolean;
  /** Duration control during synthesis, not playback rate. 0.5–2, default 1. */
  speed?: number;
}
export interface BelVoiceOptions {
  /** Each engine owns one voice. Dispose it before switching to limit memory. */
  voice?: 'default' | 'female-1';
  /** Same-origin static runtime directory; defaults to this module's directory. */
  assetsUrl?: string | URL;
  /** 0 = auto (up to 4 threads); without cross-origin isolation falls back to 1. */
  numThreads?: number;
  onLog?: (message: string) => void;
  onStatus?: (message: string) => void;
  onFrontend?: (result: FrontendResult) => void;
}
export interface RuntimeInfo {
  voice: 'default' | 'female-1';
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
