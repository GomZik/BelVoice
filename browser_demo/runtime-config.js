// Pure helper, shared with tests. Independent from the UI and ONNX Runtime.
export function resolveNumThreads(requested, environment) {
  if (!Number.isInteger(requested) || requested < 0) throw new Error('Invalid numThreads');
  if (!environment.crossOriginIsolated || !environment.hasSharedArrayBuffer) return 1;
  const cores = Math.max(1, environment.hardwareConcurrency || 1);
  return requested || Math.min(4, Math.max(1, Math.floor(cores / 2)));
}
