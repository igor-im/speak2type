If you’re already leaning IBus, you’re on the shortest path to “WhisperFlow-like dictation” on GNOME—because IBus is exactly the system-wide text injection layer GNOME already uses for input methods (and it works on Wayland).

The good news: Fedora has effectively already built the “dictation IME” skeleton you want. Fedora ships **`ibus-speech-to-text`**, which is an IBus engine + a GTK4/libadwaita setup app; it originally used **Vosk**, and newer builds add **Whisper.cpp via `pywhispercpp`**, with **backend switching** and **model management**. ([Fedora Project][1])

Below is a concrete plan to **reuse Fedora’s work**, start with **push-to-talk**, and architect it so **always-on** becomes “add another mode,” not a rewrite.

---

## 1) Baseline: reuse Fedora’s `ibus-speech-to-text` codebase, not reinvent IBus

### Why this is the right base

Fedora’s current direction already matches your requirements:

* **IBus engine** that dictates into any IBus-aware app (GTK/Qt/etc). ([Fedora Project][1])
* **Backend selection** (Vosk vs Whisper) and **multiple models**, including downloading models (Hugging Face is explicitly mentioned for Whisper). ([Fedora Discussion][2])
* Uses **GStreamer** in the pipeline (important for mic capture and future streaming/VAD). ([Fedora Discussion][2])
* Includes a **setup UI** (GTK4/libadwaita) for configuration/model management. ([Fedora Project][1])

Upstream repo Fedora points to is the fork you found:

* `Manish7093/IBus-Speech-To-Text` (Fedora package “Upstream” and changelog track it). ([Fedora Packages][3])

---

## 2) Will Fedora’s source work on Ubuntu 25.10?

### Short answer

**Yes, the source is not Fedora-specific.** It’s “normal IBus + Python + GStreamer + GTK4/libadwaita”. The Fedora bits are mostly *packaging* (RPM spec, dependency names, patches). ([Fedora Project][1])

### The real portability gotchas (Ubuntu side)

1. **GStreamer plugin availability**

   * Vosk integration depends on **`gst-vosk`** (a separate plugin project). Fedora packages it; on Ubuntu you may need to build it. ([GitHub][4])

2. **Whisper.cpp Python bindings**

   * Fedora depends on `python3-pywhispercpp`. On Ubuntu you’ll likely use **pip (`pywhispercpp`)** or build it yourself.
   * If you want GPU acceleration, `pywhispercpp` documents building with CUDA (`WHISPER_CUDA=1`). ([PyPI][5])

3. **Installing your engine without replacing system files (dev mode)**

   * IBus can load component XMLs from custom dirs using `IBUS_COMPONENT_PATH`. This is perfect for iterative dev on Ubuntu. ([Ubuntu Manpages][6])

So: Fedora’s code is reusable; Ubuntu just needs dependency mapping + possibly building `gst-vosk` and `pywhispercpp`.

---

## 3) Target UX: start with push-to-talk, keep always-on as a later “mode”

### Phase 1 UX (push-to-talk)

* User switches to “Speech To Text” input source (already normal GNOME UX).
* **Hold a key to record** → release to stop → model transcribes → text commits into focused app.
* Optional: show a small preedit “🎙 Recording…” / “⏳ Transcribing…” so it feels responsive.

Why this is a good first milestone:

* No VAD required.
* No streaming partials required.
* No continuous mic indicator UX yet.
* Still provides 80% of “WhisperFlow value” quickly.

### Phase 2 UX (always-on)

* Always-on becomes “Segmenter plugin + policy checks + UI indicator + privacy rules.”
* Because we’ll architect the engine as: **Audio Capture → Segmenter → Backend → Commit**, always-on is mostly swapping the Segmenter.

Also: IBus engines can react to the app’s content type (e.g., password fields) via `set_content_type`, so you can force-disable dictation in sensitive contexts later. ([Intelligent Input Bus][7])

