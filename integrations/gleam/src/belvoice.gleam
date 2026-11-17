/// Browser-only handle. Keep one Engine and reuse it for all synthesis requests.
pub type Engine

/// Owns the PCM, WAV, frontend output and diagnostics for one synthesis.
pub type Audio

pub type Float32Samples

pub type WavBytes

/// Select "default" or "female-1"; each engine owns one fixed voice.
pub fn create_with_voice(
  assets_url: String,
  voice: String,
  num_threads: Int,
  on_log: fn(String) -> Nil,
  on_status: fn(String) -> Nil,
  callback: fn(Result(Engine, String)) -> Nil,
) -> Nil {
  create_with_voice_raw(
    assets_url,
    voice,
    num_threads,
    on_log,
    on_status,
    fn(engine) { callback(Ok(engine)) },
    fn(error) { callback(Error(error)) },
  )
}

@external(javascript, "./belvoice_ffi.mjs", "create_with_voice")
fn create_with_voice_raw(
  assets_url: String,
  voice: String,
  num_threads: Int,
  on_log: fn(String) -> Nil,
  on_status: fn(String) -> Nil,
  on_created: fn(Engine) -> Nil,
  on_error: fn(String) -> Nil,
) -> Nil

/// Dynamically import the static library and preload models.
/// No JS Promise or JS representation of Result crosses the public boundary.
pub fn create(
  assets_url: String,
  num_threads: Int,
  on_log: fn(String) -> Nil,
  on_status: fn(String) -> Nil,
  callback: fn(Result(Engine, String)) -> Nil,
) -> Nil {
  create_raw(
    assets_url,
    num_threads,
    on_log,
    on_status,
    fn(engine) { callback(Ok(engine)) },
    fn(error) { callback(Error(error)) },
  )
}

@external(javascript, "./belvoice_ffi.mjs", "create")
fn create_raw(
  assets_url: String,
  num_threads: Int,
  on_log: fn(String) -> Nil,
  on_status: fn(String) -> Nil,
  on_created: fn(Engine) -> Nil,
  on_error: fn(String) -> Nil,
) -> Nil

/// There is no internal queue: a second simultaneous call returns an error.
pub fn synthesize(
  engine: Engine,
  text: String,
  callback: fn(Result(Audio, String)) -> Nil,
) -> Nil {
  synthesize_raw(engine, text, fn(audio) { callback(Ok(audio)) }, fn(error) {
    callback(Error(error))
  })
}

@external(javascript, "./belvoice_ffi.mjs", "synthesize")
fn synthesize_raw(
  engine: Engine,
  text: String,
  on_audio: fn(Audio) -> Nil,
  on_error: fn(String) -> Nil,
) -> Nil

/// Optional per-request neural fallback for unknown-word stresses.
pub fn synthesize_with_stress_ml(
  engine: Engine,
  text: String,
  use_ml: Bool,
  callback: fn(Result(Audio, String)) -> Nil,
) -> Nil {
  synthesize_with_stress_ml_raw(
    engine,
    text,
    use_ml,
    fn(audio) { callback(Ok(audio)) },
    fn(error) { callback(Error(error)) },
  )
}

@external(javascript, "./belvoice_ffi.mjs", "synthesize_with_stress_ml")
fn synthesize_with_stress_ml_raw(
  engine: Engine,
  text: String,
  use_ml: Bool,
  on_audio: fn(Audio) -> Nil,
  on_error: fn(String) -> Nil,
) -> Nil

@external(javascript, "./belvoice_ffi.mjs", "dispose")
pub fn dispose(engine: Engine) -> Nil

/// Per-request StressML and synthesis speed (0.5–2.0, 1.0 = original).
pub fn synthesize_with_options(
  engine: Engine,
  text: String,
  use_ml: Bool,
  speed: Float,
  callback: fn(Result(Audio, String)) -> Nil,
) -> Nil {
  synthesize_with_options_raw(
    engine,
    text,
    use_ml,
    speed,
    fn(audio) { callback(Ok(audio)) },
    fn(error) { callback(Error(error)) },
  )
}

@external(javascript, "./belvoice_ffi.mjs", "synthesize_with_options")
fn synthesize_with_options_raw(
  engine: Engine,
  text: String,
  use_ml: Bool,
  speed: Float,
  on_audio: fn(Audio) -> Nil,
  on_error: fn(String) -> Nil,
) -> Nil

@external(javascript, "./belvoice_ffi.mjs", "speed")
pub fn speed(audio: Audio) -> Float

@external(javascript, "./belvoice_ffi.mjs", "voice")
pub fn voice(engine: Engine) -> String

@external(javascript, "./belvoice_ffi.mjs", "samples")
pub fn samples(audio: Audio) -> Float32Samples

@external(javascript, "./belvoice_ffi.mjs", "wav")
pub fn wav(audio: Audio) -> WavBytes

@external(javascript, "./belvoice_ffi.mjs", "sample_rate")
pub fn sample_rate(audio: Audio) -> Int

@external(javascript, "./belvoice_ffi.mjs", "phonemes")
pub fn phonemes(audio: Audio) -> String

@external(javascript, "./belvoice_ffi.mjs", "normalized")
pub fn normalized(audio: Audio) -> String

@external(javascript, "./belvoice_ffi.mjs", "duration")
pub fn duration(audio: Audio) -> Float

@external(javascript, "./belvoice_ffi.mjs", "stress_ml_enabled")
pub fn stress_ml_enabled(audio: Audio) -> Bool

@external(javascript, "./belvoice_ffi.mjs", "stress_ml_word_count")
pub fn stress_ml_word_count(audio: Audio) -> Int

@external(javascript, "./belvoice_ffi.mjs", "stress_ml_time_ms")
pub fn stress_ml_time_ms(audio: Audio) -> Float

@external(javascript, "./belvoice_ffi.mjs", "num_threads")
pub fn num_threads(engine: Engine) -> Int

/// Useful for an audio element or download link. Revoke it when no longer used.
@external(javascript, "./belvoice_ffi.mjs", "wav_url")
pub fn wav_url(audio: Audio) -> String

@external(javascript, "./belvoice_ffi.mjs", "revoke_url")
pub fn revoke_url(url: String) -> Nil
