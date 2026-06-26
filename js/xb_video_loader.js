import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ============================================================
// 以下函数�?VHS.core.js 一字不差复�?
// ============================================================

function chainCallback(object, property, callback) {
    if (object == undefined) {
        console.error("Tried to add callback to non-existant object")
        return;
    }
    if (property in object && object[property]) {
        const callback_orig = object[property]
        object[property] = function () {
            const r = callback_orig.apply(this, arguments);
            return callback.apply(this, arguments) ?? r
        };
    } else {
        object[property] = callback;
    }
}

function fitHeight(node) {
    node.setSize([node.size[0], node.computeSize([node.size[0], node.size[1]])[1]])
    node?.graph?.setDirtyCanvas(true);
}

function allowDragFromWidget(widget) {
    widget.onPointerDown = function(pointer, node) {
        pointer.onDragStart = () => {
            app.canvas.emitBeforeChange()
            app.canvas.graph?.beforeChange()
            pointer.finally = () => {
                app.canvas.isDragging = false
                app.canvas.graph?.afterChange()
                app.canvas.emitAfterChange()
            }
            app.canvas.processSelect(node, pointer.eDown, true)
            app.canvas.isDragging = true
        }
        pointer.onDragEnd = (e) => {
            if (e.shiftKey || LiteGraph.alwaysSnapToGrid)
                app.canvas?.graph?.snapToGrid(app.canvas.selectedItems)
            app.canvas.dirty_canvas = true
            app.canvas.dirty_bgcanvas = true
            app.canvas.onNodeMoved?.(app.canvas.selectedItems.find(n => n))
        }
        app.canvas.dirty_canvas = true
        return true
    }
}

// ============================================================
// addVideoPreview �?原样保留，服务于 VideoLoader
// ============================================================
function addVideoPreview(nodeType, isInput=true) {
    chainCallback(nodeType.prototype, "onNodeCreated", function() {
        var element = document.createElement("div");
        const previewNode = this;
        var previewWidget = this.addDOMWidget("videopreview", "preview", element, {
            serialize: false,
            hideOnZoom: false,
            getValue() { return element.value; },
            setValue(v) { element.value = v; },
        });
        allowDragFromWidget(previewWidget)
        previewWidget.computeSize = function(width) {
            if (this.aspectRatio && !this.parentEl.hidden) {
                let height = (previewNode.size[0]-20)/ this.aspectRatio + 10;
                if (!(height > 0)) height = 0;
                this.computedHeight = height + 10;
                return [width, height];
            }
            return [width, -4];
        }
        element.addEventListener('contextmenu', (e) => { e.preventDefault(); return app.canvas._mousedown_callback(e) }, true);
        element.addEventListener('pointerdown', (e) => { e.preventDefault(); return app.canvas._mousedown_callback(e) }, true);
        element.addEventListener('mousewheel', (e) => { e.preventDefault(); return app.canvas._mousewheel_callback(e) }, true);
        element.addEventListener('pointermove', (e) => { e.preventDefault(); return app.canvas._mousemove_callback(e) }, true);
        element.addEventListener('pointerup', (e) => { e.preventDefault(); return app.canvas._mouseup_callback(e) }, true);
        element.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; app.dragOverNode = this })

        previewWidget.value = {hidden: false, paused: false, params: {}, muted: false}
        previewWidget.parentEl = document.createElement("div");
        previewWidget.parentEl.className = "vhs_preview";
        previewWidget.parentEl.style['width'] = "100%"
        element.appendChild(previewWidget.parentEl);
        previewWidget.videoEl = document.createElement("video");
        previewWidget.videoEl.controls = false;
        previewWidget.videoEl.loop = true;
        previewWidget.videoEl.muted = true;
        previewWidget.videoEl.style['width'] = "100%"
        previewWidget.videoEl.addEventListener("loadedmetadata", () => {
            previewWidget.aspectRatio = previewWidget.videoEl.videoWidth / previewWidget.videoEl.videoHeight;
            fitHeight(this);
        });
        previewWidget.videoEl.addEventListener("error", () => {
            previewWidget.parentEl.hidden = true;
            fitHeight(this);
        });
        previewWidget.videoEl.onmouseenter = () => { previewWidget.videoEl.muted = previewWidget.value.muted };
        previewWidget.videoEl.onmouseleave = () => { previewWidget.videoEl.muted = true };

        previewWidget.imgEl = document.createElement("img");
        previewWidget.imgEl.style['width'] = "100%"
        previewWidget.imgEl.hidden = true;
        previewWidget.imgEl.onload = () => {
            previewWidget.aspectRatio = previewWidget.imgEl.naturalWidth / previewWidget.imgEl.naturalHeight;
            fitHeight(this);
        };
        previewWidget.parentEl.appendChild(previewWidget.videoEl)
        previewWidget.parentEl.appendChild(previewWidget.imgEl)
        var timeout = null;
        this.updateParameters = (params, force_update) => {
            if (!previewWidget.value.params) {
                if(typeof(previewWidget.value) != 'object') {
                    previewWidget.value = {hidden: false, paused: false}
                }
                previewWidget.value.params = {}
            }
            if (!Object.entries(params).some(([k,v]) => previewWidget.value.params[k] !== v)) {
                return
            }
            Object.assign(previewWidget.value.params, params)
            if (timeout) { clearTimeout(timeout); }
            if (force_update) {
                previewWidget.updateSource();
            } else {
                timeout = setTimeout(() => previewWidget.updateSource(),100);
            }
        };
        previewWidget.updateSource = function () {
            if (this.value.params == undefined) { return; }
            let params = {}
            Object.assign(params, this.value.params);
            params.timestamp = Date.now()
            this.parentEl.hidden = this.value.hidden;
            if (params.format?.split('/')[0] == 'video' || params.format == 'folder') {
                this.videoEl.autoplay = !this.value.paused && !this.value.hidden;
                let target_width = (previewNode.size[0]-20)*2 || 256;
                if (!params.custom_width || !params.custom_height) {
                    params.force_size = target_width+"x?";
                } else {
                    let ar = params.custom_width/params.custom_height;
                    params.force_size = target_width+"x"+Math.round(target_width/ar);
                }
                this.videoEl.src = api.apiURL('/xb/viewvideo?' + new URLSearchParams(params));
                this.videoEl.hidden = false;
                this.imgEl.hidden = true;
            } else if (params.format?.split('/')[0] == 'image'){
                this.imgEl.src = api.apiURL('/view?' + new URLSearchParams(params));
                this.videoEl.hidden = true;
                this.imgEl.hidden = false;
            }
            delete previewNode.video_query
            const doQuery = async () => {
                if (!previewWidget?.value?.params?.filename) { return }
                let qurl = api.apiURL('/xb/queryvideo?' + new URLSearchParams(previewWidget.value.params))
                let query = undefined
                try {
                    let query_res = await fetch(qurl)
                    query = await query_res.json()
                } catch(e) { return }
                previewNode.video_query = query
            }
            doQuery()
        }
        previewWidget.callback = previewWidget.updateSource
        previewWidget.parentEl.appendChild(previewWidget.videoEl)
        previewWidget.parentEl.appendChild(previewWidget.imgEl)
    });
}

