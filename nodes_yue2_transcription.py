"""XB-BOX - 🎵 YuE2 转谱导入（SheetSage2 输出 → 可用谱面）

官方转谱链路（SheetSage2，音频 → ABC/MIDI/events）需要**独立的 Python 环境**
（Python 3.10/3.11 + torch 2.8/cu126，与 YuE2 依赖冲突），所以本节点不做转谱本身，
只负责把它的产物**读进来、校验、规范化**，再交给后面的节点：

    官方 CLI 转谱 ──→ score.abc / events.json ──→ 本节点 ──→ 🎵 翻唱准备 / 🎵 乐谱工作台
                                                        └──→ 官方 YuE2GenerateMusic（abc 输入）

规范化严格限定在官方 abc-repair.md「常见修复」里可机械判定的项（去 BOM / Markdown 围栏 /
弯引号、M:C→M:4/4、Q:81→Q:1/4=81、K:B minor→K:Bm）。语义性修复（展开反复、量化三连音、
补休止…）一律不猜 —— 那种情况官方要求人工修谱，节点只把官方校验器的原始报错原样给你。

⚠️ 转谱误差是独立误差来源：官方明确「转轨/比对检查只证明转写谱上的音符被保住，
不代表转写本身忠于录音」。节点报告里会一直带着这句。

CATEGORY: JZL/YuE2
"""

import json
import os
import pathlib

try:
    from .yue2_abc import (
        AbcError, compile_events, diff_lines, mode_suggestion, normalize_abc_text,
        parse_abc, sha_line, summary_text,
    )
except ImportError:  # 以文件方式直接加载时的兜底
    from yue2_abc import (
        AbcError, compile_events, diff_lines, mode_suggestion, normalize_abc_text,
        parse_abc, sha_line, summary_text,
    )

DISCLAIMER = "（符号层结论：不代表音频效果；转谱误差是独立误差来源）"
ABC_NAMES = ("score.abc", "melody.abc", "cover.abc")
EVENT_NAMES = ("events.json",)


def _comfy_input_dir() -> str:
    try:
        import folder_paths
        return folder_paths.get_input_directory()
    except Exception:  # 脱离 ComfyUI 时（如单元测试）
        return os.getcwd()


