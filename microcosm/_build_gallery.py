"""ONE master gallery combining both tools Brian likes:
 - like _FOV_VIEWER: a LIVE panel synced to playback showing the prompt / LoRAs / FOV / camera changing
   over time (bigger text, EACH on its own row).
 - like _MASTER_RENDER_SHEET: every render as a vertical card with ALL settings listed below.
Scans the ENTIRE img2img-images tree (every render). De-dupes by filename and MOVES duplicates + known-bad
renders (rejected / short test partials) into _trash_review\ (not hard-deleted, per archive-before-delete).
Output: _MASTER_GALLERY.html
"""
import json, os, re, html, subprocess, shutil, sys

# --standalone: emit a SHAREABLE single-file viewer with NO local videos baked in (the real gallery
# points at 100s of GB of local mp4s, so it can't just be emailed). The standalone build is the same
# page with an empty grid - the recipient drags their OWN renders (+ settings.txt) onto it and gets
# the identical live prompt/LoRA/camera panel and side-by-side compare. One source of truth, no dupes.
STANDALONE = "--standalone" in sys.argv

def _arg(flag, default=None):
    """--flag=value or --flag value"""
    for i, a in enumerate(sys.argv):
        if a.startswith(flag + "="): return a.split("=", 1)[1]
        if a == flag and i + 1 < len(sys.argv): return sys.argv[i + 1]
    return default

def _find_root():
    """Locate the Deforum output folder: --root, then DEFORUM_OUTPUT env, then the standard
    A1111 layout relative to this script, then CWD. Keeps the repo usable on any machine."""
    c = _arg("--root") or os.environ.get("DEFORUM_OUTPUT")
    if c: return c
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "outputs", "img2img-images"),
                 os.path.join(os.getcwd(), "outputs", "img2img-images")):
        if os.path.isdir(cand): return cand
    return os.getcwd()

def _find_ffprobe():
    """--ffprobe, then FFPROBE env, then PATH. Falls back to bare name (probe just degrades)."""
    c = _arg("--ffprobe") or os.environ.get("FFPROBE")
    if c: return c
    found = shutil.which("ffprobe")
    return found or "ffprobe"

ROOT = _find_root()
OUT = os.path.join(ROOT, "Deforum_Render_Viewer.html") if STANDALONE else os.path.join(ROOT, "_MASTER_GALLERY.html")
FFPROBE = _find_ffprobe()
TRASH = os.path.join(ROOT, "_trash_review")
EXCLUDE = {"INIT_IMAGES", "_render_queue", "_trash_review", "_deferred_old_batch", "_thumbs",
           "_gallery_data", "_contact_sheet", "_contact_sheets", "_sheet", "_early", "_NEW_MOVIES",
           "prompts from Vello"}

# Baked-in snapshot of the notes (comments/flags/best practices) so the page shows them even when
# opened as a plain file. When served through the WebUI the live API takes over and edits persist
# to outputs/img2img-images/_gallery_data/gallery_notes.json.
def load_notes_snapshot():
    """Snapshot for the baked page. The STANDALONE build (the file that gets shared) ships the
    Best Practices ONLY - per-render comments and deletion flags are private working notes about
    renders the recipient doesn't even have, so they'd just show up as orphan entries in their
    Saved tab. The local gallery keeps everything."""
    p = os.path.join(ROOT, "_gallery_data", "gallery_notes.json")
    try:
        with open(p, encoding="utf-8") as fh:
            n = json.load(fh)
        if STANDALONE:
            return {"comments": {}, "flags": [], "best_practices": n.get("best_practices", "")}
        return {"comments": n.get("comments", {}), "flags": n.get("flags", []),
                "best_practices": n.get("best_practices", "")}
    except Exception:
        return {"comments": {}, "flags": [], "best_practices": ""}
THUMBS = os.path.join(ROOT, "_thumbs")


def make_thumb(mp4, name, dur):
    """One small poster JPEG per video, cached. preload='none' (the fix for the 111-request
    storm) also means the browser never fetches a first frame - without a poster every card
    is a blank gray box. Grab a frame ~10% in (frame 0 is often still the init image)."""
    os.makedirs(THUMBS, exist_ok=True)
    out = os.path.join(THUMBS, name + ".jpg")
    if os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    ffmpeg = os.path.join(os.path.dirname(FFPROBE), "ffmpeg.exe")
    if not os.path.isfile(ffmpeg):
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    try:
        seek = max(1.0, (dur or 60) * 0.10)
        r = subprocess.run([ffmpeg, "-y", "-ss", f"{seek:.1f}", "-i", mp4, "-frames:v", "1",
                            "-vf", "scale=512:-2", "-q:v", "4", out],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 1000:
            return out
    except Exception:
        pass
    return None
BAD_MARKERS = ("_rejected", "_short_tests", "_partials")

def load(p):
    for e in ("utf-8", "utf-8-sig"):
        try: return json.load(open(p, encoding=e))
        except Exception: pass
    return None

def probe(mp4):
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                               "-show_entries", "stream=nb_frames,width,height", "-show_entries", "format=duration",
                               "-of", "json", mp4], capture_output=True, text=True, timeout=30)
        j = json.loads(out.stdout or "{}"); st = (j.get("streams") or [{}])[0]
        return float(j.get("format", {}).get("duration", 0) or 0), st.get("nb_frames")
    except Exception:
        return 0, None

def first_expr(sched):
    s = str(sched or ""); i, j = s.find("("), s.rfind(")")
    return s[i+1:j].strip() if (i != -1 and j != -1 and j > i) else "0"

def to_js(expr):
    return re.sub(r"\b(sin|cos|tan|sqrt|abs)\(", r"Math.\1(", expr)

def split_prompt(text):
    loras = [n for n, w in re.findall(r"<lora:([^:>]+):([\d.]+)>", text or "")
             if n != "add-detail-xl"]   # ignore the always-present utility lora when diffing
    scene = re.sub(r"<lora:[^>]+>", "", text or ""); scene = re.split(r"--neg", scene)[0]
    return re.sub(r"\s+", " ", scene).strip(), loras   # loras is a LIST for JS diffing

def parse_sched(s):
    out = [[int(a), float(b)] for a, b in re.findall(r"(\d+)\s*:\s*\(?\s*([\d.]+)", str(s or ""))]
    return out or [[0, 0.0]]

# ---- full settings payload: EVERYTHING that can explain why one render looks different ----
# Brian: "I can't tell why some suck and why some are good, because you're not showing me all the
# parameters and what changed between them." So every card carries its complete settings (minus
# noise keys that can never explain a visual difference), ordered so the levers come first.
SKIP_KEYS = {"prompts", "animation_prompts_positive", "animation_prompts_negative", "positive_prompts",
             "init_sample", "image_path", "outdir", "init_image_box", "deforum_git_commit_id",
             "sd_model_hash", "batch_name", "resume_from_timestring", "resume_timestring",
             "override_settings_with_file", "custom_settings_file", "show_info_on_ui", "motion_preview_mode"}
PRIORITY = ["sd_model_name", "animation_mode", "max_frames", "W", "H", "fps", "steps", "sampler", "scheduler",
    "cfg_scale", "cfg_scale_schedule", "strength_schedule", "noise_schedule", "noise_multiplier_schedule",
    "diffusion_cadence", "optical_flow_cadence", "optical_flow_redo_generation", "cadence_flow_factor_schedule",
    "redo_flow_factor_schedule", "color_coherence", "contrast_schedule", "amount_schedule",
    "seed", "seed_behavior", "seed_schedule",
    "fov_schedule", "near_schedule", "far_schedule", "midas_weight", "use_depth_warping", "depth_algorithm",
    "translation_x", "translation_y", "translation_z", "rotation_3d_x", "rotation_3d_y", "rotation_3d_z",
    "zoom", "angle", "enable_perspective_flip", "perspective_flip_fv", "perspective_flip_theta",
    "perspective_flip_phi", "perspective_flip_gamma",
    "use_init", "init_image", "strength_0_no_init", "use_looper", "init_images", "image_strength_schedule",
    "blendFactorMax", "blendFactorSlope", "tweening_frames_schedule", "color_correction_factor",
    "border", "sampling_mode", "padding_mode", "color_force_grayscale", "noise_type"]

def fullify(d):
    """Complete, ordered settings dict for a card. ControlNet keys are collapsed to a single
    summary (they're ~100 keys of default noise unless actually enabled)."""
    out = {}
    cn_on = [k for k, v in d.items() if k.startswith("cn_") and "enabled" in k and v]
    for k in PRIORITY:
        if k in d and k not in SKIP_KEYS:
            out[k] = d[k]
    for k in sorted(d.keys()):
        if k in out or k in SKIP_KEYS or k.startswith("cn_"):
            continue
        out[k] = d[k]
    out["controlnet"] = f"{len(cn_on)} unit(s) enabled" if cn_on else "off"
    # long path values -> basenames so columns stay readable
    for k in ("init_image", "video_init_path", "video_mask_path", "mask_file", "soundtrack_path",
              "color_coherence_image_path"):
        if out.get(k):
            out[k] = os.path.basename(str(out[k]))
    if out.get("init_images"):
        out["init_images"] = re.sub(r'"[^"]*[\\/]([^"\\/]+)"', r'"\1"', str(out["init_images"]))[:300]
    return {k: ("" if v is None else v) for k, v in out.items()}

def lora_counts(d):
    """Which LoRAs this render actually uses, with keyframe counts - across ALL its prompts."""
    tally = {}
    for v in (d.get("prompts", {}) or {}).values():
        for n, w in re.findall(r"<lora:([^:>]+):([\d.]+)>", str(v)):
            key = f"{n} @{w}"
            tally[key] = tally.get(key, 0) + 1
    return tally

# ---- scan whole tree, collect mp4s (skipped entirely for the shareable standalone build) ----
found = []
if not STANDALONE:
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in EXCLUDE]
        for f in fn:
            if f.lower().endswith(".mp4"):
                found.append(os.path.join(dp, f))

# de-dup by basename + move dups/bad to trash
os.makedirs(TRASH, exist_ok=True)
seen, keep, trashed = {}, [], 0
def is_bad(p): return any(m in p.lower() for m in BAD_MARKERS)
# prefer the copy in +Master, else shortest path
found.sort(key=lambda p: (0 if "+master_deforum_renders" in p.lower() else 1, len(p)))
for p in found:
    base = os.path.basename(p)
    if is_bad(p):
        try: shutil.move(p, os.path.join(TRASH, base)); trashed += 1
        except Exception: pass
        continue
    if base in seen:  # duplicate filename -> trash this copy
        try: shutil.move(p, os.path.join(TRASH, os.path.dirname(p).split(os.sep)[-1] + "__" + base)); trashed += 1
        except Exception: pass
        continue
    seen[base] = p; keep.append(p)

keep.sort(key=lambda p: os.path.getmtime(p), reverse=True)

CAM = [("FOV", "fov_schedule"), ("Zoom Z", "translation_z"), ("Pan X", "translation_x"),
       ("Pan Y", "translation_y"), ("Rot X", "rotation_3d_x"), ("Rot Y", "rotation_3d_y"), ("Rot Z", "rotation_3d_z")]
SET_ROWS = [("Checkpoint","sd_model_name"),("Frames","max_frames"),("Cadence","diffusion_cadence"),
    ("Steps","steps"),("CFG","cfg_scale_schedule"),("Strength","strength_schedule"),("Noise","noise_schedule"),
    ("Midas","midas_weight"),("Color coherence","color_coherence"),("FOV schedule","fov_schedule"),
    ("Speed Z","translation_z"),("Init image","init_image")]

def sset(d, k):
    v = d.get(k, "-")
    if k == "init_image": return os.path.basename(str(v)) or "-"
    return str(first_expr(v)) if ("schedule" in k or k == "translation_z") and "(" in str(v) else str(v)

def experiment(d):
    """One-line summary of what THIS render was testing / what makes it distinct."""
    p = []
    ck = str(d.get("sd_model_name", "")).replace(".safetensors", "")
    p.append("MOHAWK" if "MOHAWK" in ck else ("RealVis" if "RealVis" in ck else (ck[:12] or "?")))
    # FOV
    fs = str(d.get("fov_schedule", ""))
    m = re.search(r"([\d.]+)\s*-\s*([\d.]+)\s*\*\s*cos", fs)
    if m:
        mid, amp = float(m.group(1)), float(m.group(2))
        per = re.search(r"t/(\d+)\)", fs)
        secs = f", {round(int(per.group(1))/30)}s cycle" if per else ""   # cos(2pi t/P) period = P frames
        p.append(f"FOV sweep {round(mid-amp)}-{round(mid+amp)}{secs}")
    else:
        mm = re.search(r"\(\s*([\d.]+)\s*\)", fs)
        p.append(f"FOV {mm.group(1)}" if mm else "no FOV anim")
    # camera
    tz, rz = str(d.get("translation_z", "")), str(d.get("rotation_3d_z", ""))
    if "cos" in tz and "0.5-0.5*cos" in tz.replace(" ", "") + rz.replace(" ", ""):
        p.append("FOV-coupled camera")
    elif "cos" in tz and "sin" in rz:
        p.append("FOV-coupled speed")
    elif "sin" in rz and "+" in rz:
        p.append("roller-coaster cam")
    elif "sin" in str(d.get("translation_x", "")):
        p.append("smooth sine cam")
    # cadence / strength / midas if notable
    cad = d.get("diffusion_cadence")
    if cad not in (8, None): p.append(f"cadence {cad}")
    st = first_expr(d.get("strength_schedule"))
    try:
        sv = float(re.findall(r"[\d.]+", st)[0])
        if abs(sv - 0.7) > 0.03: p.append(f"strength {sv}")
    except Exception: pass
    # Parseq-style multi-parameter animation: count how many native schedules actually oscillate (not flat)
    PARSEQ_FIELDS = ["strength_schedule", "noise_schedule", "noise_multiplier_schedule",
        "cfg_scale_schedule", "contrast_schedule", "antiblur_amount_schedule"]
    animated = [k for k in PARSEQ_FIELDS if "sin" in str(d.get(k, "")) or "cos" in str(d.get(k, ""))]
    if len(animated) >= 3:
        p.append(f"Parseq-style ({len(animated)} params animated)")
    # Looper: guide image swapped in mid-render
    if d.get("use_looper"):
        try:
            n_loop = len(json.loads(d.get("init_images", "{}")))
            if n_loop > 1: p.append(f"Looper: {n_loop} guide-image swaps")
        except Exception:
            p.append("Looper enabled")
    # scene diversity by SUBJECT DOMAIN (not text) so single-theme renders aren't mislabeled diverse
    DOMAINS = {
        "ocean/reef": ["coral","reef","fish","ocean","underwater","squid","octopus","jellyfish","wave","sea ","whale"],
        "ice/aurora": ["aurora","glacier","ice","frost","snow","frozen","icicle"],
        "space": ["galaxy","nebula","supernova","cosmic","star","milky way","void"],
        "flowers": ["flower","rose","petal","lotus","tulip","lavender","sunflower","blossom","pistil"],
        "waterfall": ["waterfall","rainbow"],
        "desert": ["canyon","desert","dune","sandstone","mesa"],
        "volcanic": ["lava","volcanic","obsidian","molten","ember"],
        "butterfly": ["butterfly","butterflies","hummingbird"],
        "forest/trees": ["tree","forest","autumn","bamboo","cherry","eucalyptus","canopy","leaves"],
        "crystal": ["crystal","cavern","gem","quartz","amethyst"],
        "jungle": ["jungle","mushroom","fern","fungus","mycelium","moss"],
        "macabre": ["skeleton","bone","skull","eyeball","fractal eye","rose vine"],
        "body/fungal-horror": ["skin","muscle","vein","sinew","hair","flesh","mold"],
        "mountain/lake": ["mountain","alpine","koi","lake","mist"],
        "storm/sky": ["storm","cloud","god ray","twilight"],
    }
    prompts = d.get("prompts", {}) or {}
    from collections import Counter
    tally = Counter()
    for v in prompts.values():
        head = re.split(r",", v)[0].lower()[:45]      # the PRIMARY subject of the scene
        for dom, kws in DOMAINS.items():
            if any(k in head for k in kws):
                tally[dom] += 1; break
        else:
            tally["other"] += 1
    if tally:
        total = sum(tally.values()); top, topn = tally.most_common(1)[0]
        ndom = len([d2 for d2, c in tally.items() if d2 != "other" and c >= 2])
        if topn / total > 0.55 and top != "other":
            p.append(f"single-theme: {top} (samey)")
        elif ndom >= 5:
            p.append(f"DIVERSE ({ndom} subject-domains)")
    return " &middot; ".join(p)

