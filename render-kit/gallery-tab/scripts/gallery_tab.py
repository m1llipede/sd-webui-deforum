"""Render Gallery tab (Brian: 'add the comparison website right into the Deforum Stable Diffusion
site, so it's all in one place').

A tiny standalone extension - deliberately NOT part of the deforum extension folder, so updating or
reinstalling Deforum can never take it out, and vice versa.

How it works:
  - on_app_started: mounts outputs/img2img-images as a static route at /deforum-gallery, so
    /deforum-gallery/_MASTER_GALLERY.html serves the comparison page and every relative video URL
    inside it (e.g. +Master_Deforum_Renders/xxx.mp4) resolves and range-streams correctly.
  - on_ui_tabs: adds a "Render Gallery" tab beside Deforum containing that page in an iframe,
    plus a Rebuild button that re-runs _build_gallery.py (picks up new finished renders) and
    cache-busts the iframe.
WebUI binds 127.0.0.1, so the mount exposes nothing beyond this machine.
"""
import os
import subprocess
import sys
import time

import gradio as gr
from modules import script_callbacks

WEBUI_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
IMG_ROOT = os.path.join(WEBUI_ROOT, "outputs", "img2img-images")
GALLERY_HTML = os.path.join(IMG_ROOT, "_MASTER_GALLERY.html")
BUILDER = os.path.join(WEBUI_ROOT, "_build_gallery.py")
MOUNT = "/deforum-gallery"


