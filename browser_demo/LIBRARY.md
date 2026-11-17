# BelVoice Browser Library

ES module, без DOM, кнопак, плеера, сервернага сінтэзу і залежнасці ад Gleam/Lustre.
Усе вылічэнні — у module Worker. Прайграванне і чарга — адказнасць прыкладання.

## Забраць у іншы праект

У рэпазіторыі BelVoice:

```bash
uv run python tools/browser_demo/package_library.py --refresh
```

Актуальны самадастатковы каталог: **`dist/belvoice/`**, каля 376 MiB з абодвума
галасамі і апцыянальнай StressML. Для Netlify-дэма ёсць асобны `dist/belvoice-demo/`.

У зыходнай бібліятэцы даступна `createBelVoice({voice: 'female-1'})`
(`'default'` па змаўчанні). Жаночы голас патрабуе папку `models/female-1/`
з асобнымі ONNX-файламі і `config.json`, ужо ўключаную ў актуальную ўпакоўку.
Экзэмпляр мае адзін фіксаваны голас; для пераключэння дэма выклікае `dispose()`
і стварае новы экзэмпляр. Гэта вызваляе старыя сесіі, але патрабуе паўторнай
ініцыялізацыі frontend/StressML. `runtime.voice` паказвае выкарыстаны голас.
Скапіяваць **увесь** каталог у `public/belvoice/` іншага праекта.
У ім ужо ёсць JS, WASM, ONNX, GrammarDB, слоўнікі, ліцэнзіі, Gleam FFI і manifest
з памерамі/SHA-256 файлаў. HTML і код дэма-інтэрфейсу туды не ўваходзяць.

Версія бібліятэкі — **0.3.0**. `--refresh` абнаўляе тую ж папку, праверыўшы
ўсе файлы паводле manifest/SHA-256. Калі ёсць змененыя ці дадатковыя файлы,
абнаўленне спыняецца без выдалення. Без `--refresh` непусты каталог не
перазапісваецца. Вялікія runtime-файлы збіраюцца камандамі з
`browser_demo/README.md`, калі іх няма пасля чыстага clone.

Статычная структура мусіць заставацца такой:

```text
/belvoice/belvoice.js       ← публічны API
/belvoice/belvoice.d.ts     ← TypeScript-тыпы, неабавязковыя для Gleam
/belvoice/worker.js
/belvoice/frontend.js
/belvoice/number-words.js
/belvoice/runtime-config.js
/belvoice/models/…
/belvoice/g2p/…
/belvoice/data/…
/belvoice/vendor/…
```

Усе шляху да мадэляў, WASM і імпартаў Worker вылічаюцца адносна гэтага каталога,
не адносна старонкі, Gleam output ці маршруту SPA. Размяшчайце яго на тым самым
origin, што і старонку. Раздавайце `.js`/`.mjs` як JavaScript, `.wasm` як
`application/wasm`; SPA fallback **не павінен** вяртаць HTML замест assets.

## JavaScript API

```js
import {createBelVoice} from '/belvoice/belvoice.js';

const voice = createBelVoice({
  assetsUrl: '/belvoice/',
  voice: 'female-1', // 'default' — арыгінальны голас
  numThreads: 0,
  onLog: message => console.log(message),
  onStatus: message => console.log(message),
  onFrontend: ({normalized, phonemes}) => console.log(normalized, phonemes),
});

// Неабавязковы preload: без яго synthesize загрузіць усё сам.
const runtime = await voice.load();
console.log(runtime.numThreads, runtime.crossOriginIsolated);

const audio = await voice.synthesize('Прывітанне! Менш тры: <3', {
  useStressML: true,
  speed: 1.35,
});
// Або: voice.synthesize(text, {useStressML: true, speed: 1.35}).
// speed: 0.5–2, default 1; працягласці GlowTTS, не playbackRate.
// audio.samples: Float32Array, mono PCM
// audio.sampleRate: 22050
// audio.wav: ArrayBuffer, PCM16 WAV
// audio.normalized, audio.phonemes, audio.warnings
// audio.stressML: enabled, applied (словы/націскі/confidence), skippedKnown
// audio.metrics: працягласць і час кожнага этапу
// audio.runtime: запытаная/фактычная колькасць патокаў і асяроддзе

const wavBlob = new Blob([audio.wav], {type: 'audio/wav'});
// Аўдыё само не прайграваецца. Перадайце PCM/WAV свайму плееру.

voice.dispose(); // Калі сэрвіс больш не патрэбны, НЕ пасля кожнай агучкі.
```

Без `assetsUrl` бярэцца каталог самога `belvoice.js`. Калі гэты facade трапляе
ў bundle вашага прыкладання, абавязкова перадайце `assetsUrl` і скапіюйце
runtime асобнымі статычнымі файламі. Не трэба бандліць `worker.js`, ORT ці
згенераваны BelG2P. Сетка патрэбная толькі для загрузкі статычных файлаў.

`package.json` таксама дазваляе імпартаваць facade як лакальны ESM/npm-пакет
`@belvoice/browser`, але аўтаматычнага плагіна для капіявання assets у bundler няма.

### Lifecycle і памылкі

- `createBelVoice(options)` — лёгкі сінхронны канструктар; мадэлі яшчэ не загружаюцца.
- `load(): Promise<RuntimeInfo>` — адна загрузка, адначасовыя preload-выклікі
  аб’ядноўваюцца. `voice.info` пасля загрузкі ўтрымлівае фактычныя параметры.
