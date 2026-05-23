
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