DATA = {}
cards = []
for i, mp4 in enumerate(keep):
    d = load(mp4[:-4] + "_settings.txt")
    dur, nbf = probe(mp4)
    rel = os.path.relpath(mp4, ROOT).replace("\\", "/")
    name = os.path.basename(mp4)[:-4]
    folder = os.path.dirname(rel)
    pid = f"v{i}"
    if d:
        prompts = d.get("prompts", {}) or {}
        ks = sorted(prompts, key=lambda x: int(x) if str(x).isdigit() else 0)
        kf = [[int(k) if str(k).isdigit() else 0, *split_prompt(prompts[k])] for k in ks]
        cam = {lab: {"js": to_js(first_expr(d.get(key))), "anim": ("t" in first_expr(d.get(key)))} for lab, key in CAM}
        DATA[pid] = {"fps": d.get("fps", 30) or 30, "kf": kf, "cam": cam, "camlabels": [c[0] for c in CAM],
                     "strength": parse_sched(d.get("strength_schedule")), "noise": parse_sched(d.get("noise_schedule")),
                     "name": name, "full": fullify(d), "loras": lora_counts(d)}
        exp = experiment(d)
    else:
        DATA[pid] = {"fps": 30, "kf": [], "cam": {}, "camlabels": [], "name": name, "full": {}, "loras": {}}
        exp = "no settings.txt (older render)"
    meta = f'{int(dur//60)}:{int(dur%60):02d} &middot; {nbf or "?"} frames'
    thumb = make_thumb(mp4, name, dur)
    poster_attr = f' poster="{html.escape(os.path.relpath(thumb, ROOT).replace(chr(92), "/"))}"' if thumb else ""
    # facets the toolbar filters on (derived once, in Python, so filtering is a cheap attr read)
    ck_raw = str(d.get("sd_model_name", "")) if d else ""
    ckpt = ("MOHAWK" if "MOHAWK" in ck_raw else "CyberRealistic" if "CyberRealistic" in ck_raw
            else "RealVis" if "RealVis" in ck_raw else "Juggernaut" if "uggernaut" in ck_raw
            else "epiCRealism" if "picrealism" in ck_raw.lower() else ("other" if ck_raw else "none"))
    tags = []
    e_low = exp.lower()
    for t, probe_s in [("roller", "roller-coaster"), ("fov-coupled", "fov-coupled"), ("fov-sweep", "fov sweep"),
                       ("parseq", "parseq-style"), ("looper", "looper:"), ("diverse", "diverse ("),
                       ("single-theme", "single-theme"), ("axis", "smooth sine cam")]:
        if probe_s in e_low: tags.append(t)
    if d and str(d.get("animation_mode", "3D")) == "2D": tags.append("2d-mode")
    if not d: tags.append("no-settings")
    # everything searchable in one lowercase blob: name, folder, checkpoint, tags, and prompt text
    hay = " ".join([name, folder, ck_raw, " ".join(tags), exp,
                    " ".join((d.get("prompts", {}) or {}).values()) if d else ""]).lower()
    cards.append(f'''<div class="card" data-pid="{pid}" data-name="{html.escape(name.lower())}"
      data-ckpt="{html.escape(ckpt)}" data-tags="{html.escape(' '.join(tags))}"
      data-mtime="{int(os.path.getmtime(mp4))}" data-frames="{nbf or 0}" data-dur="{int(dur)}"
      data-hay="{html.escape(hay[:4000])}">
      <div class="chead">
        <button class="flagbtn" data-name="{html.escape(name)}" title="Mark this render (video + settings) for deletion. Saved to the project folder; nothing is deleted until Brian says go.">&#128465; flag</button>
        <button class="exportbtn" data-name="{html.escape(name)}" title="Download a zip of this render's mp4 + settings.txt, ready to share.">&#11015; export</button>
        <label class="cmp"><input type="checkbox" class="cmp-check" data-pid="{pid}"> compare</label>
        <div class="fn" title="{html.escape(name)}">{html.escape(name)}</div>
        <div class="fd" title="{html.escape(folder or 'root')}">{html.escape(folder or 'root')} &middot; {meta}</div>
      </div>
      <div class="vidbox"><video id="{pid}" data-pid="{pid}" controls preload="none" playsinline
        src="{html.escape(rel)}"{poster_attr}></video></div>
      <div class="live" id="live-{pid}"><div class="lrow hint">press play &mdash; live prompt, LoRAs and camera appear here</div></div>
      <div class="exp">{exp}</div>
      <div class="lorachips" data-pid="{pid}"></div>
      <div class="cmts" data-name="{html.escape(name)}"></div>
      <div class="setfill" data-pid="{pid}"></div>
    </div>''')

# ---------------------------------------------------------------------------------------------
# PRESETS - 8 built-in recipes. Every one of these is a REAL setting-set that actually rendered on
# this project (verified against the on-disk settings files / the deforum skill), not invented:
#   1 Photoreal Master      - the current best photoreal stack (CyberRealisticXL, camera-forward prompts)
#   2 Microcosm v2          - Brian's "best render ever", read straight from Microcosm_v2_BEST_EVER_settings.txt
#   3 Roller Coaster Cam    - the curve-anticipating camera (yaw/pitch phase-LEAD the turn)
#   4 FOV Sweep Coupled     - the signature dolly-zoom FOV sweep w/ FOV-coupled camera speed
#   5 Parseq Multi-Param    - 6 native schedules animated on independent periods + Looper image swaps
#   6 Pure Axis Dolly       - clean single-axis travel (horizontal), gentle pitch tip
#   7 Laffoley Time Machine - LAB colour-lock + Looper (skill Path 1: palette-consistent abstract)
#   8 Jungle Bioluminescent - DIS Fine optical flow + very low noise (skill Path 2: photoreal/evolving)
# Each is a settings OVERLAY: the fields that define the look. The viewer can merge one over a dropped
# render's full settings to emit a complete, Deforum-loadable settings.txt.
PRESETS = [
  {"name": "1 - Photoreal Master (CyberRealistic XL)",
   "use": "Maximum photorealism. The current best stack: real-camera prompt language + CyberRealistic XL. Start here for anything that must not look like AI.",
   "settings": {
      "sd_model_name": "CyberRealisticXL_V9.0_FP16.safetensors",
      "steps": 50, "cfg_scale": 7.5, "cfg_scale_schedule": "0: (7.5)",
      "sampler": "DPM++ 2M SDE", "scheduler": "Karras",
      "strength_schedule": "0: (0.55)", "noise_schedule": "0: (0.003)",
      "diffusion_cadence": 6, "optical_flow_cadence": "DIS Fine",
      "cadence_flow_factor_schedule": "0: (1.0)",
      "near_schedule": "0: (200)", "sampling_mode": "bicubic",
      "use_depth_warping": True, "midas_weight": 0.4, "color_coherence": "None",
      "W": 1024, "H": 1024, "fps": 30}},

  {"name": "2 - Microcosm v2 (best render ever)",
   "use": "The gold standard for organic long-form morphing. Exact settings from the render Brian rated his best. LAB locks the palette; cadence 5 keeps it dense.",
   "settings": {
      "sd_model_name": "MOHAWK_v20.safetensors",
      "steps": 40, "cfg_scale_schedule": "0: (6)",
      "sampler": "DPM++ 2M SDE", "scheduler": "Karras",
      "strength_schedule": "0: (0.6)", "noise_schedule": "0: (0.01)",
      "noise_multiplier_schedule": "0: (1.0)",
      "diffusion_cadence": 5, "optical_flow_cadence": "DIS Fine",
      "color_coherence": "LAB",
      "translation_z": "0: (2.5)", "midas_weight": 0.5, "seed": 31415,
      "W": 1024, "H": 1024, "fps": 30}},

  {"name": "3 - Roller Coaster Camera",
   "use": "Fluid coaster flight that never sits level. Yaw/pitch phase-LEAD the translation so the camera looks INTO the curve before it turns - the anticipation that makes it feel like a real ride.",
   "settings": {
      "translation_z": "0: (1.9 + 1.1*sin(t/130) + 0.5*sin(t/47))",
      "translation_x": "0: (0.45*sin(t/95) + 0.2*sin(t/38))",
      "translation_y": "0: (0.4*sin(t/110 + 1.0) + 0.18*cos(t/44))",
      "rotation_3d_z": "0: (0.14 + 0.5*sin(t/95 + 0.5) + 0.12*sin(t/33))",
      "rotation_3d_y": "0: (0.04 + 0.13*sin(t/95 + 0.9))",
      "rotation_3d_x": "0: (-0.03 + 0.1*sin(t/110 + 1.4))",
      "fov_schedule": "0: (80-70*cos(2*3.14*t/900))",
      "diffusion_cadence": 6, "strength_schedule": "0: (0.55)"}},

  {"name": "4 - FOV Sweep + FOV-Coupled Camera",
   "use": "The signature dolly-zoom look. FOV breathes 18-66 over 67s and the WHOLE camera is coupled in-phase to it, so it crawls when telephoto and opens up when wide. Z keeps moving (never fully stops).",
   "settings": {
      "fov_schedule": "0: (42-24*cos(2*3.14*t/2000))",
      "translation_z": "0: (1.4*(0.55+0.45*(0.5-0.5*cos(2*3.14*t/2000))))",
      "translation_x": "0: (0.28*sin(t/180)*(0.15+0.85*(0.5-0.5*cos(2*3.14*t/2000))))",
      "translation_y": "0: (0.24*sin(t/210 + 1.0)*(0.15+0.85*(0.5-0.5*cos(2*3.14*t/2000))))",
      "rotation_3d_z": "0: ((0.04 + 0.2*sin(t/160 + 0.5))*(0.15+0.85*(0.5-0.5*cos(2*3.14*t/2000))))",
      "rotation_3d_y": "0: ((0.02 + 0.08*sin(t/180 + 0.9))*(0.15+0.85*(0.5-0.5*cos(2*3.14*t/2000))))",
      "rotation_3d_x": "0: ((-0.01 + 0.05*sin(t/210 + 1.4))*(0.15+0.85*(0.5-0.5*cos(2*3.14*t/2000))))",
      "diffusion_cadence": 6, "strength_schedule": "0: (0.55)"}},

  {"name": "5 - Parseq-Style Multi-Param + Looper",
   "use": "Parseq-like multi-track animation using Deforum's own native schedules: 6 params oscillating on DIFFERENT periods so they drift in/out of phase (not lockstep), plus Looper swapping the guide image every 600 frames.",
   "settings": {
      "strength_schedule": "0: (0.55 + 0.06*sin(2*3.14*t/1200))",
      "noise_schedule": "0: (0.003 + 0.0015*sin(2*3.14*t/900 + 1.0))",
      "noise_multiplier_schedule": "0: (1.0 + 0.15*sin(2*3.14*t/1500 + 0.4))",
      "cfg_scale_schedule": "0: (7.5 + 1.0*sin(2*3.14*t/1800 + 0.8))",
      "contrast_schedule": "0: (1.0 + 0.08*sin(2*3.14*t/2400 + 0.2))",
      "antiblur_amount_schedule": "0: (0.02 + 0.02*sin(2*3.14*t/2000 + 1.2))",
      "use_looper": True,
      "image_strength_schedule": "0: (0.65)", "blendFactorMax": "0: (0.35)",
      "blendFactorSlope": "0: (0.25)", "tweening_frames_schedule": "0: (20)",
      "color_correction_factor": "0: (0.15 + 0.1*sin(2*3.14*t/1200))",
      "diffusion_cadence": 6}},

  {"name": "6 - Pure Axis Dolly (horizontal)",
   "use": "Clean single-axis travel through the world - only sideways motion plus a slow pitch tip. Nothing else moves. Swap translation_x for _y to get the vertical version, or use only _z for a slow push/pull.",
   "settings": {
      "fov_schedule": "0: (45-25*cos(2*3.14*t/1800))",
      "translation_x": "0: (1.3+0.5*sin(2*3.14*t/2100))",
      "translation_y": "0: (0)", "translation_z": "0: (0)",
      "rotation_3d_x": "0: (0.08*sin(2*3.14*t/1500))",
      "rotation_3d_y": "0: (0)", "rotation_3d_z": "0: (0)",
      "diffusion_cadence": 6, "strength_schedule": "0: (0.48)",
      "noise_schedule": "0: (0.012)"}},

  {"name": "7 - Laffoley Time Machine (LAB + Looper)",
   "use": "Palette-locked abstract/psychedelic morphing. LAB pins the colour scheme to frame 1 so it never drifts across thousands of frames; Looper anchors the morph. Trade-off: one colour mood for the whole render.",
   "settings": {
      "color_coherence": "LAB", "use_looper": True,
      "looper_imageStrength_schedule": "0:(0.75), 60:(0.5)",
      "image_strength_schedule": "0: (0.75)",
      "strength_schedule": "0: (0.55)", "noise_schedule": "0: (0.005)",
      "diffusion_cadence": 6, "sampling_mode": "bicubic"}},

  {"name": "8 - Jungle Bioluminescent (DIS Fine)",
   "use": "Smooth AND colour-varied. Optical flow carries consistency instead of a locked palette, so prompts can fully shift colour/mood per scene. Best for photoreal / nature / evolving-story renders.",
   "settings": {
      "color_coherence": "None",
      "optical_flow_cadence": "DIS Fine", "optical_flow_redo_generation": "DIS Fine",
      "cadence_flow_factor_schedule": "0: (1.0)", "redo_flow_factor_schedule": "0: (1.0)",
      "noise_schedule": "0: (0.003)", "strength_schedule": "0: (0.55)",
      "diffusion_cadence": 6, "midas_weight": 0.4,
      "near_schedule": "0: (200)", "sampling_mode": "bicubic"}},
]

EXTRA_CSS = r"""
/* ============ real tabs - ONE source of truth for which page is visible ============
   Replaces two earlier collapsible-panel systems (an outer show/hide wrapper toggled by a
   panelbar button, and an inner open/closed accordion toggled by the panel's own header) that
   were left stacked on top of each other and could desync: clicking the two independent
   controls could land the panel in a state where the outer wrapper was hidden while the inner
   content reported open, so clicks stopped visibly doing anything. Repro'd live: 8+8 alternating
   clicks -> outer .show=false, inner .open=true, panel invisible despite "open" state - the
   frantic re-clicking that produces was mistaken for the page hanging. Fixed by deleting both
   old systems and using exactly one [hidden] attribute per tab page, nothing else. */
.tabbar{display:flex;gap:6px;align-items:center;margin:0 16px 12px;max-width:calc(100vw - 36px);
  border-bottom:1px solid var(--line);padding-bottom:0}
.tabbtn{background:transparent;border:1px solid transparent;border-bottom:none;color:var(--ink-3);
  font-size:13px;font-weight:600;padding:8px 16px;border-radius:8px 8px 0 0;cursor:pointer;
  position:relative;top:1px}
.tabbtn:hover{color:var(--ink-2)}
.tabbtn.active{color:var(--ink);background:var(--surface);border-color:var(--line);
  border-bottom:1px solid var(--surface)}
.tabbtn .tabcount{color:var(--ink-3);font-family:var(--mono);font-size:11px;margin-left:5px}
.tabpage[hidden]{display:none}
/* drop zone is a persistent, always-visible BOX (Brian: "it needs a box") - not hidden until
   a drag starts. It gains an active-drag highlight but is never invisible. */
.dropzone{margin:0 16px 16px;padding:22px 18px;border:2px dashed var(--line-2);border-radius:var(--r);
  color:var(--ink-3);font-size:13px;text-align:center;line-height:1.6;transition:all .15s var(--ease);
  max-width:calc(100vw - 36px)}
.dropzone b{color:var(--ink-2)}
.dropzone.drag{border-color:var(--accent);border-style:solid;background:oklch(0.24 0.05 240 / 0.25);color:var(--ink)}
.dzbtn{background:var(--surface-2);border:1px solid var(--line-2);color:var(--ink-2);border-radius:var(--r-sm);
  padding:5px 14px;font-size:12.5px;cursor:pointer;margin:0 3px}
.dzbtn:hover{color:var(--ink);border-color:var(--accent)}
.dzlib{margin-top:9px;font-family:var(--mono);font-size:11.5px;color:var(--ink-3)}
.dzlib b{color:var(--ink-2);font-weight:600}
/* folders bar - the selectable paths, at the very top of the Gallery tab */
.dirbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 16px 12px;
  background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:10px 14px;max-width:calc(100vw - 36px)}
.dirbar .dbt{font-size:12px;font-weight:650;color:var(--ink);letter-spacing:.02em}
.dirbar label{display:flex;align-items:center;gap:6px;font-size:11.5px;color:var(--ink-3);white-space:nowrap}
.dirbar input{background:var(--bg);border:1px solid var(--line);border-radius:var(--r-sm);
  color:var(--ink-2);font-family:var(--mono);font-size:11.5px;padding:5px 8px;width:230px}
.dirbar input:focus{outline:2px solid var(--accent);outline-offset:1px}
.dirstatus{font-size:11.5px;color:var(--ink-3);font-family:var(--mono)}
.dirstatus.err{color:var(--warn)}
/* top row: just the view/compare drop zone (input-folder settings live in the Deforum panel now) */
.dzrow{display:flex;gap:10px;align-items:stretch;margin:0 16px 14px;max-width:calc(100vw - 36px)}
.dzrow .dropzone{margin:0;flex:1;max-width:none}
.fstat{font-family:var(--mono);font-size:11px;color:var(--ink-3)}
.fstat.ok{color:var(--good)} .fstat.err{color:var(--warn)}
/* server-side folder browser popup */
.fb-ov{position:fixed;inset:0;z-index:40;background:oklch(0.1 0.01 265 / 0.6);display:flex;
  align-items:center;justify-content:center}
.fb-ov[hidden]{display:none}
.fb-panel{width:560px;max-width:92vw;max-height:78vh;background:var(--surface);border:1px solid var(--line-2);
  border-radius:var(--r);display:flex;flex-direction:column;overflow:hidden}
.fb-head{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line)}
.fb-head span{font-family:var(--mono);font-size:12px;color:var(--ink);flex:1;word-break:break-all}
.fb-list{overflow:auto;flex:1;padding:6px 8px}
.fb-list .fb-item{display:block;width:100%;text-align:left;background:transparent;border:0;
  color:var(--ink-2);font-family:var(--mono);font-size:12.5px;padding:6px 9px;border-radius:var(--r-sm);cursor:pointer}
.fb-list .fb-item:hover{background:var(--surface-2);color:var(--ink)}
.fb-foot{display:flex;gap:10px;align-items:center;padding:10px 14px;border-top:1px solid var(--line)}
/* ---- view modes: one giant row (default) / definable grid / full-width rows ---- */
body.gridmode .grid{display:grid;grid-template-columns:repeat(var(--gcols,4),minmax(0,1fr));gap:14px;min-width:0}
body.gridmode .grid>.card{width:auto;flex:none}
body.listrows .grid{display:block;min-width:0}
body.listrows .grid>.card{display:grid;width:auto;flex:none;margin-bottom:14px;
  grid-template-columns:minmax(280px,360px) minmax(300px,400px) minmax(240px,1fr) minmax(340px,1.7fr);
  gap:4px 18px}
body.listrows .grid>.card .chead{grid-column:1;grid-row:1}
body.listrows .grid>.card .vidbox{grid-column:1;grid-row:2/7}
body.listrows .grid>.card .live{grid-column:2;grid-row:1/7}
body.listrows .grid>.card .exp{grid-column:3;grid-row:1;margin-top:0}
body.listrows .grid>.card .lorachips{grid-column:3;grid-row:2}
body.listrows .grid>.card .cmts{grid-column:3;grid-row:3}
body.listrows .grid>.card .setfill{grid-column:4;grid-row:1/7;column-count:2;column-gap:26px}
@media (min-width:2400px){body.listrows .grid>.card .setfill{column-count:3}}
/* Best Practices as a readable document, not a text dump */
.bpdoc{max-width:100ch}
.bptitle{font-size:16.5px;font-weight:650;color:var(--ink);margin:0 0 3px}
.bpsub{color:var(--ink-3);font-size:12.5px;margin:0}
.bpintro{margin-bottom:16px}
.bpsec{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:13px 18px;margin:0 0 12px}
.bpsec h2{margin:0 0 9px;font-size:11.5px;letter-spacing:.08em;color:var(--accent);
  text-transform:uppercase;font-family:var(--mono);font-weight:650}
.bpsec ul{margin:0;padding-left:20px}
.bpsec li{font-size:13.5px;line-height:1.7;color:var(--ink-2);margin:5px 0;max-width:95ch}
.bpsec li::marker{color:var(--accent)}
.bpsec p{font-size:13.5px;line-height:1.65;color:var(--ink-2);margin:6px 0;max-width:95ch}
.bpedithint{color:var(--ink-3);font-size:11.5px;margin-top:7px;font-family:var(--mono)}
.comparewrap{display:none;margin:0 16px 20px;padding:14px;background:#12121a;border:1px solid #2a2a38;border-radius:10px}
.cwhead{display:flex;align-items:center;gap:14px;margin-bottom:10px;flex-wrap:wrap}
.cwhead h2{margin:0;font-size:15px;color:#eaeaf2}
.cwhead label{font-size:13px;color:#cdd}
.cwhead button{background:#3a1e1e;color:#ffb0b0;border:1px solid #5a2a2a;border-radius:6px;padding:5px 12px;cursor:pointer;font-size:12px}
.comparerow{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.comparerow .card{width:calc(50% - 8px);min-width:380px;flex:1 1 420px}
.dropcard{position:relative}
.rmbtn{position:absolute;top:10px;right:10px;z-index:2;background:#2a2a3a;color:#cdd;border:1px solid #363648;border-radius:5px;padding:3px 9px;cursor:pointer;font-size:11px}
.savepreset{position:absolute;top:10px;right:74px;z-index:2;background:#12301c;color:#8fff af;border:1px solid #2a5a38;border-radius:5px;padding:3px 9px;cursor:pointer;font-size:11px}
.presetnote{color:#7a9;font-size:12.5px;margin:0 16px 12px;line-height:1.5;max-width:90ch}
.pgrid{display:flex;flex-wrap:wrap;gap:12px;margin:0 16px}
.pcard{background:#181820;border:1px solid #2a2a38;border-radius:8px;padding:11px;width:340px;display:flex;flex-direction:column}
.pcard.custom{border-color:#2a5a38}
.pcard h3{margin:0 0 5px;font-size:13px;color:#ffcf80;font-family:monospace}
.pcard .puse{color:#aab;font-size:12px;line-height:1.45;margin-bottom:8px}
.pcard .prows{background:#0c1622;border:1px solid #1d3350;border-radius:5px;padding:7px 8px;margin-bottom:9px;max-height:150px;overflow:auto}
.prow{display:flex;justify-content:space-between;gap:8px;font-family:monospace;font-size:11px;padding:1px 0}
.prow .pk{color:#5cc0ff;white-space:nowrap}
.prow .pv{color:#e0e0e8;text-align:right;word-break:break-all}
.pbtns{display:flex;gap:6px;flex-wrap:wrap;margin-top:auto}
.pbtns button{background:#2a2a3a;color:#cdd;border:1px solid #363648;border-radius:5px;padding:5px 9px;cursor:pointer;font-size:11px}
.pbtns button.primary{background:#123049;color:#bfe0ff;border-color:#1d4a70}
.pbtns button.danger{background:#3a1e1e;color:#ffb0b0;border-color:#5a2a2a}
.pnote{color:#7a9;font-size:12px;margin:0 16px 12px;line-height:1.5;max-width:90ch}
"""