---

## 4) Architecture that reuses Fedora’s structure but opens the door to more models

Fedora’s 0.7.0 file layout strongly suggests it already has a factory split like:

* `sttgstfactory.py` chooses pipeline/backend
* `sttgstvosk.py` and `sttgstwhisper.py` implement the recognition pipeline
* `sttvoskmodelmanagers.py` and `sttwhispermodelmanagers.py` manage model downloads/selection ([Fedora Packages][8])

So instead of inventing a new system, we **generalize that pattern**:

### Core components (clean separation)

1. **Engine / UX State Machine**

   * States: `IDLE → RECORDING → TRANSCRIBING → COMMITTING`
   * Handles hotkeys, tray/property actions, focus changes.

2. **Audio capture**

   * GStreamer pipeline to capture mic to PCM (for push-to-talk, you buffer until release).

3. **Segmenter (pluggable)**

   * Push-to-talk segmenter: “one segment = key-held audio”
   * Always-on segmenter (later): VAD + endpointing + chunker

4. **Backend interface (pluggable)**

   * Vosk backend (existing)
   * Whisper.cpp backend (existing)
   * **Parakeet backend (new)**
   * **Canary Qwen backend (likely out-of-process) (new)**

5. **Post-processing**

   * punctuation/casing commands, voice shortcuts, formatting (the existing project already has voice commands + formatting support) ([GitHub][9])

### Suggested backend interface (minimal, future-proof)

Define something like:

* `backend.id`, `backend.name`
* `backend.capabilities = {streaming, timestamps, language_detect, punctuation}`
* `backend.list_models(locale) -> [ModelSpec]`
* `backend.ensure_model(model_id) -> InstalledModel`
* `backend.transcribe(audio_pcm16k, locale_hint, options) -> TranscriptResult`
* Optional later: `backend.stream(frames_iter, partial_cb, endpoint_cb)`

This lets Parakeet/Canary/Qwen plug in cleanly without rewriting engine logic.

---

## 5) Push-to-talk implementation details in IBus (the “how”)

### Detect press vs release

IBus key events include a release mask: `IBus.ModifierType.RELEASE_MASK`. ([Lazka][10])
So you can implement:

* On key-press: start recording
* On key-release: stop recording → transcribe

### Hotkey scope (important reality check)

* An IBus engine only reliably receives key events **when it’s the active input method** (and the app’s input context is using it).
* True **global** push-to-talk (works even when another input source is active) is usually a **GNOME Shell keybinding → D-Bus call** story.

So the concrete plan is:

* **V1:** push-to-talk hotkey works while STT engine is selected (fastest path).
* **V2:** optional GNOME Shell extension to provide a global shortcut that toggles/activates the STT engine and triggers record.

This aligns with your “push-to-talk first, always-on later” approach.

---

## 6) Model options: how Parakeet + Canary Qwen fit realistically

You linked the Northflank January 2026 roundup; it lists:

* **Canary Qwen 2.5B** (accuracy, RTFx ~418 in their table, requires NVIDIA NeMo; English-only per the article) ([Northflank][11])
* **Parakeet TDT** (ultra-low-latency streaming; very high throughput claims in their table) ([Northflank][11])

Two practical integration paths:

### A) “In-process” backends (best UX, simplest deploy)

**Parakeet via ONNXRuntime in-process** is the most promising for “regular CPU” and a clean local workflow.

A concrete way to do this is to implement a new backend using **`onnx-asr`**, which explicitly supports “Parakeet TDT 0.6B v3” models and runs on ONNXRuntime. ([PyPI][12])

This gives you:

* CPU-friendly inference (and you can tune threads)
* No separate server needed
* Fits your “multiple local models” goal nicely

### B) “Out-of-process” backends (most flexible for heavy stacks)

