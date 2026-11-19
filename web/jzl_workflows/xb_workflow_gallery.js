/**
 * XB_ToolBox — 「机智罗的工作流」入口
 * ============================================================
 * 交互对齐官方「模板」：
 *   点左侧栏的 JZL 图标 → 屏幕正中弹出大面板（左侧分类 + 顶部搜索 + 卡片网格），
 *   点卡片在工作流新标签页打开，Esc / 点遮罩 / 关闭按钮收起。
 *   侧栏 tab 只当作按钮用：弹出面板后立刻把侧栏收起，避免出现窄侧栏界面。
 *
 * 数据：插件内 xb_templates/ 下的 index.json / index.zh.json
 *   结构与官方 comfyui-workflow-templates 完全一致，按 category / title 分组。
 *   工作流本体与预览图由 xb_templates.py 托管，只放行清单登记过的文件。
 */

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const TAB_ID = "xb_workflow_gallery";
const ASSET_BASE = "/xb_toolbox/templates/";
const WEB_BASE = "/xb_toolbox/assets/";
const ICON_CLASS = "xb-gallery-icon";

const MANIFESTS = {
    zh: ["index.zh.json", "index.json"],
    en: ["index.json", "index.zh.json"],
};

/** 提示词页「全部类型」的分组顺序（后端按标题关键词归类） */
const PROMPT_GROUPS = ["text2image", "image_edit", "text2video", "image2video", "video_edit"];

/** 工作流清单里可能出现的 type 值，其余一律按图片处理 */
const WORKFLOW_TYPES = ["image", "video", "music", "speech", "text"];

