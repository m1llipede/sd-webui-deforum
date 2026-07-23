# Copyright (C) 2023 Deforum LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

# Contact the authors: https://deforum.github.io/

from .args import DeforumOutputArgs, get_component_names, get_settings_component_names
from modules.shared import opts, state
from modules.ui import create_output_panel, wrap_gradio_call
from modules.call_queue import wrap_gradio_gpu_call
from .run_deforum import run_deforum
from .settings import save_settings, load_all_settings, load_video_settings, load_prompts_only, pick_save_path, stash_init_image
from .general_utils import get_deforum_version
from .ui_left import setup_deforum_left_side_ui
from scripts.deforum_extend_paths import deforum_sys_extend
import gradio as gr
import os as _os, glob as _glob


# --- Preset support (added) ------------------------------------------------------------------
# A preset is just a complete Deforum settings .txt in the /presets folder at the WebUI root.
# Built-ins are written by _make_presets.py; the render viewer's "save as preset" drops files
# here too, so a good render becomes a reusable recipe. Nothing here parses settings itself -
# selecting a preset hands its path to Deforum's own load_all_settings.
DEFORUM_PRESETS_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                    "..", "..", "..", "..", "presets")
DEFORUM_PRESETS_DIR = _os.path.normpath(DEFORUM_PRESETS_DIR)


def deforum_preset_label(path):
    """'03_Roller_Coaster_Camera_settings.txt' -> '03 - Roller Coaster Camera'"""
    b = _os.path.basename(path)
    for suf in ("_settings.txt", ".txt"):
        if b.endswith(suf):
            b = b[: -len(suf)]
            break
    b = b.replace("_", " ").strip()
    if len(b) > 3 and b[:2].isdigit() and b[2:3] == " ":
        b = b[:2] + " - " + b[3:]
    return b


def deforum_list_presets():
    """Labels for the dropdown. Never raises: a bad presets dir just yields an empty list."""
    try:
        if not _os.path.isdir(DEFORUM_PRESETS_DIR):
            return []
        files = sorted(_glob.glob(_os.path.join(DEFORUM_PRESETS_DIR, "*.txt")))
        return [deforum_preset_label(f) for f in files]
    except Exception as e:
        print(f"[deforum-presets] could not list presets: {e}")
        return []


def deforum_preset_path(label):
    """Map a dropdown label back to its file. Returns None if it no longer exists."""
    try:
        for f in sorted(_glob.glob(_os.path.join(DEFORUM_PRESETS_DIR, "*.txt"))):
            if deforum_preset_label(f) == label:
                return f
    except Exception as e:
        print(f"[deforum-presets] could not resolve preset '{label}': {e}")
    return None


def _deforum_fix_init_image(d):
    """A settings file records init_image as an absolute path. If that file is gone, loading the
    preset silently gives you use_init=True pointing at nothing - which is the 'images are missing'
    bug. Repair on import: keep a real image, otherwise disable init rather than reference a ghost.
    Returns (settings, note)."""
    import json as _json
    ii = str(d.get("init_image") or "").strip()
    if not d.get("use_init"):
        return d, None
    if ii and _os.path.isfile(ii):
        return d, None                       # image is real, nothing to do
    if ii:
        # try to recover it by filename from the usual homes before giving up
        base = _os.path.basename(ii)
        root = _os.path.normpath(_os.path.join(DEFORUM_PRESETS_DIR, ".."))
        for cand in (_os.path.join(root, "outputs", "deforum_init_images", base),
                     _os.path.join(root, "outputs", "img2img-images", "INIT_IMAGES", base)):
            if _os.path.isfile(cand):
                d["init_image"] = cand
                return d, f"init image relinked -> {base}"
    d["use_init"] = False
    d["init_image"] = ""
    return d, f"init image missing ({_os.path.basename(ii) or 'unset'}) -> use_init turned OFF"