**Canary Qwen** in that article is described as requiring **NVIDIA NeMo**. ([Northflank][11])
NeMo-based runtimes often bring heavier dependencies and sometimes want GPU-optimized stacks.

So for Canary Qwen I would plan:

* Run a local service (HTTP/gRPC) that exposes `POST /transcribe`
* IBus backend just sends audio and receives text
* This isolates dependencies and lets you swap servers/models easily

This is also the cleanest way to support “multiple models” without turning the IBus engine into a giant ML environment.

### About your “418 RTFx covers CPU drop” idea

Treat that **418 RTFx** as a benchmark-context number (hardware + batching + precision matter). It may not translate to CPU performance directly. ([Northflank][11])
So we’ll bake in a **benchmark harness** early (see milestone plan) to measure real RTF on *your* machine.

---

## 7) Concrete milestone plan (reuse Fedora, add your backend layer, ship push-to-talk)

### Milestone 0 — Get Fedora upstream running on Ubuntu (no behavior changes)

**Deliverable:** You can install and use the existing engine on Ubuntu 25.10.

* Clone `Manish7093/IBus-Speech-To-Text` ([GitHub][9])
* Install dependencies (Ubuntu equivalents of Fedora runtime deps; Fedora lists them clearly) ([Copr Fedora Infracloud][13])
* For dev install, don’t write to `/usr`:

  * Install to `~/.local`
  * Point IBus at your component dir using `IBUS_COMPONENT_PATH` ([Ubuntu Manpages][6])
* Validate: Vosk works end-to-end, setup tool opens, models download.

### Milestone 1 — Push-to-talk (hold-to-record) mode

**Deliverable:** Hold hotkey to record; release triggers transcription; commits text.

* Add a new setting: `record_mode = {toggle, push_to_talk}`
* Add a new setting: `ptt_hotkey = <key combo>`
* Engine changes:

  * Hook `process_key_event(...)`
  * Use `RELEASE_MASK` to differentiate press/release ([Lazka][10])
  * On press: start capture; show “recording” indicator
  * On release: stop capture; spawn transcription job; show “transcribing”
* Keep existing “toggle recognition” behavior as an option (so you don’t regress current UX).

### Milestone 2 — Formalize backend interface (without breaking Vosk/Whisper)

**Deliverable:** Vosk + Whisper are “plugins” behind a stable interface.

* Wrap existing Vosk and Whisper code paths behind the interface
* Ensure model selection and setup UI still work
* This step is mostly refactor + tests

Fedora explicitly added backend switching and model management, so you’ll be aligning with their direction, not fighting it. ([Fedora Discussion][2])

### Milestone 3 — Add Parakeet local backend (CPU-first)

**Deliverable:** Choose “Parakeet” backend in setup; pick model; dictation works.

* Implement `ParakeetOnnxBackend` using `onnx-asr` (or similar ONNX pipeline). ([PyPI][12])
* Add `sttparakeetmodelmanagers.py` (mirrors the existing model manager pattern in Fedora’s package) ([Fedora Packages][8])
* Threading knobs:

  * `num_threads`, `intra_op`, `inter_op`
* Benchmark on your machine:

  * RTF for 10s, 30s, 60s dictations
  * Latency distribution (p50/p95)

### Milestone 4 — Optional: “model server” backend (for Canary Qwen / anything heavy)

**Deliverable:** You can point IBus at `http://localhost:PORT/transcribe`.

* Add `HttpBackend` that:

  * sends audio + metadata (locale, timestamps option)
  * receives transcript + optional segments
* This is how you cleanly support NeMo-required models like Canary Qwen without polluting the IBus environment. ([Northflank][11])

### Milestone 5 — Always-on (design + prototype only)

**Deliverable:** A prototype “always-on mode” behind a flag.

* Add Segmenter interface:

  * `PushToTalkSegmenter` (already)
  * `VadSegmenter` (new)
