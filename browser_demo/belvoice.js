/** Browser-only, UI-independent BelVoice API. See belvoice.d.ts and LIBRARY.md. */
export class BelVoiceError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'BelVoiceError';
    this.code = code;
  }
}

export function createBelVoice(options = {}) {
  return new BelVoice(options);
}

class BelVoice {
  constructor(options) {
    const voice = options.voice ?? 'default';
    if (!['default', 'female-1'].includes(voice)) throw new BelVoiceError('INVALID_OPTIONS', 'Unknown voice.');
    const numThreads = options.numThreads ?? 0;
    if (!Number.isInteger(numThreads) || numThreads < 0) {
      throw new BelVoiceError('INVALID_OPTIONS', 'numThreads must be a nonnegative integer (0 = auto).');
    }
    for (const name of ['onLog', 'onStatus', 'onFrontend']) {
      if (options[name] !== undefined && typeof options[name] !== 'function') {
        throw new BelVoiceError('INVALID_OPTIONS', `${name} must be a function.`);
      }
    }
    const url = options.assetsUrl === undefined
      ? new URL('./', import.meta.url)
      : new URL(options.assetsUrl, globalThis.location?.href ?? import.meta.url);
    if (!url.pathname.endsWith('/')) url.pathname += '/';
    url.search = ''; url.hash = '';
    this._url = url;
    this._options = {...options, numThreads, voice};
    this._worker = null;
    this._pending = new Map();
    this._nextId = 0;
    this._loading = null;
    this._info = null;
    this._busy = false;
    this._disposed = false;
  }

  get info() { return this._info; }

  load() {
    if (this._disposed) return Promise.reject(this._disposedError());
    if (this._loading) return this._loading;
    try { this._ensureWorker(); }
    catch (error) { return Promise.reject(error); }
    const worker = this._worker;
    const loading = this._request('load', {numThreads: this._options.numThreads, voice: this._options.voice})
      .then(info => {
        if (this._disposed) throw this._disposedError();
        if (this._worker !== worker) throw new BelVoiceError('WORKER_ERROR', 'The loading Worker was terminated.');
        this._info = Object.freeze(info);
        return this._info;
      })
      .catch(error => {
        // A failed load can be retried using a fresh Worker/WASM runtime.
        if (this._worker === worker) this._stopWorker(error);
        if (this._loading === loading) this._loading = null;
        throw error;
      });
    this._loading = loading;
    return loading;
  }

  async synthesize(text, options = {}) {
    if (this._disposed) throw this._disposedError();
    if (typeof text !== 'string' || !text.trim()) {
      throw new BelVoiceError('INVALID_TEXT', 'Expected nonempty Belarusian text.');
    }
    const useStressML = options.useStressML ?? false;
    if (typeof useStressML !== 'boolean') throw new BelVoiceError('INVALID_OPTIONS', 'useStressML must be a boolean.');
    const speed = options.speed ?? 1;
    if (!Number.isFinite(speed) || speed < 0.5 || speed > 2) throw new BelVoiceError('INVALID_OPTIONS', 'speed must be a number between 0.5 and 2.');
    if (this._busy) throw new BelVoiceError('BUSY', 'A synthesis is already in progress. There is no internal queue.');
    this._busy = true;
    try {
      await this.load();
      if (this._disposed) throw this._disposedError();
      const result = await this._request('synthesize', {text, useStressML, speed});
      return {...result, runtime: this._info};
    } finally { this._busy = false; }
  }

  dispose() {
    if (this._disposed) return;
    this._disposed = true;
    this._stopWorker(this._disposedError());
  }

  _disposedError() { return new BelVoiceError('DISPOSED', 'This BelVoice instance has been disposed.'); }

  _notify(name, value) {
    try { this._options[name]?.(value); }
    catch (error) { console.error(`BelVoice ${name} callback failed:`, error); }
  }

  _ensureWorker() {
    if (this._worker) return;
    if (typeof Worker === 'undefined') throw new BelVoiceError('UNSUPPORTED', 'BelVoice requires a browser with module Workers.');
    // The whole directory is a static runtime; no bundler-specific Worker magic.
    let worker;
    try { worker = new Worker(new URL('worker.js', this._url), {type: 'module', name: 'belvoice'}); }
    catch (error) { throw new BelVoiceError('WORKER_ERROR', `Could not create BelVoice Worker: ${error.message}`); }
    this._worker = worker;
    worker.onmessage = ({data}) => {
      if (this._worker !== worker) return;
      if (data.type === 'log') this._notify('onLog', data.text);
      else if (data.type === 'status') this._notify('onStatus', data.text);
      else if (data.type === 'frontend') this._notify('onFrontend', {normalized: data.normalized, phonemes: data.phonemes, ...(data.stressML ? {stressML: data.stressML} : {})});
      else if (data.type === 'response' || data.type === 'error') {
        const pending = this._pending.get(data.id);
        if (!pending) return;
        this._pending.delete(data.id);
        if (data.type === 'error') pending.reject(new BelVoiceError(data.code ?? 'SYNTHESIS_ERROR', data.text));
        else pending.resolve(data.result);
      }
    };
    worker.onerror = event => {
      if (this._worker === worker) this._stopWorker(new BelVoiceError('WORKER_ERROR', event.message || 'Could not start the BelVoice Worker. Check assetsUrl, MIME types and CSP.'));
    };
    worker.onmessageerror = () => {
      if (this._worker === worker) this._stopWorker(new BelVoiceError('WORKER_ERROR', 'Could not decode a Worker message.'));
    };
  }

  _request(type, payload) {
    const id = ++this._nextId;
    return new Promise((resolve, reject) => {
      this._pending.set(id, {resolve, reject});
      try { this._worker.postMessage({type, id, ...payload}); }
      catch (error) { this._pending.delete(id); reject(error); }
    });
  }

  _stopWorker(error) {
    this._worker?.terminate();
    this._worker = null;
    this._info = null;
    this._loading = null;
    for (const {reject} of this._pending.values()) reject(error);
    this._pending.clear();
  }
}