def deforum_import_presets(files):
    """Drag-and-drop any number of Deforum settings files straight into the preset list.

    Each file is validated as JSON, has its init_image repaired (see above), and is copied into
    /presets. Nothing is executed and nothing is overwritten silently - a name clash gets a suffix.
    Returns (dropdown_update, status_text).
    """
    import json as _json, shutil as _shutil
    if not files:
        return gr.update(), "Nothing dropped."
    if not isinstance(files, (list, tuple)):
        files = [files]
    _os.makedirs(DEFORUM_PRESETS_DIR, exist_ok=True)
    added, skipped, notes = [], [], []
    for f in files:
        src = getattr(f, "name", None) or (f if isinstance(f, str) else None)
        if not src or not _os.path.isfile(src):
            skipped.append(f"{f}: not a readable file"); continue
        base = _os.path.basename(src)
        try:
            with open(src, encoding="utf-8-sig") as fh:
                d = _json.load(fh)
            if not isinstance(d, dict) or "prompts" not in d:
                skipped.append(f"{base}: not a Deforum settings file"); continue
        except Exception as e:
            skipped.append(f"{base}: unreadable JSON ({e})"); continue

        d, note = _deforum_fix_init_image(d)
        if note: notes.append(f"{base}: {note}")
        # never resume a stale render off an imported preset
        d["resume_from_timestring"] = False
        d["resume_timestring"] = ""

        stem = base[:-4] if base.lower().endswith(".txt") else base
        if not stem.endswith("_settings"): stem += "_settings"
        dst = _os.path.join(DEFORUM_PRESETS_DIR, stem + ".txt")
        n = 2
        while _os.path.exists(dst):
            dst = _os.path.join(DEFORUM_PRESETS_DIR, f"{stem}_{n}.txt"); n += 1
        try:
            with open(dst, "w", encoding="utf-8") as fh:
                _json.dump(d, fh, indent=4)
            added.append(deforum_preset_label(dst))
        except Exception as e:
            skipped.append(f"{base}: could not write ({e})")

    msg = []
    if added:   msg.append("Added " + str(len(added)) + ": " + ", ".join(added))
    if notes:   msg.append("Fixed: " + " | ".join(notes))
    if skipped: msg.append("Skipped: " + " | ".join(skipped))
    return gr.update(choices=deforum_list_presets()), ("  ".join(msg) or "Nothing imported.")


# --- Folder settings (added): init images / video+ControlNet inputs / models -----------------
# These belong HERE in the Deforum panel (they are Deforum's inputs), not in the render gallery.
# Stored in the same shared config the gallery extension uses, so both stay in agreement.
_DEFORUM_WEBUI_ROOT = _os.path.dirname(DEFORUM_PRESETS_DIR)
_DEFORUM_SHARED_CONFIG = _os.path.join(_DEFORUM_WEBUI_ROOT, "outputs", "img2img-images",
                                       "_gallery_data", "config.json")
_DEFORUM_FOLDER_DEFAULTS = {
    "init": _os.path.join(_DEFORUM_WEBUI_ROOT, "outputs", "img2img-images", "INIT_IMAGES"),
    "video": _os.path.join(_DEFORUM_WEBUI_ROOT, "outputs", "deforum_video_inputs"),
}