// ============================================================
// 右键菜单：暂停/隐藏/同步预览等
// ============================================================
function addPreviewOptions(nodeType) {
    chainCallback(nodeType.prototype, "getExtraMenuOptions", function(_, options) {
        let optNew = []
        const previewWidget = this.widgets.find((w) => w.name === "videopreview");
        if (!previewWidget) return;

        let url = null
        if (previewWidget.videoEl?.hidden == false && previewWidget.videoEl.src) {
            if (['input', 'output', 'temp'].includes(previewWidget.value.params.type)) {
                url = api.apiURL('/view?' + new URLSearchParams(previewWidget.value.params));
                url = url.replace('%2503d', '001')
            }
        } else if (previewWidget.imgEl?.hidden == false && previewWidget.imgEl.src) {
            url = previewWidget.imgEl.src;
        }

        if (this.video_query?.source) {
            let info = this.video_query.source.size.join('x') + '@' + this.video_query.source.fps + 'fps ' + this.video_query.source.frames + 'frames'
            optNew.push({content: info, disabled: true})
        }

        if (url) {
            optNew.push(
                {content: "Open preview", callback: () => window.open(url, "_blank")},
                {content: "Save preview", callback: () => {
                    const a = document.createElement("a");
                    a.href = url;
                    a.setAttribute("download", previewWidget.value.params.filename);
                    document.body.append(a);
                    a.click();
                    requestAnimationFrame(() => a.remove());
                }}
            );
            if (previewWidget.value.params.fullpath) {
                optNew.push({content: "Copy output filepath", callback: async () => {
                    const blob = new Blob([previewWidget.value.params.fullpath], {type: 'text/plain'})
                    await navigator.clipboard.write([new ClipboardItem({'text/plain': blob})])
                }});
            }
            if (previewWidget.value.params.workflow) {
                let wParams = {...previewWidget.value.params, filename: previewWidget.value.params.workflow}
                let wUrl = api.apiURL('/view?' + new URLSearchParams(wParams));
                optNew.push({content: "Save workflow image", callback: () => {
                    const a = document.createElement("a");
                    a.href = wUrl;
                    a.setAttribute("download", previewWidget.value.params.workflow);
                    document.body.append(a);
                    a.click();
                    requestAnimationFrame(() => a.remove());
                }});
            }
        }

        if (previewWidget.videoEl?.hidden == false) {
            const PauseDesc = (previewWidget.value.paused ? "Resume" : "Pause") + " preview";
            optNew.push({content: PauseDesc, callback: () => {
                if (previewWidget.value.paused) {
                    previewWidget.videoEl?.play();
                } else {
                    previewWidget.videoEl?.pause();
                }
                previewWidget.value.paused = !previewWidget.value.paused;
            }});
        }

        const visDesc = (previewWidget.value.hidden ? "Show" : "Hide") + " preview";
        optNew.push({content: visDesc, callback: () => {
            if (!previewWidget.videoEl.hidden && !previewWidget.value.hidden) {
                previewWidget.videoEl.pause();
            } else if (previewWidget.value.hidden && !previewWidget.videoEl.hidden && !previewWidget.value.paused) {
                previewWidget.videoEl.play();
            }
            previewWidget.value.hidden = !previewWidget.value.hidden;
            previewWidget.parentEl.hidden = previewWidget.value.hidden;
            fitHeight(this);
        }});

        optNew.push({content: "Sync preview", callback: () => {
            for (let p of document.getElementsByClassName("vhs_preview")) {
                for (let child of p.children) {
                    if (child.tagName == "VIDEO") child.currentTime = 0;
                    else if (child.tagName == "IMG") child.src = child.src;
                }
            }
        }});

        const muteDesc = (previewWidget.value.muted ? "Unmute" : "Mute") + " Preview"
        optNew.push({content: muteDesc, callback: () => {
            previewWidget.value.muted = !previewWidget.value.muted
        }})

        if (options.length > 0 && options[0] != null && optNew.length > 0) optNew.push(null);
        options.unshift(...optNew);
    });
}

