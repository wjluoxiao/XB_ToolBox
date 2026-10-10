/**
 * XB-BOX - 🎵 YuE2 歌词 — 前端面板
 * ============================================================
 * 节点：XB_YuE2Lyrics（后端 nodes_yue2_lyrics.py，V1 经典 API）
 * 职责：
 *   ① ➕ 添加元素：段落标签快捷插入（独占一行）+ 自定义标签 + 行内角色标注
 *   ② 🎹 纯音乐骨架：一键写入官方器乐工作流的歌词写法
 *      （[Intro]/[Verse]/[Chorus]/[Outro] 只有标签、没有实词）
 *
 * 标签规范（来自 YuE2 官方 skill，不是模板说明里的举例）：
 *   · 官方段落词表共 **8 个**，来自 ABC 的 % section 规范，
 *     官方 instrumental.lyric_tags() 会标题化输出：
 *       % intro → [Intro]        % chorus → [Chorus]
 *       % verse → [Verse]        % bridge → [Bridge]
 *       % pre-chorus → [Pre-Chorus]   % interlude → [Interlude]
 *       % instrumental → [Instrumental]  % outro → [Outro]
 *   · 官方 ComfyUI 模板的说明只举了 [Verse]/[Chorus]/[Bridge]/[Outro] 四个，
 *     措辞是 "such as"，**不是全集**；YuE2 把 [xxx] 当通用段落标记，任意标签都能用；
 *   · 只认 [方括号]：圆括号 (Singer A): 会被当成歌词唱出来；
 *   · 角色标注属社区惯例（YuE2 原生 Vocal 是单声部），只能做弱控制；
 *   · 段落标签与歌词挤在同一行会降低识别率，插入时强制独占一行。
 */

import { app } from "../../scripts/app.js";
import { setWidgetValue } from "./xb_compat.js";

const NODE_TYPE = "XB_YuE2Lyrics";
const TEXT_WIDGET = "lyrics_text";
const PICKER_ID = "xb-yue2-lyrics-tag-picker";

// ① 官方 8 个段落标签（完整词表）
//    按钮文案 = 中文含义 + 实际标签；插入的是第二个元素（标签本身），中文只是给人看的。
const OFFICIAL_TAGS = [
    ["前奏 [Intro]", "[Intro]", "block", "歌曲开头的引子段"],
    ["主歌 [Verse]", "[Verse]", "block", "叙事段落，交代内容"],
    ["预副歌 [Pre-Chorus]", "[Pre-Chorus]", "block", "副歌前的爬升，推向高潮"],
    ["副歌 [Chorus]", "[Chorus]", "block", "高潮 / 记忆点，通常会重复"],
    ["桥段 [Bridge]", "[Bridge]", "block", "转折段落，一般在第二次副歌之后"],
    ["间奏 [Interlude]", "[Interlude]", "block", "段与段之间的器乐过渡"],
    ["器乐段 [Instrumental]", "[Instrumental]", "block", "整段无人声，纯器乐演奏"],
    ["尾奏 [Outro]", "[Outro]", "block", "结束段落，收尾"],
];

// ② 非官方写法（社区惯例，官方词表里没有）
const COMMUNITY_TAGS = [
    ["后副歌 [Post-Chorus]", "[Post-Chorus]", "block", "副歌之后的延伸段落"],
    ["独奏 [Solo]", "[Solo]", "block", "器乐独奏段"],
    ["主歌1 [Verse 1]", "[Verse 1]", "block", "第一段主歌（编号写法）"],
    ["主歌2 [Verse 2]", "[Verse 2]", "block", "第二段主歌（编号写法）"],
    ["副歌2 [Chorus 2]", "[Chorus 2]", "block", "第二段副歌（编号写法）"],
    ["最终副歌 [Final Chorus]", "[Final Chorus]", "block", "最后一次副歌，常加和声或升调"],
    ["记忆点 [Hook]", "[Hook]", "block", "反复出现的短句记忆点"],
    ["高潮 [Drop]", "[Drop]", "block", "电子曲风的高潮段"],
    ["骤停 [Breakdown]", "[Breakdown]", "block", "突然收窄的段落，用于对比"],
];

// ③ 人声角色（社区惯例，弱控制）
//    kind="block" → 独占一行的段落标签；kind="inline" → 光标处行内插入
const VOCAL_TAGS = [
    ["段落·男声 [Verse: Male Vocal]", "[Verse: Male Vocal]", "block", "整段由男声演唱"],
    ["段落·女声 [Verse: Female Vocal]", "[Verse: Female Vocal]", "block", "整段由女声演唱"],
    ["段落·对唱 [Chorus: Duet]", "[Chorus: Duet]", "block", "整段由两人对唱"],
    ["段落·合唱 [Chorus: Full Choir]", "[Chorus: Full Choir]", "block", "整段合唱"],
    ["行·角色A [Singer A]", "[Singer A] ", "inline", "行首标注角色 A：插在句首，后面接着写歌词"],
    ["行·角色B [Singer B]", "[Singer B] ", "inline", "行首标注角色 B：插在句首，后面接着写歌词"],
    ["行·齐唱 [Together]", "[Together] ", "inline", "行首标注齐唱：插在句首，后面接着写歌词"],
];