* Enforce privacy / correctness rules:

  * On `set_content_type`, if purpose is PASSWORD/PIN, disable recording/transcribing. ([Intelligent Input Bus][7])
* Add clear UI indicator (mic live)
* Decide whether partial streaming text is committed as preedit or only on endpoint

---

## 8) The key decision I’d make up front (so you don’t paint yourself into a corner)

**Run inference out-of-thread or out-of-process from day 1.**

Even if you keep everything “local,” you don’t want the IBus main loop frozen while a model runs. Practically:

* For Vosk streaming: keep current behavior
* For push-to-talk + heavier models: background worker thread/process, then `commit_text` when done

(That also makes “always-on” far less painful later.)

---

## 9) Summary recommendation (if you want the fastest path)

1. **Fork `Manish7093/IBus-Speech-To-Text`** (it’s already where Fedora is landing). ([Fedora Packages][3])
2. Add **push-to-talk mode** using IBus key press/release (`RELEASE_MASK`). ([Lazka][10])
3. Generalize the backend factory so you can add:

   * **Parakeet ONNX** in-process via `onnx-asr` ([PyPI][12])
   * **Canary Qwen** later via a local server backend (because the NeMo requirement makes in-process integration messy). ([Northflank][11])
4. Keep always-on as a future Segmenter plugin (VAD + policy) rather than building it into the engine loop.

---

If you want, I can take the Fedora package file list as the “map” and propose **exact filenames + class names** for where to implement:

* `PushToTalkController`
* `AudioCapture` (appsink)
* `BackendBase` + `ParakeetBackend`
* setup UI changes (where to add the backend/model rows)

…but the outline above is the concrete architecture and milestone path that will keep you moving quickly without boxing you in later.

[1]: https://fedoraproject.org/wiki/Changes/ibus-speech-to-text "Changes/ibus-speech-to-text - Fedora Project Wiki"
[2]: https://discussion.fedoraproject.org/t/f44-change-proposal-ibus-speech-to-text-pywhispercpp-selfcontained/179397 "F44 Change Proposal: ibus-speech-to-text pywhispercpp [SelfContained] - Fedora Discussion"
[3]: https://packages.fedoraproject.org/pkgs/ibus-speech-to-text/ibus-speech-to-text/index.html "ibus-speech-to-text - Fedora Packages"
[4]: https://github.com/PhilippeRo/gst-vosk?utm_source=chatgpt.com "PhilippeRo/gst-vosk: Gstreamer plugin for ..."
[5]: https://pypi.org/project/pywhispercpp/1.3.0/?utm_source=chatgpt.com "pywhispercpp"
[6]: https://manpages.ubuntu.com/manpages/bionic/man1/ibus.1.html?utm_source=chatgpt.com "command line utility for ibus"
[7]: https://ibus.github.io/docs/ibus-1.5/IBusEngine.html?utm_source=chatgpt.com "IBusEngine"
[8]: https://packages.fedoraproject.org/pkgs/ibus-speech-to-text/ibus-speech-to-text/fedora-rawhide.html "ibus-speech-to-text-0.7.0-2.fc44 - Fedora Packages"
[9]: https://github.com/Manish7093/IBus-Speech-To-Text "GitHub - Manish7093/IBus-Speech-To-Text: A speech to text IBus engine using VOSK"
[10]: https://lazka.github.io/pgi-docs/IBus-1.0/mapping.html?utm_source=chatgpt.com "Symbol Mapping - IBus 1.0"
[11]: https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks "Best open source speech-to-text (STT) model in 2026 (with benchmarks) | Blog — Northflank"
[12]: https://pypi.org/project/onnx-asr/0.7.0/?utm_source=chatgpt.com "onnx-asr"
[13]: https://download.copr.fedorainfracloud.org/results/matiwari/IBus-Speech-To-Text/fedora-43-x86_64/09944640-ibus-speech-to-text/ibus-speech-to-text.spec "download.copr.fedorainfracloud.org"
