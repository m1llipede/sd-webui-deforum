
# Deforum Stable Diffusion — m1llipede fork

> **Fork of [deforum-art/sd-webui-deforum](https://github.com/deforum-art/sd-webui-deforum)** with UI improvements focused on usability during long render sessions.

## Changes vs upstream

### Layout & Navigation
- **Keyframes tab two-column layout** — Strength schedules (Strength / CFG / Seed / SubSeed / Step / Sampler / Checkpoint) and Motion tabs (Motion / Noise / Coherence / Anti-Blur / Depth) now display side-by-side in two columns instead of stacked. See both at the same time without scrolling.
- **Larger output gallery** — gallery fills ~75% of the viewport so you can actually see what you're rendering.

### Settings File Workflow
- **Drag & drop settings upload** — drop any `.txt` or `.json` Deforum settings file onto the Upload area; all UI controls populate instantly.
- **Upload auto-updates path** — the Settings File path textbox now updates to the uploaded file's path automatically, so Save writes back to the correct file.
- **Save As... button** — saves settings to any filename/path via a popup dialog instead of always overwriting the same file.
- **Live JSON settings editor** — a full JSON editor is built into the left panel. Click "Load UI to Editor" to see all current settings as JSON, edit directly, then "Apply Editor to UI" to push changes back to all controls.

### Init Image Fix
- **Init image auto-enables "Use init"** — dropping an image into the Init image box now automatically ticks the "Use init" checkbox. Previously renders would silently ignore the image if the checkbox wasn't manually ticked.

### Depth Settings
- **MiDaS/Zoe weight always visible** — the MiDaS weight field is now always shown in Depth Warping & FOV. Previously it was hidden unless you selected a legacy depth algorithm from the dropdown.

### Improved Tooltips
Hover-over descriptions added or improved for:
- `noise_schedule` — explains what higher/lower values do to per-frame variation
- `diffusion_cadence` — explains the speed/quality tradeoff (1 = every frame diffused, 2-4 = good balance)
- `optical_flow_cadence` — explains RAFT vs DIS Fine vs DIS Medium vs Farneback tradeoffs
- `color_coherence` — explains LAB vs HSV vs RGB vs None and when to use each
- `seed_behavior` — explains iter / fixed / random / schedule in plain English
- `midas_weight` — adds range guidance and default recommendation
- `perspective_flip_theta/phi/gamma` — were blank, now describe the axis each controls
- `enable_perspective_flip` — explains the 2D-simulates-3D use case

### Bug Fixes
- **Save crash fix** — fixed a NoneType crash when saving settings with no model loaded.

---

## Best Practices — Hard-Won Notes from Long Render Sessions

These are practical lessons learned from hundreds of hours of Deforum renders, not from docs. Take what's useful.

### Sampler & Quality

- **DPM++ 2M SDE + Karras at 40 steps** is the most reliable baseline. Smooth, coherent frame-to-frame, and fast enough for 8000+ frame runs. Don't chase exotic samplers — consistency matters more than peak quality in animation.
- **Resolution: 1024x1024** for SDXL models. Don't go higher unless you have the VRAM headroom; it slows cadence and rarely improves the animation read at video playback speed.

### Coherence & Motion

- **Diffusion cadence 2-4** is the sweet spot. Cadence 1 (every frame diffused) burns time and often over-cooks motion artifacts. Cadence 2-4 lets optical flow do the heavy lifting between frames while keeping the model's creative contribution where it counts.
- **Strength 0.80-0.85** is the working range for 3D mode. Lower than 0.78 and the model loses creative grip; higher than 0.88 and you get frame flicker. 0.82 is a reliable default.
- **Seed behavior: schedule** — lets seed drift organically over time. Fixed seed freezes the aesthetic (useful for locked looks), random seed scrambles coherence. Schedule gives you controlled organic variation.

### Prompt Keyframing

- **Keyframe every 600-800 frames** for smooth thematic transitions. Tighter than 500 and transitions feel rushed; looser than 1000 and sections feel aimless.
- **Write prompts as active camera moves** — "Flying into", "Penetrating a", "Soaring through" — this reinforces the motion vectors you set and keeps the model oriented to the 3D movement.
- **Keep negative prompts consistent across all keyframes.** Changing negatives mid-render causes tonal lurches even if positives are smooth.

### LoRA Stacking

These LoRAs have proven reliable for psychedelic/visionary/abstract animation work:

| LoRA | Role | Typical weight |
|---|---|---|
| `Unfazed_Psychedelic-000009` | Core psychedelic style driver | 0.70-0.85 |
| `3D_Fractals_wDoF` | Depth-of-field fractal dimension | 0.40-0.50 |
| `ral-mndlbrt-sdxl` | Mandelbrot/sacred geometry | 0.45-0.65 |
| `ral-colorswirl-sdxl` | Vivid color motion | 0.40-0.50 |
| `ral-hlgrphc-sdxl` | Holographic / diagrammatic overlay | 0.35-0.45 |
| `ral-polygon-sdxl` | Hard geometric structure | 0.45-0.55 |
| `ral-3dcubes-sdxl` | Isometric cube lattices | 0.40-0.50 |
| `ral-iricnt-sdxl` | Iridescent surface shimmer | 0.40-0.50 |
| `add-detail-xl` | Global detail enhancement | 0.40-0.60 |
| `HR_Giger_SDXL` | Biomechanical texture | 0.40-0.55 |
| `fractalex` | Fractal field extension | 0.40-0.50 |

**Keep total LoRA weight under ~2.0.** Stacking 3-4 LoRAs at moderate weights (0.35-0.55 each) is more stable than 2 LoRAs at high weights. Going over ~2.0 total causes color saturation blowout and geometry instability.

### Checkpoint Models

All models below are SDXL. Deforum with SDXL requires the Forge fork or a webui build with SDXL support.

| Model | Best for |
|---|---|
| `juggernautXL_v8Rundiffusion` | Photorealistic base, holds detail well across long runs |
| `dynavisionXLAllInOneStylized` | Stylized/illustrated renders, great LoRA compatibility |
| `dreamshaperXL_lightningDPMSDE` | Fast, good for motion-heavy sequences |
| `nightvisionxl_V900` | Dark atmospheric work, Giger-adjacent aesthetics |
| `RealVisXL_V5.0` | High-realism, clean geometry, pairs well with fractal LoRAs |
| `epicrealismXL_pureFix` | Grounded surrealism, strong structure |
| `CyberRealisticXL_V9.0` | Sci-fi and tech aesthetics |
| `MOHAWK_v20` | Stylized character/organic work |

For pure abstract/psychedelic animation, `dynavisionXL` + heavy LoRA stack is the most expressive combination. For structure-forward renders (geometric, diagrammatic), `RealVisXL` or `epicrealismXL` hold form better across 1000+ frames.

### Settings File Workflow

- **Save a named settings file after every render you like.** The auto-save in `outputs/img2img-images/Deforum_*/` is your safety net, but give good runs a real name immediately — you will not remember which timestamp was the good one.
- **Use the Settings File path box + Save As** to write named presets. Load them back with "Load All Settings" to resume from a known state.
- **Always check "Use init"** if you're using an init image — or use this fork, which auto-checks it on image drop.
- The `smooth_master_settings.txt` in the webui root is a working baseline from a successful 8000-frame run. Load it as a starting point.

### 3D Mode Tips

- **Large delay on first frame is normal** — depth models load at render start. Don't interrupt; wait for it.
- If you get depth artifacts mid-run, the depth model ran out of VRAM. Lower resolution or add `--lowvram` to your webui launch args.
- **MiDaS weight 0.3-0.5** is a good range. Too high and depth warping dominates motion; too low and 3D parallax disappears.

---

# Deforum Stable Diffusion — official extension for AUTOMATIC1111's webui

<p align="left">
    <a href="https://github.com/deforum-art/sd-webui-deforum/commits"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/deforum-art/deforum-for-automatic1111-webui"></a>
    <a href="https://github.com/deforum-art/sd-webui-deforum/issues"><img alt="GitHub issues" src="https://img.shields.io/github/issues/deforum-art/deforum-for-automatic1111-webui"></a>
    <a href="https://github.com/deforum-art/sd-webui-deforum/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/deforum-art/deforum-for-automatic1111-webui"></a>
    <a href="https://github.com/deforum-art/sd-webui-deforum/network"><img alt="GitHub forks" src="https://img.shields.io/github/forks/deforum-art/deforum-for-automatic1111-webui"></a>
    </a>
</p>

## Need help? See our [FAQ](https://github.com/deforum-art/sd-webui-deforum/wiki/FAQ-&-Troubleshooting)

## Getting Started

1. Install [AUTOMATIC1111's webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui/).

2. Now two ways: either clone the repo into the `extensions` directory via git commandline launched within in the `stable-diffusion-webui` folder

```sh
git clone https://github.com/deforum-art/sd-webui-deforum extensions/deforum
```

Or download this repository, locate the `extensions` folder within your WebUI installation, create a folder named `deforum` and put the contents of the downloaded directory inside of it. Then restart WebUI.

Or launch A1111, navigate to the Extensions tab, choose Available, find deforum in the list of available extensions and install it. Restart A1111 once the extension has been installed.
3. Open the webui, find the Deforum tab at the top of the page.

4. Enter the animation settings. Refer to [this general guide](https://docs.google.com/document/d/1pEobUknMFMkn8F5TMsv8qRzamXX_75BShMMXV8IFslI/edit) and [this guide to math keyframing functions in Deforum](https://docs.google.com/document/d/1pfW1PwbDIuW0cv-dnuyYj1UzPqe23BlSLTJsqazffXM/edit?usp=sharing). However, **in this version prompt weights less than zero don't just like in original Deforum!** Split the positive and the negative prompt in the json section using --neg argument like this "apple:\`where(cos(t)>=0, cos(t), 0)\`, snow --neg strawberry:\`where(cos(t)<0, -cos(t), 0)\`"

5. To view animation frames as they're being made, without waiting for the completion of an animation, go to the 'Settings' tab and set the value of this toolbar **above zero**. Warning: it may slow down the generation process.

![adsdasunknown](https://user-images.githubusercontent.com/14872007/196064311-1b79866a-e55b-438a-84a7-004ff30829ad.png)


6. Run the script and see if you got it working or even got something. **In 3D mode a large delay is expected at first** as the script loads the depth models. In the end, using the default settings the whole thing should consume 6.4 GBs of VRAM at 3D mode peaks and no more than 3.8 GB VRAM in 3D mode if you launch the webui with the '--lowvram' command line argument.

7. After the generation process is completed, click the button with the self-describing name to show the video or gif result right in the GUI!

8. Join our Discord where you can post generated stuff, ask questions and more: https://discord.gg/deforum. <br>
* There's also the 'Issues' tab in the repo, for well... reporting issues ;) 

9. Profit!

## Known issues

* This port is not fully backward-compatible with the notebook and the local version both due to the changes in how AUTOMATIC1111's webui handles Stable Diffusion models and the changes in this script to get it to work in the new environment. *Expect* that you may not get exactly the same result or that the thing may break down because of the older settings.

## Screenshots

Amazing raw Deforum animation by [Pxl.Pshr](https://www.instagram.com/pxl.pshr):
* Turn Audio ON!

(Audio credits: SKRILLEX, FRED AGAIN & FLOWDAN - RUMBLE (PHACE'S DNB FLIP))

https://user-images.githubusercontent.com/121192995/224450647-39529b28-be04-4871-bb7a-faf7afda2ef2.mp4

Setting file of that video: [here](https://github.com/deforum-art/sd-webui-deforum/files/11353167/PxlPshrWinningAnimationSettings.txt).

<br>

Main extension tab:

![image](https://user-images.githubusercontent.com/121192995/226101131-43bf594a-3152-45dd-a5d1-2538d0bc221d.png)

Keyframes tab:

![image](https://user-images.githubusercontent.com/121192995/226101140-bfe6cce7-9b78-4a1d-be9a-43e1fc78239e.png)

## License

This program is distributed under the terms of the GNU Affero Public License v3.0, copyright (c) 2023 Deforum LLC.

Some of its sublicensed integrated 3rd party components may have other licenses, see LICENSE for usage terms.