// 面板分组标题的悬浮说明
const GROUP_TIPS = {
    "OFFICIAL": "官方 skill 的完整段落词表（8 个），来自 ABC 的 % section 规范。"
        + "官方 ComfyUI 模板的说明只举了 [Verse]/[Chorus]/[Bridge]/[Outro] 四个，措辞是 “such as”，不是全集。",
    "COMMUNITY": "官方词表里没有这些标签。YuE2 把 [xxx] 当通用段落标记，因此能用，但属弱控制。",
    "VOCAL": "⚠️ YuE2 原生 Vocal 只有一条单声部旋律线，角色标注只能做文本弱控制。"
        + "只有 [方括号] 有效：用 (Singer A): 这种圆括号写法会被当成歌词唱出来。",
};

const SKELETON = "[Intro]\n\n[Verse]\n\n[Chorus]\n\n[Outro]\n";

function getLyricsWidget(node) {
    return (node?.widgets || []).find((w) => w.name === TEXT_WIDGET) || null;
}

function findTextarea(w) {
    const el = w?.element || w?.inputEl;
    if (!el) return null;
    if (el.tagName === "TEXTAREA") return el;
    if (typeof el.querySelector === "function") {
        return el.querySelector("textarea") || el.querySelector("input[type='text']") || null;
    }
    return null;
}

function bindCursorTracking(w) {
    const ta = findTextarea(w);
    if (!ta || ta.__xbLyricsBound) return;
    ta.__xbLyricsBound = true;
    const record = () => {
        w._xbSelStart = ta.selectionStart;
        w._xbSelEnd = ta.selectionEnd;
    };
    for (const event of ["focus", "click", "keyup", "mouseup"]) ta.addEventListener(event, record);
}