def _resolve(path_text: str) -> pathlib.Path:
    """相对路径按 ComfyUI 的 input 目录解析；绝对路径原样使用。"""
    raw = (path_text or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("路径为空：请填 SheetSage2 输出的目录或 score.abc / events.json 的路径")
    candidate = pathlib.Path(os.path.expandvars(os.path.expanduser(raw)))
    if not candidate.is_absolute():
        candidate = pathlib.Path(_comfy_input_dir()) / candidate
    return candidate


def _sniff_kind(path: pathlib.Path, text: str) -> str:
    if path.suffix.lower() == ".json":
        return "events"
    if path.suffix.lower() == ".abc":
        return "abc"
    head = text.lstrip()[:1]
    if head == "{" or path.suffix.lower() in (".jsonl", ".txt") and '"bars"' in text:
        return "events"
    return "abc"


def _list_files(directory: pathlib.Path) -> list:
    """列出目录里的关键产物，方便用户知道转谱到底给了什么。"""
    try:
        names = sorted(item.name for item in directory.iterdir() if item.is_file())
    except OSError:
        return []
    keep = [name for name in names
            if name.endswith((".abc", ".json", ".mid", ".lab", ".txt"))]
    return keep[:12]


def _error_report(title: str, error: Exception, extra: str = "") -> str:
    body = [f"❌ {title}失败", f"原因: {error}"]
    if extra:
        body.append(extra)
    body.append("")
    body.append("官方修谱表里可机械判定的项（去围栏/BOM/弯引号、M:C→M:4/4、Q:81→Q:1/4=81、"
                "K:B minor→K:Bm）本节点会自动处理；其余属于语义性修复（展开反复、量化三连音、"
                "补休止、多轨缩编…），官方要求人工处理，节点不猜。")
    return "\n".join(body) + f"\n{DISCLAIMER}"


class XB_YuE2Transcription:
    """YuE2 转谱导入 — 读取 SheetSage2 的 score.abc / events.json 并校验"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "转谱路径": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": ("SheetSage2 的输出目录，或直接指向 score.abc / events.json。\n"
                                "目录时会自动找 score.abc，找不到再用 events.json；\n"
                                "相对路径按 ComfyUI 的 input 目录解析，绝对路径原样使用"),
                }),
                "规范化": ("BOOLEAN", {
                    "default": True,
                    "tooltip": ("按官方 abc-repair.md 做机械规范化：去 BOM / Markdown 围栏 / 弯引号 / "
                                "行尾空白，M:C→M:4/4，Q:81→Q:1/4=81，K:B minor→K:Bm。\n"
                                "改动会逐条写进报告；语义性修复不会做"),
                }),
            },
            "optional": {
                "abc": ("STRING", {"forceInput": True,
                                   "tooltip": "可选：接入上游谱面做比对方（留空则只处理文件）"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("abc", "报告")
    FUNCTION = "run"
    CATEGORY = "JZL/YuE2"

    def run(self, 转谱路径, 规范化, abc=None):
        try:
            path = _resolve(转谱路径)
        except ValueError as error:
            return ("", _error_report("解析路径", error))

        if not path.exists():
            return ("", _error_report("读取转谱结果", FileNotFoundError(f"路径不存在：{path}")))
        if path.is_dir():
            listing = _list_files(path)
            found = next((path / name for name in ABC_NAMES if (path / name).is_file()), None)
            if found is None:
                found = next((path / name for name in EVENT_NAMES if (path / name).is_file()), None)
            if found is None:
                return ("", _error_report(
                    "在目录里找谱面",
                    FileNotFoundError(f"{path} 里没有 score.abc 也没有 events.json"),
                    "目录内文件: " + ("、".join(listing) if listing else "（空）")))
            source_path = found
        else:
            source_path = path
        # 报告里列「同目录其它产物」时用原始目录，而不是定位到的文件
        base_dir = path if path.is_dir() else path.parent

        try:
            raw = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            return ("", _error_report("读取文件", error))

        kind = _sniff_kind(source_path, raw)
        header = [f"📋 YuE2 转谱导入报告　｜　来源: {source_path.name}（{kind}）", ""]

        try:
            changes = []
            if kind == "events":
                events = json.loads(raw)
                if not isinstance(events, dict):
                    raise AbcError("events.json 顶层必须是对象")
                output, _check = compile_events(events)
                header.append(
                    f"事件: 小节 {len(events.get('bars') or [])}，音符 {len(events.get('notes') or [])}，"
                    f"和弦 {len(events.get('chords') or [])}    BPM {events.get('bpm')}，"
                    f"调号 {events.get('key', 'C')}")
                header.append("说明: 事件已按官方事件编译器展开为原生谱面（自动补休止/连音/分组）")
            else:
                output, changes = (normalize_abc_text(raw) if 规范化 else (raw, []))
                if 规范化:
                    header.append("规范化: " + ("、".join(changes) if changes else "无需改动"))
                parse_abc(output)
        except json.JSONDecodeError as error:
            return ("", _error_report("解析 events.json", error,
                                      "目录内文件: 见路径提示" if path.is_dir() else ""))
        except (AbcError, ValueError) as error:
            note = ""
            listing = _list_files(base_dir)
            if listing:
                note = "目录内文件: " + "、".join(listing)
            return ("", _error_report(f"校验 {source_path.name}", error, note))

        mode, reason = mode_suggestion(output)
        header.append(f"模式建议: mode={mode} —— {reason}")
        body = ["\n".join(header), "", summary_text(output)]
        upstream = (abc or "").strip()
        if upstream:
            try:
                body += ["", "与接入的谱面差异:"] + [f"  · {item}" for item in diff_lines(upstream, output)]
            except (AbcError, ValueError) as error:
                body += ["", f"与接入的谱面对比跳过（上游谱面无法解析：{error}）"]
        body.append("")
        body.append("【官方转谱链路提醒】")
        body.append("1. 转谱误差是独立误差来源：本节点的校验只证明「转写谱」合法，"
                    "不代表转写忠于原录音 —— 请对照原音频复核音符、拍号、调号与段落顺序。")
        body.append("2. 转谱输出通常还要去掉和弦（本节点或「🎵 乐谱工作台」的去掉和弦），"
                    "再按官方规则选 mode：无和弦→melody 翻唱、保留和弦→full。")
        body.append("3. 歌词不由转谱给出：官方要求另行获取或转写并校对，"
                    "段落标签要与谱面结构对齐。")
        listing = _list_files(base_dir)
        if listing:
            body.append("")
            body.append("同目录其它产物: " + "、".join(listing))
        body.append("")
        body.append("配器（乐器 / 音色）不在谱面里：请用上游「🎵 YuE2 风格提示」的"
                     "「主奏乐器 / 辅助乐器」设定")
        report = "\n".join(body) + f"\n\n{sha_line(output)}\n{DISCLAIMER}"
        return (output, report)
