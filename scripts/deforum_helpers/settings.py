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

import os
import json
import modules.shared as sh
from .args import DeforumArgs, DeforumAnimArgs, DeforumOutputArgs, ParseqArgs, LoopArgs, get_settings_component_names, pack_args
from .deforum_controlnet import controlnet_component_names
from .defaults import mask_fill_choices
from .deprecation_utils import handle_deprecated_settings
from .general_utils import get_deforum_version, clean_gradio_path_strings

def get_keys_to_exclude():
    return ["init_sample", "perlin_w", "perlin_h", "image_path", "outdir", "init_image_box"]
    # perlin params are used just not shown in ui for now, so not to be deleted
    # image_path and outdir are in use, not to be deleted
    # init_image_box is PIL object not string, so ignore.

def load_args(args_dict_main, args, anim_args, parseq_args, loop_args, controlnet_args, video_args, custom_settings_file, root, run_id):
    custom_settings_file = custom_settings_file[run_id]
    print(f"reading custom settings from {custom_settings_file.name}")
    if not os.path.isfile(custom_settings_file.name):
        print('Custom settings file does not exist. Using in-notebook settings.')
        return
    with open(custom_settings_file.name, "r") as f:
        try:
            jdata = json.loads(f.read())
        except:
            return False
        handle_deprecated_settings(jdata)
        root.animation_prompts = jdata.get("prompts", root.animation_prompts)
        if "animation_prompts_positive" in jdata:
            args_dict_main['animation_prompts_positive'] = jdata["animation_prompts_positive"]
        if "animation_prompts_negative" in jdata:
            args_dict_main['animation_prompts_negative'] = jdata["animation_prompts_negative"]
        keys_to_exclude = get_keys_to_exclude()
        for args_namespace in [args, anim_args, parseq_args, loop_args, controlnet_args, video_args]:
            for k, v in vars(args_namespace).items():
                if k not in keys_to_exclude:
                    if k in jdata:
                        setattr(args_namespace, k, jdata[k])
                    else:
                        print(f"Key {k} doesn't exist in the custom settings data! Using default value of {v}")
        print(args, anim_args, parseq_args, loop_args)
        return True

# save settings function that get calls when run_deforum is being called
def save_settings_from_animation_run(args, anim_args, parseq_args, loop_args, controlnet_args, video_args, root, full_out_file_path = None):
    if full_out_file_path:
        args.__dict__["seed"] = root.raw_seed
        args.__dict__["batch_name"] = root.raw_batch_name
    args.__dict__["prompts"] = root.animation_prompts
    args.__dict__["positive_prompts"] = args.positive_prompts
    args.__dict__["negative_prompts"] = args.negative_prompts
    exclude_keys = get_keys_to_exclude()
    settings_filename = full_out_file_path if full_out_file_path else os.path.join(args.outdir, f"{root.timestring}_settings.txt")
    with open(settings_filename, "w+", encoding="utf-8") as f:
        s = {}
        for d in (args.__dict__, anim_args.__dict__, parseq_args.__dict__, loop_args.__dict__, controlnet_args.__dict__, video_args.__dict__):
            s.update({k: v for k, v in d.items() if k not in exclude_keys})
        s["sd_model_name"] = sh.sd_model.sd_checkpoint_info.name if sh.sd_model else "unknown"
        s["sd_model_hash"] = sh.sd_model.sd_checkpoint_info.hash if sh.sd_model else "unknown"
        s["deforum_git_commit_id"] = get_deforum_version()
        json.dump(s, f, ensure_ascii=False, indent=4)

