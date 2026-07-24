# Microcosm

*Deforum render viewer, best-settings recipe, and the notes behind them.*

Tools for reviewing Deforum renders and dialling in settings, plus the settings and notes behind them.

Three independent pieces. The first needs nothing installed — you can use it in about ten seconds.

| | What it is | Needs |
|---|---|---|
| **[`Microcosm.html`](Microcosm.html)** | Inspect + compare renders | a browser |
| **[`BEST_DEFAULT_settings.txt`](BEST_DEFAULT_settings.txt)** | My best working recipe, ready to load | Deforum |
| **[`BEST_PRACTICES.txt`](BEST_PRACTICES.txt)** | What makes renders good or garbage | nothing |
| **[`gallery-tab/`](gallery-tab/)** | The same viewer, live inside A1111 | A1111 (optional) |

---

## 1. The viewer — no install

**[Download `Microcosm.html`](Microcosm.html)** (right-click → Save link as), then double-click it.

That's the entire setup. No Python, no pip, no server, no build step, no internet — it's one 291 KB file with everything inline (including the Best Practices screenshots) and zero external references. It works with your wifi off, and nothing you open in it ever leaves your machine.

### Why it exists

Deforum writes a video and a settings file side by side, then leaves you guessing. The settings are a wall of JSON full of math like:

```
"0: (42-24*cos(2*3.14*t/2000))"
```

That describes a value *changing* across thousands of frames. Reading it tells you nothing about what frame 8,400 actually looked like.

This viewer evaluates that math live against playback. Press play, and the panel under the video shows the prompt, the LoRAs, the FOV and every camera value **at the frame you're watching**. When a LoRA changes it lights up green. So when a render turns out great — or like total garbage — you can see exactly what was happening at that moment.

### Using it

- Drag a render's `.mp4` **and** its `_settings.txt` onto the box. (Or a whole folder, or use the Browse buttons.)
- Press play. Watch the panel under the video.
- Tick **compare** on two or more, hit **Compare selected**: side-by-side, synced playback, every parameter aligned in rows with **differences highlighted** and identical ones dimmed. "Differences only" cuts straight to what changed.
- **View** menu: One row / Grid (you pick how many across) / Rows.

The video and settings must be name-matched:

```
MyRender_20260101120000.mp4
MyRender_20260101120000_settings.txt
```

That's exactly how Deforum saves them, so normally it just works.

---

## 2. `BEST_DEFAULT_settings.txt` — the Microcosm recipe

The actual Microcosm v2 settings — the render this whole thing is named after. Real prompts, real LoRA stack, nothing gutted. Only the machine-specific plumbing (output dir, resume state) has been cleared.

**To load it**, either:

- **Drop it on the preset box** in the Deforum tab, then pick it from the **Preset** dropdown. (This fork adds that — drag in any number of settings files and they become presets.)
- Or the old way: **Settings File** box → path → **Load all settings**.

Then swap the prompts for your own and render.

### What it needs

**Checkpoint:** `MOHAWK_v20`. Any good SDXL model works — just pick a different one in the normal checkpoint dropdown, or change `sd_model_name` in the file.

**Init image:** `microcosm-init.png` ships next to this file. Drop it into the **Init image** box — this fork auto-ticks "use init" when you do. (The settings reference it by filename, so point it wherever you keep it.)

**LoRAs** — three on every keyframe, the rest as accents:

| LoRA | Weight | Keyframes |
|---|---|---|
| `add-detail-xl` | 0.7 | all 50 |
| `JuggerCineXL2` | 0.55 | all 50 |
| `xl_more_art-full_v1` | 0.35 | all 50 |
| `ral-amber-sdxl` | 0.35–0.45 | 38 |
| `ral-trichome-sdxl` | 0.40 | 31 |
| `ral-iricnt-sdxl` | 0.30 | 27 |
| `coralbugXL` | 0.30–0.40 | 25 |
| `ral-anmlsktn-sdxl-dora` | 0.35 | 20 |
| `Fractal_Fusion-000009` | 0.30 | 17 |
| `HR_Giger_SDXL` | — | 13 |
| `ral-melting-sdxl` | — | 12 |
| `epoxy_skull-sdxl`, `ral-blueresin-sdxl`, `fractalex` | — | 3–7 |

Missing one isn't fatal — A1111 prints "couldn't find Lora" and carries on without it. The render still works, it just looks different. The three on every keyframe are the ones that matter most.

**Heads up:** it's set to 15,000 frames, which is the full ~20-hour run. Drop `max_frames` to a few thousand for a first look.

The recipe, and why (all covered in [`BEST_PRACTICES.txt`](BEST_PRACTICES.txt)):

```
steps 40, DPM++ 2M SDE / Karras, CFG 6
strength 0.6, noise 0.01, cadence 5
optical flow DIS Fine, color coherence LAB
midas 0.5, translation_z 2.5, FOV 70, seed 31415
```

Strength 0.6 + noise 0.01 is the combination that survived an A/B test past 3,000 frames without degrading. LAB locks the palette so colour doesn't drift over a long render. Cadence 5 keeps it dense.

---

## 3. `BEST_PRACTICES.txt`

Every line came from a real render that either worked or failed: checkpoint behaviour, the exact settings that cause the "spaghetti line" streaking, the two proven smoothness recipes, camera/FOV rules, init images, prompt and LoRA practice.

The viewer's **Best Practices** tab lays this out in two columns with a screenshot of the actual Deforum control each note is about — click any screenshot to see it full size.

There's a **VELLO'S SECTION** at the bottom. Add yours and send it back and I'll merge it in. (The viewer's Best Practices tab has an Edit button that gives you a download for exactly that.)

---

## 4. `gallery-tab/` — the viewer live inside A1111 (optional)

The standalone viewer only knows about files you drop into it. This extension gives you the full version: a **Render Gallery** tab inside AUTOMATIC1111 that scans a folder live, plus flagging, comments saved to disk, folder settings, and one-click export of a render with its settings as a zip.

### Install

Copy the folder into your extensions directory so it ends up here:

```
stable-diffusion-webui/
  extensions/
    deforum-gallery-tab/
      scripts/
        gallery_tab.py
```

Then restart A1111. A **Render Gallery** tab appears next to Deforum.

**No pip installs.** It only uses libraries A1111 already ships with (fastapi, starlette, gradio, and the standard library). `ffmpeg`/`ffprobe` on your PATH is optional — used for poster thumbnails and durations; without them everything else still works.

It's deliberately a *separate* extension rather than part of Deforum, so updating or reinstalling Deforum can never remove it, and vice versa.

`_build_gallery.py` is the generator behind both the standalone viewer and the in-A1111 page:

```bash
python _build_gallery.py --standalone   # rebuild the shareable single-file viewer
python _build_gallery.py                # build a local gallery of your whole output folder
```

It auto-detects your output folder (`--root`, then `$DEFORUM_OUTPUT`, then the standard A1111 layout). Heads-up: the non-standalone build de-duplicates by filename and **moves** duplicates into a `_trash_review/` folder next to your renders — it moves, never deletes, but point it at a backed-up tree the first time.

---

## Troubleshooting

**Windows or the browser warns when opening the HTML** — expected. It's a local file containing JavaScript; the warning is generic. Nothing in it talks to the network.

**Video shows a still but won't play** — the file's fine; some browsers are fussy with large local videos. Try Chrome or Edge.

**Panel says "press play" and never fills** — that render has no matching `_settings.txt` (see name-matching above), or only the `.mp4` was dropped.

**Page looks empty** — nothing's loaded yet. It ships with no renders inside; that's why it's 291 KB and not 40 GB. Drop something in.
