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

const STRINGS = {
    zh: {
        tab: "机智罗",
        tooltip: "机智罗的工作流 · XB_ToolBox",
        panel: "机智罗的工作流",
        all: "全部",
        search: "搜索工作流…",
        refresh: "刷新",
        close: "关闭",
        loading: "正在加载工作流…",
        empty: "还没有工作流",
        noMatch: "没有匹配的工作流",
        listFailed: "工作流清单加载失败",
        loadFailed: "工作流加载失败",
        openedNew: "已在新标签页打开",
        loadedCurrent: "已加载到当前画布",
    },
    en: {
        tab: "JZL Workflows",
        tooltip: "JZL Workflows · XB_ToolBox",
        panel: "JZL Workflows",
        all: "Show all",
        search: "Search workflows…",
        refresh: "Refresh",
        close: "Close",
        loading: "Loading workflows…",
        empty: "No workflows yet",
        noMatch: "No matching workflows",
        listFailed: "Failed to load workflow index",
        loadFailed: "Failed to load workflow",
        openedNew: "Opened in a new workflow tab",
        loadedCurrent: "Loaded into the current canvas",
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

function flatten(manifest) {
    const items = [];
    for (const group of manifest) {
        if (!group || !Array.isArray(group.templates)) continue;
        const category = typeof group.category === "string" ? group.category : "";
        const subcategory = typeof group.title === "string" ? group.title : "";
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
                thumbnail: thumbnail ? thumbnail.replace(/\\/g, "/").split("/").pop() : "",
            });
        }
    }
    return items;
}

function filterItems(items, subcategory, query) {
    const needle = (query || "").trim().toLowerCase();
    return items.filter((item) => {
        if (subcategory && (item.subcategory || item.category) !== subcategory) return false;
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
 * 新建空白工作流标签页。
 * 无 workflow 标签页机制的老版本会退化为清空当前画布，因此这里只做「尝试」。
 */
async function tryNewBlankWorkflow() {
    try {
        const command = app.extensionManager?.command;
        if (command?.execute) {
            await command.execute("Comfy.NewBlankWorkflow");
            return true;
        }
    } catch (error) {
        console.warn("[XB_ToolBox] 新建空白工作流失败，回退为替换当前画布", error);
    }
    return false;
}

/** 打开清单里的一个工作流；返回是否新建了标签页 */
async function openWorkflowItem(item) {
    const response = await api.fetchApi(ASSET_BASE + item.name + ".json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const graph = await response.json();

    const workflowStore = app.extensionManager?.workflow;
    const before = new Set(workflowStore?.openWorkflows?.map((wf) => wf.path) ?? []);

    // 工作流自带 id 时 loadGraphData 会直接开新标签页；否则先补一个空白标签页，
    // 避免顶掉用户当前画布。
    if (!graph?.id && !graph?.path) await tryNewBlankWorkflow();

    await app.loadGraphData(graph);

    // 模板不是用户保存过的文件，新标签页默认叫 “Unsaved Workflow (n)”，改成可读标题
    const created = workflowStore?.openWorkflows?.find((wf) => !before.has(wf.path));
    if (created && workflowStore.renameWorkflow) {
        try {
            await workflowStore.renameWorkflow(created, item.title);
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

    card.append(thumb, name, tags);
    card.addEventListener("click", () => onOpen(item));
    return card;
}

/** 居中大弹窗 —— 与官方「模板」一致的布局：左分类 / 顶部搜索 / 卡片网格 */
class WorkflowModal {
    constructor() {
        this.items = [];
        this.subcategory = "";
        this.query = "";
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

        const side = el("aside", "xb-wf-side");
        const sideHead = el("div", "xb-wf-side-head");
        const logo = document.createElement("img");
        logo.className = "xb-wf-logo";
        logo.alt = "";
        logo.src = logoUrl();
        sideHead.append(logo, el("span", "xb-wf-side-title", text.panel));
        this.sideList = el("div", "xb-wf-side-list");
        side.append(sideHead, this.sideList);

        const main = el("section", "xb-wf-main");
        const head = el("header", "xb-wf-main-head");
        this.searchInput = document.createElement("input");
        this.searchInput.type = "search";
        this.searchInput.className = "xb-wf-search-input";
        this.searchInput.placeholder = text.search;
        this.searchInput.addEventListener("input", () => {
            this.query = this.searchInput.value;
            this.renderGrid();
        });

        this.refreshBtn = el("button", "xb-wf-icon-btn", "⟳");
        this.refreshBtn.type = "button";
        this.refreshBtn.title = text.refresh;
        this.refreshBtn.addEventListener("click", () => this.load());

        this.closeBtn = el("button", "xb-wf-icon-btn xb-wf-close", "✕");
        this.closeBtn.type = "button";
        this.closeBtn.title = text.close;
        this.closeBtn.setAttribute("aria-label", text.close);
        this.closeBtn.addEventListener("click", () => this.close());

        head.append(this.searchInput, this.refreshBtn, this.closeBtn);

        this.grid = el("div", "xb-wf-grid");
        this.status = el("div", "xb-wf-status");
        main.append(head, this.grid, this.status);

        modal.append(side, main);
        this.backdrop.append(modal);
        document.body.append(this.backdrop);

        this.onKeyDown = (event) => {
            if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                this.close();
            }
        };
        this.onBackdropClick = (event) => {
            if (event.target === this.backdrop) this.close();
        };
        document.addEventListener("keydown", this.onKeyDown, true);
        this.backdrop.addEventListener("mousedown", this.onBackdropClick);

        this.previousOverflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";

        this.searchInput.focus();
        this.load();
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
        this.sideList.innerHTML = "";

        const counts = new Map();
        for (const item of this.items) {
            const key = item.subcategory || item.category;
            counts.set(key, (counts.get(key) || 0) + 1);
        }

        const makeItem = (label, value, count) => {
            const item = el("button", "xb-wf-side-item");
            item.type = "button";
            item.title = `${label} (${count})`;
            item.append(
                el("span", "xb-wf-side-label", label),
                el("span", "xb-wf-side-count", String(count)),
            );
            item.classList.toggle("is-active", this.subcategory === value);
            item.addEventListener("click", () => {
                this.subcategory = value;
                this.renderCategories();
                this.renderGrid();
            });
            return item;
        };

        this.sideList.append(makeItem(text.all, "", this.items.length));
        for (const name of subcategoriesOf(this.items)) {
            this.sideList.append(makeItem(name, name, counts.get(name) || 0));
        }
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