# Split so the (later-defined) video cards can be injected INSIDE the gallery tabpage - the whole
# point of real tabs is that switching away actually excludes the 44k-node grid from layout via
# [hidden], which only works if the grid lives inside the tabpage element.
EXTRA_HTML_HEAD = """<div class="tabbar" role="tablist">
  <button class="tabbtn active" data-tab="gallery" role="tab" aria-selected="true">Gallery</button>
  <button class="tabbtn" data-tab="practices" role="tab" aria-selected="false">Best Practices</button>
  <button class="tabbtn" data-tab="presets" role="tab" aria-selected="false">Presets</button>
  <button class="tabbtn" data-tab="saved" role="tab" aria-selected="false">Saved <span class="tabcount" id="savedcount"></span></button>
</div>

<div class="tabpage" id="tabpage-gallery" data-tabpage="gallery">
  <div class="dirbar" id="dirbar" hidden>
    <span class="dbt">Renders / output folder</span>
    <input type="text" id="dir-renders" spellcheck="false"
      title="The gallery lists every render in this folder (live - Rescan re-reads it). To change where Deforum WRITES renders: WebUI Settings > Paths for saving > 'Output directory for img2img images'.">
    <button type="button" class="dzbtn fbrowse" data-for="dir-renders">Browse&hellip;</button>
    <button type="button" class="dzbtn" id="dirsave">Save</button>
    <button type="button" class="dzbtn" id="dirrescan">Rescan</button>
    <span class="dirstatus" id="dirstatus"></span>
  </div>
  <div class="dzrow">
    <div class="dropzone dz-view" id="dropzone">
      <b>View &amp; compare renders</b><br>
      Drag a rendered .mp4 + its _settings.txt (or a whole folder) here &mdash; or
      <button type="button" class="dzbtn" id="browsefiles">Browse files&hellip;</button>
      <button type="button" class="dzbtn" id="browsedir">Browse folder&hellip;</button>
      <div class="dzlib" id="dzlib">__LIBLINE__</div>
      <input type="file" id="pickfiles" multiple accept=".mp4,.txt,.json" hidden>
      <input type="file" id="pickdir" webkitdirectory hidden>
    </div>
  </div>
  <div class="fb-ov" id="fb-ov" hidden>
    <div class="fb-panel">
      <div class="fb-head"><span id="fb-path">Drives</span><button type="button" class="dzbtn" id="fb-close">&times;</button></div>
      <div class="fb-list" id="fb-list"></div>
      <div class="fb-foot"><button type="button" class="dzbtn" id="fb-use">Use this folder</button><span class="fstat" id="fb-stat"></span></div>
    </div>
  </div>
  <div class="comparewrap" id="comparewrap"></div>"""

EXTRA_HTML_TAIL = """</div>

<div class="tabpage" id="tabpage-practices" data-tabpage="practices" hidden>
  <div class="pnote">The lab notes &mdash; what makes renders good, what wrecks them. Editable; saves to the project folder.</div>
  <div id="bpbody" style="margin:0 16px"></div>
</div>

<div class="tabpage" id="tabpage-presets" data-tabpage="presets" hidden>
  <div id="presetbody"></div>
</div>

<div class="tabpage" id="tabpage-saved" data-tabpage="saved" hidden>
  <div id="savedbody"></div>
</div>

<div class="cbar" id="cbar">
  <span class="cnt" id="cbar-count"></span>
  <button id="cbar-go">Compare selected</button>
  <button class="ghost" id="cbar-clear">clear selection</button>
  <span class="cnt" style="opacity:.55">tick "compare" on the renders you want, like picking TVs at Best Buy</span>
</div>
<div class="cmp-overlay" id="cmp-overlay">
  <div class="cmp-head">
    <h2>Compare</h2>
    <label><input type="checkbox" id="cmp-diffsonly"> differences only</label>
    <label><input type="checkbox" id="cmp-sync" checked> sync playback</label>
    <button class="x" id="cmp-close">close &times;</button>
  </div>
  <div class="cmp-scroll" id="cmp-scroll"></div>
</div>"""

