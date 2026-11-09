/**
 * XB_ToolBox — 主题变量
 * ============================================================
 * 插件的 DOM widget（提示词面板、选择器、弹窗等）里的大量内联样式原本写死深色，
 * 在 ComfyUI 浅色主题下会变成"黑块"。这里统一注入一组 CSS 变量，
 * 各 widget 改用 var(--xb-*) 后即可自动跟随明暗主题。
 *
 * ComfyUI 通过调色板设置切换主题（不同版本可能改 <html> / <body> 的 class），
 * 所以这里监听 class 变化实时更新，无需刷新页面。
 */

import { app } from "../../scripts/app.js";

const PALETTE = {
    // 名称: [深色值, 浅色值]
    "--xb-bg": ["#1c1c1e", "#ffffff"],
    "--xb-bg-soft": ["#232326", "#f2f3f5"],
    "--xb-bg-raise": ["#2b2b2b", "#e9eaee"],
    "--xb-border": ["#3a3a3a", "#c9ced6"],
    "--xb-text": ["#dddddd", "#23262a"],
    "--xb-text-dim": ["#8a97a5", "#5c626b"],
    "--xb-accent-bg": ["#2d5a88", "#2f6fbf"],
    "--xb-info": ["#cfe3f7", "#1b5e9c"],
    "--xb-ok": ["#d7f0c8", "#1f7a3a"],
    "--xb-warn": ["#ffd98a", "#8a5f10"],
    "--xb-error": ["#ffd0d0", "#a32626"],
    "--xb-orange": ["#e8a87c", "#8a4a1f"],
    "--xb-on-accent": ["#eaf4ff", "#ffffff"],
    "--xb-tint-info": ["#2a4a6a", "#e3edf9"],
    "--xb-tint-warn": ["#5a4a2a", "#fdf1d6"],
    "--xb-tint-ok": ["#3a5a2a", "#e7f5e9"],
    "--xb-tint-error": ["#5a2a2a", "#fdeaea"],
    "--xb-btn-primary": ["#2d5a88", "#1f6fd0"],
    "--xb-inset": ["#191919", "#f5f6f8"],
    "--xb-float": ["#2a2a2e", "#ffffff"],
    "--xb-btn-info": ["#2a4a6a", "#1f6fd0"],
    "--xb-btn-warn": ["#b45309", "#c2410c"],
    "--xb-btn-ok": ["#2d5a3a", "#1f7a3a"],
    "--xb-btn-error": ["#a33a3a", "#b3261e"],
    "--xb-accent-bg-hover": ["#22456b", "#1a5cb0"],
    "--xb-accent-text": ["#eaf4ff", "#ffffff"],
};

function prefersLight() {
    const html = document.documentElement;
    const body = document.body;
    if (html?.classList?.contains("light-theme")) return true;
    if (html?.classList?.contains("dark-theme")) return false;
    if (body?.classList?.contains("light-theme")) return true;
    if (body?.classList?.contains("dark-theme")) return false;
    try {
        const palette = app?.ui?.settings?.getSettingValue?.("Comfy.ColorPalette");
        if (palette === "light") return true;
        if (palette === "dark") return false;
    } catch (_) { /* ignore */ }
    return false;
}

function applyTheme() {
    const light = prefersLight();
    const root = document.documentElement;
    for (const [name, [dark, bright]] of Object.entries(PALETTE)) {
        root.style.setProperty(name, light ? bright : dark);
    }
    root.dataset.xbTheme = light ? "light" : "dark";
}

let installed = false;

function install() {
    if (installed) return;
    installed = true;
    applyTheme();

    const observer = new MutationObserver(applyTheme);
    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class", "data-theme"],
    });
    if (document.body) {
        observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    }
}

app.registerExtension({
    name: "XB_ToolBox.Theme",
    async setup() {
        install();
    },
});