def _deforum_shared_cfg_load():
    import json
    try:
        with open(_DEFORUM_SHARED_CONFIG, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def deforum_folder_get(key):
    c = _deforum_shared_cfg_load()
    return (c.get("dirs") or {}).get(key) or _DEFORUM_FOLDER_DEFAULTS.get(key, "")


def deforum_folder_set(key, value):
    import json
    value = str(value or "").strip()
    if not value:
        return
    c = _deforum_shared_cfg_load()
    c.setdefault("dirs", {})[key] = value
    try:
        _os.makedirs(_os.path.dirname(_DEFORUM_SHARED_CONFIG), exist_ok=True)
        tmp = _DEFORUM_SHARED_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(c, fh, indent=4)
        _os.replace(tmp, _DEFORUM_SHARED_CONFIG)
    except Exception as e:
        print(f"[deforum-folders] could not save config: {e}")


def deforum_models_dir():
    """The folder the CURRENT session actually loads checkpoints from (read-only here:
    it is fixed at launch by --ckpt-dir, or defaults to models/Stable-diffusion)."""
    try:
        from modules import shared, paths
        d = getattr(shared.cmd_opts, "ckpt_dir", None)
        return d or _os.path.join(paths.models_path, "Stable-diffusion")
    except Exception:
        return _os.path.join(_DEFORUM_WEBUI_ROOT, "models", "Stable-diffusion")


def deforum_pick_folder(current):
    """Native Windows folder dialog (this WebUI runs on the same machine as the browser)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        picked = filedialog.askdirectory(
            initialdir=current if current and _os.path.isdir(current) else None,
            title="Select folder")
        root.destroy()
        return picked.replace("/", "\\") if picked else (current or "")
    except Exception as e:
        print(f"[deforum-folders] folder picker failed: {e}")
        return current or ""
# ---------------------------------------------------------------------------------------------

def on_ui_tabs():
    # extend paths using sys.path.extend so we can access all of our files and folders
    deforum_sys_extend()
    # set text above generate button
    i1_store_backup = f"<p style=\"text-align:center;font-weight:bold;margin-bottom:0em\">Deforum extension version 3.1, for auto1111 v1.9 | Git commit: {get_deforum_version()}</p>"
    i1_store = i1_store_backup

    deforum_css = """
        /* Gallery starts compact, zoom control scales it */
        #deforum_gallery_container { min-height: unset !important; }
        #deforum_gallery { min-height: unset !important; height: 280px !important; transition: height 0.2s; }
        #deforum_gallery > div { height: 100% !important; }
        #deforum_gallery button.thumbnail-item { height: 100% !important; }
        #deforum_gallery button.thumbnail-item img { object-fit: contain !important; height: 100% !important; width: auto !important; }
        #deforum_zoom_row { position: relative; z-index: 500; }
        #deforum_preview_zoom { display: flex; align-items: center; gap: 4px; padding: 2px 0; }
        #deforum_preview_zoom button:hover { background: #3a3d56 !important; }
    """
    with gr.Blocks(analytics_enabled=False, css=deforum_css) as deforum_interface:
        components = {}
        dummy_component = gr.Label(visible=False)
        with gr.Row(elem_id='deforum_progress_row').style(equal_height=False, variant='compact'):
            with gr.Column(scale=1, variant='panel'):
                # setting the left side of the ui:
                components = setup_deforum_left_side_ui()
            with gr.Column(scale=1, variant='compact'):
                with gr.Row(variant='compact'):
                    btn = gr.Button("Click here after the generation to show the video")
                    components['btn'] = btn
                    close_btn = gr.Button("Close the video", visible=False)
                with gr.Row(variant='compact'):
                    i1 = gr.HTML(i1_store, elem_id='deforum_header')
                    components['i1'] = i1
                    def show_vid(): # Show video button related func
                        from .run_deforum import last_vid_data # get latest vid preview data (this import needs to stay inside the function!)
                        return {
                            i1: gr.update(value=last_vid_data, visible=True),
                            close_btn: gr.update(visible=True),
                            btn: gr.update(value="Update the video", visible=True),
                        }
                    btn.click(
                        fn=show_vid,
                        inputs=[],
                        outputs=[i1, close_btn, btn],
                        )
                    def close_vid(): # Close video button related func
                        return {
                            i1: gr.update(value=i1_store_backup, visible=True),
                            close_btn: gr.update(visible=False),
                            btn: gr.update(value="Click here after the generation to show the video", visible=True),
                        }
                    
                    close_btn.click(
                        fn=close_vid,
                        inputs=[],
                        outputs=[i1, close_btn, btn],
                        )
                id_part = 'deforum'
                with gr.Row(elem_id=f"{id_part}_generate_box", variant='compact'):
                    skip = gr.Button('Pause/Resume', elem_id=f"{id_part}_skip", visible=True)
                    interrupt = gr.Button('Interrupt', elem_id=f"{id_part}_interrupt", visible=True)
                    interrupting = gr.Button('Interrupting...', elem_id=f"{id_part}_interrupting", elem_classes="generate-box-interrupting", tooltip="Interrupting generation...")
                    submit = gr.Button('Generate', elem_id=f"{id_part}_generate", variant='primary')

                    skip.click(
                        fn=lambda: state.skip(),
                        inputs=[],
                        outputs=[],
                    )

                    interrupt.click(
                        fn=lambda: state.interrupt(),
                        inputs=[],
                        outputs=[],
                    )
                    
                    interrupting.click(
                        fn=lambda: state.interrupt(),
                        inputs=[],
                        outputs=[],
                    )
                
                # Force live preview in modal lightbox so fullscreen view updates during render
                gr.HTML("""<script>(function(){function f(){if(typeof opts!=='undefined'){opts.js_live_preview_in_modal_lightbox=true}};if(typeof onAfterUiUpdate==='function'){onAfterUiUpdate(f)}else{setTimeout(f,3000)}})();</script>""", visible=False)
                gr.HTML("""<div id="deforum_preview_zoom">
                    <span style="font-size:12px;color:#888;margin-right:4px;">Preview:</span>
                    <button onclick="(function(h){var g=document.getElementById('deforum_gallery');g.style.setProperty('height',h,'important');var lp=g.querySelector('.livePreview');if(lp){lp.style.height='100%';lp.style.width='100%'}window.dispatchEvent(new Event('resize'))})('280px')" style="background:#2b2d42;color:#ccc;border:1px solid #555;border-radius:4px;padding:2px 10px;font-size:12px;cursor:pointer;margin:0 2px;">256</button>
                    <button onclick="(function(h){var g=document.getElementById('deforum_gallery');g.style.setProperty('height',h,'important');var lp=g.querySelector('.livePreview');if(lp){lp.style.height='100%';lp.style.width='100%'}window.dispatchEvent(new Event('resize'))})('540px')" style="background:#2b2d42;color:#ccc;border:1px solid #555;border-radius:4px;padding:2px 10px;font-size:12px;cursor:pointer;margin:0 2px;">512</button>
                    <button onclick="(function(h){var g=document.getElementById('deforum_gallery');g.style.setProperty('height',h,'important');var lp=g.querySelector('.livePreview');if(lp){lp.style.height='100%';lp.style.width='100%'}window.dispatchEvent(new Event('resize'))})('1060px')" style="background:#2b2d42;color:#ccc;border:1px solid #555;border-radius:4px;padding:2px 10px;font-size:12px;cursor:pointer;margin:0 2px;">1024</button>
                    <button onclick="(function(h){var g=document.getElementById('deforum_gallery');g.style.setProperty('height',h,'important');var lp=g.querySelector('.livePreview');if(lp){lp.style.height='100%';lp.style.width='100%'}window.dispatchEvent(new Event('resize'))})('85vh')" style="background:#2b2d42;color:#ccc;border:1px solid #555;border-radius:4px;padding:2px 10px;font-size:12px;cursor:pointer;margin:0 2px;">Full</button>
                </div>""", elem_id="deforum_zoom_row")
                output_panel = create_output_panel("deforum", opts.outdir_img2img_samples)
                if isinstance(output_panel, tuple):
                    deforum_gallery = output_panel[0]
                    generation_info = output_panel[1]
                    html_info = output_panel[2]
                else:
                    deforum_gallery = output_panel.gallery
                    generation_info = output_panel.generation_info
                    html_info = output_panel.infotext

                # --- Preset dropdown (added): pick a proven recipe, it loads into every field below.
                # Presets are ordinary complete settings files in F:\stable-diffusion-webui\presets\,
                # so this reuses Deforum's own load_all_settings - no parallel loader to drift.
                with gr.Row(variant='compact'):
                    preset_dropdown = gr.Dropdown(
                        label="Preset", choices=deforum_list_presets(), value=None,
                        elem_id='deforum_preset_dropdown', scale=5,
                        info="Loads a saved recipe into all settings below. Files live in /presets. Swap prompts after loading.")
                    refresh_presets_btn = gr.Button('Refresh', elem_id='deforum_refresh_presets_btn', scale=1)
                with gr.Row(variant='compact'):
                    preset_drop = gr.File(
                        label="Drop settings files here to add them as presets (multiple at once)",
                        file_count="multiple", file_types=[".txt", ".json"],
                        elem_id='deforum_preset_drop')
                with gr.Row(variant='compact'):
                    preset_status = gr.Textbox(value="", label="Presets", interactive=False, lines=1,
                                               elem_id='deforum_preset_status')
                with gr.Row(variant='compact'):
                    gr.HTML('<a href="/deforum-gallery/_MASTER_GALLERY.html" target="_blank" '
                            'style="font-size:13px">&#128444; Open the Render Gallery / comparison page'
                            '</a> <span style="opacity:.6;font-size:12px">(also available as the '
                            '&quot;Render Gallery&quot; tab above)</span>')
                with gr.Accordion("Folders — init images, video/ControlNet inputs, models", open=False):
                    with gr.Row(variant='compact'):
                        init_folder_tb = gr.Textbox(value=deforum_folder_get('init'), scale=5,
                            label="Init images folder", elem_id='deforum_init_folder',
                            info="Where your init images live.")
                        init_browse_btn = gr.Button('Browse…', scale=1, elem_id='deforum_init_browse')
                    with gr.Row(variant='compact'):
                        video_folder_tb = gr.Textbox(value=deforum_folder_get('video'), scale=5,
                            label="Video / ControlNet inputs folder", elem_id='deforum_video_folder',
                            info="Source videos for video-to-video and ControlNet.")
                        video_browse_btn = gr.Button('Browse…', scale=1, elem_id='deforum_video_browse')
                    with gr.Row(variant='compact'):
                        gr.Textbox(value=deforum_models_dir(), interactive=False, scale=6,
                            label="Models (checkpoints) folder — read-only",
                            elem_id='deforum_models_folder',
                            info="Fixed at launch. To change it, add --ckpt-dir \"D:\\path\" (and --lora-dir for LoRAs) to COMMANDLINE_ARGS in Start Deforum.bat, then restart.")
                with gr.Row(variant='compact'):
                    settings_path = gr.Textbox("deforum_settings.txt", elem_id='deforum_settings_path', label="Settings File", info="Path to load/save settings. Updated automatically when you upload a file.")
                with gr.Row(variant='compact'):
                    upload_settings_file = gr.File(label="Upload Settings (Drag & Drop)", file_count="single", file_types=[".txt", ".json"])
                with gr.Row(variant='compact'):
                    save_settings_btn = gr.Button('Save Settings', elem_id='deforum_save_settings_btn')
                    save_as_settings_btn = gr.Button('Save As...', elem_id='deforum_save_as_settings_btn')
                    load_settings_btn = gr.Button('Load all settings', elem_id='deforum_load_settings_btn')
                    load_video_settings_btn = gr.Button('Load only video settings', elem_id='deforum_load_video_settings_btn')
                    load_prompts_only_btn = gr.Button('Load only prompts', elem_id='deforum_load_prompts_only_btn')
                with gr.Row(variant='compact'):
                    save_status = gr.Textbox(value="", elem_id='deforum_save_status', label="Last save / load", interactive=False, lines=1)

        component_list = [components[name] for name in get_component_names()]

        submit.click(
                    fn=wrap_gradio_gpu_call(run_deforum),
                    _js="submit_deforum",
                    inputs=[dummy_component, dummy_component] + component_list,
                    outputs=[
                         deforum_gallery,
                         components["resume_timestring"],
                         generation_info,
                         html_info                 
                    ],
                )
        
        settings_component_list = [components[name] for name in get_settings_component_names()]
        video_settings_component_list = [components[name] for name in list(DeforumOutputArgs().keys())]

        # Auto-update path textbox when a settings file is uploaded.
        # Reconstruct the proper output path from batch_name inside the settings,
        # so Save / Save As default to the real output folder, not gradio temp.
        def update_settings_path_from_upload(f):
            if f is None:
                return gr.update()
            import os, json
            name = os.path.basename(f.name)
            root_dir = os.path.realpath(opts.outdir_img2img_samples or 'outputs/img2img-images')
            # Most settings files live in the img2img-images root; auto-saved ones live in a
            # batch_name subfolder. Check both and point at whichever actually exists, as an
            # absolute path, so Save / Save As target the real file's folder (not the SD root).
            candidates = [os.path.join(root_dir, name)]
            try:
                with open(f.name, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                batch = data.get('batch_name', '')
                if batch:
                    candidates.append(os.path.join(root_dir, batch, name))
            except Exception:
                pass
            for c in candidates:
                if os.path.isfile(c):
                    return gr.update(value=os.path.realpath(c))
            return gr.update(value=os.path.realpath(candidates[0]))
        upload_settings_file.change(
            fn=update_settings_path_from_upload,
            inputs=[upload_settings_file],
            outputs=[settings_path],
        )

        save_settings_btn.click(
            fn=wrap_gradio_call(save_settings),
            inputs=[settings_path] + settings_component_list + video_settings_component_list,
            outputs=[save_status],
        )

        # Save As: opens a real native Windows file picker via tkinter (server-side,
        # but server = your machine since WebUI is on localhost). Then saves to the chosen path.
        save_as_settings_btn.click(
            fn=pick_save_path,
            inputs=[settings_path],
            outputs=[settings_path],
        ).then(
            fn=wrap_gradio_call(save_settings),
            inputs=[settings_path] + settings_component_list + video_settings_component_list,
            outputs=[save_status],
        )

        # Load only prompts: read animation_prompts + positive/negative from a file,
        # leave every other setting alone.
        prompts_comp = components["animation_prompts"]
        prompts_pos_comp = components["animation_prompts_positive"]
        prompts_neg_comp = components["animation_prompts_negative"]
        load_prompts_only_btn.click(
            fn=wrap_gradio_call(load_prompts_only),
            inputs=[settings_path, prompts_comp, prompts_pos_comp, prompts_neg_comp],
            outputs=[prompts_comp, prompts_pos_comp, prompts_neg_comp, save_status],
        )

        # When the user drops an image into the init_image_box, save it under
        # outputs/deforum_init_images/<hash>.png and mirror that path into the
        # init_image URL textbox. The textbox IS persisted by save_settings, so
        # the next time the settings file is loaded, init_image points at the
        # same PNG on disk and the image effectively "comes back" — even though
        # the PIL box widget itself can't be serialized.
        init_image_box_comp = components["init_image_box"]
        init_image_comp = components["init_image"]
        init_image_box_comp.change(
            fn=stash_init_image,
            inputs=[init_image_box_comp, init_image_comp],
            outputs=[init_image_comp, save_status],
        )

        load_settings_btn.click(
            fn=wrap_gradio_call(lambda *args, **kwargs: load_all_settings(*args, ui_launch=False, **kwargs)),
            inputs=[settings_path] + settings_component_list,
            outputs=settings_component_list,
        )

        # --- Preset dropdown wiring (added) ---
        # Selecting a preset resolves its label to a file path and hands it to the SAME
        # load_all_settings the button uses, so there is no second code path to drift.
        # Also mirrors the path into settings_path so it's obvious what got loaded (and so
        # "Save Settings" doesn't silently overwrite the preset unless that's intended).
        def _load_preset(preset_label, *args):
            path = deforum_preset_path(preset_label) if preset_label else None
            if not path:
                # unknown/removed preset: change nothing rather than wiping the user's settings
                return [gr.update() for _ in settings_component_list]
            return load_all_settings(path, *args, ui_launch=False)

        preset_dropdown.change(
            fn=wrap_gradio_call(_load_preset),
            inputs=[preset_dropdown] + settings_component_list,
            outputs=settings_component_list,
        )
        preset_dropdown.change(
            fn=lambda label: (deforum_preset_path(label) or "") if label else gr.update(),
            inputs=[preset_dropdown],
            outputs=[settings_path],
        )
        refresh_presets_btn.click(
            fn=lambda: gr.update(choices=deforum_list_presets()),
            inputs=[],
            outputs=[preset_dropdown],
        )
        # drag-and-drop any number of settings files -> they become presets immediately
        preset_drop.upload(
            fn=deforum_import_presets,
            inputs=[preset_drop],
            outputs=[preset_dropdown, preset_status],
        )

        # folder settings: Browse opens a native folder dialog; any change persists to the
        # shared config (the same file the render gallery reads its folder settings from)
        init_browse_btn.click(fn=deforum_pick_folder, inputs=[init_folder_tb], outputs=[init_folder_tb])
        video_browse_btn.click(fn=deforum_pick_folder, inputs=[video_folder_tb], outputs=[video_folder_tb])
        init_folder_tb.change(fn=lambda v: deforum_folder_set('init', v), inputs=[init_folder_tb], outputs=[])
        video_folder_tb.change(fn=lambda v: deforum_folder_set('video', v), inputs=[video_folder_tb], outputs=[])

        load_video_settings_btn.click(
            fn=wrap_gradio_call(load_video_settings),
            inputs=[settings_path] + video_settings_component_list,
            outputs=video_settings_component_list,
        )
        
        # New Settings Editor and File Upload logic
        from .gradio_funcs import sync_ui_to_editor, sync_editor_to_ui, process_settings_upload
        
        settings_editor_code = components['settings_editor_code']
        load_ui_to_editor_btn = components['load_ui_to_editor_btn']
        apply_editor_to_ui_btn = components['apply_editor_to_ui_btn']
        
        load_ui_to_editor_btn.click(
            fn=sync_ui_to_editor,
            inputs=settings_component_list,
            outputs=[settings_editor_code],
        )
        
        apply_editor_to_ui_btn.click(
            fn=sync_editor_to_ui,
            inputs=[settings_editor_code] + settings_component_list,
            outputs=settings_component_list,
        )
        
        upload_settings_file.change(
            fn=process_settings_upload,
            inputs=[upload_settings_file] + settings_component_list,
            outputs=settings_component_list,
        )
        
    # handle persistent settings - load the persistent file upon UI launch
    def trigger_load_general_settings():
        print("Loading general settings...")
        wrapped_fn = wrap_gradio_call(lambda *args, **kwargs: load_all_settings(*args, ui_launch=True, **kwargs))
        inputs = [settings_path.value] + [component.value for component in settings_component_list]
        outputs = settings_component_list
        updated_values = wrapped_fn(*inputs, *outputs)[0]
        settings_component_name_to_obj = {name: component for name, component in zip(get_settings_component_names(), settings_component_list)}
        for key, value in updated_values.items():
            settings_component_name_to_obj[key].value = value['value']
    # actually check persistent setting status
    if opts.data.get("deforum_enable_persistent_settings", False):
        trigger_load_general_settings()
        
    return [(deforum_interface, "Deforum", "deforum_interface")]