EXTRA_JS = r"""
var CAM_JS=[["FOV","fov_schedule"],["Zoom Z","translation_z"],["Pan X","translation_x"],["Pan Y","translation_y"],["Rot X","rotation_3d_x"],["Rot Y","rotation_3d_y"],["Rot Z","rotation_3d_z"]];
var SET_ROWS_JS=[["Checkpoint","sd_model_name"],["Frames","max_frames"],["Cadence","diffusion_cadence"],["Steps","steps"],["CFG","cfg_scale_schedule"],["Strength","strength_schedule"],["Noise","noise_schedule"],["Midas","midas_weight"],["Color coherence","color_coherence"],["FOV schedule","fov_schedule"],["Speed Z","translation_z"],["Init image","init_image"]];

function firstExprJS(sched){
  var s=String(sched==null?'':sched); var i=s.indexOf('('), j=s.lastIndexOf(')');
  return (i!==-1 && j!==-1 && j>i) ? s.slice(i+1,j).trim() : '0';
}

// Hand-rolled recursive-descent parser/evaluator for the tiny math-schedule language
// (numbers, t, + - * /, parens, sin/cos/tan/sqrt/abs). No eval / no Function() - dropped
// settings files are the least-trusted input on this page, so their expressions are
// walked as data instead of being turned into executable code.
function tokenizeExpr(s){
  var toks=[]; var i=0; var n=s.length;
  while(i<n){
    var c=s[i];
    if(/\s/.test(c)){ i++; continue; }
    if(/[0-9.]/.test(c)){ var j=i; while(j<n && /[0-9.]/.test(s[j])) j++; toks.push({t:'num', v:parseFloat(s.slice(i,j))}); i=j; continue; }
    if(/[a-zA-Z_]/.test(c)){ var j=i; while(j<n && /[a-zA-Z_0-9]/.test(s[j])) j++; toks.push({t:'id', v:s.slice(i,j)}); i=j; continue; }
    if('+-*/(),'.indexOf(c)!==-1){ toks.push({t:c}); i++; continue; }
    i++;
  }
  return toks;
}
function compileExpr(exprString){
  var toks;
  try{ toks=tokenizeExpr(String(exprString==null?'0':exprString)); }catch(e){ return function(){return NaN;}; }
  var pos=0;
  function peek(){ return toks[pos]; }
  function adv(){ return toks[pos++]; }
  function pExpr(){
    var node=pTerm();
    while(peek() && (peek().t==='+'||peek().t==='-')){
      var op=adv().t; var rhs=pTerm();
      node=(function(a,op,b){ return function(t){ return op==='+' ? a(t)+b(t) : a(t)-b(t); }; })(node,op,rhs);
    }
    return node;
  }
  function pTerm(){
    var node=pUnary();
    while(peek() && (peek().t==='*'||peek().t==='/')){
      var op=adv().t; var rhs=pUnary();
      node=(function(a,op,b){ return function(t){ return op==='*' ? a(t)*b(t) : a(t)/b(t); }; })(node,op,rhs);
    }
    return node;
  }
  function pUnary(){
    if(peek() && peek().t==='-'){ adv(); var n=pUnary(); return (function(n){ return function(t){ return -n(t); }; })(n); }
    if(peek() && peek().t==='+'){ adv(); return pUnary(); }
    return pPrimary();
  }
  function pPrimary(){
    var tok=peek();
    if(!tok) return function(){ return 0; };
    if(tok.t==='num'){ adv(); var v=tok.v; return function(){ return v; }; }
    if(tok.t==='('){ adv(); var n=pExpr(); if(peek()&&peek().t===')') adv(); return n; }
    if(tok.t==='id'){
      adv(); var name=tok.v;
      if(peek() && peek().t==='('){
        adv(); var arg=pExpr(); if(peek()&&peek().t===')') adv();
        var fn={sin:Math.sin,cos:Math.cos,tan:Math.tan,sqrt:Math.sqrt,abs:Math.abs}[name];
        if(fn) return (function(fn,arg){ return function(t){ return fn(arg(t)); }; })(fn,arg);
        return function(){ return NaN; };
      }
      if(name==='t') return function(t){ return t; };
      return function(){ return 0; };
    }
    adv();
    return function(){ return 0; };
  }
  var built=pExpr();
  return function(t){ try{ var r=built(t); return (typeof r==='number' && isFinite(r)) ? r : NaN; }catch(e){ return NaN; } };
}

function splitPromptJS(text){
  text = text||'';
  var loras=[];
  var reLora=/<lora:([^:>]+):([\d.]+)>/g;
  Array.from(text.matchAll(reLora)).forEach(function(m){ if(m[1]!=='add-detail-xl') loras.push(m[1]); });
  var scene = text.replace(/<lora:[^>]+>/g,''); scene = scene.split('--neg')[0];
  scene = scene.replace(/\s+/g,' ').trim();
  return [scene, loras];
}
function parseSchedJS(s){
  var str=String(s==null?'':s);
  var reSched=/(\d+)\s*:\s*\(?\s*([\d.]+)/g;
  var out=Array.from(str.matchAll(reSched)).map(function(m){ return [parseInt(m[1]),parseFloat(m[2])]; });
  return out.length?out:[[0,0.0]];
}
function ssetJS(d,key){
  var v=(d[key]!==undefined && d[key]!==null)?d[key]:'-';
  if(key==='init_image'){ var s=String(v||''); var parts=s.split(/[\\/]/); return parts[parts.length-1]||'-'; }
  var vs=String(v);
  if((key.indexOf('schedule')!==-1 || key==='translation_z') && vs.indexOf('(')!==-1) return String(firstExprJS(v));
  return vs;
}
function experimentJS(d){
  var p=[];
  var ck=String(d.sd_model_name||'').replace('.safetensors','');
  if(ck.indexOf('MOHAWK')!==-1)p.push('MOHAWK');
  else if(ck.indexOf('CyberRealistic')!==-1)p.push('CyberRealisticXL');
  else if(ck.indexOf('RealVis')!==-1)p.push('RealVis');
  else p.push(ck.slice(0,12)||'?');
  var fs=String(d.fov_schedule||'');
  var m=fs.match(/([\d.]+)\s*-\s*([\d.]+)\s*\*\s*cos/);
  if(m){
    var mid=parseFloat(m[1]), amp=parseFloat(m[2]);
    var per=fs.match(/t\/(\d+)\)/);
    var secs=per?(', '+Math.round(parseInt(per[1])/30)+'s cycle'):'';
    p.push('FOV sweep '+Math.round(mid-amp)+'-'+Math.round(mid+amp)+secs);
  } else {
    var mm=fs.match(/\(\s*([\d.]+)\s*\)/);
    p.push(mm?('FOV '+mm[1]):'no FOV anim');
  }
  var tz=String(d.translation_z||''), rz=String(d.rotation_3d_z||'');
  if(tz.indexOf('cos')!==-1 && (tz.replace(/\s/g,'')+rz.replace(/\s/g,'')).indexOf('0.5-0.5*cos')!==-1) p.push('FOV-coupled camera');
  else if(tz.indexOf('cos')!==-1 && rz.indexOf('sin')!==-1) p.push('FOV-coupled speed');
  else if(rz.indexOf('sin')!==-1 && rz.indexOf('+')!==-1) p.push('roller-coaster cam');
  else if(String(d.translation_x||'').indexOf('sin')!==-1) p.push('smooth sine cam');
  var cad=d.diffusion_cadence;
  if(cad!==8 && cad!==undefined && cad!==null) p.push('cadence '+cad);
  var stv=firstExprJS(d.strength_schedule);
  var svm=String(stv).match(/[\d.]+/);
  if(svm){ var sv=parseFloat(svm[0]); if(Math.abs(sv-0.7)>0.03) p.push('strength '+sv); }
  var PARSEQ_FIELDS=["strength_schedule","noise_schedule","noise_multiplier_schedule","cfg_scale_schedule","contrast_schedule","antiblur_amount_schedule"];
  var animated=PARSEQ_FIELDS.filter(function(k){ var v=String(d[k]||''); return v.indexOf('sin')!==-1||v.indexOf('cos')!==-1; });
  if(animated.length>=3) p.push('Parseq-style ('+animated.length+' params animated)');
  if(d.use_looper){
    try{ var nLoop=Object.keys(JSON.parse(d.init_images||'{}')).length; if(nLoop>1) p.push('Looper: '+nLoop+' guide-image swaps'); }
    catch(e){ p.push('Looper enabled'); }
  }
  var DOMAINS={
    "ocean/reef":["coral","reef","fish","ocean","underwater","squid","octopus","jellyfish","wave","sea ","whale"],
    "ice/aurora":["aurora","glacier","ice","frost","snow","frozen","icicle"],
    "space":["galaxy","nebula","supernova","cosmic","star","milky way","void"],
    "flowers":["flower","rose","petal","lotus","tulip","lavender","sunflower","blossom","pistil"],
    "waterfall":["waterfall","rainbow"],
    "desert":["canyon","desert","dune","sandstone","mesa"],
    "volcanic":["lava","volcanic","obsidian","molten","ember"],
    "butterfly":["butterfly","butterflies","hummingbird"],
    "forest/trees":["tree","forest","autumn","bamboo","cherry","eucalyptus","canopy","leaves"],
    "crystal":["crystal","cavern","gem","quartz","amethyst"],
    "jungle":["jungle","mushroom","fern","fungus","mycelium","moss"],
    "macabre":["skeleton","bone","skull","eyeball","fractal eye","rose vine"],
    "body/fungal-horror":["skin","muscle","vein","sinew","hair","flesh","mold"],
    "mountain/lake":["mountain","alpine","koi","lake","mist"],
    "storm/sky":["storm","cloud","god ray","twilight"]
  };
  var prompts=d.prompts||{};
  var tally={};
  Object.keys(prompts).forEach(function(k){
    var v=String(prompts[k]||'');
    var head=v.split(',')[0].toLowerCase().slice(0,45);
    var matched=false;
    for(var dom in DOMAINS){
      if(DOMAINS[dom].some(function(kw){return head.indexOf(kw)!==-1;})){ tally[dom]=(tally[dom]||0)+1; matched=true; break; }
    }
    if(!matched) tally['other']=(tally['other']||0)+1;
  });
  var keys=Object.keys(tally);
  if(keys.length){
    var total=0; keys.forEach(function(k){total+=tally[k];});
    var top=null, topn=0;
    keys.forEach(function(k){ if(tally[k]>topn){topn=tally[k];top=k;} });
    var ndom=keys.filter(function(k){return k!=='other'&&tally[k]>=2;}).length;
    if(top && topn/total>0.55 && top!=='other') p.push('single-theme: '+top+' (samey)');
    else if(ndom>=5) p.push('DIVERSE ('+ndom+' subject-domains)');
  }
  return p.join(' · ');
}

var dropped=[];
var dropSeq=0;

/* JS mirrors of the Python fullify/lora_counts so DROPPED renders get the same full column,
   uncommon-value marking, and compare support as library renders */
var SKIP_JS={prompts:1,animation_prompts_positive:1,animation_prompts_negative:1,positive_prompts:1,
 init_sample:1,image_path:1,outdir:1,init_image_box:1,deforum_git_commit_id:1,sd_model_hash:1,
 batch_name:1,resume_from_timestring:1,resume_timestring:1,override_settings_with_file:1,
 custom_settings_file:1,show_info_on_ui:1,motion_preview_mode:1};
function fullifyJS(d){
  var out={}, prio=[];
  SGROUPS.forEach(function(g){ prio=prio.concat(g[1]); });
  var cnOn=Object.keys(d).filter(function(k){ return k.indexOf('cn_')===0 && k.indexOf('enabled')!==-1 && d[k]; });
  prio.forEach(function(k){ if(k in d && !SKIP_JS[k]) out[k]=d[k]; });
  Object.keys(d).sort().forEach(function(k){
    if(k in out || SKIP_JS[k] || k.indexOf('cn_')===0) return;
    out[k]=d[k];
  });
  out['controlnet']=cnOn.length? cnOn.length+' unit(s) enabled':'off';
  ['init_image','video_init_path','video_mask_path','mask_file','soundtrack_path','color_coherence_image_path'].forEach(function(k){
    if(out[k]){ var s=String(out[k]).split(/[\\/]/); out[k]=s[s.length-1]; }
  });
  if(out['init_images']) out['init_images']=String(out['init_images']).slice(0,300);
  for(var k in out){ if(out[k]===null||out[k]===undefined) out[k]=''; }
  return out;
}
function loraCountsJS(d){
  var t={}, prompts=d.prompts||{};
  Object.keys(prompts).forEach(function(k){
    Array.from(String(prompts[k]).matchAll(/<lora:([^:>]+):([\d.]+)>/g)).forEach(function(m){
      var key=m[1]+' @'+m[2]; t[key]=(t[key]||0)+1;
    });
  });
  return t;
}

function registerDataJS(pid,d){
  if(!d){ DATA[pid]={fps:30,kf:[],cam:{},camlabels:[],name:pid,full:{},loras:{}}; camFns[pid]={}; return; }
  var prompts=d.prompts||{};
  var ks=Object.keys(prompts).sort(function(a,b){return (parseInt(a)||0)-(parseInt(b)||0);});
  var kf=ks.map(function(k){ var sp=splitPromptJS(prompts[k]); return [parseInt(k)||0, sp[0], sp[1]]; });
  var cam={};
  CAM_JS.forEach(function(pair){
    var lab=pair[0], key=pair[1];
    var ex=firstExprJS(d[key]);
    cam[lab]={js:ex, anim: ex.indexOf('t')!==-1};
  });
  DATA[pid]={fps:d.fps||30, kf:kf, cam:cam, camlabels:CAM_JS.map(function(p){return p[0];}),
    strength:parseSchedJS(d.strength_schedule), noise:parseSchedJS(d.noise_schedule),
    name:pid, full:fullifyJS(d), loras:loraCountsJS(d)};
  camFns[pid]={};
  for(var lab in cam){ camFns[pid][lab]=compileExpr(cam[lab].js); }
}

function getAllFileEntries(dataTransferItemList){
  return new Promise(function(resolve){
    var items=[];
    for(var i=0;i<dataTransferItemList.length;i++){
      var it=dataTransferItemList[i];
      var entry = it.webkitGetAsEntry ? it.webkitGetAsEntry() : null;
      if(entry) items.push(entry);
    }
    var entries=[];
    var pending=items.length;
    if(!pending){ resolve([]); return; }
    items.forEach(function(entry){ readEntry(entry, done); });
    function done(){ pending--; if(pending<=0) resolve(entries); }
    function readEntry(entry, cb){
      if(entry.isFile){
        entry.file(function(file){ entries.push(file); cb(); }, cb);
      } else if(entry.isDirectory){
        var reader=entry.createReader();
        var all=[];
        (function readBatch(){
          reader.readEntries(function(results){
            if(!results.length){
              var sub=all.length;
              if(!sub){ cb(); return; }
              all.forEach(function(e2){ readEntry(e2, function(){ sub--; if(sub<=0) cb(); }); });
            } else { all=all.concat(results); readBatch(); }
          }, cb);
        })();
      } else { cb(); }
    }
  });
}

async function handleDropFiles(files){
  var videos=files.filter(function(f){return /\.mp4$/i.test(f.name);});
  var texts=files.filter(function(f){return /\.(txt|json)$/i.test(f.name);});
  if(!videos.length){ alert("No .mp4 video found in what you dropped. Drop a rendered video (optionally with its _settings.txt), or a folder containing one."); return; }
  if(videos.length>12){
    if(!confirm("Found "+videos.length+" videos in that drop - load the first 12?")) return;
    videos=videos.slice(0,12);
  }
  for(var vi=0; vi<videos.length; vi++){
    var vf=videos[vi];
    var match=null;
    var tsMatch=vf.name.match(/(\d{10,14})/);
    if(tsMatch){ match = texts.find(function(t){return t.name.indexOf(tsMatch[1])!==-1;}); }
    if(!match && videos.length===1 && texts.length===1) match=texts[0];
    if(!match){
      var base=vf.name.replace(/\.mp4$/i,'');
      match = texts.find(function(t){return t.name.replace(/_settings\.(txt|json)$/i,'')===base;});
    }
    var settingsObj=null;
    if(match){
      try{ settingsObj = JSON.parse(await match.text()); }catch(e){ settingsObj=null; }
    }
    var pid='drop'+(dropSeq++);
    var url=URL.createObjectURL(vf);
    dropped.push({pid:pid, name:vf.name.replace(/\.mp4$/i,''), url:url, settingsObj:settingsObj});
    registerDataJS(pid, settingsObj);
    DATA[pid].name=vf.name.replace(/\.mp4$/i,'');
  }
  renderCompare();
  renderPresets();   // a loaded render unlocks "download MERGED settings.txt"
}

// All card/panel DOM built via createElement + textContent (never innerHTML) - dropped
// settings.txt files are the least-trusted input on this page.
function clearEl(el){ while(el.firstChild) el.removeChild(el.firstChild); }

function buildDropCardEl(item){
  var d=item.settingsObj;
  var card=document.createElement('div'); card.className='card dropcard';

  var rm=document.createElement('button'); rm.className='rmbtn'; rm.textContent='remove';
  rm.addEventListener('click', function(){ removeDropped(item.pid); });
  card.appendChild(rm);

  if(d){
    var sp=document.createElement('button'); sp.className='savepreset'; sp.textContent='save as preset';
    sp.title='Capture this render\'s settings as a reusable preset (stored in this browser).';
    sp.addEventListener('click', function(){ saveRenderAsPreset(item.pid); });
    card.appendChild(sp);
  }

  var cl=document.createElement('label'); cl.className='cmp';
  var cc=document.createElement('input'); cc.type='checkbox'; cc.className='cmp-check'; cc.dataset.pid=item.pid;
  cl.appendChild(cc); cl.appendChild(document.createTextNode(' compare'));
  card.appendChild(cl);

  var fn=document.createElement('div'); fn.className='fn'; fn.textContent=item.name;
  card.appendChild(fn);

  var fd=document.createElement('div'); fd.className='fd';
  fd.textContent='dropped '+(d?'· settings loaded':'· NO settings found');
  card.appendChild(fd);

  var exp=document.createElement('div'); exp.className='exp';
  exp.textContent='EXPERIMENT: '+(d?experimentJS(d):'no settings.txt (dropped without a matching pair)');
  card.appendChild(exp);

  var vidbox=document.createElement('div'); vidbox.className='vidbox';
  var vid=document.createElement('video'); vid.id=item.pid; vid.dataset.pid=item.pid;
  vid.controls=true; vid.preload='metadata'; vid.playsInline=true; vid.src=item.url;
  vidbox.appendChild(vid); card.appendChild(vidbox);

  var live=document.createElement('div'); live.className='live'; live.id='live-'+item.pid;
  var hint=document.createElement('div'); hint.className='lrow hint';
  hint.textContent='press play — live prompt / LoRAs / camera appear here';
  live.appendChild(hint); card.appendChild(live);

  // same full column + lora chips as library cards - filled by renderColumn after mount
  var lchips=document.createElement('div'); lchips.className='lorachips'; lchips.dataset.pid=item.pid;
  card.appendChild(lchips);
  var fill=document.createElement('div'); fill.className='setfill'; fill.dataset.pid=item.pid;
  card.appendChild(fill);
  return card;
}

function renderCompare(){
  var wrap=document.getElementById('comparewrap');
  clearEl(wrap);
  if(!dropped.length){ wrap.style.display='none'; return; }
  wrap.style.display='block';

  var head=document.createElement('div'); head.className='cwhead';
  var h2=document.createElement('h2'); h2.textContent='Dropped'+(dropped.length>=2?' · Compare Mode':'');
  head.appendChild(h2);
  if(dropped.length>=2){
    var lbl=document.createElement('label');
    var chk=document.createElement('input'); chk.type='checkbox'; chk.id='synclink'; chk.checked=true;
    lbl.appendChild(chk); lbl.appendChild(document.createTextNode(' sync playback'));
    head.appendChild(lbl);
  }
  var clearBtn=document.createElement('button'); clearBtn.textContent='clear dropped';
  clearBtn.addEventListener('click', clearDropped);
  head.appendChild(clearBtn);
  wrap.appendChild(head);

  var row=document.createElement('div'); row.className = dropped.length>=2 ? 'comparerow' : 'grid';
  dropped.forEach(function(item){ row.appendChild(buildDropCardEl(item)); });
  wrap.appendChild(row);

  dropped.forEach(function(item){
    var v=document.getElementById(item.pid);
    if(!v) return;
    ['timeupdate','seeked'].forEach(function(e){ v.addEventListener(e,function(){ upd(v); syncFrom(v); }); });
    v.addEventListener('play',function(){ upd(v); syncPlay(v,true); });
    v.addEventListener('pause',function(){ syncPlay(v,false); });
  });
  if(typeof buildFreq==='function'){ buildFreq(); dropped.forEach(function(item){ renderColumn(item.pid); }); attachChecks(wrap); }
}

var syncing=false;
function syncFrom(v){
  var chk=document.getElementById('synclink');
  if(!chk || !chk.checked || dropped.length<2 || syncing) return;
  syncing=true;
  var frac = v.duration? v.currentTime/v.duration : 0;
  dropped.forEach(function(item){
    if(item.pid===v.dataset.pid) return;
    var ov=document.getElementById(item.pid);
    if(ov && ov.duration){ var target=frac*ov.duration; if(Math.abs(ov.currentTime-target)>0.15) ov.currentTime=target; }
  });
  syncing=false;
}
function syncPlay(v,playing){
  var chk=document.getElementById('synclink');
  if(!chk || !chk.checked || dropped.length<2) return;
  dropped.forEach(function(item){
    if(item.pid===v.dataset.pid) return;
    var ov=document.getElementById(item.pid);
    if(!ov) return;
    if(playing && ov.paused) ov.play().catch(function(){});
    if(!playing && !ov.paused) ov.pause();
  });
}
function removeDropped(pid){
  dropped=dropped.filter(function(item){
    if(item.pid===pid){ URL.revokeObjectURL(item.url); delete DATA[pid]; delete camFns[pid]; return false; }
    return true;
  });
  if(typeof selOrder!=='undefined'){ selOrder=selOrder.filter(function(p){ return p!==pid; }); selUpdate(); }
  renderCompare(); renderPresets();
}
function clearDropped(){
  dropped.forEach(function(item){
    URL.revokeObjectURL(item.url); delete DATA[item.pid]; delete camFns[item.pid];
    if(typeof selOrder!=='undefined') selOrder=selOrder.filter(function(p){ return p!==item.pid; });
  });
  dropped=[];
  if(typeof selUpdate==='function') selUpdate();
  renderCompare(); renderPresets();
}

// ============================== PRESETS ==============================
// BUILTIN_PRESETS is injected from Python. Custom presets persist in localStorage so a preset you
// save from a good render survives page reloads. Everything stays local - nothing is uploaded.
var LS_KEY='deforum_viewer_custom_presets_v1';
// The fields that actually define a "look" - what gets captured when you save a render as a preset.
var PRESET_FIELDS=["sd_model_name","steps","cfg_scale","cfg_scale_schedule","sampler","scheduler",
 "strength_schedule","noise_schedule","noise_multiplier_schedule","diffusion_cadence",
 "optical_flow_cadence","optical_flow_redo_generation","cadence_flow_factor_schedule",
 "redo_flow_factor_schedule","color_coherence","contrast_schedule","antiblur_amount_schedule",
 "fov_schedule","near_schedule","translation_x","translation_y","translation_z",
 "rotation_3d_x","rotation_3d_y","rotation_3d_z","midas_weight","use_depth_warping","sampling_mode",
 "use_looper","image_strength_schedule","blendFactorMax","blendFactorSlope",
 "tweening_frames_schedule","color_correction_factor","W","H","fps","seed"];

function loadCustomPresets(){
  try{ var raw=localStorage.getItem(LS_KEY); return raw?JSON.parse(raw):[]; }catch(e){ return []; }
}
function saveCustomPresets(list){
  try{ localStorage.setItem(LS_KEY, JSON.stringify(list)); return true; }
  catch(e){ alert('Could not save preset: '+e.message); return false; }
}
function downloadJSON(obj, filename){
  var blob=new Blob([JSON.stringify(obj,null,4)],{type:'application/json'});
  var url=URL.createObjectURL(blob);
  var a=document.createElement('a'); a.href=url; a.download=filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
}
// Merge a preset OVER a dropped render's FULL settings -> a complete, Deforum-loadable settings.txt.
// Without a dropped render we can only emit the overlay itself (documented in the UI + README).
function presetDownload(p){
  var full=null;
  for(var i=0;i<dropped.length;i++){ if(dropped[i].settingsObj){ full=dropped[i].settingsObj; break; } }
  var safe=String(p.name).replace(/[^a-z0-9]+/gi,'_').replace(/^_|_$/g,'');
  if(full){
    var merged=JSON.parse(JSON.stringify(full));
    for(var k in p.settings) merged[k]=p.settings[k];
    downloadJSON(merged, safe+'_settings.txt');
  } else {
    downloadJSON(p.settings, safe+'_OVERLAY_settings.txt');
  }
}
function presetHasFullBase(){
  for(var i=0;i<dropped.length;i++){ if(dropped[i].settingsObj) return true; }
  return false;
}
function saveRenderAsPreset(pid){
  var item=null;
  for(var i=0;i<dropped.length;i++){ if(dropped[i].pid===pid){ item=dropped[i]; break; } }
  if(!item || !item.settingsObj){ alert('That render has no settings.txt, so there is nothing to save as a preset.'); return; }
  var name=prompt('Name this preset:', item.name);
  if(!name) return;
  var settings={};
  PRESET_FIELDS.forEach(function(k){
    if(item.settingsObj[k]!==undefined && item.settingsObj[k]!==null) settings[k]=item.settingsObj[k];
  });
  var list=loadCustomPresets();
  list.push({name:name, use:'Saved from '+item.name, settings:settings, custom:true});
  if(saveCustomPresets(list)){ renderPresets(); openPresets(); }
}
function deleteCustomPreset(idx){
  var list=loadCustomPresets();
  if(idx<0||idx>=list.length) return;
  if(!confirm('Delete preset "'+list[idx].name+'"?')) return;
  list.splice(idx,1); saveCustomPresets(list); renderPresets();
}
function buildPresetCard(p, customIdx){
  var card=document.createElement('div'); card.className='pcard'+(p.custom?' custom':'');
  var h=document.createElement('h3'); h.textContent=p.name; card.appendChild(h);
  var u=document.createElement('div'); u.className='puse'; u.textContent=p.use||''; card.appendChild(u);
  var rows=document.createElement('div'); rows.className='prows';
  Object.keys(p.settings).forEach(function(k){
    var r=document.createElement('div'); r.className='prow';
    var kk=document.createElement('span'); kk.className='pk'; kk.textContent=k;
    var vv=document.createElement('span'); vv.className='pv'; vv.textContent=String(p.settings[k]);
    r.appendChild(kk); r.appendChild(vv); rows.appendChild(r);
  });
  card.appendChild(rows);
  var btns=document.createElement('div'); btns.className='pbtns';
  var dl=document.createElement('button'); dl.className='primary';
  dl.textContent = presetHasFullBase() ? 'Download merged settings.txt' : 'Download overlay .txt';
  dl.title = presetHasFullBase()
    ? 'Merges this preset over your dropped render\'s full settings -> a complete file you can Load All Settings in Deforum.'
    : 'No render dropped yet, so this downloads just the preset fields. Drop a render first to get a complete, loadable settings.txt.';
  dl.addEventListener('click', function(){ presetDownload(p); });
  btns.appendChild(dl);
  var cp=document.createElement('button'); cp.textContent='Copy JSON';
  cp.addEventListener('click', function(){
    navigator.clipboard.writeText(JSON.stringify(p.settings,null,4)).then(function(){
      cp.textContent='Copied'; setTimeout(function(){ cp.textContent='Copy JSON'; },1200);
    }).catch(function(){ alert('Clipboard blocked by the browser; use Download instead.'); });
  });
  btns.appendChild(cp);
  if(p.custom && customIdx!==undefined){
    var del=document.createElement('button'); del.className='danger'; del.textContent='Delete';
    del.addEventListener('click', function(){ deleteCustomPreset(customIdx); });
    btns.appendChild(del);
  }
  card.appendChild(btns);
  return card;
}
function renderPresets(){
  var body=document.getElementById('presetbody');
  if(!body) return;
  clearEl(body);
  var note=document.createElement('div'); note.className='pnote';
  note.textContent = presetHasFullBase()
    ? 'A render is loaded, so "Download merged settings.txt" gives you a COMPLETE Deforum settings file: this preset\'s look applied over that render\'s settings. Load it in Deforum via the Settings File box -> Load All Settings.'
    : 'Drop a render below first, then a preset download becomes a COMPLETE Deforum settings file (preset merged over that render). Without one, you get just the preset fields as a reference overlay.';
  body.appendChild(note);
  var grid=document.createElement('div'); grid.className='pgrid';
  BUILTIN_PRESETS.forEach(function(p){ grid.appendChild(buildPresetCard(p)); });
  loadCustomPresets().forEach(function(p,i){ grid.appendChild(buildPresetCard(p,i)); });
  body.appendChild(grid);
}
function openPresets(){ if(typeof switchTab==='function') switchTab('presets'); }
renderPresets();

/* ============ FULL SETTINGS COLUMNS + "why is this one different" marking ============
   Every card lists its COMPLETE settings, grouped, in one long column. For each parameter the
   value is compared against the whole library: a value that differs from the majority is marked
   (color + asterisk + tooltip of the majority value) - the fastest answer to "why does this one
   suck / rock". */
var SGROUPS=[["MODEL / SAMPLING",["sd_model_name","animation_mode","max_frames","W","H","fps","steps","sampler","scheduler","cfg_scale","cfg_scale_schedule","seed","seed_behavior","seed_schedule"]],
 ["IMAGE EVOLUTION",["strength_schedule","noise_schedule","noise_multiplier_schedule","diffusion_cadence","optical_flow_cadence","optical_flow_redo_generation","cadence_flow_factor_schedule","redo_flow_factor_schedule","color_coherence","contrast_schedule","amount_schedule","color_force_grayscale","noise_type"]],
 ["CAMERA / 3D",["fov_schedule","near_schedule","far_schedule","midas_weight","use_depth_warping","depth_algorithm","translation_x","translation_y","translation_z","rotation_3d_x","rotation_3d_y","rotation_3d_z","zoom","angle","enable_perspective_flip","perspective_flip_fv","perspective_flip_theta","perspective_flip_phi","perspective_flip_gamma","border","sampling_mode","padding_mode"]],
 ["INIT / LOOPER",["use_init","init_image","strength_0_no_init","use_looper","init_images","image_strength_schedule","blendFactorMax","blendFactorSlope","tweening_frames_schedule","color_correction_factor"]]];
var SGROUP_KEYS={}; SGROUPS.forEach(function(g){ g[1].forEach(function(k){ SGROUP_KEYS[k]=g[0]; }); });

function allFullPids(){ return Object.keys(DATA).filter(function(p){ return DATA[p].full && Object.keys(DATA[p].full).length; }); }
var VAL_FREQ=null;
function buildFreq(){
  VAL_FREQ={};
  allFullPids().forEach(function(p){
    var f=DATA[p].full;
    for(var k in f){ var v=String(f[k]); (VAL_FREQ[k]=VAL_FREQ[k]||{})[v]=(VAL_FREQ[k][v]||0)+1; }
  });
}
function modalValue(k){
  var m=VAL_FREQ[k]||{}; var best=null,bn=-1;
  for(var v in m){ if(m[v]>bn){ bn=m[v]; best=v; } }
  return best;
}
function groupedKeys(full){
  var used={}, out=[];
  SGROUPS.forEach(function(g){
    var ks=g[1].filter(function(k){ return k in full; });
    if(ks.length){ out.push([g[0],ks]); ks.forEach(function(k){ used[k]=1; }); }
  });
  var rest=Object.keys(full).filter(function(k){ return !used[k]; });
  if(rest.length) out.push(["OTHER",rest]);
  return out;
}
function renderColumn(pid){
  var D=DATA[pid]; if(!D) return;
  var fill=document.querySelector('.setfill[data-pid="'+pid+'"]');
  if(fill){
    clearEl(fill);
    if(!D.full || !Object.keys(D.full).length){
      var e=document.createElement('div'); e.className='srow';
      var sv=document.createElement('span'); sv.className='sv'; sv.textContent='no settings.txt';
      e.appendChild(sv); fill.appendChild(e);
    } else {
      groupedKeys(D.full).forEach(function(g){
        var h=document.createElement('div'); h.className='sgroup'; h.textContent=g[0]; fill.appendChild(h);
        g[1].forEach(function(k){
          var v=String(D.full[k]);
          var row=document.createElement('div'); row.className='srow';
          var sk=document.createElement('span'); sk.className='sk'; sk.textContent=k;
          var sv=document.createElement('span'); sv.className='sv'; sv.textContent=v.slice(0,120);
          var modal=modalValue(k);
          if(modal!==null && v!==modal && (VAL_FREQ[k][modal]||0)>=3){
            sv.classList.add('odd'); sv.title='most renders use: '+modal;
          }
          row.appendChild(sk); row.appendChild(sv); fill.appendChild(row);
        });
      });
    }
  }
  var lc=document.querySelector('.lorachips[data-pid="'+pid+'"]');
  if(lc){
    clearEl(lc);
    var names=Object.keys(D.loras||{});
    names.slice(0,14).forEach(function(n){
      var c=document.createElement('span'); c.className='lc';
      c.textContent=n+' ×'+D.loras[n]; lc.appendChild(c);
    });
    if(names.length>14){ var m=document.createElement('span'); m.className='lc'; m.textContent='+'+(names.length-14)+' more'; lc.appendChild(m); }
  }
}
function renderAllColumns(){ buildFreq(); Object.keys(DATA).forEach(renderColumn); }

/* ============ Best-Buy COMPARE: tick renders, see them side-by-side with every
   parameter aligned in rows, differences highlighted, similarities dimmed ============ */
var selOrder=[];
function selUpdate(){
  var bar=document.getElementById('cbar');
  document.querySelectorAll('.cmp-check').forEach(function(c){
    var card=c.closest('.card'); if(card) card.classList.toggle('selected', c.checked);
  });
  var n=selOrder.length;
  document.getElementById('cbar-count').textContent=n+' selected';
  bar.classList.toggle('on', n>0);
  document.getElementById('cbar-go').disabled = n<2;
}
function attachChecks(root){
  (root||document).querySelectorAll('.cmp-check').forEach(function(c){
    if(c.dataset.wired) return; c.dataset.wired='1';
    c.addEventListener('change',function(){
      var pid=c.dataset.pid;
      selOrder=selOrder.filter(function(p){ return p!==pid; });
      if(c.checked) selOrder.push(pid);
      selUpdate();
    });
  });
}
function cmpCell(tr, text, cls){
  var td=document.createElement('td'); if(cls) td.className=cls;
  td.textContent=text; tr.appendChild(td); return td;
}
function cmpSection(tbody, label, span){
  var tr=document.createElement('tr'); tr.className='sec';
  var td=document.createElement('td'); td.textContent=label; tr.appendChild(td);
  var td2=document.createElement('td'); td2.colSpan=span; tr.appendChild(td2);
  tbody.appendChild(tr);
}
function buildCompare(){
  var pids=selOrder.slice();
  var scroll=document.getElementById('cmp-scroll'); clearEl(scroll);
  var table=document.createElement('table'); table.className='cmp-t';
  var thead=document.createElement('thead'); var thr=document.createElement('tr');
  var th0=document.createElement('th'); th0.textContent='parameter'; thr.appendChild(th0);
  pids.forEach(function(pid){
    var th=document.createElement('th');
    var nm=document.createElement('div'); nm.textContent=(DATA[pid]&&DATA[pid].name)||pid; th.appendChild(nm);
    var src=document.getElementById(pid);
    var v=document.createElement('video'); v.controls=true; v.preload='none'; v.playsInline=true;
    if(src){ v.src=src.getAttribute('src')||src.src||''; var po=src.getAttribute('poster'); if(po) v.poster=po; }
    v.dataset.cmpvid='1';
    th.appendChild(v); thr.appendChild(th);
  });
  thead.appendChild(thr); table.appendChild(thead);
  var tbody=document.createElement('tbody');

  // LORAS: union across selected, presence + keyframe counts per render
  var lset={}; pids.forEach(function(p){ Object.keys(DATA[p].loras||{}).forEach(function(n){ lset[n]=1; }); });
  var lnames=Object.keys(lset).sort();
  if(lnames.length){
    cmpSection(tbody,'LORAS',pids.length);
    lnames.forEach(function(n){
      var vals=pids.map(function(p){ return (DATA[p].loras||{})[n]||0; });
      var same=vals.every(function(x){ return x===vals[0]; });
      var tr=document.createElement('tr'); tr.className=same?'same':'diff';
      cmpCell(tr,n);
      vals.forEach(function(x){ cmpCell(tr, x? ('yes ×'+x):'—', x?'has':'not'); });
      tbody.appendChild(tr);
    });
  }

  // SETTINGS: union of every parameter, grouped; diff rows highlighted
  var union={}; pids.forEach(function(p){ Object.keys(DATA[p].full||{}).forEach(function(k){ union[k]=1; }); });
  groupedKeys(union).forEach(function(g){
    cmpSection(tbody,g[0],pids.length);
    g[1].forEach(function(k){
      var vals=pids.map(function(p){ var f=DATA[p].full||{}; return (k in f)? String(f[k]) : '(absent)'; });
      var same=vals.every(function(x){ return x===vals[0]; });
      var tr=document.createElement('tr'); tr.className=same?'same':'diff';
      cmpCell(tr,k);
      vals.forEach(function(x){ cmpCell(tr,x.slice(0,240)); });
      tbody.appendChild(tr);
    });
  });

  // PROMPTS: full keyframe prompt list per render
  cmpSection(tbody,'PROMPTS',pids.length);
  var tr=document.createElement('tr'); tr.className='diff';
  cmpCell(tr,'keyframe prompts');
  pids.forEach(function(p){
    var td=document.createElement('td'); var cell=document.createElement('div'); cell.className='pcell';
    ((DATA[p]&&DATA[p].kf)||[]).forEach(function(kf){
      var d1=document.createElement('div');
      var fspan=document.createElement('span'); fspan.className='pk2'; fspan.textContent=kf[0]+': ';
      d1.appendChild(fspan);
      d1.appendChild(document.createTextNode(kf[1]+(kf[2]&&kf[2].length? '  ['+kf[2].join(', ')+']':'')));
      cell.appendChild(d1);
    });
    if(!cell.childNodes.length) cell.textContent='(no prompt data)';
    td.appendChild(cell); tr.appendChild(td);
  });
  tbody.appendChild(tr);

  table.appendChild(tbody); scroll.appendChild(table);
  document.getElementById('cmp-overlay').classList.add('on');
  document.body.style.overflow='hidden';

  // sync playback across the compared videos (by fraction, like the old compare mode)
  var vids=[].slice.call(scroll.querySelectorAll('video[data-cmpvid]'));
  var syncing2=false;
  vids.forEach(function(v){
    v.addEventListener('timeupdate',function(){
      if(!document.getElementById('cmp-sync').checked || syncing2) return;
      syncing2=true;
      var frac=v.duration? v.currentTime/v.duration:0;
      vids.forEach(function(o){ if(o!==v && o.duration && Math.abs(o.currentTime-frac*o.duration)>0.2) o.currentTime=frac*o.duration; });
      syncing2=false;
    });
    v.addEventListener('play',function(){ if(document.getElementById('cmp-sync').checked) vids.forEach(function(o){ if(o!==v&&o.paused) o.play().catch(function(){}); }); });
    v.addEventListener('pause',function(){ if(document.getElementById('cmp-sync').checked) vids.forEach(function(o){ if(o!==v&&!o.paused) o.pause(); }); });
  });
}
document.getElementById('cbar-go').addEventListener('click',function(){ if(selOrder.length>=2) buildCompare(); });
document.getElementById('cbar-clear').addEventListener('click',function(){
  selOrder=[]; document.querySelectorAll('.cmp-check').forEach(function(c){ c.checked=false; }); selUpdate();
});
document.getElementById('cmp-close').addEventListener('click',function(){
  var ov=document.getElementById('cmp-overlay');
  ov.querySelectorAll('video').forEach(function(v){ try{ v.pause(); }catch(e){} });
  ov.classList.remove('on'); document.body.style.overflow='';
});
document.getElementById('cmp-diffsonly').addEventListener('change',function(){
  document.getElementById('cmp-overlay').classList.toggle('donly', this.checked);
});
var _st=document.createElement('style');
_st.textContent='.cmp-overlay.donly tr.same{display:none}';
document.head.appendChild(_st);
document.addEventListener('keydown',function(e){
  if(e.key==='Escape' && document.getElementById('cmp-overlay').classList.contains('on'))
    document.getElementById('cmp-close').click();
});

/* ===== COMMENTS + DELETION FLAGS + BEST PRACTICES, persisted to the project folder =====
   Served through the WebUI, every edit POSTs to the gallery extension's notes API and lands in
   outputs/img2img-images/_gallery_data/gallery_notes.json (keyed by render NAME, so notes survive
   rebuilds). Opened as a plain file, the page shows the baked snapshot read-only. Flagging marks
   a render for deletion - NOTHING is deleted by the page; Brian reviews the flag list and the
   deletion (video + settings + originals) happens deliberately, off-page. */
var NOTES = NOTES_INIT || {comments:{},flags:[],best_practices:''};
var API_LIVE=false, NAPI='/deforum-gallery-api';

function cardByName(name){
  var b=document.querySelector('.flagbtn[data-name="'+(window.CSS&&CSS.escape?CSS.escape(name):name)+'"]');
  return b? b.closest('.card') : null;
}
function renderFlagStates(){
  document.querySelectorAll('.flagbtn').forEach(function(b){
    var on=NOTES.flags.indexOf(b.dataset.name)!==-1;
    b.classList.toggle('on',on);
    b.textContent=on? '🗑 flagged' : '🗑 flag';
    var card=b.closest('.card'); if(card) card.classList.toggle('flagged',on);
  });
}
function renderCommentsFor(el){
  var name=el.dataset.name; clearEl(el);
  var list=(NOTES.comments||{})[name]||[];
  list.forEach(function(c){
    var d=document.createElement('div'); d.className='c1';
    var ts=document.createElement('span'); ts.className='ts'; ts.textContent=c.ts||'';
    d.appendChild(ts); d.appendChild(document.createTextNode(c.text||''));
    el.appendChild(d);
  });
  var ta=document.createElement('textarea'); ta.placeholder='add a comment on this render…';
  el.appendChild(ta);
  var row=document.createElement('div'); row.className='crow';
  var btn=document.createElement('button'); btn.textContent='save comment';
  if(API_LIVE){
    btn.addEventListener('click',function(){
      var text=ta.value.trim(); if(!text) return;
      fetch(NAPI+'/comment',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:name,text:text})})
      .then(function(r){return r.json();}).then(function(j){
        if(j.ok){ NOTES.comments[name]=j.comments; renderCommentsFor(el); renderSaved(); }
        else alert('save failed: '+(j.error||'?'));
      }).catch(function(e){ alert('save failed: '+e); });
    });
  } else {
    btn.disabled=true;
    var note=document.createElement('span'); note.className='apinote';
    note.textContent='comments save when opened via the WebUI Render Gallery tab';
    row.appendChild(note);
  }
  row.insertBefore(btn,row.firstChild);
  el.appendChild(row);
}
function renderNotesAll(){
  renderFlagStates();
  document.querySelectorAll('.cmts[data-name]').forEach(renderCommentsFor);
}
function wireFlagBtn(b){
  if(b.dataset.wired) return; b.dataset.wired='1';
  b.addEventListener('click',function(){
    var name=b.dataset.name;
    if(!API_LIVE){ alert('Flagging saves when the gallery is opened via the WebUI Render Gallery tab.'); return; }
    var flagged=NOTES.flags.indexOf(name)===-1;
    fetch(NAPI+'/flag',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:name,flagged:flagged})})
    .then(function(r){return r.json();}).then(function(j){
      if(j.ok){ NOTES.flags=j.flags; renderFlagStates(); renderSaved(); applyFilter(); }
    }).catch(function(e){ alert('flag failed: '+e); });
  });
}
document.querySelectorAll('.flagbtn').forEach(wireFlagBtn);

// "flagged only" folds into the existing filter pipeline
var _origApplyFilter=applyFilter;
applyFilter=function(){
  _origApplyFilter();
  var fc=document.getElementById('flagchk');
  if(fc && fc.checked){
    document.querySelectorAll('.card[data-pid]').forEach(function(c){
      if(c.hidden) return;
      var b=c.querySelector('.flagbtn');
      if(!b || NOTES.flags.indexOf(b.dataset.name)===-1) c.hidden=true;
    });
  }
};
var _fc=document.getElementById('flagchk');
if(_fc) _fc.addEventListener('change',function(){ applyFilter(); });

// ----- Best Practices: view + edit; saved to the project folder via the API, or downloadable -----
/* Best Practices formatter - renders the plain-text notes as a readable document:
   "== HEADING ==" lines become titled section cards, "- " lines become real bullet lists,
   wrapped continuation lines fold into their bullet. Edit mode still works on the raw text. */
function formatBP(text){
  var root=document.createElement('div'); root.className='bpdoc';
  var intro=document.createElement('div'); intro.className='bpintro';
  var sec=null, list=null;
  function tgt(){ return sec||root; }
  String(text||'').split(/\r?\n/).forEach(function(raw){
    var line=raw.replace(/\s+$/,'');
    var m=line.match(/^==\s*(.+?)\s*==$/);
    if(m){
      list=null;
      sec=document.createElement('section'); sec.className='bpsec';
      var h=document.createElement('h2'); h.textContent=m[1]; sec.appendChild(h);
      root.appendChild(sec); return;
    }
    if(!line.trim()){ list=null; return; }
    if(/^- /.test(line.trim()) ){
      if(!list){ list=document.createElement('ul'); tgt().appendChild(list); }
      var li=document.createElement('li'); li.textContent=line.trim().slice(2); list.appendChild(li); return;
    }
    if(/^\s{2,}/.test(raw) && list && list.lastChild){   // wrapped continuation of the last bullet
      list.lastChild.textContent += ' ' + line.trim(); return;
    }
    list=null;
    if(!sec){
      var p0=document.createElement('p');
      p0.className = intro.childNodes.length ? 'bpsub' : 'bptitle';
      p0.textContent=line;
      intro.appendChild(p0);
      if(!root.contains(intro)) root.insertBefore(intro, root.firstChild);
      return;
    }
    var p=document.createElement('p'); p.textContent=line; tgt().appendChild(p);
  });
  if(!root.childNodes.length){
    var e=document.createElement('p'); e.className='bpsub'; e.textContent='(empty)'; root.appendChild(e);
  }
  return root;
}
function renderBP(){
  var body=document.getElementById('bpbody'); if(!body) return;
  clearEl(body);
  body.appendChild(formatBP(NOTES.best_practices));
  var row=document.createElement('div'); row.className='bprow';
  var edit=document.createElement('button'); edit.textContent='Edit';
  edit.addEventListener('click',function(){
    clearEl(body);
    var ta=document.createElement('textarea'); ta.value=NOTES.best_practices||''; body.appendChild(ta);
    var hint=document.createElement('div'); hint.className='bpedithint';
    hint.textContent='plain text: "== HEADING ==" starts a section, lines beginning "- " become bullets';
    body.appendChild(hint);
    var r2=document.createElement('div'); r2.className='bprow';
    if(API_LIVE){
      var save=document.createElement('button'); save.textContent='Save to project folder';
      save.addEventListener('click',function(){
        fetch(NAPI+'/bestpractices',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({text:ta.value})})
        .then(function(r){return r.json();}).then(function(j){
          if(j.ok){ NOTES.best_practices=ta.value; renderBP(); } else alert('save failed');
        }).catch(function(e){ alert('save failed: '+e); });
      });
      r2.appendChild(save);
    } else {
      var dl=document.createElement('button'); dl.textContent='Download my edits (send the file back to Brian)';
      dl.addEventListener('click',function(){
        var blob=new Blob([ta.value],{type:'text/plain'});
        var url=URL.createObjectURL(blob);
        var a=document.createElement('a'); a.href=url; a.download='best_practices_edited.txt';
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        setTimeout(function(){ URL.revokeObjectURL(url); },1000);
      });
      r2.appendChild(dl);
    }
    var cancel=document.createElement('button'); cancel.className='ghost'; cancel.textContent='Cancel';
    cancel.addEventListener('click',renderBP);
    r2.appendChild(cancel);
    body.appendChild(r2);
  });
  row.appendChild(edit);
  if(!API_LIVE){
    var n=document.createElement('span'); n.className='apinote';
    n.textContent='live saving needs the WebUI Render Gallery tab; here Edit gives you a downloadable copy';
    row.appendChild(n);
  }
  body.appendChild(row);
}
/* ===== live folders + dynamic library =====
   Served via the WebUI, the library is NOT the baked snapshot: /scan walks the folder chosen in
   the Folders bar and the page rebuilds its cards from that JSON. Change the folder, hit Rescan,
   different library. Opened from disk (no API), the baked snapshot stays as the offline fallback. */
var libSeq=0;
function wireCardVideo(v){
  ['timeupdate','seeked','play'].forEach(function(e){ v.addEventListener(e,function(){ upd(v); }); });
}
function buildLibCard(entry){
  var pid='lib'+(libSeq++);
  registerDataJS(pid, entry.settings||null);
  DATA[pid].name=entry.name;
  var card=document.createElement('div'); card.className='card';
  card.dataset.pid=pid; card.dataset.name=entry.name.toLowerCase();
  card.dataset.mtime=entry.mtime||0;
  card.dataset.frames=(entry.settings&&entry.settings.max_frames)||0;
  card.dataset.dur=0;
  card.dataset.hay=(entry.name+' '+String(entry.settings&&entry.settings.sd_model_name||'')+' '
    +JSON.stringify((entry.settings&&entry.settings.prompts)||'')).toLowerCase().slice(0,4000);

  var chead=document.createElement('div'); chead.className='chead';
  var fb=document.createElement('button'); fb.className='flagbtn'; fb.dataset.name=entry.name;
  fb.textContent='🗑 flag'; wireFlagBtn(fb); chead.appendChild(fb);
  var eb=document.createElement('button'); eb.className='exportbtn'; eb.dataset.name=entry.name;
  eb.textContent='⬇ export'; wireExportBtn(eb); chead.appendChild(eb);
  var cl=document.createElement('label'); cl.className='cmp';
  var cc=document.createElement('input'); cc.type='checkbox'; cc.className='cmp-check'; cc.dataset.pid=pid;
  cl.appendChild(cc); cl.appendChild(document.createTextNode(' compare')); chead.appendChild(cl);
  var fn=document.createElement('div'); fn.className='fn'; fn.textContent=entry.name; fn.title=entry.name;
  chead.appendChild(fn);
  var fd=document.createElement('div'); fd.className='fd';
  fd.textContent=(entry.settings?'':'no settings.txt · ')+(entry.size? Math.round(entry.size/1e6)+' MB':'');
  chead.appendChild(fd);
  card.appendChild(chead);

  var vb=document.createElement('div'); vb.className='vidbox';
  var v=document.createElement('video'); v.id=pid; v.dataset.pid=pid;
  v.controls=true; v.preload='none'; v.playsInline=true;
  v.src=entry.video; if(entry.poster) v.poster=entry.poster;
  wireCardVideo(v); vb.appendChild(v); card.appendChild(vb);

  var live=document.createElement('div'); live.className='live'; live.id='live-'+pid;
  var hint=document.createElement('div'); hint.className='lrow hint';
  hint.textContent='press play — live prompt, LoRAs and camera appear here';
  live.appendChild(hint); card.appendChild(live);

  var exp=document.createElement('div'); exp.className='exp';
  exp.textContent=entry.settings? experimentJS(entry.settings) : 'no settings.txt';
  card.appendChild(exp);

  var lc=document.createElement('div'); lc.className='lorachips'; lc.dataset.pid=pid; card.appendChild(lc);
  var cm=document.createElement('div'); cm.className='cmts'; cm.dataset.name=entry.name; card.appendChild(cm);
  var sf=document.createElement('div'); sf.className='setfill'; sf.dataset.pid=pid; card.appendChild(sf);
  return card;
}
function loadLibrary(){
  var st=document.getElementById('dirstatus');
  if(st){ st.textContent='scanning…'; st.classList.remove('err'); }
  return fetch(NAPI+'/scan').then(function(r){ return r.json(); }).then(function(j){
    if(!j.ok){ if(st){ st.textContent=j.error||'scan failed'; st.classList.add('err'); } return; }
    Object.keys(DATA).forEach(function(p){ if(p.indexOf('drop')!==0){ delete DATA[p]; delete camFns[p]; } });
    selOrder=selOrder.filter(function(p){ return p.indexOf('drop')===0; }); selUpdate();
    if(gridEl) clearEl(gridEl);
    var frag=document.createDocumentFragment();
    j.renders.forEach(function(e){ frag.appendChild(buildLibCard(e)); });
    if(gridEl) gridEl.appendChild(frag);
    cardsAll=[].slice.call(document.querySelectorAll('.grid .card[data-pid]'));
    buildFreq();
    cardsAll.forEach(function(c){ renderColumn(c.dataset.pid); });
    attachChecks(gridEl); renderNotesAll(); applyFilter(); renderSaved();
    var lib=document.getElementById('dzlib');
    if(lib){ lib.textContent='Live library: '+j.root+' · '+j.renders.length+' renders'; }
    if(st) st.textContent=j.renders.length+' renders';
  }).catch(function(e){ if(st){ st.textContent='scan error: '+e; st.classList.add('err'); } });
}
/* The gallery references ONE folder: where the renders live. (Init-image / video / ControlNet /
   model folder settings belong to the Deforum panel, not here.) Browse... opens a server-side
   folder picker, because web pages cannot read real filesystem paths from native file dialogs. */
var DIR_INPUTS={renders:'dir-renders'};
function autoSaveDirs(changedKey){
  var dirs={};
  Object.keys(DIR_INPUTS).forEach(function(k){
    var el=document.getElementById(DIR_INPUTS[k]); if(el && el.value.trim()) dirs[k]=el.value.trim();
  });
  var st=document.getElementById(changedKey==='renders' ? 'dirstatus' : ('fstat-'+changedKey))
      || document.getElementById('dirstatus');
  return fetch(NAPI+'/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({dirs:dirs})})
  .then(function(r){ return r.json(); }).then(function(j){
    if(j.ok){
      if(st){ st.textContent='saved'; st.className=(st.id==='dirstatus'?'dirstatus':'fstat ok'); }
      if(changedKey==='renders') loadLibrary();
    } else if(st){
      st.textContent=j.error||'save failed';
      st.className=(st.id==='dirstatus'?'dirstatus err':'fstat err');
    }
  }).catch(function(e){
    if(st){ st.textContent='save error: '+e; st.className=(st.id==='dirstatus'?'dirstatus err':'fstat err'); }
  });
}
function initDirBar(){
  fetch(NAPI+'/config').then(function(r){ return r.json(); }).then(function(c){
    var bar=document.getElementById('dirbar'); if(bar) bar.removeAttribute('hidden');
    Object.keys(DIR_INPUTS).forEach(function(k){
      var el=document.getElementById(DIR_INPUTS[k]); if(el) el.value=(c.dirs&&c.dirs[k])||'';
    });
    var sv=document.getElementById('dirsave');
    if(sv) sv.addEventListener('click',function(){ autoSaveDirs('renders'); });
    var rs=document.getElementById('dirrescan');
    if(rs) rs.addEventListener('click',loadLibrary);
  }).catch(function(){});
}
/* server-side folder browser popup */
var fbTargetInput=null, fbCurrentPath='';
function fbNav(path){
  var list=document.getElementById('fb-list'), head=document.getElementById('fb-path'),
      stat=document.getElementById('fb-stat'), use=document.getElementById('fb-use');
  fetch(NAPI+'/browse?path='+encodeURIComponent(path||'')).then(function(r){ return r.json(); })
  .then(function(j){
    if(!j.ok){ if(stat){ stat.textContent=j.error||'browse failed'; stat.className='fstat err'; } return; }
    if(stat){ stat.textContent=''; stat.className='fstat'; }
    fbCurrentPath=j.path;
    if(head) head.textContent=j.path||'Drives';
    if(use) use.disabled=j.isRoot;
    clearEl(list);
    if(j.parent!==null && !j.isRoot){
      var up=document.createElement('button'); up.className='fb-item'; up.textContent='⬑ ..';
      up.addEventListener('click',function(){ fbNav(j.parent); });
      list.appendChild(up);
    }
    j.dirs.forEach(function(d){
      var b=document.createElement('button'); b.className='fb-item';
      b.textContent=(j.isRoot? '' : '📁 ')+d;
      b.addEventListener('click',function(){
        fbNav(j.isRoot ? d : (j.path.replace(/[\\/]+$/,'')+'\\'+d));
      });
      list.appendChild(b);
    });
    if(!j.dirs.length){
      var e=document.createElement('div'); e.className='fb-item'; e.textContent='(no subfolders)';
      list.appendChild(e);
    }
  }).catch(function(e){ if(stat){ stat.textContent='browse error: '+e; stat.className='fstat err'; } });
}
function openBrowse(inputId){
  if(!API_LIVE){ alert('Browsing folders needs the page opened via the WebUI (Render Gallery tab).'); return; }
  fbTargetInput=document.getElementById(inputId);
  document.getElementById('fb-ov').removeAttribute('hidden');
  fbNav((fbTargetInput&&fbTargetInput.value)||'');
}
(function(){
  document.querySelectorAll('.fbrowse').forEach(function(b){
    b.addEventListener('click',function(){ openBrowse(b.dataset.for); });
  });
  var cl=document.getElementById('fb-close');
  if(cl) cl.addEventListener('click',function(){ document.getElementById('fb-ov').setAttribute('hidden',''); });
  var use=document.getElementById('fb-use');
  if(use) use.addEventListener('click',function(){
    if(fbTargetInput && fbCurrentPath){
      fbTargetInput.value=fbCurrentPath;
      var key=Object.keys(DIR_INPUTS).filter(function(k){ return DIR_INPUTS[k]===fbTargetInput.id; })[0];
      autoSaveDirs(key||'renders');
    }
    document.getElementById('fb-ov').setAttribute('hidden','');
  });
  var ov=document.getElementById('fb-ov');
  if(ov) ov.addEventListener('click',function(ev){ if(ev.target===ov) ov.setAttribute('hidden',''); });
})();
function notesInit(){
  fetch(NAPI+'/state').then(function(r){ if(!r.ok) throw 0; return r.json(); })
  .then(function(n){ NOTES=n; API_LIVE=true; document.body.classList.add('apilive');
    renderNotesAll(); renderBP(); renderSaved(); applyFilter();
    initDirBar(); loadLibrary(); })
  .catch(function(){ API_LIVE=false; renderNotesAll(); renderBP(); renderSaved(); });
}
// export = download a zip of this render's mp4 + settings (server bundles the pair)
function wireExportBtn(b){
  if(b.dataset.wired) return; b.dataset.wired='1';
  b.addEventListener('click',function(){
    window.location.href = NAPI+'/export?name='+encodeURIComponent(b.dataset.name);
  });
}
document.querySelectorAll('.exportbtn').forEach(wireExportBtn);

/* ============ SAVED tab: review surface for anything flagged and/or commented ============
   Brian wasn't sure what this tab should be ("the ones we save... I don't know") - this surfaces
   exactly the data that's actually persisted (flags + comments), so it's a management view of
   what he's tagged rather than a new, untested concept. */
function renderSaved(){
  var body=document.getElementById('savedbody'); if(!body) return;
  clearEl(body);
  var names={}; (NOTES.flags||[]).forEach(function(n){ names[n]=1; });
  Object.keys(NOTES.comments||{}).forEach(function(n){ if((NOTES.comments[n]||[]).length) names[n]=1; });
  var list=Object.keys(names).sort();
  var cnt=document.getElementById('savedcount');
  if(cnt) cnt.textContent = list.length ? '('+list.length+')' : '';
  if(!list.length){
    var e=document.createElement('div'); e.className='savedempty';
    e.textContent='Nothing flagged or commented yet. Flag a render for deletion, or add a comment, from the Gallery tab.';
    body.appendChild(e); return;
  }
  list.forEach(function(name){
    var flagged=(NOTES.flags||[]).indexOf(name)!==-1;
    var row=document.createElement('div'); row.className='savedrow'+(flagged?' flagged':'');
    var h=document.createElement('h3'); h.textContent=name; row.appendChild(h);
    var meta=document.createElement('div'); meta.className='srmeta';
    var jump=document.createElement('button'); jump.textContent='View in Gallery';
    jump.addEventListener('click',function(){
      switchTab('gallery');
      var card=cardByName(name);
      if(card) card.scrollIntoView({behavior:'smooth',inline:'center',block:'start'});
    });
    meta.appendChild(jump);
    if(flagged){
      var unflag=document.createElement('button'); unflag.textContent='Unflag';
      unflag.addEventListener('click',function(){
        if(!API_LIVE){ alert('Unflagging needs the WebUI Render Gallery tab.'); return; }
        fetch(NAPI+'/flag',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({name:name,flagged:false})})
        .then(function(r){return r.json();}).then(function(j){
          if(j.ok){ NOTES.flags=j.flags; renderFlagStates(); renderSaved(); applyFilter(); }
        }).catch(function(e){ alert('unflag failed: '+e); });
      });
      meta.appendChild(unflag);
      var tag=document.createElement('span'); tag.textContent='flagged for deletion'; tag.style.color='var(--warn)';
      tag.style.fontSize='11.5px'; tag.style.fontFamily='var(--mono)'; meta.appendChild(tag);
    }
    row.appendChild(meta);
    (NOTES.comments[name]||[]).forEach(function(c){
      var d=document.createElement('div'); d.className='c1';
      var ts=document.createElement('span'); ts.className='ts'; ts.textContent=c.ts||'';
      d.appendChild(ts); d.appendChild(document.createTextNode(c.text||''));
      row.appendChild(d);
    });
    body.appendChild(row);
  });
}

// pin the sticky column headers just below the real toolbar height
(function(){
  var ctl=document.querySelector('.ctl');
  function setStick(){ if(ctl) document.documentElement.style.setProperty('--stick',(ctl.offsetHeight+8)+'px'); }
  setStick(); window.addEventListener('resize',setStick);
})();
renderAllColumns(); attachChecks(document); selUpdate(); notesInit();

/* view modes, persisted: strip = one giant horizontal row (49-inch friendly);
   grid = wrapped cards, N across (user-defined); list = one render per full-width row,
   settings spread into text columns. Card-size slider only applies to strip;
   the "across" count only applies to grid - each control hides when irrelevant. */
(function(){
  var vs=document.getElementById('viewsel'), gc=document.getElementById('gridcols');
  if(!vs) return;
  function applyView(){
    var m=vs.value;
    document.body.classList.toggle('gridmode', m==='grid');
    document.body.classList.toggle('listrows', m==='list');
    document.documentElement.style.setProperty('--gcols', String((gc&&parseInt(gc.value,10))||4));
    var sz=document.getElementById('szwrap'); if(sz) sz.style.display=(m==='strip')?'':'none';
    var gw=document.getElementById('gcwrap'); if(gw) gw.style.display=(m==='grid')?'':'none';
    try{ localStorage.setItem('dg_view3', m); if(gc) localStorage.setItem('dg_gcols', gc.value); }catch(e){}
  }
  try{
    var sv=localStorage.getItem('dg_view3'); if(sv && ['strip','grid','list'].indexOf(sv)!==-1) vs.value=sv;
    var sg=localStorage.getItem('dg_gcols'); if(sg && gc) gc.value=sg;
  }catch(e){}
  vs.addEventListener('change',applyView);
  if(gc) gc.addEventListener('input',applyView);
  applyView();
})();

/* ============ TABS: one switch, one state, nothing else touches visibility ============
   Replaces the two independent collapsible-panel systems that could desync (see the CSS comment
   at the top of EXTRA_CSS for the repro). [hidden] on the inactive tabpages takes the 44k-node
   gallery grid fully out of layout/paint while on another tab - not just visually hidden. */
var TABS=['gallery','practices','presets','saved'];
function switchTab(name){
  if(TABS.indexOf(name)===-1) name='gallery';
  TABS.forEach(function(t){
    var page=document.getElementById('tabpage-'+t);
    if(page){ if(t===name) page.removeAttribute('hidden'); else page.setAttribute('hidden',''); }
  });
  document.querySelectorAll('.tabbtn').forEach(function(b){
    var on=b.dataset.tab===name;
    b.classList.toggle('active',on);
    b.setAttribute('aria-selected', on?'true':'false');
  });
  if(name!=='gallery'){
    // don't leave a render quietly playing behind a tab you can't see
    document.querySelectorAll('#tabpage-gallery video').forEach(function(v){ if(!v.paused) v.pause(); });
  }
  if(name==='saved') renderSaved();
  try{ localStorage.setItem('deforum_gallery_tab', name); }catch(e){}
}
document.querySelectorAll('.tabbtn').forEach(function(b){
  b.addEventListener('click',function(){ switchTab(b.dataset.tab); });
});
(function(){
  var saved=null;
  try{ saved=localStorage.getItem('deforum_gallery_tab'); }catch(e){}
  switchTab(saved||'gallery');
})();

/* Browse buttons - normal file/folder pickers feeding the SAME pipeline as drag-and-drop
   (webkitdirectory gives the whole folder tree; prefiltered to mp4/txt/json so a folder full of
   PNG frames doesn't trip the "no mp4 found" alert for the wrong reason) */
(function(){
  var pf=document.getElementById('pickfiles'), pd=document.getElementById('pickdir');
  var bf=document.getElementById('browsefiles'), bd=document.getElementById('browsedir');
  function useful(fl){
    return [].slice.call(fl||[]).filter(function(f){ return /\.(mp4|txt|json)$/i.test(f.name); });
  }
  if(bf&&pf){
    bf.addEventListener('click',function(){ pf.click(); });
    pf.addEventListener('change',function(){
      var fs=useful(pf.files);
      if(fs.length) handleDropFiles(fs); else if(pf.files.length) alert('No .mp4 / settings files in that selection.');
      pf.value='';
    });
  }
  if(bd&&pd){
    bd.addEventListener('click',function(){ pd.click(); });
    pd.addEventListener('change',function(){
      var fs=useful(pd.files);
      if(fs.length) handleDropFiles(fs); else if(pd.files.length) alert('No .mp4 / settings files found in that folder.');
      pd.value='';
    });
  }
})();

var dropzoneEl=document.getElementById('dropzone');
['dragenter','dragover'].forEach(function(e){
  document.addEventListener(e,function(ev){ ev.preventDefault(); dropzoneEl.classList.add('drag'); });
});
document.addEventListener('dragleave',function(ev){ if(ev.clientX<=0||ev.clientY<=0) dropzoneEl.classList.remove('drag'); });
document.addEventListener('drop',function(ev){
  ev.preventDefault();
  dropzoneEl.classList.remove('drag');
  getAllFileEntries(ev.dataTransfer.items).then(function(files){
    if(files.length) handleDropFiles(files);
  });
});
"""