# In gradio gui settings save/ load funcs:
def save_settings(*args, **kwargs):
    settings_path = args[0].strip()
    settings_path = clean_gradio_path_strings(settings_path)
    settings_path = os.path.realpath(settings_path)
    settings_component_names = get_settings_component_names()
    data = {settings_component_names[i]: args[i+1] for i in range(0, len(settings_component_names))}
    args_dict = pack_args(data, DeforumArgs)
    anim_args_dict = pack_args(data, DeforumAnimArgs)
    parseq_dict = pack_args(data, ParseqArgs)
    args_dict["prompts"] = json.loads(data['animation_prompts'])
    args_dict["animation_prompts_positive"] = data['animation_prompts_positive']
    args_dict["animation_prompts_negative"] = data['animation_prompts_negative']
    loop_dict = pack_args(data, LoopArgs)
    controlnet_dict = pack_args(data, controlnet_component_names)
    video_args_dict = pack_args(data, DeforumOutputArgs)
    combined = {**args_dict, **anim_args_dict, **parseq_dict, **loop_dict, **controlnet_dict, **video_args_dict}
    exclude_keys = get_keys_to_exclude()
    filtered_combined = {k: v for k, v in combined.items() if k not in exclude_keys}
    filtered_combined["sd_model_name"] = sh.sd_model.sd_checkpoint_info.name if sh.sd_model else "unknown"
    filtered_combined["sd_model_hash"] = sh.sd_model.sd_checkpoint_info.hash if sh.sd_model else "unknown"
    filtered_combined["deforum_git_commit_id"] = get_deforum_version()
    print(f"saving custom settings to {settings_path}")
    with open(settings_path, "w", encoding='utf-8') as f:
        f.write(json.dumps(filtered_combined, ensure_ascii=False, indent=4))
    status = f"Saved to: {settings_path}"
    return [status]

def load_all_settings(*args, ui_launch=False, jdata=None, **kwargs):
    import gradio as gr
    settings_path = args[0].strip() if not jdata else ""
    settings_path = clean_gradio_path_strings(settings_path)
    settings_path = os.path.realpath(settings_path)
    settings_component_names = get_settings_component_names()
    data = {settings_component_names[i]: args[i+1] for i in range(len(settings_component_names))}
    
    if not jdata:
        print(f"reading custom settings from {settings_path}")
        if not os.path.isfile(settings_path):
            print('The custom settings file does not exist. The values will be unchanged.')
            if ui_launch:
                return ({key: gr.update(value=value) for key, value in data.items()},)
            else:
                return list(data.values()) + [""]

        with open(settings_path, "r", encoding='utf-8') as f:
            try:
                jdata = json.load(f)
            except Exception as e:
                print(f"Error loading settings file: {e}")
                if ui_launch: return ({key: gr.update(value=value) for key, value in data.items()},)
                else: return list(data.values()) + [""]
                
    handle_deprecated_settings(jdata)
    if 'animation_prompts' in jdata:
        jdata['prompts'] = jdata['animation_prompts']
    elif 'prompts' not in jdata and 'animation_prompts' not in jdata:
        # if prompts are missing entirely, don't overwrite current ones
        jdata['prompts'] = json.loads(data.get('animation_prompts', '{}'))

    result = {}
    for key, default_val in data.items():
        val = jdata.get(key, default_val)
        if key == 'sampler' and isinstance(val, str):
            samp_val = val.split()
            scheduler_val = None
            if samp_val[-1] in ['Uniform','SGM Uniform','Karras','Exponential','Polyexponential']:
                scheduler_val = samp_val[-1]
                val = (val.split(" " + samp_val[-1]))[0]
        if key == 'scheduler' and isinstance(val, str):
            if scheduler_val is not None:
                val = scheduler_val
            else:
                from modules.sd_schedulers import schedulers_map
                val = schedulers_map[val].label
        elif key == 'fill' and isinstance(val, int):
            val = mask_fill_choices[val]
        elif key in {'reroll_blank_frames', 'noise_type'} and key not in jdata:
            default_key_val = (DeforumArgs if key != 'noise_type' else DeforumAnimArgs)[key]
            print(f"{key} not found in load file, using default value: {default_key_val}")
            val = default_key_val
        elif key in {'animation_prompts_positive', 'animation_prompts_negative'}:
            val = jdata.get(key, default_val)
        elif key == 'animation_prompts':
            val = json.dumps(jdata['prompts'], ensure_ascii=False, indent=4)
        result[key] = val

    if ui_launch:
        return ({key: gr.update(value=value) for key, value in result.items()},)
    else:
        return list(result.values()) + [""]