// ============================================================
// 注册 XB_VideoLoader �?原样保留
// ============================================================
app.registerExtension({
    name: "XB_ToolBox.VideoLoader",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_VideoLoader") return;

        chainCallback(nodeType.prototype, "onNodeCreated", function() {
            const pathWidget = this.widgets.find((w) => w.name === "video");
            chainCallback(pathWidget, "callback", (value) => {
                if (!value) { return; }
                let parts = ["input", value];
                let extension_index = parts[1].lastIndexOf(".");
                let extension = parts[1].slice(extension_index+1);
                let format = "video"
                if (["gif", "webp", "avif"].includes(extension)) {
                    format = "image"
                }
                format += "/" + extension;
                let params = {filename : parts[1], type : parts[0], format: format};
                this.updateParameters(params, true);
            });
        });

        chainCallback(nodeType.prototype, "onNodeCreated", function() {
            const node = this;
            const pathWidget = this.widgets.find((w) => w.name === "video");
            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = "video/webm,video/mp4,video/x-matroska,image/gif";
            fileInput.style.display = "none";
            async function doUpload(file) {
                const fd = new FormData(); fd.append("image", file);
                let resp = await api.fetchApi("/upload/image", { method: "POST", body: fd });
                if (resp.status != 200) { return false; }
                const name = (await resp.json()).name;
                if (!pathWidget.options.values.includes(name)) pathWidget.options.values.push(name);
                pathWidget.value = name;
                if (pathWidget.callback) { pathWidget.callback(name); }
                return true;
            }
            Object.assign(fileInput, {
                onchange: async () => { if (fileInput.files.length) return await doUpload(fileInput.files[0]); },
            });
            document.body.append(fileInput);
            const oR = node.onRemoved;
            node.onRemoved = function () { fileInput?.remove(); oR?.apply(node); };
            let uploadWidget = this.addWidget("button", "choose video to upload", "image", () => {
                app.canvas.node_widget = null;
                fileInput.click();
            });
            uploadWidget.options.serialize = false;
        });

        addVideoPreview(nodeType);
        addPreviewOptions(nodeType);
        chainCallback(nodeType.prototype, "onNodeCreated", function() {
            const node = this;
            function update(key) {
                return function(value) {
                    let params = {}
                    params[key] = this.value
                    node?.updateParameters(params)
                }
            }
            let prior_ar = -2;
            const widthWidget = this.widgets.find((w) => w.name === "custom_width");
            const heightWidget = this.widgets.find((w) => w.name === "custom_height");

            function resolveLinkedValue(node, widgetName) {
                const w = node.widgets.find(x => x.name === widgetName);
                const localVal = parseInt(w?.value) || 0;

                const links = app.graph?.links || {};
                for (const linkId in links) {
                    const link = links[linkId];
                    if (!link || link.target_id !== node.id) continue;
                    const targetInput = node.inputs?.[link.target_slot];
                    if (!targetInput || targetInput.name !== widgetName) continue;
                    const src = app.graph.getNodeById(link.origin_id);
                    if (!src) continue;
                    const outName = (src.outputs?.[link.origin_slot]?.name || "").toLowerCase();
                    if (outName) {
                        const m = src.widgets?.find(x => (x.name || "").toLowerCase() === outName);
                        if (m?.value != null) { return parseInt(m.value) || 0; }
                    }
                    const sw = src.widgets?.[link.origin_slot];
                    if (sw?.value != null) { return parseInt(sw.value) || 0; }
                    if (src.widgets_values?.[link.origin_slot] != null) { return parseInt(src.widgets_values[link.origin_slot]) || 0; }
                }
                return localVal;
            }

            function updateAR(value) {
                let new_ar = -1;
                const wv = resolveLinkedValue(node, "custom_width");
                const hv = resolveLinkedValue(node, "custom_height");
                if (wv && hv) {
                    new_ar = wv / hv;
                }
                if (new_ar != prior_ar) {
                    const wv = resolveLinkedValue(node, "custom_width");
                    const hv = resolveLinkedValue(node, "custom_height");
                    node?.updateParameters({'custom_width': wv, 'custom_height': hv});
                    prior_ar = new_ar;
                }
            }
            function syncLinked(name) {
                var cur = resolveLinkedValue(node, name);
                if (cur != node["_xb_" + name]) {
                    node["_xb_" + name] = cur;
                    node?.updateParameters({[name]: cur});
                }
            }
            let widgetMap = {
                'frame_load_cap': 'frame_load_cap',
                'skip_first_frames': 'skip_first_frames',
                'select_every_nth': 'select_every_nth',
                'force_rate': 'force_rate',
                'custom_width': updateAR,
                'custom_height': updateAR,
            }
            for (let widget of this.widgets) {
                if (widget.name in widgetMap) {
                    if (typeof(widgetMap[widget.name]) == 'function') {
                        chainCallback(widget, "callback", widgetMap[widget.name]);
                    } else {
                        chainCallback(widget, "callback", update(widgetMap[widget.name]))
                    }
                }
                if (widget.type != "button") {
                    widget.callback?.(widget.value)
                }
            }

            const poll = () => { if (node) { updateAR(); ['frame_load_cap','skip_first_frames','select_every_nth','force_rate'].forEach(syncLinked); } };
            setInterval(poll, 500);

            const origAC = app.graph.afterChange;
            app.graph.afterChange = function () {
                origAC?.apply(this, arguments);
                if (node) { updateAR(); ['frame_load_cap','skip_first_frames','select_every_nth','force_rate'].forEach(syncLinked); }
            };
        });
    }
});