import time as _time
if STANDALONE:
    PAGE_TITLE = "Microcosm"
    PAGE_SUB = ("Standalone viewer &mdash; drag your own Deforum render (.mp4) plus its _settings.txt onto the "
        "drop zone below, or drag a whole render folder. Drop 2+ to compare them side-by-side with synced playback. "
        "Nothing is uploaded anywhere: everything runs locally in your browser.")
    HEAD_TITLE = "Microcosm"
    LIB_LINE = ("No library is baked into this page &mdash; everything you view comes from files you "
        "drop or browse. Nothing is uploaded anywhere.")
else:
    PAGE_TITLE = "Microcosm"
    PAGE_SUB = (f"{len(keep)} renders (every one in the folder) &middot; {trashed} duplicate/bad moved to "
        "_trash_review &middot; play a video to see the prompt/LoRAs/camera change over time &middot; "
        "or drag in any render to add/compare it")
    HEAD_TITLE = "Microcosm"
    LIB_LINE = (f"Opened from disk: showing the snapshot built {_time.strftime('%Y-%m-%d %H:%M')} "
        f"({len(keep)} renders from <b>{html.escape(ROOT)}</b>). Open this page via the WebUI's "
        "Render Gallery tab for LIVE folders, rescan, and editing.")

doc = f'''<!DOCTYPE html><html><head><meta charset="utf-8"><title>{HEAD_TITLE}</title><style>
/* Instrument, not gallery. The renders are the only saturated thing on screen; chrome recedes.
   Near-black neutrals tinted toward the one accent (blue), OKLCH throughout. Contrast verified:
   --ink 4.5:1+ on --bg, --ink-2 4.5:1+ on --surface, --ink-3 only ever on large/secondary text. */
:root{{
  --bg:oklch(0.17 0.012 265); --surface:oklch(0.21 0.014 265); --surface-2:oklch(0.25 0.016 265);
  --line:oklch(0.31 0.018 265); --line-2:oklch(0.40 0.022 265);
  --ink:oklch(0.96 0.004 265); --ink-2:oklch(0.83 0.010 265); --ink-3:oklch(0.68 0.014 265);
  --accent:oklch(0.78 0.145 240); --accent-dim:oklch(0.40 0.075 240);
  --data:oklch(0.86 0.105 195); --good:oklch(0.82 0.170 145); --good-bg:oklch(0.32 0.085 145);
  --warn:oklch(0.83 0.130 85);
  --r:10px; --r-sm:6px;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  --z-sticky:10; --z-pop:20;
  --ease:cubic-bezier(0.22,1,0.36,1);
}}
*{{box-sizing:border-box}}
html{{color-scheme:dark}}
body{{background:var(--bg);color:var(--ink);margin:0;padding:0;
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}}

/* ---- toolbar: find before browse. FIXED (not sticky) because the page scrolls horizontally
   through the strip - a sticky toolbar would slide off-screen as you scroll across. ---- */
.ctl{{position:fixed;top:0;left:0;right:0;z-index:var(--z-sticky);background:oklch(0.19 0.013 265 / 0.94);
  backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding:10px 18px 9px}}
body{{padding-top:var(--stick,132px)}}
.comparewrap{{max-width:calc(100vw - 36px)}}
.ctl-row{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
.ctl-row-2{{margin-top:9px}}
.ctl h1{{font-size:15px;font-weight:650;margin:0;letter-spacing:-0.01em;white-space:nowrap;color:var(--ink)}}
#q{{flex:1 1 280px;min-width:200px;background:var(--bg);border:1px solid var(--line);
  border-radius:var(--r-sm);padding:7px 11px;color:var(--ink);font-size:13.5px;font-family:inherit}}
#q::placeholder{{color:var(--ink-3)}}
#q:focus,#sort:focus,.chip:focus-visible,#sz:focus-visible{{outline:2px solid var(--accent);outline-offset:1px}}
#sort{{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-sm);
  padding:7px 9px;color:var(--ink-2);font-size:13px;font-family:inherit;cursor:pointer}}
.count{{font-family:var(--mono);font-size:12.5px;color:var(--ink-3);white-space:nowrap}}
.count b{{color:var(--ink);font-weight:600}}
.sub{{color:var(--ink-3);font-size:12.5px;margin-top:8px;max-width:78ch;line-height:1.45}}
.mini{{font-size:12px;color:var(--ink-3);display:flex;align-items:center;gap:6px;white-space:nowrap}}
.mini input[type=range]{{width:110px;accent-color:var(--accent)}}
.mini input[type=checkbox]{{accent-color:var(--accent)}}
.chips{{display:flex;gap:5px;flex-wrap:wrap;flex:1 1 auto}}
.chip{{background:transparent;border:1px solid var(--line);color:var(--ink-3);border-radius:999px;
  padding:3px 10px;font-size:11.5px;font-family:var(--mono);cursor:pointer;
  transition:color .15s var(--ease),border-color .15s var(--ease),background .15s var(--ease)}}
.chip:hover{{color:var(--ink-2);border-color:var(--line-2)}}
.chip[aria-pressed="true"]{{background:var(--accent-dim);border-color:var(--accent);color:var(--ink)}}
.chip .n{{opacity:.6;margin-left:5px}}

/* ---- ONE horizontal strip: each render is a tall column, scroll ACROSS (Brian's spec).
   Page scrolls horizontally through renders and vertically through each column's full settings.
   The video/live-panel block is sticky at the top of its column so it stays visible while you
   scroll down the long parameter list. ---- */
.grid{{display:flex;flex-wrap:nowrap;gap:14px;padding:14px 18px 84px;align-items:flex-start;
  overflow-x:visible;min-width:max-content}}
/* "view as rows": cards wrap and the page scrolls vertically only (saved preference) */
body.rows .grid{{flex-wrap:wrap;min-width:0}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:12px;width:var(--cw,460px);flex:0 0 var(--cw,460px);display:flex;flex-direction:column}}
.card[hidden]{{display:none}}
/* FIXED-height header so every video sits on exactly the same line across all columns
   (Brian: "videos at the very top, just underneath the title, all perfectly aligned").
   No sticky, no inner scrolling anywhere - the page is the only scroller. */
.chead{{height:46px;overflow:hidden;margin-bottom:8px}}
.cmp{{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--ink-3);
  font-family:var(--mono);cursor:pointer;float:right}}
.cmp input{{accent-color:var(--accent)}}
.card.selected{{border-color:var(--accent)}}
.lorachips{{display:flex;flex-wrap:wrap;gap:4px;margin-top:7px}}
.lorachips .lc{{font-family:var(--mono);font-size:10.5px;color:var(--ink-2);background:var(--bg);
  border:1px solid var(--line);border-radius:999px;padding:1px 8px}}
/* uncommon values pop: a value differing from the majority across the library is the likeliest
   answer to "why does this one look different" */
.srow .sv.odd{{color:var(--warn);font-weight:600}}
.srow .sv.odd::after{{content:" ✳";font-size:10px}}
.sgroup{{color:var(--ink-3);font-family:var(--mono);font-size:10px;letter-spacing:.08em;
  text-transform:uppercase;padding:9px 5px 3px;border-bottom:1px solid var(--line);margin-bottom:3px}}

/* ---- compare bar + Best-Buy-style compare table ---- */
.cbar{{position:fixed;left:0;right:0;bottom:0;z-index:var(--z-pop);display:none;gap:12px;
  align-items:center;padding:10px 18px;background:oklch(0.21 0.014 265 / 0.97);
  backdrop-filter:blur(10px);border-top:1px solid var(--line-2)}}
.cbar.on{{display:flex}}
.cbar .cnt{{font-family:var(--mono);font-size:13px;color:var(--ink)}}
.cbar button{{background:var(--accent-dim);color:var(--ink);border:1px solid var(--accent);
  border-radius:var(--r-sm);padding:7px 16px;cursor:pointer;font-size:13px;font-weight:600}}
.cbar button.ghost{{background:transparent;border-color:var(--line-2);color:var(--ink-3);font-weight:400}}
.cmp-overlay{{position:fixed;inset:0;z-index:30;background:var(--bg);display:none;flex-direction:column}}
.cmp-overlay.on{{display:flex}}
.cmp-head{{display:flex;gap:14px;align-items:center;padding:11px 18px;border-bottom:1px solid var(--line);
  background:var(--surface)}}
.cmp-head h2{{margin:0;font-size:15px}}
.cmp-head label{{font-size:12.5px;color:var(--ink-2);display:flex;gap:6px;align-items:center}}
.cmp-head .x{{margin-left:auto;background:var(--surface-2);color:var(--ink);border:1px solid var(--line-2);
  border-radius:var(--r-sm);padding:6px 14px;cursor:pointer;font-size:13px}}
.cmp-scroll{{flex:1;overflow:auto}}
table.cmp-t{{border-collapse:separate;border-spacing:0;font-size:12.5px;min-width:100%}}
.cmp-t th,.cmp-t td{{padding:6px 12px;border-bottom:1px solid var(--line);vertical-align:top;
  text-align:left;max-width:420px}}
.cmp-t th{{position:sticky;top:0;background:var(--surface);z-index:2;font-family:var(--mono);
  font-size:12px;border-bottom:1px solid var(--line-2)}}
.cmp-t td:first-child,.cmp-t th:first-child{{position:sticky;left:0;background:var(--surface);
  z-index:1;font-family:var(--mono);color:var(--ink-3);font-size:11.5px;white-space:nowrap;
  border-right:1px solid var(--line-2)}}
.cmp-t th:first-child{{z-index:3}}
.cmp-t td{{font-family:var(--mono);color:var(--ink-2);word-break:break-word}}
.cmp-t tr.diff td{{background:oklch(0.24 0.030 85 / 0.35)}}
.cmp-t tr.diff td:first-child{{color:var(--warn)}}
.cmp-t tr.same td{{opacity:.62}}
.cmp-t .sec td{{background:var(--surface-2);color:var(--ink);font-weight:600;letter-spacing:.05em;
  text-transform:uppercase;font-size:10.5px;opacity:1}}
.cmp-t video{{width:230px;aspect-ratio:1/1;border-radius:6px;background:#000;display:block}}
.cmp-t .pcell{{max-height:300px;overflow:auto;display:block;max-width:420px;font-size:11.5px;line-height:1.5}}
.cmp-t .pcell .pk2{{color:var(--data);font-weight:600}}
.cmp-t .has{{color:var(--good);font-weight:600}}
.cmp-t .not{{color:var(--ink-3)}}

/* ---- flags, comments, best practices ---- */
.flagbtn{{background:transparent;border:1px solid var(--line);color:var(--ink-3);border-radius:var(--r-sm);
  padding:2px 9px;font-size:11px;font-family:var(--mono);cursor:pointer;float:right;margin-left:6px}}
.exportbtn{{display:none;background:transparent;border:1px solid var(--line);color:var(--ink-3);
  border-radius:var(--r-sm);padding:2px 9px;font-size:11px;font-family:var(--mono);cursor:pointer;
  float:right;margin-left:6px}}
body.apilive .exportbtn{{display:inline-block}}
.exportbtn:hover{{color:var(--ink);border-color:var(--line-2)}}
.flagbtn.on{{background:oklch(0.30 0.09 25);border-color:oklch(0.55 0.16 25);color:oklch(0.88 0.06 25)}}
.card.flagged{{border-color:oklch(0.50 0.16 25)}}
.card.flagged .vidbox{{opacity:.55}}
.card.flagged .fn::after{{content:"  — FLAGGED FOR DELETION";color:oklch(0.75 0.15 25);font-size:10.5px}}
.cmts{{margin-top:7px;border-top:1px dashed var(--line);padding-top:6px}}
.cmts .c1{{font-size:12px;color:var(--ink-2);padding:3px 0;line-height:1.45;border-bottom:1px solid var(--line)}}
.cmts .c1 .ts{{color:var(--ink-3);font-family:var(--mono);font-size:10.5px;margin-right:7px}}
.cmts textarea{{width:100%;background:var(--bg);border:1px solid var(--line);border-radius:var(--r-sm);
  color:var(--ink);font-size:12.5px;font-family:inherit;padding:6px 8px;resize:vertical;min-height:34px;margin-top:6px}}
.cmts .crow{{display:flex;gap:6px;margin-top:5px;align-items:center}}
.cmts button{{background:var(--surface-2);border:1px solid var(--line-2);color:var(--ink-2);border-radius:var(--r-sm);
  padding:4px 12px;font-size:11.5px;cursor:pointer}}
.cmts .apinote{{color:var(--ink-3);font-size:11px;font-style:italic}}
/* Best Practices content - no wrapper/accordion, it just IS the practices tabpage's content now */
#bpbody pre{{white-space:pre-wrap;font-family:var(--mono);font-size:12.5px;line-height:1.65;color:var(--ink-2);
  margin:0;max-width:100ch}}
#bpbody textarea{{width:100%;min-height:420px;background:var(--bg);border:1px solid var(--line);
  border-radius:var(--r-sm);color:var(--ink);font-family:var(--mono);font-size:12.5px;line-height:1.6;padding:10px}}
#bpbody .bprow{{display:flex;gap:8px;margin-top:9px;align-items:center}}
#bpbody .bprow button{{background:var(--accent-dim);border:1px solid var(--accent);color:var(--ink);
  border-radius:var(--r-sm);padding:6px 14px;font-size:12.5px;cursor:pointer}}
#bpbody .bprow button.ghost{{background:transparent;border-color:var(--line-2);color:var(--ink-3)}}
/* Saved tab: review surface for anything flagged and/or commented */
.savedrow{{margin:0 16px 12px;background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:12px 14px;max-width:900px}}
.savedrow.flagged{{border-color:oklch(0.50 0.16 25)}}
.savedrow h3{{margin:0 0 4px;font-size:13.5px;font-family:var(--mono);color:var(--ink)}}
.savedrow .srmeta{{display:flex;gap:10px;align-items:center;margin-bottom:6px}}
.savedempty{{margin:24px 16px;color:var(--ink-3);font-size:13.5px}}
.fn{{font-family:var(--mono);font-size:13px;font-weight:600;color:var(--ink);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.35}}
.fd{{color:var(--ink-3);font-size:11.5px;font-family:var(--mono);margin-top:3px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
/* experiment summary: quiet structured readout, below the video/live block */
.exp{{color:var(--ink-2);font-size:12px;line-height:1.5;font-family:var(--mono);
  background:var(--bg);border:1px solid var(--line);border-radius:var(--r-sm);
  padding:7px 9px;margin-top:9px}}
.vidbox{{line-height:0;position:relative;background:#000;border-radius:var(--r-sm);overflow:hidden}}
.vidbox video{{width:100%;aspect-ratio:1/1;display:block;background:#000}}
.vidbox::after{{content:"loading video…";position:absolute;inset:0;display:grid;place-items:center;
  color:var(--ink-3);font-size:12px;font-family:var(--mono);pointer-events:none;opacity:0}}


/* ---- live readout: the actual product ---- */
.live{{margin-top:9px;background:var(--bg);border:1px solid var(--line);border-radius:var(--r-sm);padding:9px 10px}}
body.nolive .live{{display:none}}
.lrow{{font-size:13.5px;line-height:1.5;padding:1.5px 0;display:flex;gap:8px;align-items:baseline}}
.lrow.hint{{color:var(--ink-3);font-size:12.5px;display:block}}
.lrow .lbl{{color:var(--ink-3);font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;
  text-transform:uppercase;flex:0 0 62px}}
.lrow.frame{{color:var(--ink-3);font-family:var(--mono);font-size:11.5px}}
.lrow.fov{{color:var(--data);font-family:var(--mono);font-size:17px;font-weight:650;
  font-variant-numeric:tabular-nums}}
.lrow.cam{{color:var(--ink-2);font-family:var(--mono);font-size:12px;font-variant-numeric:tabular-nums;
  flex-wrap:wrap}}
.lrow.cam .an{{color:var(--data)}}
.lrow.scene{{color:var(--ink);font-size:13.5px;display:block}}
.lrow.lora{{color:var(--ink-2);font-family:var(--mono);font-size:12px;flex-wrap:wrap}}
.lrow.sched{{color:var(--ink-2);font-family:var(--mono);font-size:12px;font-variant-numeric:tabular-nums}}
.lrow.up{{color:var(--ink-3);font-family:var(--mono);font-size:11.5px;border-top:1px solid var(--line);
  margin-top:6px;padding-top:6px}}
/* changed marker carries a text glyph too, never colour alone (colourblind-safe) */
.lrow .chg{{background:var(--good-bg);color:var(--good);font-weight:600;padding:0 5px;
  border-radius:3px;font-family:var(--mono)}}
.lrow .chg::before{{content:"▸ "}}

/* ---- settings: collapsed by default; density on demand ---- */
.settings{{margin-top:9px;border-top:1px solid var(--line);padding-top:7px}}
.settings summary{{cursor:pointer;color:var(--ink-3);font-size:11px;font-family:var(--mono);
  letter-spacing:.06em;text-transform:uppercase;list-style:none;user-select:none}}
.settings summary::-webkit-details-marker{{display:none}}
.settings summary::before{{content:"▸ ";display:inline-block;transition:transform .15s var(--ease)}}
.settings[open] summary::before{{content:"▾ "}}
.settings summary:hover{{color:var(--ink-2)}}
.srow{{display:flex;justify-content:space-between;gap:10px;padding:3px 5px;border-radius:3px;font-size:12px}}
.srow:nth-child(even){{background:var(--bg)}}
.srow .sk{{color:var(--ink-3);font-family:var(--mono);white-space:nowrap;font-size:11.5px}}
.srow .sv{{color:var(--ink-2);font-family:var(--mono);text-align:right;word-break:break-word;font-size:11.5px}}
.empty{{color:var(--ink-3);font-size:14px;padding:56px 18px;text-align:center;width:100%}}
.empty b{{color:var(--ink-2);font-weight:600}}
@media (prefers-reduced-motion:reduce){{
  *,*::before,*::after{{transition-duration:.01ms !important;animation-duration:.01ms !important}}
}}
{EXTRA_CSS}
</style></head><body>
<div class="ctl">
  <div class="ctl-row">
    <h1>{PAGE_TITLE}</h1>
    <select id="sort" title="Sort renders">
      <option value="new">Newest first</option>
      <option value="old">Oldest first</option>
      <option value="name">Name A&ndash;Z</option>
      <option value="frames">Most frames</option>
      <option value="dur">Longest</option>
    </select>
    <span class="count" id="count"></span>
    <label class="mini" title="One row: a single horizontal strip (49-inch friendly). Grid: wrapped cards, you set how many across. Rows: one render per full-width row, settings spread into columns.">View
      <select id="viewsel">
        <option value="strip">One row (scroll across)</option>
        <option value="grid">Grid</option>
        <option value="list">Rows</option>
      </select>
    </label>
    <span class="mini" id="gcwrap">across <input type="number" id="gridcols" min="1" max="12" value="4" style="width:52px"></span>
    <label class="mini"><input type="checkbox" id="flagchk"> flagged only</label>
    <span class="mini" id="szwrap">Card size <input type="range" id="sz" min="340" max="900" value="460" step="20"></span>
    <label class="mini"><input type="checkbox" id="livechk" checked> live panel</label>
  </div>
</div>
{EXTRA_HTML_HEAD.replace("__LIBLINE__", LIB_LINE)}
<div class="grid">{"".join(cards)}</div>
{EXTRA_HTML_TAIL}
<script>
var DATA={json.dumps(DATA)};
var BUILTIN_PRESETS={json.dumps(PRESETS)};
var NOTES_INIT={json.dumps(load_notes_snapshot())};
var camFns={{}};
for(var pid in DATA){{camFns[pid]={{}};for(var lab in DATA[pid].cam){{try{{camFns[pid][lab]=new Function('t','return ('+DATA[pid].cam[lab].js+');');}}catch(e){{camFns[pid][lab]=function(){{return NaN;}};}}}}}}
function esc(s){{var d=document.createElement('div');d.textContent=s;return d.innerHTML;}}
function fmtn(v){{return isNaN(v)?'?':(Math.abs(v)>=10?v.toFixed(0):v.toFixed(2));}}
function kfIdx(kf,fr){{var idx=0;for(var i=0;i<kf.length;i++){{if(kf[i][0]<=fr)idx=i;else break;}}return idx;}}
function schedAt(sc,fr){{var v=sc[0][1];for(var i=0;i<sc.length;i++){{if(sc[i][0]<=fr)v=sc[i][1];else break;}}return v;}}
function upd(v){{
  var pid=v.dataset.pid,D=DATA[pid];if(!D)return;var fr=Math.floor(v.currentTime*D.fps);
  var fov=camFns[pid]['FOV']?camFns[pid]['FOV'](fr):NaN;
  var cam=D.camlabels.filter(function(l){{return l!=='FOV';}}).map(function(l){{
    var val=camFns[pid][l]?camFns[pid][l](fr):NaN;
    return '<span class="'+(D.cam[l]&&D.cam[l].anim?'an':'')+'">'+l+' '+fmtn(val)+'</span>';}}).join(' &nbsp; ');
  var h='<div class="lrow frame">frame '+fr+' &middot; '+v.currentTime.toFixed(1)+'s</div>'
      +'<div class="lrow fov">FOV '+fmtn(fov)+'</div><div class="lrow cam">'+cam+'</div>';
  if(D.kf.length){{
    var i=kfIdx(D.kf,fr), cur=D.kf[i], prev=i>0?D.kf[i-1]:null, next=i<D.kf.length-1?D.kf[i+1]:null;
    h+='<div class="lrow scene"><span class="lbl">PROMPT</span>'+esc(cur[1])+'</div>';
    // LoRAs: green = just changed at this keyframe (not in previous)
    var curL=cur[2]||[], prevL=prev?prev[2]||[]:[];
    var lh=curL.map(function(n){{return prevL.indexOf(n)<0?'<span class="chg">'+esc(n)+'</span>':esc(n);}}).join(', ')||'&mdash;';
    h+='<div class="lrow lora"><span class="lbl">LORAS</span>'+lh+'</div>';
    // strength / noise: value at this keyframe, green if it changed since previous keyframe
    ['strength','noise'].forEach(function(key){{
      var val=schedAt(D[key],cur[0]), pv=prev?schedAt(D[key],prev[0]):val;
      var cls=(prev&&val!==pv)?' chg':'';
      h+='<div class="lrow sched"><span class="lbl">'+key.toUpperCase()+'</span><span class="'+cls.trim()+'">'+val
        +(prev&&val!==pv?' (was '+pv+')':'')+'</span></div>';
    }});
    // UPCOMING: what changes at the next keyframe
    if(next){{
      var nAdd=(next[2]||[]).filter(function(n){{return curL.indexOf(n)<0;}});
      var up=[]; if(nAdd.length)up.push('+LoRA '+nAdd.join(', '));
      ['strength','noise'].forEach(function(key){{var nv=schedAt(D[key],next[0]),cv=schedAt(D[key],cur[0]);if(nv!==cv)up.push(key+'->'+nv);}});
      var secs=((next[0]-fr)/D.fps).toFixed(0);
      h+='<div class="lrow up"><span class="lbl">NEXT in '+secs+'s</span>'+(up.length?esc(up.join(' , ')):'new scene')+'</div>';
    }}
  }}
  document.getElementById('live-'+pid).innerHTML=h;
}}
document.querySelectorAll('video').forEach(function(v){{['timeupdate','seeked','play'].forEach(function(e){{v.addEventListener(e,function(){{upd(v);}});}});}});
document.getElementById('sz').addEventListener('input',function(e){{document.documentElement.style.setProperty('--cw',e.target.value+'px');document.getElementById('szval').textContent=e.target.value+'px';}});
document.getElementById('livechk').addEventListener('change',function(){{document.body.classList.toggle('nolive',!this.checked);}});

/* ===================== FIND =====================
   Two real problems this fixes:
   1. 111 <video preload="metadata"> fired 111 range requests at multi-hundred-MB files on page load.
      Now every video carries preload="none", which means the browser fetches NOTHING until the user
      actually presses play (measured: src set on all 111 -> 0 fetched data). No IntersectionObserver
      gating: an observer that silently never fires in some renderers would ship a permanently blank
      gallery, and preload="none" already achieves the same cost profile with no moving parts.
   2. 111 cards in one 34,000px wall with no way to find anything. Search/filter/sort added.  */
var cardsAll=[].slice.call(document.querySelectorAll('.card[data-pid]'));
var gridEl=document.querySelector('.grid');

// --- facet chips built from what's actually in the library ---
var activeFacets={{}};
function facetCounts(){{
  var ck={{}}, tg={{}};
  cardsAll.forEach(function(c){{
    var k=c.dataset.ckpt||'none'; ck[k]=(ck[k]||0)+1;
    (c.dataset.tags||'').split(/\\s+/).filter(Boolean).forEach(function(t){{ tg[t]=(tg[t]||0)+1; }});
  }});
  return {{ck:ck,tg:tg}};
}}
function buildChips(){{
  var el=document.getElementById('chips'); if(!el) return;
  var f=facetCounts();
  function add(group,val,label,n){{
    var b=document.createElement('button');
    b.className='chip'; b.type='button'; b.setAttribute('aria-pressed','false');
    b.textContent=label;
    var s=document.createElement('span'); s.className='n'; s.textContent=n; b.appendChild(s);
    b.addEventListener('click',function(){{
      var key=group+':'+val;
      if(activeFacets[key]) delete activeFacets[key]; else activeFacets[key]=true;
      b.setAttribute('aria-pressed', activeFacets[key]?'true':'false');
      applyFilter();
    }});
    el.appendChild(b);
  }}
  Object.keys(f.ck).sort().forEach(function(k){{ if(k!=='none') add('ckpt',k,k,f.ck[k]); }});
  Object.keys(f.tg).sort().forEach(function(t){{ add('tag',t,t,f.tg[t]); }});
}}

function applyFilter(){{
  var _qe=document.getElementById('q');
  var q=_qe?(_qe.value||'').trim().toLowerCase():'';
  var terms=q?q.split(/\\s+/):[];
  var ckSel=Object.keys(activeFacets).filter(function(k){{return k.indexOf('ckpt:')===0;}}).map(function(k){{return k.slice(5);}});
  var tgSel=Object.keys(activeFacets).filter(function(k){{return k.indexOf('tag:')===0;}}).map(function(k){{return k.slice(4);}});
  var shown=0;
  cardsAll.forEach(function(c){{
    var hay=c.dataset.hay||'';
    var okQ=terms.every(function(t){{ return hay.indexOf(t)!==-1; }});
    var okCk=!ckSel.length || ckSel.indexOf(c.dataset.ckpt)!==-1;                       // OR within checkpoint
    var tags=(c.dataset.tags||'').split(/\\s+/);
    var okTg=!tgSel.length || tgSel.every(function(t){{ return tags.indexOf(t)!==-1; }}); // AND across tags
    var vis=okQ&&okCk&&okTg;
    c.hidden=!vis; if(vis) shown++;
  }});
  var cEl=document.getElementById('count');
  if(cEl){{
    cEl.textContent='';
    var b=document.createElement('b'); b.textContent=shown;
    cEl.appendChild(b); cEl.appendChild(document.createTextNode(' of '+cardsAll.length+' renders'));
  }}
  var emp=document.getElementById('emptystate');
  if(emp) emp.remove();
  if(shown===0 && gridEl){{
    emp=document.createElement('div'); emp.className='empty'; emp.id='emptystate';
    var bb=document.createElement('b');
    if(cardsAll.length===0){{
      bb.textContent='No renders loaded yet.';
      emp.appendChild(bb);
      emp.appendChild(document.createTextNode(' Drag & drop a rendered .mp4 + its _settings.txt (or a whole folder) into the box above, or use Browse.'));
    }} else {{
      bb.textContent='Nothing matches your filter.';
      emp.appendChild(bb);
      emp.appendChild(document.createTextNode(' Untick "flagged only" (or adjust the filter) to see the library again.'));
    }}
    gridEl.appendChild(emp);
  }}
}}

function applySort(){{
  var mode=document.getElementById('sort').value;
  var sorted=cardsAll.slice().sort(function(a,b){{
    if(mode==='new')    return (+b.dataset.mtime)-(+a.dataset.mtime);
    if(mode==='old')    return (+a.dataset.mtime)-(+b.dataset.mtime);
    if(mode==='name')   return (a.dataset.name||'').localeCompare(b.dataset.name||'');
    if(mode==='frames') return (+b.dataset.frames)-(+a.dataset.frames);
    if(mode==='dur')    return (+b.dataset.dur)-(+a.dataset.dur);
    return 0;
  }});
  var frag=document.createDocumentFragment();
  sorted.forEach(function(c){{ frag.appendChild(c); }});
  if(gridEl) gridEl.appendChild(frag);
}}

var _qt=null;
var qEl=document.getElementById('q');
if(qEl){{
  qEl.addEventListener('input',function(){{ clearTimeout(_qt); _qt=setTimeout(applyFilter,110); }});
  qEl.addEventListener('keydown',function(e){{ if(e.key==='Escape'){{ qEl.value=''; applyFilter(); qEl.blur(); }} }});
}}
document.addEventListener('keydown',function(e){{
  if(e.key==='/' && document.activeElement!==qEl && !/^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement||{{}}).tagName||'')){{
    e.preventDefault(); if(qEl) qEl.focus();
  }}
}});
var sortEl=document.getElementById('sort');
if(sortEl) sortEl.addEventListener('change',applySort);
buildChips(); applyFilter();
{EXTRA_JS}
</script>
</body></html>'''
with open(OUT, "w", encoding="utf-8") as f:
    f.write(doc)
print("Wrote:", OUT)
print(f"{len(keep)} renders in gallery | {trashed} duplicate/bad moved to _trash_review")