def _mount_static(demo, app):
    try:
        from starlette.staticfiles import StaticFiles
        from starlette.responses import Response, StreamingResponse
        if not os.path.isdir(IMG_ROOT):
            print(f"[deforum-gallery] missing dir, not mounted: {IMG_ROOT}")
            return

        # Explicit mp4 route WITH HTTP Range support, registered before the static mount so it wins.
        # The bundled starlette is too old to honor Range on StaticFiles, and without 206 responses
        # every seek in a 700MB render re-downloads the whole file - scrubbing is the entire point
        # of the comparison page, so this matters.
        from fastapi import Request

        async def _video_route(path: str, request: Request):
            full = os.path.normpath(os.path.join(IMG_ROOT, path + ".mp4"))
            if not full.startswith(os.path.normpath(IMG_ROOT)) or not os.path.isfile(full):
                return Response(status_code=404)
            size = os.path.getsize(full)
            rng = request.headers.get("range")
            start, end = 0, size - 1
            status = 200
            if rng and rng.startswith("bytes="):
                try:
                    s, _, e = rng[6:].partition("-")
                    start = int(s) if s else 0
                    end = int(e) if e else size - 1
                    end = min(end, size - 1)
                    if start > end or start >= size:
                        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
                    status = 206
                except ValueError:
                    start, end, status = 0, size - 1, 200
            length = end - start + 1

            def reader(s=start, remaining=length):
                with open(full, "rb") as fh:
                    fh.seek(s)
                    while remaining > 0:
                        chunk = fh.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            headers = {"Accept-Ranges": "bytes", "Content-Length": str(length),
                       "Content-Type": "video/mp4"}
            if status == 206:
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            return StreamingResponse(reader(), status_code=status, headers=headers)

        app.add_api_route(MOUNT + "/{path:path}.mp4", _video_route, methods=["GET"])

        # ---- comments / deletion-flags / best-practices, persisted to the project folder ----
        # One human-readable JSON at outputs/img2img-images/_gallery_data/gallery_notes.json.
        # Keyed by render NAME (not page-load ids) so notes survive gallery rebuilds.
        import json as _json
        import threading as _threading
        NOTES_PATH = os.path.join(IMG_ROOT, "_gallery_data", "gallery_notes.json")
        _notes_lock = _threading.Lock()

        def _load_notes():
            try:
                with open(NOTES_PATH, encoding="utf-8") as fh:
                    n = _json.load(fh)
            except Exception:
                n = {}
            n.setdefault("comments", {})
            n.setdefault("flags", [])
            n.setdefault("best_practices", "")
            return n

        def _save_notes(n):
            os.makedirs(os.path.dirname(NOTES_PATH), exist_ok=True)
            tmp = NOTES_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                _json.dump(n, fh, indent=4, ensure_ascii=False)
            os.replace(tmp, NOTES_PATH)   # atomic - a crash can't half-write the notes file

        async def _api_state():
            with _notes_lock:
                return _load_notes()

        async def _api_comment(request: Request):
            b = await request.json()
            name, text = str(b.get("name", ""))[:300], str(b.get("text", ""))[:4000]
            if not name or not text.strip():
                return {"ok": False, "error": "name and text required"}
            with _notes_lock:
                n = _load_notes()
                n["comments"].setdefault(name, []).append(
                    {"text": text.strip(), "ts": time.strftime("%Y-%m-%d %H:%M")})
                _save_notes(n)
                return {"ok": True, "comments": n["comments"][name]}

        async def _api_flag(request: Request):
            b = await request.json()
            name, flagged = str(b.get("name", ""))[:300], bool(b.get("flagged"))
            if not name:
                return {"ok": False, "error": "name required"}
            with _notes_lock:
                n = _load_notes()
                flags = set(n["flags"])
                (flags.add if flagged else flags.discard)(name)
                n["flags"] = sorted(flags)
                _save_notes(n)
                return {"ok": True, "flags": n["flags"]}

        async def _api_bp(request: Request):
            b = await request.json()
            with _notes_lock:
                n = _load_notes()
                n["best_practices"] = str(b.get("text", ""))[:100000]
                _save_notes(n)
                return {"ok": True}

        # ---- export: one click -> a zip of the render's mp4 + its settings.txt, for sharing ----
        # (Deforum already writes them side by side; this just bundles the pair so Brian can hand
        # a single file to Vello. ZIP_STORED - the mp4 is already compressed, recompressing is waste.)
        import zipfile as _zipfile
        from starlette.responses import FileResponse
        EXPORT_TMP = os.path.join(IMG_ROOT, "_gallery_data", "exports")

        def _find_render_pair(name):
            """Locate <name>.mp4 and its settings file anywhere under the outputs tree."""
            mp4 = sett = None
            for dp, dn, fn in os.walk(IMG_ROOT):
                if "_gallery_data" in dp or "_trash_review" in dp:
                    continue
                if mp4 is None and (name + ".mp4") in fn:
                    mp4 = os.path.join(dp, name + ".mp4")
                if sett is None and (name + "_settings.txt") in fn:
                    sett = os.path.join(dp, name + "_settings.txt")
                if mp4 and sett:
                    break
            return mp4, sett

        async def _api_export(name: str = ""):
            name = os.path.basename(str(name or "").strip())   # no path tricks
            if not name:
                return Response(status_code=400)
            mp4, sett = _find_render_pair(name)
            if not mp4:
                return Response(content=f"no mp4 found for {name}", status_code=404)
            os.makedirs(EXPORT_TMP, exist_ok=True)
            for old in os.listdir(EXPORT_TMP):                 # keep the tmp folder from growing
                try:
                    os.remove(os.path.join(EXPORT_TMP, old))
                except Exception:
                    pass
            out = os.path.join(EXPORT_TMP, name + ".zip")
            with _zipfile.ZipFile(out, "w", _zipfile.ZIP_STORED) as z:
                z.write(mp4, os.path.basename(mp4))
                if sett:
                    z.write(sett, os.path.basename(sett))
            return FileResponse(out, filename=name + ".zip", media_type="application/zip")

        # ---- configurable folders + LIVE library scan (nothing baked into the page) ----
        # Brian: "I don't want anything baked in. I need to be able to select the output and also
        # the input image or video or controlnet directories." Config persists in the project
        # folder; /scan walks the chosen renders dir on demand and returns the library as JSON,
        # so the page always shows the CURRENT folder contents, not a build-time snapshot.
        CONFIG_PATH = os.path.join(IMG_ROOT, "_gallery_data", "config.json")
        DEFAULT_DIRS = {
            "renders": IMG_ROOT,
            "init": os.path.join(IMG_ROOT, "INIT_IMAGES"),
            "video": os.path.join(WEBUI_ROOT, "outputs", "deforum_video_inputs"),
            "cn": os.path.join(WEBUI_ROOT, "outputs", "controlnet_inputs"),
        }
        SCAN_EXCLUDE = {"_render_queue", "_trash_review", "_deferred_old_batch", "_thumbs",
                        "_gallery_data", "_contact_sheet", "_contact_sheets", "INIT_IMAGES"}
        THUMBS_DIR = os.path.join(IMG_ROOT, "_thumbs")

        def _load_config():
            try:
                with open(CONFIG_PATH, encoding="utf-8") as fh:
                    c = _json.load(fh)
            except Exception:
                c = {}
            dirs = dict(DEFAULT_DIRS)
            dirs.update({k: v for k, v in (c.get("dirs") or {}).items() if v})
            return {"dirs": dirs}

        def _save_config(c):
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                _json.dump(c, fh, indent=4)
            os.replace(tmp, CONFIG_PATH)

        def _in_allowed_dir(path):
            rp = os.path.realpath(path)
            for d in _load_config()["dirs"].values():
                if rp.startswith(os.path.realpath(d)):
                    return True
            return False

        def _ffmpeg():
            import shutil as _sh
            cand = os.path.join(os.path.dirname(
                r"C:\Users\Dev\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe"), "ffmpeg.exe")
            return cand if os.path.isfile(cand) else (_sh.which("ffmpeg") or "ffmpeg")

        def _ensure_thumb(mp4, name):
            os.makedirs(THUMBS_DIR, exist_ok=True)
            out = os.path.join(THUMBS_DIR, name + ".jpg")
            if os.path.isfile(out) and os.path.getsize(out) > 1000:
                return out
            try:
                subprocess.run([_ffmpeg(), "-y", "-ss", "8", "-i", mp4, "-frames:v", "1",
                                "-vf", "scale=512:-2", "-q:v", "4", out],
                               capture_output=True, timeout=45)
                if os.path.isfile(out) and os.path.getsize(out) > 1000:
                    return out
            except Exception:
                pass
            return None

        async def _api_config_get():
            return _load_config()

        async def _api_config_set(request: Request):
            b = await request.json()
            dirs = {k: str(v).strip() for k, v in (b.get("dirs") or {}).items()
                    if k in DEFAULT_DIRS and str(v).strip()}
            bad = {k: v for k, v in dirs.items() if not os.path.isdir(v)}
            if bad:
                return {"ok": False, "error": "not a folder: " + "; ".join(f"{k}={v}" for k, v in bad.items())}
            c = _load_config()
            c["dirs"].update(dirs)
            _save_config(c)
            return {"ok": True, "dirs": c["dirs"]}

        async def _api_scan():
            root = _load_config()["dirs"]["renders"]
            if not os.path.isdir(root):
                return {"ok": False, "error": f"renders folder missing: {root}", "renders": []}
            entries, seen = [], set()
            for dp, dn, fn in os.walk(root):
                dn[:] = [d for d in dn if d not in SCAN_EXCLUDE]
                for f in fn:
                    if not f.lower().endswith(".mp4"):
                        continue
                    name = f[:-4]
                    if name in seen:
                        continue
                    seen.add(name)
                    mp4 = os.path.join(dp, f)
                    sett_path = os.path.join(dp, name + "_settings.txt")
                    settings = None
                    if os.path.isfile(sett_path):
                        try:
                            with open(sett_path, encoding="utf-8-sig") as fh:
                                settings = _json.load(fh)
                        except Exception:
                            settings = None
                    thumb = _ensure_thumb(mp4, name)
                    entries.append({
                        "name": name,
                        "video": MOUNT + "-api/file?p=" + mp4.replace("\\", "/"),
                        "poster": (MOUNT + "/_thumbs/" + name + ".jpg") if thumb else None,
                        "settings": settings,
                        "mtime": int(os.path.getmtime(mp4)),
                        "size": os.path.getsize(mp4),
                    })
            entries.sort(key=lambda e: -e["mtime"])
            return {"ok": True, "root": root, "renders": entries}

        async def _api_file(p: str = "", request: Request = None):
            full = os.path.realpath(str(p or ""))
            if not full or not os.path.isfile(full) or not _in_allowed_dir(full):
                return Response(status_code=404)
            size = os.path.getsize(full)
            rng = request.headers.get("range") if request else None
            start, end, status = 0, size - 1, 200
            if rng and rng.startswith("bytes="):
                try:
                    s, _, e = rng[6:].partition("-")
                    start = int(s) if s else 0
                    end = min(int(e) if e else size - 1, size - 1)
                    if start > end or start >= size:
                        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
                    status = 206
                except ValueError:
                    start, end, status = 0, size - 1, 200
            length = end - start + 1

            def rd(s=start, remaining=length):
                with open(full, "rb") as fh:
                    fh.seek(s)
                    while remaining > 0:
                        ch = fh.read(min(1 << 20, remaining))
                        if not ch:
                            break
                        remaining -= len(ch)
                        yield ch

            ctype = "video/mp4" if full.lower().endswith(".mp4") else "application/octet-stream"
            hdrs = {"Accept-Ranges": "bytes", "Content-Length": str(length), "Content-Type": ctype}
            if status == 206:
                hdrs["Content-Range"] = f"bytes {start}-{end}/{size}"
            return StreamingResponse(rd(), status_code=status, headers=hdrs)

        async def _api_upload(request: Request, cat: str = "", name: str = ""):
            cat = str(cat)
            if cat not in ("init", "video", "cn"):
                return {"ok": False, "error": "cat must be init|video|cn"}
            fname = os.path.basename(str(name or "")).strip()
            if not fname or len(fname) > 200:
                return {"ok": False, "error": "bad filename"}
            dirs = _load_config()["dirs"]
            os.makedirs(dirs[cat], exist_ok=True)
            dst = os.path.join(dirs[cat], fname)
            stem, ext = os.path.splitext(fname)
            n = 2
            while os.path.exists(dst):
                dst = os.path.join(dirs[cat], f"{stem}_{n}{ext}")
                n += 1
            body = await request.body()
            if not body:
                return {"ok": False, "error": "empty file"}
            with open(dst, "wb") as fh:
                fh.write(body)
            return {"ok": True, "saved": dst}

        # ---- server-side folder browser: the page can't get real filesystem paths from the
        # browser's own pickers (browsers hide absolute paths), so Browse... walks the disk
        # here: empty path lists drives, otherwise lists subfolders of the given folder.
        async def _api_browse(path: str = ""):
            import string as _string
            p = str(path or "").strip()
            if not p:
                drives = [f"{d}:\\" for d in _string.ascii_uppercase if os.path.isdir(f"{d}:\\")]
                return {"ok": True, "path": "", "parent": None, "dirs": drives, "isRoot": True}
            p = os.path.realpath(p)
            if not os.path.isdir(p):
                return {"ok": False, "error": "not a folder: " + p}
            try:
                subs = [d for d in sorted(os.listdir(p), key=str.lower)
                        if os.path.isdir(os.path.join(p, d)) and not d.startswith("$")]
            except PermissionError:
                return {"ok": False, "error": "permission denied: " + p}
            parent = os.path.dirname(p.rstrip("\\/"))
            if not parent or parent == p:
                parent = ""          # drive root -> back to the drives list
            return {"ok": True, "path": p, "parent": parent, "dirs": subs, "isRoot": False}

        API = "/deforum-gallery-api"
        app.add_api_route(API + "/browse", _api_browse, methods=["GET"])
        app.add_api_route(API + "/state", _api_state, methods=["GET"])
        app.add_api_route(API + "/comment", _api_comment, methods=["POST"])
        app.add_api_route(API + "/flag", _api_flag, methods=["POST"])
        app.add_api_route(API + "/bestpractices", _api_bp, methods=["POST"])
        app.add_api_route(API + "/export", _api_export, methods=["GET"])
        app.add_api_route(API + "/config", _api_config_get, methods=["GET"])
        app.add_api_route(API + "/config", _api_config_set, methods=["POST"])
        app.add_api_route(API + "/scan", _api_scan, methods=["GET"])
        app.add_api_route(API + "/file", _api_file, methods=["GET"])
        app.add_api_route(API + "/upload", _api_upload, methods=["POST"])

        app.mount(MOUNT, StaticFiles(directory=IMG_ROOT, html=True), name="deforum-gallery")
        print(f"[deforum-gallery] mounted {IMG_ROOT} at {MOUNT} (mp4 Range streaming + notes API enabled)")
    except Exception as e:
        print(f"[deforum-gallery] mount failed: {e}")