def stash_init_image(pil_image, current_init_path):
    """When the user drops an image into init_image_box, save the PIL to disk
    under outputs/deforum_init_images/<sha8>.png and return the path so it
    can be mirrored into the init_image URL textbox. That makes the path
    serializable to settings .txt — the box widget itself can't be saved
    because PIL objects don't survive JSON.

    Returns (new_init_image_path, status_text). On clear, returns ("", "").
    """
    if pil_image is None:
        # User cleared the box. Leave the existing textbox path alone.
        return current_init_path, ""
    try:
        import hashlib
        from io import BytesIO
        # Hash the PNG bytes so the same image always lands at the same path
        # (no orphan duplicates if you drop the same file twice).
        buf = BytesIO()
        pil_image.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        digest = hashlib.sha1(png_bytes).hexdigest()[:8]
        outdir = os.path.join(
            sh.opts.outdir_img2img_samples or "outputs/img2img-images",
            "..", "deforum_init_images"
        )
        outdir = os.path.realpath(outdir)
        os.makedirs(outdir, exist_ok=True)
        out_path = os.path.join(outdir, f"init_{digest}.png")
        if not os.path.isfile(out_path):
            with open(out_path, "wb") as f:
                f.write(png_bytes)
        return out_path, f"Init image saved -> {out_path}"
    except Exception as e:
        print(f"[stash_init_image] failed: {e}")
        return current_init_path, f"Init image save failed: {e}"


def pick_save_path(current_path):
    """Open a native Save As dialog (Windows Explorer style) on the server,
    which is the same machine as the user since WebUI runs on localhost.
    Returns the chosen absolute path, or the unchanged current path on cancel."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        # Default to the resolved current_path so the dialog opens in the right folder
        default_dir = ""
        default_name = "deforum_settings.txt"
        if current_path and current_path.strip():
            cp = clean_gradio_path_strings(current_path.strip())
            cp = os.path.realpath(cp)
            if os.path.isdir(os.path.dirname(cp)):
                default_dir = os.path.dirname(cp)
            default_name = os.path.basename(cp) or default_name
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.asksaveasfilename(
            parent=root,
            title="Save Deforum settings as...",
            initialdir=default_dir or None,
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Settings file", "*.txt *.json"), ("All files", "*.*")],
        )
        root.destroy()
        if not chosen:
            return current_path  # user cancelled
        return os.path.realpath(chosen)
    except Exception as e:
        print(f"[Save As] file dialog failed: {e}")
        return current_path


def load_prompts_only(settings_path, current_prompts, current_pos, current_neg):
    """Load only the animation_prompts (+ positive/negative) from a settings file,
    leaving every other field untouched. Returns 3 values in order matching the
    button's outputs: animation_prompts, animation_prompts_positive, animation_prompts_negative."""
    sp = clean_gradio_path_strings(settings_path.strip())
    sp = os.path.realpath(sp)
    if not os.path.isfile(sp):
        print(f"[Load only prompts] file not found: {sp}")
        return [current_prompts, current_pos, current_neg, ""]
    try:
        with open(sp, "r", encoding="utf-8") as f:
            jdata = json.load(f)
    except Exception as e:
        print(f"[Load only prompts] error reading {sp}: {e}")
        return [current_prompts, current_pos, current_neg, ""]
    handle_deprecated_settings(jdata)
    prompts = jdata.get("prompts", jdata.get("animation_prompts", None))
    pos = jdata.get("animation_prompts_positive", current_pos)
    neg = jdata.get("animation_prompts_negative", current_neg)
    if prompts is None:
        new_prompts = current_prompts
    else:
        new_prompts = json.dumps(prompts, ensure_ascii=False, indent=4) if not isinstance(prompts, str) else prompts
    print(f"[Load only prompts] loaded prompts from {sp}")
    return [new_prompts, pos, neg, ""]


def load_video_settings(*args, jdata=None, **kwargs):
    video_settings_path = args[0].strip() if not jdata else ""
    vid_args_names = list(DeforumOutputArgs().keys())
    data = {vid_args_names[i]: args[i+1] for i in range(0, len(vid_args_names))}
    
    if not jdata:
        print(f"reading custom video settings from {video_settings_path}")
        if not os.path.isfile(video_settings_path):
            print('The custom video settings file does not exist. The values will be unchanged.')
            return [data[name] for name in vid_args_names] + [""]
        else:
            with open(video_settings_path, "r") as f:
                try:
                    jdata = json.loads(f.read())
                except Exception as e:
                    print(f"Error loading video settings: {e}")
                    return [data[name] for name in vid_args_names] + [""]
                handle_deprecated_settings(jdata)
    ret = []

    for key in data:
        if key == 'add_soundtrack':
            add_soundtrack_val = jdata[key]
            if type(add_soundtrack_val) == bool:
                ret.append('File' if add_soundtrack_val else 'None')
            else:
                ret.append(add_soundtrack_val)
        elif key in jdata:
            ret.append(jdata[key])
        else:
            ret.append(data[key])
    
    return ret