const STRINGS = {
    zh: {
        tab: "机智罗",
        tooltip: "机智罗的工作流 · XB_ToolBox",
        panel: "机智罗的工作流",
        brandName: "机智罗",
        tabWorkflows: "工作流",
        tabPrompts: "提示词",
        tabHelp: "说明",
        all: "全部",
        typeAll: "全部类型",
        typeImage: "图片工作流",
        typeVideo: "视频工作流",
        typeMusic: "音乐工作流",
        typeSpeech: "语音工作流",
        typeText: "文本工作流",
        promptGroups: {
            text2image: "文生图片",
            image_edit: "图片编辑",
            text2video: "文生视频",
            image2video: "图生视频",
            video_edit: "视频编辑",
        },
        search: "搜索工作流…",
        searchPrompts: "搜索提示词…",
        refresh: "刷新",
        close: "关闭",
        loading: "正在加载工作流…",
        empty: "还没有工作流",
        noMatch: "没有匹配的工作流",
        listFailed: "工作流清单加载失败",
        loadFailed: "工作流加载失败",
        openedNew: "已在新标签页打开",
        loadedCurrent: "已加载到当前画布",
        promptLoading: "正在加载提示词…",
        promptEmpty: "还没有提示词",
        promptFailed: "提示词加载失败",
        copy: "复制",
        copied: "已复制到剪贴板",
        copyFailed: "复制失败，请手动选择文本",
        help: {
            intro: "这里是 XB_ToolBox（小白工具箱）自带的资源面板，集中放我整理好的工作流、提示词和使用说明。",
            sections: [
                {
                    title: "工作流",
                    items: [
                        "左侧按模型分类，右侧是缩略图卡片；顶部搜索框可按名称、标签过滤，右上角「全部类型」可按图片 / 视频 / 音乐 / 语音 / 文本筛选。",
                        "点卡片会用<b>一份独立副本</b>在新标签页打开——不会覆盖你已保存的工作流，也不会改动插件里的原始文件。",
                        "改完按 <kbd>Ctrl</kbd>+<kbd>S</kbd> 保存到你自己的 <code>user/default/workflows</code>，之后这份就完全归你，跟我们无关。",
                        "缩略图右上角带红色 <b>GGUF</b> 标记的，是用 GGUF 量化模型加载的版本：显存占用更低，需要先装 ComfyUI-GGUF 节点。",
                        "同一个工作流可以反复打开，每次都是干净的副本（已在用时会命名为 标题 (2)、(3)…）。",
                    ],
                },
                {
                    title: "提示词",
                    items: [
                        "内置常用结构化提示词（人物多视图、信息图、分镜、全景等），中英文随界面语言自动切换。",
                        "九宫格卡片展示，可用「全部类型」按文生图片 / 图片编辑 / 文生视频 / 图生视频 / 视频编辑筛选；鼠标悬停会在旁边弹出大图预览与完整提示词（只读，不能直接编辑）。",
                        "点「复制」后粘贴到任意提示词输入框或文本节点即可。",
                        "效果图放在 <code>xb_skill/XB_ImagePromptPreset/&lt;语言&gt;/</code> 下，文件名与对应的 <code>.txt</code> 相同即可（支持 webp / png / jpg / gif，也可放在 <code>preview/</code> 子目录）；没有图的条目显示占位卡片。",
                        "这些提示词与插件里的「生图提示词预设」节点共用同一批文件，改了节点里的预设，这里也会跟着变。",
                    ],
                },
                {
                    title: "常见问题",
                    items: [
                        "更新插件后界面没变化：插件脚本有 24 小时浏览器缓存，按 <kbd>Ctrl</kbd>+<kbd>F5</kbd> 强制刷新。",
                        "缩略图不显示：确认插件目录下 <code>jzl_workflows/data</code> 里有同名的 <code>&lt;name&gt;-1.webp</code>。",
                        "想加自己的工作流：把 JSON 放进 <code>jzl_workflows/data</code>，再在 <code>index.json</code> 与 <code>index.zh.json</code> 各加一条，预览图命名 <code>&lt;name&gt;-1.webp</code>。",
                        "工作流能打开但缺节点：多半是缺对应自定义节点或模型，控制台会列出缺失的节点类型。",
                    ],
                },
            ],
            linksTitle: "相关链接",
            links: [
                { label: "GitHub 仓库 · wjluoxiao/XB_ToolBox", url: "https://github.com/wjluoxiao/XB_ToolBox" },
                { label: "问题反馈 · Issues", url: "https://github.com/wjluoxiao/XB_ToolBox/issues" },
            ],
            footer: "工作流与提示词由 机智罗 整理，仅供学习交流使用。",
        },
    },
    en: {
        tab: "JZL Workflows",
        tooltip: "JZL Workflows · XB_ToolBox",
        panel: "JZL Workflows",
        brandName: "JZL",
        tabWorkflows: "Workflows",
        tabPrompts: "Prompts",
        tabHelp: "About",
        all: "Show all",
        typeAll: "All types",
        typeImage: "Image workflows",
        typeVideo: "Video workflows",
        typeMusic: "Music workflows",
        typeSpeech: "Speech workflows",
        typeText: "Text workflows",
        promptGroups: {
            text2image: "Text to image",
            image_edit: "Image edit",
            text2video: "Text to video",
            image2video: "Image to video",
            video_edit: "Video edit",
        },
        search: "Search workflows…",
        searchPrompts: "Search prompts…",
        refresh: "Refresh",
        close: "Close",
        loading: "Loading workflows…",
        empty: "No workflows yet",
        noMatch: "No matching workflows",
        listFailed: "Failed to load workflow index",
        loadFailed: "Failed to load workflow",
        openedNew: "Opened in a new workflow tab",
        loadedCurrent: "Loaded into the current canvas",
        promptLoading: "Loading prompts…",
        promptEmpty: "No prompts yet",
        promptFailed: "Failed to load prompts",
        copy: "Copy",
        copied: "Copied to clipboard",
        copyFailed: "Copy failed — please select the text manually",
        help: {
            intro: "This is the resource panel bundled with XB_ToolBox: my curated workflows, prompts and usage notes.",
            sections: [
                {
                    title: "Workflows",
                    items: [
                        "Categories on the left, thumbnail cards on the right. The search box filters by name and tag; “All types” filters image / video / music / speech / text.",
                        "A card click opens <b>an independent copy</b> in a new tab — your saved workflows are never overwritten and the bundled files stay untouched.",
                        "Press <kbd>Ctrl</kbd>+<kbd>S</kbd> to save it into <code>user/default/workflows</code>; from then on the copy is entirely yours.",
                        "Cards with a red <b>GGUF</b> badge load the GGUF-quantized models: lower VRAM usage, requires ComfyUI-GGUF.",
                        "Loading the same card again always gives a clean copy (named Title (2), (3)… while the earlier one is open).",
                    ],
                },
                {
                    title: "Prompts",
                    items: [
                        "Structured prompt presets (character sheets, infographics, storyboards, panoramas…) in Chinese and English.",
                        "Shown as a 3-column card grid, filterable by type (text-to-image / image edit / text-to-video / image-to-video / video edit); hovering a card pops up a large preview plus the full read-only prompt.",
                        "Click “Copy” and paste it into any prompt box or text node.",
                        "Drop effect images into <code>xb_skill/XB_ImagePromptPreset/&lt;locale&gt;/</code>, named exactly like the matching <code>.txt</code> (webp / png / jpg / gif; a <code>preview/</code> subfolder also works). Entries without an image show a placeholder card.",
                        "These share the same files as the “Image Prompt Preset” node, so editing the node presets updates this page too.",
                    ],
                },
                {
                    title: "FAQ",
                    items: [
                        "Interface unchanged after updating: extension scripts are cached for 24 hours — press <kbd>Ctrl</kbd>+<kbd>F5</kbd>.",
                        "Missing thumbnails: make sure <code>&lt;name&gt;-1.webp</code> exists under <code>jzl_workflows/data</code>.",
                        "Adding your own workflow: drop the JSON into <code>jzl_workflows/data</code>, add an entry to <code>index.json</code> and <code>index.zh.json</code>, and name the preview <code>&lt;name&gt;-1.webp</code>.",
                        "Workflow opens but nodes are missing: a custom node pack or model is missing; the console lists the missing types.",
                    ],
                },
            ],
            linksTitle: "Links",
            links: [
                { label: "GitHub · wjluoxiao/XB_ToolBox", url: "https://github.com/wjluoxiao/XB_ToolBox" },
                { label: "Issues", url: "https://github.com/wjluoxiao/XB_ToolBox/issues" },
            ],
            footer: "Workflows and prompts curated by JZL, for learning and sharing.",
        },
    },
};

function currentLocale() {
    try {
        const value = app?.ui?.settings?.getSettingValue?.("Comfy.Locale");
        if (typeof value === "string" && value.toLowerCase().startsWith("zh")) return "zh";
    } catch (_) { /* ignore */ }
    return "en";
}

function strings() {
    return STRINGS[currentLocale()] || STRINGS.en;
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

/** 内联 SVG 图标：直接用 currentColor，跟随明暗主题与选中态 */
const SVG_NS = "http://www.w3.org/2000/svg";

function svgIcon(className, paths, { stroke = true } = {}) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    if (stroke) {
        svg.setAttribute("fill", "none");
        svg.setAttribute("stroke", "currentColor");
        svg.setAttribute("stroke-width", "1.7");
        svg.setAttribute("stroke-linecap", "round");
        svg.setAttribute("stroke-linejoin", "round");
    } else {
        svg.setAttribute("fill", "currentColor");
    }
    if (className) svg.setAttribute("class", className);
    for (const d of paths) {
        const path = document.createElementNS(SVG_NS, "path");
        path.setAttribute("d", d);
        svg.append(path);
    }
    return svg;
}