/** 把新文本写回 widget（DOM 输入框 / Vue 部件 / 回调三条通道都兜住） */
function writeText(node, w, text, caret) {
    setWidgetValue(w, text);
    const ta = findTextarea(w);
    if (ta) {
        ta.value = text;
        try {
            ta.focus();
            ta.setSelectionRange(caret, caret);
        } catch (_) { /* ignore */ }
        ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (typeof w.callback === "function") {
        try { w.callback(text); } catch (_) { /* ignore */ }
    }
    w._xbSelStart = caret;
    w._xbSelEnd = caret;
    node.graph?.setDirtyCanvas?.(true, true);
}

function insertTag(node, w, tag, inline) {
    bindCursorTracking(w);
    const ta = findTextarea(w);
    const text = String(w.value ?? "");
    let start, end;

    if (typeof w._xbSelStart === "number") {
        start = w._xbSelStart;
        end = typeof w._xbSelEnd === "number" ? w._xbSelEnd : start;
    } else if (ta && document.activeElement === ta) {
        start = ta.selectionStart ?? text.length;
        end = ta.selectionEnd ?? start;
    } else {
        start = text.length;
        end = text.length;
    }
    if (!Number.isFinite(start) || start < 0) start = text.length;
    if (!Number.isFinite(end) || end < start) end = start;

    // 段落标签独占一行；行级角色标注在光标处行内插入
    const prefix = (!inline && start > 0 && text[start - 1] !== "\n") ? "\n" : "";
    const inserted = inline ? tag : prefix + tag + "\n";
    const next = text.slice(0, start) + inserted + text.slice(end);
    writeText(node, w, next, start + inserted.length);
}

let pickerEscHandler = null;

function closeTagPicker() {
    document.getElementById(PICKER_ID)?.remove();
    if (pickerEscHandler) {
        window.removeEventListener("keydown", pickerEscHandler);
        pickerEscHandler = null;
    }
}

function makeButton(node, w, item) {
    const [label, tag, kind, tip] = item;
    const inline = kind === "inline";
    const button = document.createElement("button");
    button.textContent = label;
    if (tip) button.title = tip;
    button.style.cssText = "padding:7px 6px;border:1px solid #555;border-radius:6px;background:#2a2a2e;color:#eee;cursor:pointer;font-size:12px;line-height:1.25;text-align:left;";
    button.addEventListener("mouseenter", () => { button.style.background = "#3a3a40"; });
    button.addEventListener("mouseleave", () => { button.style.background = "#2a2a2e"; });
    button.addEventListener("click", () => {
        insertTag(node, w, tag, inline);
        if (!inline) closeTagPicker();
    });
    if (inline) button.style.borderColor = "#6a5acd";
    return button;
}

/** 分组标题：说明放 title（悬停可见），标题本身只写分组名 */
function addGroup(panel, title, tip, items, node, w, accent) {
    const head = document.createElement("div");
    head.textContent = title;
    if (tip) head.title = tip;
    head.style.cssText = `color:${accent || "#9ad"};font-size:12px;font-weight:600;margin:10px 0 6px;`
        + (tip ? "cursor:help;" : "");
    panel.appendChild(head);
    const grid = document.createElement("div");
    grid.style.cssText = "display:grid;grid-template-columns:repeat(3,1fr);gap:6px;";
    for (const item of items) grid.appendChild(makeButton(node, w, item));
    panel.appendChild(grid);
}

function addCustomTagRow(panel, node, w) {
    const head = document.createElement("div");
    head.textContent = "④ 自定义标签";
    head.title = "YuE2 接受任意 [标记]，例如 Rap / 吟唱 / 尾声；输入后回车或点「插入标签」。"
        + "官方词表之外的标签属弱控制，不保证被稳定识别。";
    head.style.cssText = "color:#c9a0dc;font-size:12px;font-weight:600;margin:12px 0 6px;cursor:help;";
    panel.appendChild(head);

    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:6px;";
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = "例如 Rap / 高潮 / 吟唱";
    input.style.cssText = "flex:1;padding:7px 8px;border:1px solid #555;border-radius:6px;background:#2a2a2e;color:#eee;font-size:12px;";
    const button = document.createElement("button");
    button.textContent = "插入标签";
    button.style.cssText = "padding:7px 12px;border:1px solid #555;border-radius:6px;background:#2a2a2e;color:#eee;cursor:pointer;font-size:12px;";
    const commit = () => {
        const raw = input.value.trim().replace(/^\[|\]$/g, "").trim();
        if (!raw) return;
        insertTag(node, w, `[${raw}]`, false);
        closeTagPicker();
    };
    button.addEventListener("click", commit);
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") commit(); });
    row.appendChild(input);
    row.appendChild(button);
    panel.appendChild(row);
    setTimeout(() => input.focus(), 30);
}

function showTagPicker(node, w) {
    closeTagPicker();
    const overlay = document.createElement("div");
    overlay.id = PICKER_ID;
    overlay.style.cssText = "position:fixed;left:0;top:0;right:0;bottom:0;background:rgba(0,0,0,.45);z-index:99999;display:flex;align-items:center;justify-content:center;";
    overlay.addEventListener("mousedown", (event) => { if (event.target === overlay) closeTagPicker(); });

    const panel = document.createElement("div");
    panel.style.cssText = "background:#1b1b1f;border:1px solid #444;border-radius:10px;padding:14px;max-width:700px;width:92%;max-height:86vh;overflow:auto;box-shadow:0 10px 40px rgba(0,0,0,.6);";

    const title = document.createElement("div");
    title.textContent = "添加元素";
    title.title = "点击标签插入到光标处。段落标签会独占一行并自动换行；"
        + "行级角色标注直接插在光标处，接着写歌词即可。";
    title.style.cssText = "color:#eee;font-size:14px;font-weight:600;margin-bottom:8px;cursor:help;";
    panel.appendChild(title);

    addGroup(panel, "① 官方段落词表（8 个）", GROUP_TIPS.OFFICIAL,
        OFFICIAL_TAGS, node, w, "#8fd18f");
    addGroup(panel, "② 社区写法（非官方）", GROUP_TIPS.COMMUNITY,
        COMMUNITY_TAGS, node, w, "#9ad");
    addGroup(panel, "③ 人声角色（弱控制）", GROUP_TIPS.VOCAL,
        VOCAL_TAGS, node, w, "#e0a96d");
    addCustomTagRow(panel, node, w);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    pickerEscHandler = (event) => { if (event.key === "Escape") closeTagPicker(); };
    window.addEventListener("keydown", pickerEscHandler);
}

app.registerExtension({
    name: "XB.YuE2Lyrics",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;
            const widget = getLyricsWidget(self);
            if (!widget) return result;

            setTimeout(() => bindCursorTracking(widget), 300);

            const buttons = [
                ["➕ 添加元素", () => showTagPicker(self, widget),
                 "插入段落标签 / 角色标注；也能输入自己的 [标签]"],
                ["🎹 纯音乐骨架", () => writeText(self, widget, SKELETON, SKELETON.length),
                 "一键写入 [Intro]/[Verse]/[Chorus]/[Outro] 空标签骨架（官方纯音乐工作流的歌词写法）"],
            ];
            const created = buttons.map(([label, handler, tip]) => {
                const btn = self.addWidget("button", label, label, handler);
                if (btn?.options) btn.options.serialize = false;
                try { btn.tooltip = tip; } catch (_) { /* ignore */ }
                return btn;
            });

            // 把按钮依次移到歌词文本框上方
            const list = self.widgets;
            const index = list.findIndex((x) => x.name === TEXT_WIDGET);
            for (const btn of created) {
                const at = list.indexOf(btn);
                if (at > -1) list.splice(at, 1);
            }
            list.splice(index < 0 ? 0 : index, 0, ...created);
            self.setDirtyCanvas?.(true, true);

            return result;
        };
    },
});
