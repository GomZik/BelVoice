# Як сабраць два галасы для браўзара

Паглядзець гатовы вынік: **[belvoice.gomzik.xyz](https://belvoice.gomzik.xyz)**.
Поўная інструкцыя зборкі дэма з усімі залежнасцямі —
у [галоўным README](../README.md#як-атрымаць-такое-ж-дэма-з-зыходнікаў).

Гэта **экспарт ужо навучаных мадэляў у ONNX**, а не навучанне новых галасоў.
Скрыпты самі спампоўваюць зыходныя чэкпойнты з Hugging Face у кэш;
рукамі шукаць `.pth` або капіяваць іх у рэпазіторый не трэба.

Усе каманды ніжэй выконваюцца **з кораня BelVoice**.

## 1. Падрыхтаваць Python-асяроддзе

Патрэбныя `uv` і Python >=3.12. Экспарт ідзе на CPU, CUDA не абавязковая.

```bash
uv sync --locked --extra browser-demo
```

Інтэрнэт патрэбны для першай загрузкі залежнасцяў і чэкпойнтаў. Пакіньце
некалькі GB вольнага дыска; кэш PyTorch/Hugging Face і build-залежнасці
займаюць значна больш месца, чым гатовыя ONNX-файлы.

## 2. Экспартаваць арыгінальны голас

```bash
uv run --locked --extra browser-demo python tools/browser_demo/export_models.py --voice default
```

Крыніца: [`alex73/BelarusianTTSviaCoquiTTS`](https://huggingface.co/alex73/BelarusianTTSviaCoquiTTS),
рэвізія `d7684c1dc4bcfd69708bbc013b251549ae40b1ca`, у model card — Apache-2.0.

Вынік: `browser_demo/models/encoder.onnx`, `decoder.onnx`, `vocoder.onnx`
і `config.json` у тым самым каталогу.

## 3. Экспартаваць жаночы голас

```bash
uv run --locked --extra browser-demo python tools/browser_demo/export_models.py --voice female-1
```

Крыніца: [`slapula/commonvoice_be_tts_female_1`](https://huggingface.co/slapula/commonvoice_be_tts_female_1),
рэвізія `95b899d31a13278364b85b88f953e92df2ff4826`, у model card — MIT.

Вынік: асобны набор `encoder.onnx`, `decoder.onnx`, `vocoder.onnx` і
`config.json` у **`browser_demo/models/female-1/`**. Першы голас не перазапісваецца.

`scale_stats_female_1.npy` спампоўваецца аўтаматычна. Скрыпт улічвае адрозненне
нармалізацыі жаночай мадэлі, не змяняючы арыгінальныя канфігурацыі і вагі.
Не замяняйце толькі адзін файл у старым наборы: кожны голас патрабуе ўсе
тры ONNX-файлы і ўласны `config.json`.

Абедзве каманды правяраюць ONNX адносна PyTorch на трох фразах рознай даўжыні.
Пры разыходжанні каманда завершыцца з памылкай. Побач з мадэлямі ствараюцца
`verification.json`, `MODEL_CARD.md` і `MODEL_SOURCE.json`.
ONNX-вагі займаюць прыблізна **163 MiB на голас**.

## 4. Сабраць агульныя рэсурсы (калі пачынаеце з чыстага clone)

Для BelG2P тут дадаткова патрэбныя **JDK 21+ і Maven**.

```bash
uv run --locked --extra browser-demo python tools/browser_demo/export_stress_ml.py
uv run --locked --extra browser-demo python tools/browser_demo/build_g2p.py
uv run --locked --extra browser-demo python tools/browser_demo/prepare_assets.py
```

Калі Maven не ў PATH, перадайце `build_g2p.py --maven /path/to/mvn`
(на Windows — шлях да `mvn.cmd`). Гэтыя рэсурсы агульныя для абодвух галасоў:
StressML, BelG2P/GrammarDB, нармалізацыя і ONNX Runtime Web.
Пры паўторным экспарце толькі аднаго голасу перазбіраць іх не трэба.

## 5. Падрыхтаваць дзве пастаянныя папкі

```bash
uv run --locked python tools/browser_demo/package_library.py --refresh
uv run --locked python tools/browser_demo/package_library.py --demo --refresh
```

| Вынік | Што рабіць |
| --- | --- |
| `dist/belvoice/` | Цалкам скапіяваць у `public/belvoice/` іншага праекта; без дэма-інтэрфейсу |
| `dist/belvoice-demo/` | Цалкам заліць на Netlify; `index.html` і `_headers` ужо ў корані |

Абедзве папкі ўключаюць два галасы і StressML, каля **376 MiB** кожная.
`--refresh` абнаўляе іх на месцы, але спыняецца, калі ў папцы ёсць змененыя
або дадатковыя файлы. Згенераваныя рэсурсы і `dist/` не каміцяцца ў Git.

## 6. Паслухаць

```bash
python browser_demo/serve.py
```

Адкрыйце **http://localhost:8000**, выберыце голас і націсніце «Агучыць».
Для жаночага паспрабуйце хуткасць **1.3–1.4×**. Невыбраны голас не загружаецца.

У JavaScript:

```js
const voice = createBelVoice({voice: 'female-1'}); // або 'default'
const audio = await voice.synthesize(text, {useStressML: true, speed: 1.35});
```

Поўны імпарт, API і Gleam-біндынгі: [LIBRARY.md](LIBRARY.md).
Абмежаванні і браўзерныя тэсты: [README.md](README.md).