function folderIcon(className) {
    return svgIcon(className, [
        "M3 7.5A1.5 1.5 0 0 1 4.5 6h4.2l2 2h8.8A1.5 1.5 0 0 1 21 9.5v8A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z",
    ]);
}

function searchIcon(className) {
    return svgIcon(className, [
        "M10.5 3a7.5 7.5 0 1 1 0 15 7.5 7.5 0 0 1 0-15z",
        "M16.2 16.2 21 21",
    ]);
}

function closeIcon(className) {
    return svgIcon(className, ["M6 6l12 12", "M18 6 6 18"]);
}

function toast(message, severity = "info") {
    try {
        const bus = app.extensionManager?.toast;
        if (bus?.add) {
            bus.add({ severity, summary: "XB_ToolBox", detail: message, life: 3000 });
            return;
        }
    } catch (_) { /* ignore */ }
    console.log("[XB_ToolBox]", message);
}

/** 当前主题是否为浅色（用于选中深浅两套图标） */
function isLightTheme() {
    try {
        const palette = app?.ui?.settings?.getSettingValue?.("Comfy.ColorPalette");
        if (palette === "light") return true;
        if (palette === "dark") return false;
    } catch (_) { /* ignore */ }
    try {
        const match = getComputedStyle(document.body).backgroundColor.match(/\d+(?:\.\d+)?/g);
        if (match && match.length >= 3) {
            const [r, g, b] = match.slice(0, 3).map(Number);
            return 0.299 * r + 0.587 * g + 0.114 * b > 140;
        }
    } catch (_) { /* ignore */ }
    return false;
}

/** 图标 / 样式走自己的 no-cache 路由，换图后普通刷新即可生效 */
function webAsset(name) {
    return api.apiURL(WEB_BASE + name);
}

function iconUrl(name) {
    return webAsset(name);
}

function logoUrl() {
    return iconUrl(isLightTheme() ? "xb_icon_light.png" : "xb_icon_dark.png");
}

async function fetchManifest() {
    const order = MANIFESTS[currentLocale()] || MANIFESTS.en;
    for (const name of order) {
        try {
            const response = await api.fetchApi(ASSET_BASE + name, { cache: "no-store" });
            if (!response.ok) continue;
            const data = await response.json();
            if (Array.isArray(data)) return data;
        } catch (error) {
            console.warn(`[XB_ToolBox] 读取 ${name} 失败`, error);
        }
    }
    return null;
}

