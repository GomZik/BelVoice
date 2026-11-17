# Gleam JavaScript FFI

Browser-only, без залежнасці ад Lustre ці іншага UI-фрэймворка. Праверана з
Gleam 1.19.2. Пакет не патрабуе `gleam_stdlib`, Promise-бібліятэкі або npm.

1. Скапіяваць гатовую папку `dist/belvoice/` у `public/belvoice/` свайго праекта.
2. Скапіяваць **абодва** файлы з `src/` сюды ў `src/` свайго Gleam-праекта.
   Ці падключыць гэты каталог як лакальную Gleam-залежнасць.
3. Выклікаць `belvoice.create_with_voice("/belvoice/", "female-1", 0, on_log, on_status, callback)`.
   `0` — аўтаматычны выбар патокаў, без cross-origin isolation будзе 1.
4. Захаваць атрыманы `Engine` у мадэлі прыкладання і паўторна выкарыстоўваць яго.

```gleam
import belvoice

pub fn start(
  on_log: fn(String) -> Nil,
  on_status: fn(String) -> Nil,
  on_ready: fn(Result(belvoice.Engine, String)) -> Nil,
) -> Nil {
  belvoice.create_with_voice("/belvoice/", "female-1", 0, on_log, on_status, on_ready)
}

pub fn speak(
  engine: belvoice.Engine,
  text: String,
  on_audio: fn(Result(belvoice.Audio, String)) -> Nil,
) -> Nil {
  belvoice.synthesize_with_options(engine, text, True, 1.35, on_audio)
}
```

У Lustre callbacks могуць адпраўляць паведамленні кшталту `VoiceReady(result)`
і `VoiceGenerated(result)` у ваш update loop. Сам модуль не патрабуе Lustre.

`Audio` — opaque JS-аб’ект. Доступ:

- `sample_rate(audio)` — частата PCM;
- `samples(audio)` — opaque `Float32Samples` (JS `Float32Array`), можна перадаць
  ва ўласны Web Audio FFI без капіявання ў Gleam-спіс;
- `wav(audio)` — opaque `WavBytes` (JS `ArrayBuffer`), **не** Gleam `BitArray`;
- `wav_url(audio)` — blob URL для `<audio src=...>` ці спампоўвання;
- `revoke_url(url)` — вызваліць blob URL, калі плеер больш яго не выкарыстоўвае;
- `phonemes(audio)`, `normalized(audio)`, `duration(audio)` — дыягностыка;
- `synthesize_with_stress_ml(engine, text, True, callback)` — уключыць
  апцыянальныя ML-націскі толькі для гэтага запыту; звычайны `synthesize`
  застаецца без ML. `stress_ml_enabled(audio)`, `stress_ml_word_count(audio)`
  і `stress_ml_time_ms(audio)` — дыягностыка рэжыму;
- `num_threads(engine)` — фактычна выбраная колькасць патокаў;
- `create_with_voice(..., "female-1", ...)` — жаночы голас; `"default"` —
  арыгінальны. Стары `create(...)` захоўвае арыгінальны голас па змаўчанні;
- `synthesize_with_options(engine, text, use_ml, speed, callback)` — хуткасць
  задаецца праграмна для кожнага запыту, ад `0.5` да `2.0`. `1.0` — зыходны
  тэмп, напрыклад `1.35` — хутчэй; гэта не хуткасць плеера. `speed(audio)`
  вяртае выкарыстаны параметр, `voice(engine)` — выбраны голас. Звычайныя
  `synthesize` і `synthesize_with_stress_ml` захоўваюць хуткасць `1.0`;
- `dispose(engine)` — спыніць Worker і вызваліць мадэлі.

Бібліятэка сама не прайгравае аўдыё. Дазвол на прайграванне ў браўзары трэба
атрымаць падчас дзеяння карыстальніка, да чакання доўгага сінтэзу.

Усе callbacks выклікаюцца асінхронна пасля выніку JS-аперацыі; вяртаецца `Nil`,
не Promise. `Result` канструюецца ў Gleam, таму FFI не залежыць ад унутранага
прадстаўлення Gleam custom types. Тэкст памылкі ўтрымлівае код (`BUSY`,
`DISPOSED`, `LOAD_ERROR` і інш.). Правіла адзінага запыту — у вашым прыкладанні;
бібліятэка дадаткова адхіляе адначасовы другі сінтэз, а не ставіць яго ў чаргу.

Праверка зборкі гэтага адаптара:

```bash
gleam build --target javascript
```