- `synthesize(text): Promise<SynthesisResult>` — адзін актыўны сінтэз на экзэмпляр.
  Другі адначасовы запыт адхіляецца з кодам `BUSY`, **чаргі няма**.
- `synthesize(text, {useStressML: true})` — апцыянальныя ML-націскі для невядомых
  слоў, па змаўчанні выключаныя. Ручныя/статыстычныя націскі, вядомыя словы
  GrammarDB і «о/ё» не перапісваюцца. Мадэль на 18.3 MiB загружаецца ляніва,
  адзін раз; наступны выклік без options зноў працуе без ML. Час ML (уключаючы
  першую загрузку) знаходзіцца ў `metrics.stressMlMs` і ўваходзіць у `frontendMs`.
- `dispose(): void` — адразу завяршае Worker, вызваляе яго мадэлі/памяць і
  адхіляе незавершаныя аперацыі з `DISPOSED`. Можна выклікаць паўторна.
  Для наступнай працы трэба стварыць новы экзэмпляр.
- Няўдалы тэкст не знішчае загружаныя мадэлі. Няўдалую загрузку можна паўтарыць
  праз `load()`: будзе створаны свежы Worker. Памылкі startup/Worker не завісаюць
  у незавершаным Promise.

`BelVoiceError` мае `code` і `message`. Асноўныя коды: `INVALID_OPTIONS`,
`INVALID_TEXT`, `BUSY`, `DISPOSED`, `UNSUPPORTED`, `LOAD_ERROR`, `WORKER_ERROR`,
`SYNTHESIS_ERROR`. Няправільныя options могуць кінуць памылку ў канструктары;
асінхронныя аперацыі адхіляюць Promise. Выключэнні ў дыягнастычных callbacks
выводзяцца ў console і не перарываюць сінтэз.

Самі PCM/WAV буферы належаць выклікальніку пасля вяртання выніку і застаюцца
прыдатнымі пасля `dispose()`. Blob URL, AudioContext і плеер вызваляе прыкладанне.
Аўдыё не струменевае — вяртаецца пасля поўнай генерацыі. Атрымайце дазвол на
Web Audio падчас карыстальніцкага кліку, **да** чакання сінтэзу.

## Адзін сінтэз, некалькі патокаў

`numThreads` задаецца да першай загрузкі і не змяняецца ў жывым экзэмпляры:

- `0` (па змаўчанні) — аўтаматычна: палова `hardwareConcurrency`, не больш за 4;
- `1` — адзін вылічальны паток;
- `2`, `4`, `8`, … — яўная колькасць патокаў; трэба вымяраць, а не лічыць,
  што большая колькасць заўсёды хутчэйшая;
- без `crossOriginIsolated` / `SharedArrayBuffer` — бяспечны fallback на **1**.

Для шматпаточнасці ваш сервер мусіць раздаваць патрэбныя загалоўкі, звычайна:

```http
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

Яны патрэбныя на старонцы і на Worker; усе астатнія рэсурсы таксама мусяць быць
сумяшчальныя з гэтай палітыкай. Бібліятэка не можа сама выставіць HTTP-загалоўкі.
Звычайны `python -m http.server` працягвае працаваць, але з адным патокам.
У OBS трэба асобна праверыць падтрымку isolation і ўплыў палітык на overlay.
Шматпаточнасць **не** запускае некалькі TTS-запытаў: адзін сінтэз можа
выкарыстоўваць некалькі CPU-ядраў. Інварыянт паміж рознымі экзэмплярамі/ўкладкамі
забяспечвае ваша сістэма.

## Gleam FFI

Гатовыя bindings: **`integrations/gleam/src/belvoice.gleam`** і
**`integrations/gleam/src/belvoice_ffi.mjs`**. Скапіяваць іх побач у `src/`
свайго Gleam-праекта ці падключыць гэты каталог як лакальны пакет.

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

`Result` канструюецца ў Gleam. Promise не пераходзіць FFI-мяжу. `Engine`,
`Audio`, `Float32Samples` і `WavBytes` — знешнія opaque types; масівы не
ператвараюцца ў вялікія Gleam-спісы. `WavBytes` — `ArrayBuffer`, не `BitArray`.
Ёсць `wav_url(audio)` / `revoke_url(url)` для аўдыё-элемента і спампоўвання.
Падрабязнасці — у `integrations/gleam/README.md`.

## Праверкі

З кораня BelVoice:

```bash
node --test tests/browser/test_library.mjs
node --test tests/browser/test_stress_ml.mjs
# Gleam-зборка: выканаць gleam build --target javascript у integrations/gleam/
uv run --extra browser-demo python tools/browser_demo/test_browser.py
uv run --extra browser-demo python tools/browser_demo/test_library_browser.py
uv run --extra browser-demo python tools/browser_demo/test_stress_ml_browser.py
```

Апошні тэст выкарыстоўвае гатовую ўпакоўку, падмантоўвае яе пад іншы URL-прэфікс
і правярае API без дэма-старонкі, а таксама сапраўдныя скампіляваныя Gleam bindings.
Ліцэнзіі і абмежаванні якасці мадэляў захоўваюцца: гэта не перакладчык, націскі
без аналізу кантэксту могуць быць памылковымі; вядомыя фанетычныя супярэчнасці
апрацоўваюцца набліжана з `warnings`. Публікацыі пакета ў npm/Hex не рабілася.
