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
from .settings import save_settings, load_all_settings, load_video_settings
from .general_utils import get_deforum_version
from .ui_left import setup_deforum_left_side_ui
from scripts.deforum_extend_paths import deforum_sys_extend
import gradio as gr

def on_ui_tabs():
    # extend paths using sys.path.extend so we can access all of our files and folders
    deforum_sys_extend()
    # set text above generate button
    i1_store_backup = f"<p style=\"text-align:center;font-weight:bold;margin-bottom:0em\">Deforum extension version 3.1, for auto1111 v1.9 | Git commit: {get_deforum_version()}</p>"
    i1_store = i1_store_backup

    deforum_css = """
        #deforum_gallery_container { min-height: 80vh; }
        #deforum_gallery { min-height: 75vh; height: 75vh; }
        #deforum_gallery > div { height: 100%; }
        #deforum_gallery button.thumbnail-item { height: 100%; max-height: 75vh; }
        #deforum_gallery button.thumbnail-item img { object-fit: contain; max-height: 72vh; width: auto; }
        #deforum_gallery .preview { max-height: 75vh; }
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
                    skip = gr.Button('Pause/Resume', elem_id=f"{id_part}_skip", visible=False)
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
                
                output_panel = create_output_panel("deforum", opts.outdir_img2img_samples)
                if isinstance(output_panel, tuple):
                    deforum_gallery = output_panel[0]
                    generation_info = output_panel[1]
                    html_info = output_panel[2]
                else:
                    deforum_gallery = output_panel.gallery
                    generation_info = output_panel.generation_info
                    html_info = output_panel.infotext

                with gr.Row(variant='compact'):
                    settings_path = gr.Textbox("deforum_settings.txt", elem_id='deforum_settings_path', label="Settings File", info="Path to load/save settings. Updated automatically when you upload a file.")
                with gr.Row(variant='compact'):
                    upload_settings_file = gr.File(label="Upload Settings (Drag & Drop)", file_count="single", file_types=[".txt", ".json"])
                with gr.Row(variant='compact'):
                    save_settings_btn = gr.Button('Save Settings', elem_id='deforum_save_settings_btn')
                    save_as_settings_btn = gr.Button('Save As...', elem_id='deforum_save_as_settings_btn')
                    load_settings_btn = gr.Button('Load All Settings', elem_id='deforum_load_settings_btn')
                    load_video_settings_btn = gr.Button('Load Video Settings', elem_id='deforum_load_video_settings_btn')

                # Quick Tools accordion
                with gr.Accordion("Quick Tools", open=False, elem_id='deforum_quick_tools'):
                    # 1. Quick-load recent settings files
                    with gr.Row(variant='compact'):
                        recent_files_dd = gr.Dropdown(label="Recent Settings Files", choices=[], elem_id='deforum_recent_files', interactive=True)
                        refresh_recent_btn = gr.Button("Refresh List", elem_id='deforum_refresh_recent', scale=0)
                    # 2. Prompt preview at frame N
                    with gr.Row(variant='compact'):
                        preview_frame = gr.Number(label="Preview prompt at frame", value=0, precision=0, elem_id='deforum_preview_frame')
                        preview_prompt_btn = gr.Button("Show Active Prompt", elem_id='deforum_preview_prompt_btn', scale=0)
                    prompt_preview_box = gr.Textbox(label="Active prompt at frame", lines=5, interactive=False, elem_id='deforum_prompt_preview')
                    # 3. Prompt diff / all keyframes viewer
                    with gr.Row(variant='compact'):
                        show_diff_btn = gr.Button("Show All Keyframe Prompts", elem_id='deforum_show_diff_btn')
                    prompt_diff_html = gr.HTML(elem_id='deforum_prompt_diff')
                    # 4. Motion curve summary
                    with gr.Row(variant='compact'):
                        show_motion_btn = gr.Button("Show Motion Schedule Summary", elem_id='deforum_show_motion_btn')
                    motion_summary_html = gr.HTML(elem_id='deforum_motion_summary')

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

        # Auto-update path textbox when a settings file is uploaded
        upload_settings_file.change(
            fn=lambda f: gr.update(value=f.name) if f is not None else gr.update(),
            inputs=[upload_settings_file],
            outputs=[settings_path],
        )

        save_settings_btn.click(
            fn=wrap_gradio_call(save_settings),
            inputs=[settings_path] + settings_component_list + video_settings_component_list,
            outputs=[],
        )

        # Save As: JS prompts for a new filename, injects it into the path box, then saves
        save_as_settings_btn.click(
            fn=None,
            inputs=[settings_path],
            outputs=[settings_path],
            _js="""(current_path) => {
                const name = prompt('Save settings as (full path or filename):', current_path || 'deforum_settings.txt');
                return name ? name : current_path;
            }"""
        ).then(
            fn=wrap_gradio_call(save_settings),
            inputs=[settings_path] + settings_component_list + video_settings_component_list,
            outputs=[],
        )
        
        load_settings_btn.click(
            fn=wrap_gradio_call(lambda *args, **kwargs: load_all_settings(*args, ui_launch=False, **kwargs)),
            inputs=[settings_path] + settings_component_list,
            outputs=settings_component_list,
        )

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

        # ── Quick Tools wiring ────────────────────────────────────────────────

        # 1. Recent settings file scanner
        def get_recent_settings_files():
            import glob, os
            scan_dirs = [
                opts.outdir_img2img_samples,
                os.path.join(opts.outdir_img2img_samples, "Finished and Awesome"),
                os.path.dirname(opts.outdir_img2img_samples),  # outputs root
            ]
            found = []
            for d in scan_dirs:
                if os.path.isdir(d):
                    found.extend(glob.glob(os.path.join(d, "**", "*settings*.txt"), recursive=True))
                    found.extend(glob.glob(os.path.join(d, "*.txt")))
            seen, result = set(), []
            for f in sorted(found, key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True):
                if f not in seen:
                    seen.add(f)
                    result.append(f)
            return gr.update(choices=result[:30], value=None)

        refresh_recent_btn.click(fn=get_recent_settings_files, inputs=[], outputs=[recent_files_dd])

        recent_files_dd.change(
            fn=lambda f: gr.update(value=f) if f else gr.update(),
            inputs=[recent_files_dd],
            outputs=[settings_path],
        ).then(
            fn=wrap_gradio_call(lambda *args, **kwargs: load_all_settings(*args, ui_launch=False, **kwargs)),
            inputs=[settings_path] + settings_component_list,
            outputs=settings_component_list,
        )

        # 2. Prompt preview at frame N
        def get_prompt_at_frame(frame_num, prompts_val):
            import json
            try:
                if isinstance(prompts_val, str):
                    prompts = json.loads(prompts_val)
                else:
                    prompts = prompts_val or {}
                frames = sorted(int(k) for k in prompts.keys())
                if not frames:
                    return "No prompts defined."
                fn = int(frame_num or 0)
                active = max((f for f in frames if f <= fn), default=frames[0])
                next_f = next((f for f in frames if f > active), None)
                header = f"Active keyframe: {active}"
                if next_f:
                    header += f"  (next change at frame {next_f})"
                return f"{header}\n\n{prompts[str(active)]}"
            except Exception as e:
                return f"Error parsing prompts: {e}"

        preview_prompt_btn.click(
            fn=get_prompt_at_frame,
            inputs=[preview_frame, components['prompts']],
            outputs=[prompt_preview_box],
        )

        # 3. All keyframes viewer
        def show_all_prompts(prompts_val):
            import json
            try:
                if isinstance(prompts_val, str):
                    prompts = json.loads(prompts_val)
                else:
                    prompts = prompts_val or {}
                frames = sorted(int(k) for k in prompts.keys())
                if not frames:
                    return "<p style='color:#888;font-family:sans-serif;'>No prompts defined.</p>"
                html = "<div style='font-family:Consolas,monospace;font-size:11px;max-height:500px;overflow-y:auto;border:1px solid #d4d4d4;padding:10px;background:#fafafa;border-radius:4px;'>"
                for i, f in enumerate(frames):
                    p = str(prompts[str(f)])
                    next_f = frames[i+1] if i+1 < len(frames) else "end"
                    html += f"<div style='margin-bottom:12px;border-left:3px solid #217346;padding-left:10px;'>"
                    html += f"<span style='font-weight:700;color:#217346;font-size:12px;'>Frame {f}</span>"
                    html += f"<span style='color:#888;font-size:10px;margin-left:10px;'>→ frame {next_f}</span><br><br>"
                    html += f"<span style='color:#1f2937;white-space:pre-wrap;word-break:break-word;'>{p}</span>"
                    html += "</div>"
                html += "</div>"
                return html
            except Exception as e:
                return f"<p style='color:red;'>Error: {e}</p>"

        show_diff_btn.click(
            fn=show_all_prompts,
            inputs=[components['prompts']],
            outputs=[prompt_diff_html],
        )

        # 4. Motion schedule summary
        def show_motion_summary(*schedule_vals):
            import re
            labels = ['translation_x','translation_y','translation_z',
                      'rotation_3d_x','rotation_3d_y','rotation_3d_z',
                      'zoom','angle']
            def parse_keyframes(s):
                if not s or not isinstance(s, str):
                    return {}
                return {int(m[0]): m[1] for m in re.findall(r'(\d+)\s*:\s*\(([^)]+)\)', s)}
            html = "<div style='font-family:Consolas,monospace;font-size:11px;border:1px solid #d4d4d4;padding:10px;background:#fafafa;border-radius:4px;'>"
            html += "<table style='border-collapse:collapse;width:100%;'>"
            html += "<tr style='background:#217346;color:white;'><th style='padding:4px 8px;text-align:left;'>Parameter</th><th style='padding:4px 8px;text-align:left;'>Keyframes</th></tr>"
            for i, (label, val) in enumerate(zip(labels, schedule_vals)):
                kf = parse_keyframes(val)
                if not kf:
                    continue
                bg = '#f9f9f9' if i % 2 == 0 else '#ffffff'
                kf_str = "  |  ".join(f"f{k}:{v}" for k, v in sorted(kf.items()))
                html += f"<tr style='background:{bg};'>"
                html += f"<td style='padding:4px 8px;font-weight:600;color:#217346;white-space:nowrap;'>{label}</td>"
                html += f"<td style='padding:4px 8px;color:#374151;'>{kf_str}</td></tr>"
            html += "</table></div>"
            return html

        motion_keys = ['translation_x','translation_y','translation_z',
                       'rotation_3d_x','rotation_3d_y','rotation_3d_z',
                       'zoom','angle']
        motion_inputs = [components[k] for k in motion_keys if k in components]
        show_motion_btn.click(
            fn=show_motion_summary,
            inputs=motion_inputs,
            outputs=[motion_summary_html],
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