def _iframe_html():
    if not os.path.isfile(GALLERY_HTML):
        return ("<div style='padding:24px;font-size:14px'>No gallery built yet - click "
                "<b>Rebuild gallery</b> to generate it.</div>")
    v = int(os.path.getmtime(GALLERY_HTML))  # cache-buster so Rebuild shows fresh content
    return (f'<iframe src="{MOUNT}/_MASTER_GALLERY.html?v={v}" '
            f'style="width:100%;height:calc(100vh - 180px);border:0;border-radius:8px;background:#0d0f15"></iframe>')


def _rebuild():
    if not os.path.isfile(BUILDER):
        return _iframe_html(), f"builder not found: {BUILDER}"
    try:
        r = subprocess.run([sys.executable, BUILDER], cwd=WEBUI_ROOT,
                           capture_output=True, text=True, timeout=600)
        tail = (r.stdout or "").strip().splitlines()
        msg = tail[-1] if tail else ("exit " + str(r.returncode))
        if r.returncode != 0:
            err = (r.stderr or "").strip().splitlines()
            msg = "rebuild FAILED: " + (err[-1] if err else f"exit {r.returncode}")
        return _iframe_html(), f"[{time.strftime('%H:%M:%S')}] {msg}"
    except Exception as e:
        return _iframe_html(), f"rebuild error: {e}"


def _make_tab():
    with gr.Blocks(analytics_enabled=False) as tab:
        with gr.Row():
            rebuild_btn = gr.Button("Rebuild gallery (pick up new renders)", variant="primary", scale=1)
            status = gr.Textbox(value="", label="", interactive=False, scale=3, container=False)
        frame = gr.HTML(_iframe_html())
        rebuild_btn.click(fn=_rebuild, inputs=[], outputs=[frame, status])
    return [(tab, "Render Gallery", "deforum_render_gallery_tab")]


script_callbacks.on_app_started(_mount_static)
script_callbacks.on_ui_tabs(_make_tab)