// ============================================================
// XB_VideoCombine - reuse addVideoPreview
app.registerExtension({
    name: "XB_ToolBox.VideoCombine",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "XB_VideoCombine") return;
        addVideoPreview(nodeType, false);
        addPreviewOptions(nodeType);
        chainCallback(nodeType.prototype, "onNodeCreated", function() {
            const pw = this.widgets.find(w => w.name === "videopreview");
            if (pw) {
                pw.videoEl.onmouseenter = function() { pw.videoEl.muted = false; };
                pw.videoEl.onmouseleave = function() { pw.videoEl.muted = true; };
                var orig = pw.updateSource;
                pw.updateSource = function () {
                    var p = this.value.params || {};
                    this.parentEl.hidden = this.value.hidden;
                    if (!p.filename) return;
                    p.type = p.type || "output";
                    p.timestamp = Date.now();
                    if (p.format && p.format.indexOf("image/") === 0) {
                        this.imgEl.src = api.apiURL('/view?' + new URLSearchParams(p));
                        this.imgEl.hidden = false; this.videoEl.hidden = true;
                    } else {
                        this.videoEl.src = api.apiURL('/view?' + new URLSearchParams(p));
                        this.videoEl.hidden = false; this.imgEl.hidden = true;
                        this.videoEl.load();
                        this.videoEl.play().catch(function() { pw.videoEl.muted = true; pw.videoEl.play().catch(function(){}); });
                    }
                };
            }
        });
        chainCallback(nodeType.prototype, "onExecuted", function(message) {
            if (message && message.gifs) this.updateParameters(message.gifs[0], true);
        });
    }
});