async function fetchPrompts() {
    const response = await api.fetchApi(`/xb_toolbox/prompts/${currentLocale()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    return Array.isArray(data) ? data : [];
}

function flatten(manifest) {
    const items = [];
    for (const group of manifest) {
        if (!group || !Array.isArray(group.templates)) continue;
        const category = typeof group.category === "string" ? group.category : "";
        const subcategory = typeof group.title === "string" ? group.title : "";
        const groupType = WORKFLOW_TYPES.includes(group.type) ? group.type : "image";
        for (const tpl of group.templates) {
            if (!tpl || typeof tpl.name !== "string" || !tpl.name) continue;
            const thumbnails = Array.isArray(tpl.thumbnail) ? tpl.thumbnail : [];
            const thumbnail = thumbnails.find((value) => typeof value === "string" && value) || "";
            items.push({
                name: tpl.name,
                title: typeof tpl.title === "string" ? tpl.title : tpl.name,
                description: typeof tpl.description === "string" ? tpl.description : "",
                tags: Array.isArray(tpl.tags) ? tpl.tags.filter((tag) => typeof tag === "string") : [],
                category,
                subcategory,
                type: groupType,
                thumbnail: thumbnail ? thumbnail.replace(/\\/g, "/").split("/").pop() : "",
            });
        }
    }
    return items;
}

function filterItems(items, subcategory, query, type = "") {
    const needle = (query || "").trim().toLowerCase();
    return items.filter((item) => {
        if (subcategory && (item.subcategory || item.category) !== subcategory) return false;
        if (type && item.type !== type) return false;
        if (!needle) return true;
        const haystack = [item.title, item.name, item.description, ...item.tags].join(" ").toLowerCase();
        return haystack.includes(needle);
    });
}

function subcategoriesOf(items) {
    const seen = [];
    for (const item of items) {
        const key = item.subcategory || item.category;
        if (key && !seen.includes(key)) seen.push(key);
    }
    return seen;
}

/**
 * 标签页名字会直接变成用户数据里的文件名（workflows/<name>.json），
 * 所以必须去掉路径分隔符等非法字符，避免拼出越界路径。
 */
function workflowTabName(item) {
    const cleaned = String(item.title || item.name || "")
        .replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 80);
    return cleaned || "JZL Workflow";
}

function freshWorkflowId() {
    const uuid = globalThis.crypto?.randomUUID?.();
    if (uuid) return uuid;
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
        const r = (Math.random() * 16) | 0;
        return (ch === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
}

/**
 * 找一个还没被占用的标签页名字。
 * 前端按「路径」识别文档：同名标签页 / 同名本地文件会被当成同一个工作流，
 * 再次加载时直接把画布重置成我们的模版内容（用户改动全丢）。所以每次都取新路径。
 */
function uniqueTabName(workflowStore, base) {
    const taken = (name) => Boolean(workflowStore?.getWorkflowByPath?.(`workflows/${name}.json`));
    if (!taken(base)) return base;
    for (let index = 2; index < 100; index += 1) {
        const candidate = `${base} (${index})`;
        if (!taken(candidate)) return candidate;
    }
    return `${base} ${Date.now()}`;
}

/** 打开清单里的一个工作流；返回是否新建了标签页 */
async function openWorkflowItem(item) {
    const response = await api.fetchApi(ASSET_BASE + item.name + ".json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const graph = await response.json();

    const workflowStore = app.extensionManager?.workflow;
    const before = new Set(workflowStore?.openWorkflows?.map((wf) => wf.path) ?? []);
    const tabName = uniqueTabName(workflowStore, workflowTabName(item));

    // 模版只是一份「仓库副本」：换掉工作流 id，保证每次都当全新文档打开，
    // 既不会合并进用户已保存的工作流，也不会覆盖它。
    graph.id = freshWorkflowId();

    await app.loadGraphData(graph, true, true, tabName);

    const created = workflowStore?.openWorkflows?.find((wf) => !before.has(wf.path));
    if (created && /^workflows\/Unsaved Workflow/.test(created.path) && workflowStore.renameWorkflow) {
        // 老版本前端会忽略第 4 个参数，标签页仍是 “Unsaved Workflow”；
        // 此时补一次重命名（第二个参数是路径而不是标题）
        const target = `workflows/${tabName}.json`;
        try {
            if (!workflowStore.getWorkflowByPath?.(target)) {
                await workflowStore.renameWorkflow(created, target);
            }
        } catch (error) {
            console.warn("[XB_ToolBox] 重命名新标签页失败", error);
        }
    }
    return Boolean(created);
}

function buildCard(item, onOpen) {
    const card = el("button", "xb-wf-card");
    card.type = "button";
    card.title = item.description || item.title;

    const thumb = el("div", "xb-wf-thumb");
    if (item.thumbnail) {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = item.title;
        img.src = api.apiURL(ASSET_BASE + item.thumbnail);
        img.addEventListener("error", () => {
            img.remove();
            thumb.classList.add("is-empty");
            thumb.append(el("span", "xb-wf-thumb-text", item.title));
        });
        thumb.append(img);
    } else {
        thumb.classList.add("is-empty");
        thumb.append(el("span", "xb-wf-thumb-text", item.title));
    }

    const name = el("div", "xb-wf-name", item.title);
    const tags = el("div", "xb-wf-tags");
    for (const tag of item.tags.slice(0, 3)) tags.append(el("span", "xb-wf-tag", tag));

    if (/\bGGUF\b/i.test(item.title)) {
        thumb.append(el("span", "xb-wf-gguf", "GGUF"));
    }

    card.append(thumb, name, tags);
    card.addEventListener("click", () => onOpen(item));
    return card;
}

/** 居中大面板：左侧品牌 + 分类，右侧「工作流 / 提示词 / 说明」三页 */
class WorkflowModal {
    constructor() {
        this.items = [];
        this.prompts = [];
        this.promptsLoaded = false;
        this.subcategory = "";
        this.typeFilter = "";
        this.promptGroup = "";
        this.query = "";
        this.tab = "workflows";
        this.busy = false;
    }

    show() {
        const text = strings();
        this.backdrop = el("div", "xb-wf-backdrop");
        this.backdrop.tabIndex = -1;

        const modal = el("div", "xb-wf-modal");
        modal.setAttribute("role", "dialog");
        modal.setAttribute("aria-modal", "true");
        modal.setAttribute("aria-label", text.panel);

        modal.append(this.buildSide(text), this.buildMain(text));
        this.backdrop.append(modal);
        document.body.append(this.backdrop);

        this.onKeyDown = (event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            event.stopPropagation();
            this.close();
        };
        this.onBackdropClick = (event) => {
            if (event.target === this.backdrop) this.close();
        };
        document.addEventListener("keydown", this.onKeyDown, true);
        this.backdrop.addEventListener("mousedown", this.onBackdropClick);
        this.body.addEventListener("scroll", () => this.hidePromptPreview(), { passive: true });

        this.previousOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";

        this.switchTab("workflows");
        this.load();
        this.searchInput.focus();
    }

    buildSide(text) {
        const side = el("aside", "xb-wf-side");
        const brand = el("div", "xb-wf-brand");
        brand.append(
            el("span", "xb-wf-brand-jzl", "JZL"),
            el("span", "xb-wf-brand-name", text.brandName),
        );
        this.sideList = el("div", "xb-wf-side-list");
        side.append(brand, this.sideList);
        return side;
    }

    buildMain(text) {
        const main = el("section", "xb-wf-main");

        this.tabButtons = {};
        const tabs = el("div", "xb-wf-tabs");
        for (const [id, label] of [
            ["workflows", text.tabWorkflows],
            ["prompts", text.tabPrompts],
            ["help", text.tabHelp],
        ]) {
            const button = el("button", "xb-wf-tab", label);
            button.type = "button";
            button.addEventListener("click", () => this.switchTab(id));
            this.tabButtons[id] = button;
            tabs.append(button);
        }

        this.searchInput = document.createElement("input");
        this.searchInput.type = "search";
        this.searchInput.className = "xb-wf-search-input";
        this.searchInput.placeholder = text.search;
        this.searchInput.addEventListener("input", () => {
            this.query = this.searchInput.value;
            this.renderContent();
        });

        const searchBtn = el("button", "xb-wf-icon-btn");
        searchBtn.type = "button";
        searchBtn.title = text.search;
        searchBtn.setAttribute("aria-label", text.search);
        searchBtn.append(searchIcon("xb-wf-icon-svg"));
        searchBtn.addEventListener("click", () => {
            this.query = this.searchInput.value;
            this.renderContent();
            this.searchInput.focus();
        });

        this.closeBtn = el("button", "xb-wf-icon-btn xb-wf-close");
        this.closeBtn.type = "button";
        this.closeBtn.title = text.close;
        this.closeBtn.setAttribute("aria-label", text.close);
        this.closeBtn.append(closeIcon("xb-wf-icon-svg"));
        this.closeBtn.addEventListener("click", () => this.close());

        this.searchWrap = el("div", "xb-wf-search-wrap");
        this.searchWrap.append(this.searchInput, searchBtn);

        // 页签独占一行，搜索框下移为「工作流 / 提示词」的二级工具条
        const topbar = el("header", "xb-wf-topbar");
        topbar.append(tabs, this.closeBtn);

        this.typeSelect = document.createElement("select");
        this.typeSelect.className = "xb-wf-select";
        this.typeSelect.addEventListener("change", () => {
            if (this.tab === "prompts") {
                this.promptGroup = this.typeSelect.value;
                this.renderPrompts();
            } else {
                this.typeFilter = this.typeSelect.value;
                this.renderGrid();
            }
        });

        this.toolbar = el("div", "xb-wf-toolbar");
        this.toolbar.append(this.typeSelect, this.searchWrap);

        this.grid = el("div", "xb-wf-grid");
        this.promptList = el("div", "xb-wf-prompts");
        this.helpPane = el("div", "xb-wf-help");
        this.body = el("div", "xb-wf-body");
        this.body.append(this.grid, this.promptList, this.helpPane);

        this.status = el("div", "xb-wf-status");
        main.append(topbar, this.toolbar, this.body, this.status);
        return main;
    }

    /** 「全部类型」下拉：工作流页列图片/视频/音乐/语音/文本，提示词页列提示词分组，带数量 */
    rebuildTypeOptions() {
        const text = strings();
        const isPrompts = this.tab === "prompts";
        const source = isPrompts ? this.prompts : this.items;
        const keyOf = isPrompts ? (item) => item.group : (item) => item.type;
        const counts = new Map();
        for (const item of source) {
            const key = keyOf(item);
            counts.set(key, (counts.get(key) || 0) + 1);
        }
        const withCount = (label, count) => `${label} (${count})`;
        const options = isPrompts
            ? [["", withCount(text.typeAll, source.length)],
                ...PROMPT_GROUPS.map((key) => [key, withCount(text.promptGroups[key], counts.get(key) || 0)])]
            : [
                ["", withCount(text.typeAll, source.length)],
                ["image", withCount(text.typeImage, counts.get("image") || 0)],
                ["video", withCount(text.typeVideo, counts.get("video") || 0)],
                ["music", withCount(text.typeMusic, counts.get("music") || 0)],
                ["speech", withCount(text.typeSpeech, counts.get("speech") || 0)],
                ["text", withCount(text.typeText, counts.get("text") || 0)],
            ];
        this.typeSelect.innerHTML = "";
        for (const [value, label] of options) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            this.typeSelect.append(option);
        }
        this.typeSelect.value = isPrompts ? this.promptGroup : this.typeFilter;
    }

    switchTab(id) {
        this.tab = id;
        for (const [key, button] of Object.entries(this.tabButtons || {})) {
            button.classList.toggle("is-active", key === id);
            button.setAttribute("aria-selected", key === id ? "true" : "false");
        }
        // 说明页没有搜索；两个内容页各有自己的「类型」下拉
        this.toolbar.classList.toggle("is-hidden", id === "help");
        this.searchWrap.classList.toggle("is-hidden", id === "help");
        this.searchInput.placeholder = id === "prompts" ? strings().searchPrompts : strings().search;
        if (id === "prompts") {
            this.promptGroup = "";
        } else if (id === "workflows") {
            this.typeFilter = "";
        }
        this.rebuildTypeOptions();
        if (id !== "prompts") this.hidePromptPreview();
        this.body.scrollTop = 0;
        this.renderContent();
    }

    renderContent() {
        const isWorkflows = this.tab === "workflows";
        this.grid.classList.toggle("is-hidden", !isWorkflows);
        this.promptList.classList.toggle("is-hidden", this.tab !== "prompts");
        this.helpPane.classList.toggle("is-hidden", this.tab !== "help");

        if (isWorkflows) {
            this.renderGrid();
        } else if (this.tab === "prompts") {
            this.renderPrompts();
        } else {
            this.renderHelp();
        }
    }

    setStatus(message, isError = false) {
        this.status.textContent = message || "";
        this.status.classList.toggle("is-error", Boolean(isError));
    }

    async load() {
        const text = strings();
        this.setStatus(text.loading);
        try {
            const manifest = await fetchManifest();
            if (manifest === null) {
                this.items = [];
                this.setStatus(text.listFailed, true);
            } else {
                this.items = flatten(manifest);
                this.setStatus("");
            }
        } catch (error) {
            console.error("[XB_ToolBox] 工作流清单加载失败", error);
            this.items = [];
            this.setStatus(text.listFailed, true);
        } finally {
            this.renderCategories();
            this.rebuildTypeOptions();
            if (this.tab === "workflows") this.renderGrid();
        }
    }

    renderCategories() {
        const text = strings();
        this.sideList.innerHTML = "";

        const counts = new Map();
        for (const item of this.items) {
            const key = item.subcategory || item.category;
            counts.set(key, (counts.get(key) || 0) + 1);
        }

        const makeItem = (label, value, count, withIcon) => {
            const item = el("button", "xb-wf-side-item");
            item.type = "button";
            item.title = `${label} (${count})`;
            if (withIcon) item.append(folderIcon("xb-wf-side-icon"));
            item.append(
                el("span", "xb-wf-side-label", label),
                el("span", "xb-wf-side-count", String(count)),
            );
            item.classList.toggle("is-active", this.subcategory === value);
            item.addEventListener("click", () => {
                this.subcategory = value;
                if (this.tab !== "workflows") this.switchTab("workflows");
                this.renderCategories();
                this.renderGrid();
            });
            return item;
        };

        this.sideList.append(makeItem(text.all, "", this.items.length, false));
        for (const name of subcategoriesOf(this.items)) {
            this.sideList.append(makeItem(name, name, counts.get(name) || 0, true));
        }
    }

    renderGrid() {
        const text = strings();
        this.grid.innerHTML = "";
        if (this.items.length === 0) {
            this.grid.append(el("div", "xb-wf-empty", text.empty));
            return;
        }
        const visible = filterItems(this.items, this.subcategory, this.query, this.typeFilter);
        if (visible.length === 0) {
            this.grid.append(el("div", "xb-wf-empty", text.noMatch));
            return;
        }
        for (const item of visible) this.grid.append(buildCard(item, (target) => this.open(target)));
    }

    ensurePrompts() {
        if (this.promptPromise) return this.promptPromise;
        this.promptPromise = fetchPrompts()
            .then((items) => {
                this.prompts = items;
                this.promptsLoaded = true;
                delete this.promptList.dataset.failed;
            })
            .catch((error) => {
                console.error("[XB_ToolBox] 提示词加载失败", error);
                this.prompts = [];
                this.promptsLoaded = true;
                this.promptList.dataset.failed = "1";
            });
        return this.promptPromise;
    }

    renderPrompts() {
        const text = strings();
        const render = () => {
            this.promptList.innerHTML = "";
            if (this.prompts.length === 0) {
                const message = this.promptList.dataset.failed ? text.promptFailed : text.promptEmpty;
                this.promptList.append(el("div", "xb-wf-empty", message));
                return;
            }
            const needle = (this.query || "").trim().toLowerCase();
            let visible = this.promptGroup
                ? this.prompts.filter((item) => item.group === this.promptGroup)
                : this.prompts;
            if (needle) {
                visible = visible.filter((item) => `${item.title} ${item.text}`.toLowerCase().includes(needle));
            }
            if (visible.length === 0) {
                this.promptList.append(el("div", "xb-wf-empty", text.noMatch));
                return;
            }
            for (const item of visible) {
                this.promptList.append(buildPromptCard(item, text, {
                    onPreview: (rect) => this.showPromptPreview(item, rect),
                    onHide: () => this.hidePromptPreview(),
                }));
            }
        };

        if (!this.promptsLoaded) {
            this.promptList.innerHTML = "";
            this.promptList.append(el("div", "xb-wf-empty", text.promptLoading));
            this.ensurePrompts().then(() => {
                if (this.tab === "prompts") {
                    this.rebuildTypeOptions();
                    render();
                }
            });
            return;
        }
        render();
    }

    showPromptPreview(item, rect) {
        if (!this.preview) {
            this.preview = el("div", "xb-wf-preview is-hidden");
            this.previewImg = el("div", "xb-wf-preview-media");
            this.previewText = el("div", "xb-wf-preview-text");
            this.preview.append(this.previewImg, this.previewText);
            this.backdrop.append(this.preview);
        }
        this.previewImg.innerHTML = "";
        if (item.image) {
            const img = document.createElement("img");
            img.src = promptImageUrl(item);
            img.alt = item.title || item.name;
            this.previewImg.append(img);
        } else {
            this.previewImg.append(el("div", "xb-wf-preview-empty", item.title || item.name));
        }
        this.previewText.textContent = item.text || "";
        this.preview.classList.remove("is-hidden");
        // 先强制一次布局，否则首次测量拿到的是 display:none 时的 0 尺寸
        void this.preview.offsetWidth;

        // 优先贴在卡片右侧，放不下就翻到左侧，始终限制在面板内
        const gap = 12;
        const box = this.preview.getBoundingClientRect();
        const modalEl = this.backdrop.querySelector(".xb-wf-modal");
        const bounds = (modalEl ?? this.backdrop).getBoundingClientRect();
        const minLeft = bounds.left + gap;
        const maxLeft = bounds.right - box.width - gap;

        let left = rect.right + gap;
        if (left > maxLeft) left = rect.left - box.width - gap;
        left = Math.max(minLeft, Math.min(left, Math.max(minLeft, maxLeft)));

        let top = rect.top;
        const maxTop = bounds.bottom - box.height - gap;
        if (top > maxTop) top = Math.max(bounds.top + gap, maxTop);

        this.preview.style.left = `${Math.round(left)}px`;
        this.preview.style.top = `${Math.round(top)}px`;
    }

    hidePromptPreview() {
        this.preview?.classList.add("is-hidden");
    }

    renderHelp() {
        if (this.helpPane.dataset.built === "1") return;
        this.helpPane.dataset.built = "1";
        const help = strings().help;

        this.helpPane.append(el("p", "xb-wf-help-intro", help.intro));
        for (const section of help.sections) {
            const heading = el("h3", "", section.title);
            const list = el("ul");
            for (const item of section.items) {
                const li = document.createElement("li");
                // 仅渲染插件内置的静态文案（含 <b>/<kbd>/<code>），不含用户输入
                li.innerHTML = item;
                list.append(li);
            }
            this.helpPane.append(heading, list);
        }
        if (help.links?.length) {
            this.helpPane.append(el("h3", "", help.linksTitle));
            const links = el("ul", "xb-wf-help-links");
            for (const link of help.links) {
                const li = document.createElement("li");
                const anchor = document.createElement("a");
                anchor.href = link.url;
                anchor.target = "_blank";
                anchor.rel = "noopener noreferrer";
                anchor.textContent = link.label;
                li.append(anchor);
                links.append(li);
            }
            this.helpPane.append(links);
        }
        if (help.footer) this.helpPane.append(el("p", "xb-wf-help-footer", help.footer));
    }

    async open(item) {
        if (this.busy) return;
        this.busy = true;
        const text = strings();
        this.backdrop.classList.add("is-busy");
        try {
            await openWorkflowItem(item);
            toast(text.openedNew);
            this.close();
        } catch (error) {
            console.error("[XB_ToolBox] 工作流加载失败", error);
            toast(`${text.loadFailed}${error?.message ? `: ${error.message}` : ""}`, "error");
        } finally {
            this.busy = false;
            this.backdrop?.classList.remove("is-busy");
        }
    }

    close() {
        if (!this.backdrop) return;
        document.removeEventListener("keydown", this.onKeyDown, true);
        this.backdrop.removeEventListener("mousedown", this.onBackdropClick);
        this.backdrop.remove();
        document.body.style.overflow = this.previousOverflow || "";
        this.backdrop = null;
        activeModal = null;
    }
}

/** 提示词效果图 URL */
function promptImageUrl(item) {
    return api.apiURL(`/xb_toolbox/prompts/${currentLocale()}/${encodeURIComponent(item.image)}`);
}

/** 九宫格里的一张提示词卡：效果图 + 标题 + 复制（只读，不可编辑） */
function buildPromptCard(item, text, handlers) {
    const card = el("article", "xb-wf-prompt-card");
    card.tabIndex = 0;

    const thumb = el("div", "xb-wf-prompt-thumb");
    if (item.image) {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = item.title || item.name;
        img.src = promptImageUrl(item);
        img.addEventListener("error", () => {
            img.remove();
            thumb.classList.add("is-empty");
            thumb.append(el("span", "xb-wf-thumb-text", item.title || item.name));
        });
        thumb.append(img);
    } else {
        thumb.classList.add("is-empty");
        thumb.append(el("span", "xb-wf-thumb-text", item.title || item.name));
    }

    const body = el("div", "xb-wf-prompt-body");
    const title = el("span", "xb-wf-prompt-title", item.title || item.name);
    const copy = el("button", "xb-wf-prompt-copy", text.copy);
    copy.type = "button";
    copy.title = text.copy;
    copy.addEventListener("click", async (event) => {
        event.stopPropagation();
        const ok = await copyText(item.text || "");
        toast(ok ? text.copied : text.copyFailed, ok ? "success" : "error");
    });
    body.append(title, copy);

    card.append(thumb, body);

    const show = () => handlers.onPreview(card.getBoundingClientRect());
    card.addEventListener("mouseenter", show);
    card.addEventListener("focusin", show);
    card.addEventListener("mouseleave", handlers.onHide);
    card.addEventListener("focusout", handlers.onHide);

    return card;
}

async function copyText(value) {
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(value);
            return true;
        }
    } catch (_) { /* 退回到 execCommand */ }
    try {
        const area = document.createElement("textarea");
        area.value = value;
        area.style.cssText = "position:fixed;top:-1000px;opacity:0";
        document.body.append(area);
        area.select();
        const ok = document.execCommand("copy");
        area.remove();
        return ok;
    } catch (_) {
        return false;
    }
}

/** 侧栏内联面板（弹窗创建失败时的兜底） */
class WorkflowPanel {
    constructor(host) {
        this.host = host;
        this.items = [];
        this.subcategory = "";
        this.query = "";
        this.busy = false;
        this.build();
        this.load();
    }

    build() {
        const text = strings();
        this.host.classList.add("xb-wf-root");
        this.host.innerHTML = "";

        const head = el("div", "xb-wf-head");
        const logo = document.createElement("img");
        logo.className = "xb-wf-logo";
        logo.alt = "";
        logo.src = logoUrl();
        this.refreshBtn = el("button", "xb-wf-icon-btn", "⟳");
        this.refreshBtn.type = "button";
        this.refreshBtn.title = text.refresh;
        this.refreshBtn.addEventListener("click", () => this.load());
        head.append(logo, el("span", "xb-wf-title", text.panel), this.refreshBtn);

        const searchWrap = el("div", "xb-wf-search");
        this.searchInput = document.createElement("input");
        this.searchInput.type = "search";
        this.searchInput.placeholder = text.search;
        this.searchInput.addEventListener("input", () => {
            this.query = this.searchInput.value;
            this.renderGrid();
        });
        searchWrap.append(this.searchInput);

        this.catBar = el("div", "xb-wf-cats");
        this.grid = el("div", "xb-wf-grid");
        this.status = el("div", "xb-wf-status");

        this.host.append(head, searchWrap, this.catBar, this.grid, this.status);
    }

    setStatus(message, isError = false) {
        this.status.textContent = message || "";
        this.status.classList.toggle("is-error", Boolean(isError));
    }

    async load() {
        const text = strings();
        this.setStatus(text.loading);
        this.refreshBtn.disabled = true;
        try {
            const manifest = await fetchManifest();
            if (manifest === null) {
                this.items = [];
                this.setStatus(text.listFailed, true);
            } else {
                this.items = flatten(manifest);
                this.setStatus("");
            }
        } catch (error) {
            console.error("[XB_ToolBox] 工作流清单加载失败", error);
            this.items = [];
            this.setStatus(text.listFailed, true);
        } finally {
            this.refreshBtn.disabled = false;
            this.renderCategories();
            this.renderGrid();
        }
    }

    renderCategories() {
        const text = strings();
        this.catBar.innerHTML = "";

        const counts = new Map();
        for (const item of this.items) {
            const key = item.subcategory || item.category;
            counts.set(key, (counts.get(key) || 0) + 1);
        }

        const makeChip = (label, value, count) => {
            const chip = el("button", "xb-wf-chip");
            chip.type = "button";
            chip.title = `${label} (${count})`;
            chip.append(
                el("span", "xb-wf-chip-label", label),
                el("span", "xb-wf-chip-count", String(count)),
            );
            chip.classList.toggle("is-active", this.subcategory === value);
            chip.addEventListener("click", () => {
                this.subcategory = value;
                this.renderCategories();
                this.renderGrid();
            });
            return chip;
        };
        this.catBar.append(makeChip(text.all, "", this.items.length));
        for (const name of subcategoriesOf(this.items)) {
            this.catBar.append(makeChip(name, name, counts.get(name) || 0));
        }
        this.catBar.classList.toggle("is-hidden", this.items.length === 0);
    }

    renderGrid() {
        const text = strings();
        this.grid.innerHTML = "";
        if (this.items.length === 0) {
            this.grid.append(el("div", "xb-wf-empty", text.empty));
            return;
        }
        const visible = filterItems(this.items, this.subcategory, this.query);
        if (visible.length === 0) {
            this.grid.append(el("div", "xb-wf-empty", text.noMatch));
            return;
        }
        for (const item of visible) this.grid.append(buildCard(item, (target) => this.open(target)));
    }

    async open(item) {
        if (this.busy) return;
        this.busy = true;
        const text = strings();
        this.host.classList.add("is-busy");
        try {
            await openWorkflowItem(item);
            toast(text.openedNew);
        } catch (error) {
            console.error("[XB_ToolBox] 工作流加载失败", error);
            toast(`${text.loadFailed}${error?.message ? `: ${error.message}` : ""}`, "error");
        } finally {
            this.busy = false;
            this.host.classList.remove("is-busy");
        }
    }
}

let activeModal = null;

function openGalleryModal() {
    try {
        if (activeModal?.backdrop) {
            activeModal.searchInput?.focus();
            return true;
        }
        activeModal = new WorkflowModal();
        activeModal.show();
        return Boolean(activeModal.backdrop);
    } catch (error) {
        console.error("[XB_ToolBox] 打开工作流面板失败，改用侧栏内联面板", error);
        activeModal = null;
        return false;
    }
}

/**
 * 内置「模板」固定渲染在所有自定义 tab 之后，所以只要把自己排到扩展 tab 的最后一位，
 * 就能紧邻「模板」上方。先立即注册保证入口及时出现，再在其它扩展注册完成后归一化一次位置。
 * 注意用数组内搬移而不是 unregister + register —— 后者会重复注册命令并打警告。
 */
function moveToEndLater(manager, attempt = 0) {
    setTimeout(() => {
        try {
            const tabs = manager.sidebarTab?.sidebarTabs;
            if (!Array.isArray(tabs) || tabs.length === 0) {
                if (attempt < 3) moveToEndLater(manager, attempt + 1);
                return;
            }
            const index = tabs.findIndex((tab) => tab?.id === TAB_ID);
            if (index === -1 || index === tabs.length - 1) return;
            const [self] = tabs.splice(index, 1);
            tabs.push(self);
        } catch (error) {
            console.warn("[XB_ToolBox] 调整「机智罗」侧栏位置失败", error);
        }
    }, attempt === 0 ? 1200 : 800);
}

/** 侧栏 tab 只当作按钮：弹出面板后立刻把侧栏收起 */
function collapseSidebarSoon() {
    setTimeout(() => {
        try {
            app.extensionManager?.command?.execute?.(`Workspace.ToggleSidebarTab.${TAB_ID}`);
        } catch (error) {
            console.warn("[XB_ToolBox] 收起侧栏失败", error);
        }
    }, 0);
}

function installAssets() {
    const cssHref = webAsset("xb_workflow_gallery.css");
    if (!document.querySelector("link[data-xb-wf-css]")) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = cssHref;
        link.dataset.xbWfCss = "1";
        document.head.append(link);
    }

    if (!document.querySelector("style[data-xb-wf-icon]")) {
        const iconHref = iconUrl("xb_icon_dark.png");
        const style = document.createElement("style");
        style.dataset.xbWfIcon = "1";
        // 用 alpha 蒙版 + currentColor，图标自动跟随明/暗主题与选中态颜色
        style.textContent = `
.${ICON_CLASS}::before {
    content: "";
    display: inline-block;
    width: 1.15em;
    height: 1.15em;
    background-color: currentColor;
    -webkit-mask: url("${iconHref}") center / contain no-repeat;
    mask: url("${iconHref}") center / contain no-repeat;
}`;
        document.head.append(style);
    }
}

app.registerExtension({
    name: "XB_ToolBox.WorkflowGallery",
    async setup() {
        installAssets();
        const manager = app.extensionManager;
        if (!manager?.registerSidebarTab) {
            console.warn("[XB_ToolBox] 当前前端不支持 registerSidebarTab，跳过「机智罗的工作流」入口");
            return;
        }
        const text = strings();
        const tab = {
            id: TAB_ID,
            icon: ICON_CLASS,
            title: text.tab,
            tooltip: text.tooltip,
            type: "custom",
            render(host) {
                if (openGalleryModal()) {
                    collapseSidebarSoon();
                    return;
                }
                Object.assign(host.style, { height: "100%", minHeight: "0", overflow: "hidden" });
                if (!host.querySelector(".xb-wf-root")) new WorkflowPanel(host);
            },
        };
        manager.registerSidebarTab(tab);
        moveToEndLater(manager);
    },
});
