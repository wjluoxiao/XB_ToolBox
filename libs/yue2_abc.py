"""YuE2 原生 ABC 方言工具（节点内嵌版，纯标准库，无文件 I/O）

本模块是官方 YuE2 skill 的移植版本：去掉 argparse / Path / json 落盘，
只保留纯函数，供 ComfyUI 节点在内存里直接调用。

  解析与结构报告   ← skills/yue2-music/scripts/abc_tools.py
  记谱编译器       ← skills/yue2-music/instrumental/scripts/compile_score.py
  人声转器乐       ← skills/yue2-music/instrumental/scripts/instrumentalize.py
  器乐请求校验     ← skills/yue2-music/instrumental/scripts/instrumental.py
                     (validate_score / lyric_tags)

来源: https://github.com/multimodal-art-projection/YuE
许可: skills/yue2-music 为 Apache-2.0；instrumental/ 下的助手脚本为 MIT
      (Copyright (c) 2026 yue2-music contributors, 见 instrumental/LICENSE)。
      XB_ToolBox 本体同为 Apache-2.0，二者兼容。

⚠️ 这是「有界原生方言」校验器，不是通用 ABC 解析器：不认识的材料一律拒绝
   （反复号、装饰音、多音叠置、连音符、w: 歌词行、非白名单和弦后缀等）。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from fractions import Fraction
from math import lcm


# ═══════════════════════════════════════════════════════════════════════
#  原生方言常量（官方 ABC 记谱规范）
# ═══════════════════════════════════════════════════════════════════════

VOICES = ("Vocal", "Ins")
DURATIONS = {1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48}
QUALITIES = ("", "m", "dim", "aug", "7", "maj7", "m7", "dim7", "m7b5",
             "sus4", "sus2", "6", "m6", "7sus4", "m(maj7)")
PITCH_NAME = r"[A-G](?:bb|##|b|#)?"
CHORD = re.compile(PITCH_NAME + "(?:" + "|".join(re.escape(q) for q in QUALITIES)
                   + ")(?:/" + PITCH_NAME + ")?")
TOKEN = re.compile(
    r'"(?P<chord>[^"\n]*)"|\[K:(?P<key>[^\]\n]+)\]|'
    r"(?P<acc>\^\^|__|\^|_|=)?(?P<note>[A-Ga-gz])"
    r"(?P<oct>[,']*)(?P<duration>[0-9]*)(?P<tie>-?)"
)
NATURAL = dict(zip("CDEFGAB", (0, 2, 4, 5, 7, 9, 11)))
KEYS = {
    **dict(zip(("Cb", "Gb", "Db", "Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#"), range(-7, 8))),
    **dict(zip(("Abm", "Ebm", "Bbm", "Fm", "Cm", "Gm", "Dm", "Am", "Em", "Bm", "F#m", "C#m", "G#m", "D#m", "A#m"), range(-7, 8))),
}

# 原生段落注释词表（% verse / % chorus …，用于器乐链路与段落标签生成）
# 这是官方 skill 的完整词表（compile_score.SECTIONS），共 8 个；
# 官方 instrumental.lyric_tags() 会把它们按原标题化成歌词标签：
#   % interlude → [Interlude]、% pre-chorus → [Pre-Chorus]、% instrumental → [Instrumental]
SECTIONS = ("intro", "verse", "pre-chorus", "chorus", "bridge", "interlude", "outro", "instrumental")

# 官方 8 个段落标签（按歌曲常见顺序排列，供 UI 与检查共用同一份数据）
OFFICIAL_SECTION_TAGS = ("Intro", "Verse", "Pre-Chorus", "Chorus", "Bridge",
                         "Interlude", "Instrumental", "Outro")


def official_section_tags() -> list:
    """官方段落标签列表 `['[Intro]', '[Verse]', …]`。"""
    return [f"[{name}]" for name in OFFICIAL_SECTION_TAGS]


class AbcError(ValueError):
    """不支持的记谱，或结构性不变量校验失败。"""


def fail(condition: bool, message: str) -> None:
    if condition:
        raise AbcError(message)


# ═══════════════════════════════════════════════════════════════════════
#  解析器
# ═══════════════════════════════════════════════════════════════════════

def key_accidentals(key: str) -> dict:
    fail(key not in KEYS, f"Unsupported key {key!r}; use a standard major or minor K: field")
    count = KEYS[key]
    result = {letter: 0 for letter in NATURAL}
    for letter in ("FCGDAEB" if count > 0 else "BEADGCF")[:abs(count)]:
        result[letter] = 1 if count > 0 else -1
    return result


def meter_value(text: str) -> tuple:
    match = re.fullmatch(r"([1-9][0-9]*)/([1-9][0-9]*)", text)
    fail(match is None, f"Unsupported meter {text!r}; write an explicit fraction")
    n, d = map(int, match.groups())
    fail(d > 1024 or d & (d - 1) != 0, f"Unsupported meter denominator {d}")
    return n, d


@dataclass
class Voice:
    meter: tuple
    key: str
    time: Fraction = Fraction(0)
    notes: list = field(default_factory=list)
    bars: list = field(default_factory=list)
    chords: list = field(default_factory=list)
    keys: list = field(default_factory=list)
    pending: tuple = None


@dataclass
class Score:
    text: str
    unit: Fraction
    bpm: int
    voices: dict
    music_lines: dict


def parse_bar(body: str, voice: Voice, unit: Fraction, context: str) -> None:
    n, d = voice.meter
    length = Fraction(4 * n, d)
    start = voice.time
    offset = Fraction(0)
    local = {}  # 原生约定：临时变音号按字母跨八度传播
    if body == "Z":
        fail(voice.pending is not None, f"{context}: tie enters a full-measure rest")
        offset = length
    else:
        cursor = 0
        while cursor < len(body):
            if body[cursor].isspace():
                cursor += 1
                continue
            match = TOKEN.match(body, cursor)
            fail(match is None, f"{context}: unsupported token at {body[cursor:cursor + 24]!r}")
            cursor = match.end()
            chord, key = match.group("chord", "key")
            fail(offset >= length, f"{context}: event after the measure end")
            if chord is not None:
                fail(CHORD.fullmatch(chord) is None, f"{context}: unsupported chord {chord!r}")
                voice.chords.append((start + offset, chord))
                continue
            if key is not None:
                key_accidentals(key)
                voice.key = key
                voice.keys.append((start + offset, key))
                local = {}
                continue
            note, acc, octave, tie = match.group("note", "acc", "oct", "tie")
            units = int(match.group("duration") or "1")
            fail(units not in DURATIONS, f"{context}: unsupported duration {units}; split it into tied supported lengths")
            duration = units * unit * 4
            fail(offset + duration > length, f"{context}: note/rest exceeds meter duration")
            fail("," in octave and "'" in octave, f"{context}: mixed octave marks")
            if note == "z":
                fail(bool(acc or octave or tie), f"{context}: a rest cannot have accidentals, octave marks or ties")
                fail(voice.pending is not None, f"{context}: tie enters a rest")
            else:
                letter = note.upper()
                written = 60 + NATURAL[letter] + (12 if note.islower() else 0)
                written += 12 * (octave.count("'") - octave.count(","))
                alteration = local.get(letter, key_accidentals(voice.key)[letter])
                if acc:
                    alteration = {"=": 0, "_": -1, "__": -2, "^": 1, "^^": 2}[acc]
                    local[letter] = alteration
                pitch = written + alteration
                if voice.pending is not None:
                    old_pitch, old_written = voice.pending
                    # 跨小节的连音延续保留原临时变音号，且不影响该小节后续非连音音符
                    if not acc and written == old_written:
                        pitch = old_pitch
                    fail(pitch != old_pitch, f"{context}: tie changes pitch from {old_pitch} to {pitch}")
                    voice.notes[-1][2] += duration
                else:
                    fail(not 0 <= pitch <= 127, f"{context}: pitch {pitch} is outside MIDI range")
                    voice.notes.append([start + offset, pitch, duration])
                voice.pending = (pitch, written) if tie else None
            offset += duration
    fail(offset != length, f"{context}: duration {offset} quarter notes != meter duration {length}")
    voice.bars.append((start, length, voice.meter))
    voice.time += length


def parse(text: str) -> Score:
    """遇到不支持的记号直接拒绝；统计的是合并连音后的发声音符，而非原始 token。"""
    lines = text.splitlines()
    fail(len(lines) < 12, "Incomplete native two-voice ABC")
    fail(lines[0:2] != ["X:1", "T:"], "Expected native X:1 and blank T: header")
    fail(not lines[2].startswith("M:"), "Missing header M:")
    meter = meter_value(lines[2][2:])
    unit_match = re.fullmatch(r"L:1/([1-9][0-9]*)", lines[3])
    fail(unit_match is None, "Expected L:1/<power of two>, usually L:1/32")
    denominator = int(unit_match.group(1))
    fail(denominator > 1024 or denominator & (denominator - 1) != 0, "Unsupported L: denominator")
    unit = Fraction(1, denominator)
    tempo_match = re.fullmatch(r"Q:1/4=([1-9][0-9]*)", lines[4])
    fail(tempo_match is None, "Expected integer quarter-note tempo Q:1/4=<BPM>")
    expected_voices = ['V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
                       'V: Ins clef=treble name="Ins Melody" snm="Inst."']
    fail(lines[5:7] != expected_voices, "Preserve native Vocal and Ins voice definitions")
    fail(not lines[7].startswith("K:"), "Missing header K:")
    key = lines[7][2:]
    key_accidentals(key)
    voices = {name: Voice(meter, key, keys=[(Fraction(0), key)]) for name in VOICES}
    music_lines = {}
    cursor = 8
    group = 0
    while cursor < len(lines):
        while cursor < len(lines) and lines[cursor].startswith("% "):
            cursor += 1
        fail(cursor == len(lines), "Dangling section comment without music")
        group += 1
        counts = []
        for name in VOICES:
            context = f"group {group}, {name}"
            fail(cursor >= len(lines) or lines[cursor] != f"V: {name}", f"{context}: expected V: {name}")
            cursor += 1
            voice = voices[name]
            fields = set()
            while cursor < len(lines) and lines[cursor].startswith(("M:", "K:")):
                field_name, value = lines[cursor].split(":", 1)
                fail(field_name in fields, f"{context}: duplicate {field_name}: field")
                fields.add(field_name)
                if field_name == "M":
                    voice.meter = meter_value(value)
                else:
                    key_accidentals(value)
                    voice.key = value
                    voice.keys.append((voice.time, value))
                cursor += 1
            fail(cursor >= len(lines), f"{context}: missing music line")
            line = lines[cursor]
            fail(not line.endswith("|"), f"{context}: music line must end with a plain barline")
            music_lines[cursor] = name
            cursor += 1
            bars = []
            for bar in line[:-1].split("|"):
                bar = bar.strip()
                fail(not bar, f"{context}: empty measure or unsupported double/repeat barline")
                rest = re.fullmatch(r"Z([2-4])?", bar)
                if rest:
                    bars.extend(["Z"] * int(rest.group(1) or "1"))
                else:
                    bars.append(bar)
            fail(not 1 <= len(bars) <= 4, f"{context}: expected 1–4 measures after expanding Z rests")
            counts.append(len(bars))
            for bar in bars:
                parse_bar(bar, voice, unit, f"{context}, bar {len(voice.bars) + 1}")
        fail(counts[0] != counts[1], f"group {group}: voices have different measure counts")
    for name, voice in voices.items():
        fail(voice.pending is not None, f"{name}: unresolved tie at end of score")
    fail(voices["Ins"].chords != [], "Native chord symbols belong in Vocal, not Ins")
    fail(voices["Vocal"].bars != voices["Ins"].bars, "Voice meter/time grids differ")
    fail(voices["Vocal"].keys != voices["Ins"].keys, "Voice key-change timelines differ")
    return Score(text, unit, int(tempo_match.group(1)), voices, music_lines)


def parse_abc(text: str) -> Score:
    """公开入口：不加载模型、不访问文件、无第三方依赖。"""
    return parse(text)


def json_value(value):
    if isinstance(value, Fraction):
        return str(value)
    raise TypeError(type(value).__name__)


def report(score: Score) -> dict:
    return {
        "scope": "native-dialect structural check; not native serializer reconstruction or audio verification",
        "sha256": hashlib.sha256(score.text.encode()).hexdigest(),
        "bpm": score.bpm, "unit_length": str(score.unit),
        "duration_quarters": str(score.voices["Vocal"].time),
        "nominal_duration_seconds": float(score.voices["Vocal"].time * 60 / score.bpm),
        "voices": {name: {"sounding_notes": len(v.notes), "measures": len(v.bars),
                          "notes": [{"onset_quarters": str(t), "midi_pitch": p, "duration_quarters": str(d)}
                                    for t, p, d in v.notes],
                          "chords": v.chords, "keys": v.keys, "bars": v.bars}
                   for name, v in score.voices.items()},
    }


def compare(before: Score, after: Score, names=VOICES, allow_tempo_change=False) -> dict:
    differences = []
    if before.bpm != after.bpm and not allow_tempo_change:
        differences.append("quarter-note tempo differs")
    for name in names:
        a, b = before.voices[name], after.voices[name]
        if a.bars != b.bars:
            differences.append(f"{name}: bar meter/time grid differs")
        if a.notes != b.notes:
            common = min(len(a.notes), len(b.notes))
            first = next((i for i in range(common) if a.notes[i] != b.notes[i]), common)
            differences.append(f"{name}: sounding notes differ starting at note {first + 1} (pitch, onset or duration)")
    return {"match": not differences, "compared_voices": list(names),
            "tempo_change_allowed": allow_tempo_change, "differences": differences,
            "scope": "exact symbolic melody and meter; no claim about generated audio or unchanged harmony"}


def strip_chords(text: str, keep_voice: str = "both") -> str:
    """去掉乐曲行里的和弦记号；keep_voice 指定只保留某一声部时，另一声部补等时值休止。"""
    fail(keep_voice not in ("both", *VOICES), f"keep_voice must be one of {'both', *VOICES}")
    source = parse(text)
    lines = text.splitlines(keepends=True)
    for index, name in source.music_lines.items():
        def transform(match):
            if match.group("chord") is not None:
                return ""
            if keep_voice != "both" and name != keep_voice and match.group("note") is not None:
                return "z" + match.group("duration")
            return match.group(0)
        lines[index] = TOKEN.sub(transform, lines[index])
    output = "".join(lines)
    result = parse(output)
    names = VOICES if keep_voice == "both" else (keep_voice,)
    invariant = compare(source, result, names)
    fail(not invariant["match"], f"Chord removal changed melody: {invariant['differences']}")
    fail(any(v.chords for v in result.voices.values()), "Chord removal left a chord symbol")
    if keep_voice != "both":
        fail(any(v.notes for name, v in result.voices.items() if name != keep_voice), "Unselected voice was not silenced")
    return output


# ═══════════════════════════════════════════════════════════════════════
#  记谱编译器（事件 → 原生 ABC）
# ═══════════════════════════════════════════════════════════════════════

def fraction(value, context):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{context}: use integer or fraction string, not a float")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{context}: invalid fraction {value!r}") from exc


def lengths(value):
    if value.denominator != 1 or value <= 0:
        raise ValueError(f"Unrepresentable duration in ABC units: {value}")
    left = int(value)
    result = []
    for part in sorted(DURATIONS, reverse=True):
        while left >= part:
            result.append(part)
            left -= part
    return result


def spelling(pitch, key, active):
    signature = key_accidentals(key)
    prefer_sharp = sum(signature.values()) >= 0
    candidates = []
    for letter, pc in NATURAL.items():
        for alteration in (-1, 0, 1):
            base = pitch - alteration - 60 - pc
            if base % 12:
                continue
            octave = base // 12
            score = (alteration != signature[letter], abs(alteration),
                     (alteration < 0) if prefer_sharp else (alteration > 0))
            candidates.append((score, letter, alteration, octave))
    _, letter, alteration, octave = min(candidates)
    accidental = ""
    if alteration != active.get(letter, signature[letter]):
        accidental = {-1: "_", 0: "=", 1: "^"}[alteration]
        active[letter] = alteration
    name = letter + "," * (-octave) if octave < 0 else (
        letter if octave == 0 else letter.lower() + "'" * (octave - 1))
    return accidental + name


def compress(bars):
    result, index = [], 0
    while index < len(bars):
        if bars[index] != "Z":
            result.append(bars[index] + "|")
            index += 1
            continue
        end = index + 1
        while end < len(bars) and bars[end] == "Z":
            end += 1
        count = end - index
        result.append("Z" + (str(count) if count > 1 else "") + "|")
        index = end
    return "".join(result)


def compile_events(data: dict) -> tuple:
    """把显式事件（bpm/key/bars/notes/chords）编译回原生 ABC 文本。"""
    if not isinstance(data, dict) or set(data) - {"bpm", "key", "bars", "notes", "chords"}:
        raise ValueError("Score requires bpm, key, bars, notes and optional chords; unknown fields are rejected")
    bpm = data.get("bpm")
    if type(bpm) is not int or bpm <= 0:
        raise ValueError("bpm must be a positive integer quarter-note tempo")
    key = data.get("key", "C")
    key_accidentals(key)
    if not isinstance(data.get("bars"), list) or not data["bars"]:
        raise ValueError("bars must be a nonempty list")
    bars, time, meter, section = [], Fraction(0), "4/4", None
    unit_denominator = 32
    for i, item in enumerate(data["bars"]):
        if not isinstance(item, dict) or set(item) - {"meter", "key", "section"}:
            raise ValueError(f"bar {i + 1}: only meter, key and section are supported")
        meter, key = item.get("meter", meter), item.get("key", key)
        n, d = meter_value(meter)
        key_accidentals(key)
        unit_denominator = lcm(unit_denominator, 4 * d)
        incoming = item.get("section", section)
        if incoming is not None and incoming not in SECTIONS:
            raise ValueError(f"bar {i + 1}: section must be one of {sorted(SECTIONS)}")
        section = incoming
        end = time + Fraction(4 * n, d)
        bars.append(dict(start=time, end=end, meter=meter, key=key, section=section))
        time = end
    notes = []
    for i, item in enumerate(data.get("notes", [])):
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError(f"note {i + 1}: expected [onset, duration, MIDI pitch]")
        start, duration = fraction(item[0], f"note {i + 1} onset"), fraction(item[1], f"note {i + 1} duration")
        pitch = item[2]
        if type(pitch) is not int or not 0 <= pitch <= 127:
            raise ValueError(f"note {i + 1}: pitch must be one MIDI integer; reduce polyphony first")
        if start < 0 or duration <= 0 or start + duration > time:
            raise ValueError(f"note {i + 1}: onset/duration is outside the score")
        notes.append((start, pitch, duration))
        unit_denominator = lcm(unit_denominator, (start / 4).denominator, (duration / 4).denominator)
    notes.sort()
    if not notes:
        raise ValueError("Instrumental score has no sounding notes")
    for a, b in zip(notes, notes[1:]):
        if a[0] + a[2] > b[0]:
            raise ValueError(f"Overlapping melody notes at quarter {b[0]}; choose one lead line before compilation")
    chords = []
    for i, item in enumerate(data.get("chords", [])):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"chord {i + 1}: expected [onset, symbol]")
        when = fraction(item[0], f"chord {i + 1} onset")
        symbol = item[1]
        if when < 0 or when >= time or not isinstance(symbol, str) or not CHORD.fullmatch(symbol):
            raise ValueError(f"chord {i + 1}: unsupported symbol or onset")
        chords.append((when, symbol))
        unit_denominator = lcm(unit_denominator, (when / 4).denominator)
    chords.sort()
    if any(a[0] == b[0] for a, b in zip(chords, chords[1:])):
        raise ValueError("Conflicting/duplicate chord events at the same onset; choose one harmony timeline")
    if unit_denominator > 1024 or unit_denominator & (unit_denominator - 1):
        raise ValueError("Rhythm is outside the power-of-two training grid; explicitly quantize tuplets and record the changes")
    unit_quarters = Fraction(4, unit_denominator)
    ins, vocal = [], []
    for bar in bars:
        start, end = bar["start"], bar["end"]
        events = [x for x in notes if x[0] < end and x[0] + x[2] > start]
        pieces, cursor, active = [], start, {}
        for onset, pitch, duration in events:
            a, b = max(start, onset), min(end, onset + duration)
            if a > cursor:
                pieces.extend("z" + (str(n) if n != 1 else "") for n in lengths((a - cursor) / unit_quarters))
            parts = lengths((b - a) / unit_quarters)
            for i, count in enumerate(parts):
                tie = "-" if i < len(parts) - 1 or b < onset + duration else ""
                pieces.append(spelling(pitch, bar["key"], active) + (str(count) if count != 1 else "") + tie)
            cursor = b
        if cursor < end:
            pieces.extend("z" + (str(n) if n != 1 else "") for n in lengths((end - cursor) / unit_quarters))
        ins.append("".join(pieces) if events else "Z")
        current = next((symbol for when, symbol in reversed(chords) if when <= start), None)
        changes = [(start, current)] + [(when, symbol) for when, symbol in chords if start < when < end]
        chunks = []
        for i, (when, symbol) in enumerate(changes):
            stop = changes[i + 1][0] if i + 1 < len(changes) else end
            chunks.append(('"' + symbol + '"') if symbol else "")
            chunks.extend("z" + (str(n) if n != 1 else "") for n in lengths((stop - when) / unit_quarters))
        vocal.append("".join(chunks) if any(symbol for _, symbol in changes) else "Z")
    header = ["X:1", "T:", "M:" + bars[0]["meter"], f"L:1/{unit_denominator}", f"Q:1/4={bpm}",
              'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
              'V: Ins clef=treble name="Ins Melody" snm="Inst."', "K:" + bars[0]["key"]]
    lines, index = header, 0
    while index < len(bars):
        bar = bars[index]
        previous = bars[index - 1] if index else bar
        end = index + 1
        while end < len(bars) and end - index < 4 and all(bars[end][k] == bar[k] for k in ("meter", "key", "section")):
            end += 1
        if bar["section"] is not None and (index == 0 or bar["section"] != previous["section"]):
            lines.append("% " + bar["section"])
        for voice, rendered in (("Vocal", vocal), ("Ins", ins)):
            lines.append("V: " + voice)
            if bar["meter"] != previous["meter"]:
                lines.append("M:" + bar["meter"])
            if bar["key"] != previous["key"]:
                lines.append("K:" + bar["key"])
            lines.append(compress(rendered[index:end]))
        index = end
    text = "\n".join(lines) + "\n"
    parsed = parse_abc(text)
    if [tuple(x) for x in parsed.voices["Ins"].notes] != notes or parsed.voices["Vocal"].notes:
        raise ValueError("Internal note roundtrip failed")

    def dedup(events):
        result = []
        for item in events:
            if not result or result[-1][1] != item[1]:
                result.append(tuple(item))
        return result

    if dedup(parsed.voices["Vocal"].chords) != dedup(chords):
        raise ValueError("Internal harmony roundtrip failed")
    check = report(parsed)
    check["event_roundtrip"] = True
    check["scope"] = "Portable compiler and independent ABC event parser; not the original training exporter"
    return text, check


# ═══════════════════════════════════════════════════════════════════════
#  人声转器乐（Vocal 音符移入 Ins，Vocal 只留和弦与休止）
# ═══════════════════════════════════════════════════════════════════════

def section_starts(text: str, score: Score) -> dict:
    """把原生段落注释映射到绝对小节起点时间。"""
    cursor, pending = 0, None
    result = {}
    for index, line in enumerate(text.splitlines()):
        if line.startswith("% "):
            pending = line[2:]
            if pending not in SECTIONS:
                raise ValueError(f"Unknown section label: {pending}")
        if score.music_lines.get(index) != "Vocal":
            continue
        if pending is not None:
            result[score.voices["Vocal"].bars[cursor][0]] = pending
            pending = None
        for bar in line[:-1].split("|"):
            rest = re.fullmatch(r"Z([2-4])?", bar.strip())
            cursor += int(rest.group(1) or 1) if rest else 1
    return result


def subtract_intervals(start, duration, occupied):
    pieces = [(start, start + duration)]
    for left, right in occupied:
        remaining = []
        for a, b in pieces:
            if right <= a or left >= b:
                remaining.append((a, b))
            else:
                if a < left:
                    remaining.append((a, left))
                if right < b:
                    remaining.append((right, b))
        pieces = remaining
    return pieces


def convert_score(text: str, overlap: str = "vocal", keep_chords: bool = True) -> tuple:
    """把 YuE2/SheetSage2 的原生唱旋律移到器乐声部，返回 (新 ABC, 校验记录)。"""
    if overlap not in ("vocal", "error"):
        raise ValueError("overlap must be vocal or error")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Need a nonempty native score")
    source = parse_abc(text)
    vocal, ins = source.voices["Vocal"], source.voices["Ins"]
    if not vocal.notes and not ins.notes:
        raise ValueError("The score contains no sounding notes")
    occupied = [(t, t + d) for t, _, d in vocal.notes]
    merged = [list(n) for n in vocal.notes]
    affected = []
    unchanged = 0
    for index, (start, pitch, duration) in enumerate(ins.notes):
        pieces = subtract_intervals(start, duration, occupied)
        if pieces == [(start, start + duration)]:
            unchanged += 1
        else:
            if overlap == "error":
                raise ValueError("Vocal and Ins overlap; choose vocal priority or edit the arrangement explicitly")
            affected.append(dict(ins_note=index, onset=str(start), pitch=pitch, duration=str(duration),
                                 retained_segments=[[str(a), str(b - a)] for a, b in pieces]))
        merged.extend([a, pitch, b - a] for a, b in pieces)
    merged.sort()
    sections = section_starts(text, source)
    starts = {start for start, _, _ in vocal.bars}
    if any(when not in starts for when, _ in vocal.keys):
        raise ValueError("An inline key change occurs inside a bar; normalize its spelling without changing pitches first")
    bars = []
    for start, _, (n, d) in vocal.bars:
        key = next(key for t, key in reversed(vocal.keys) if t <= start)
        bar = dict(meter=f"{n}/{d}", key=key)
        if start in sections:
            bar["section"] = sections[start]
        bars.append(bar)
    chords = []
    if keep_chords:
        for when, symbol in vocal.chords:
            if chords and chords[-1][0] == str(when):
                if chords[-1][1] != symbol:
                    raise ValueError("Conflicting chord labels at the same time")
                continue
            chords.append([str(when), symbol])
    events = dict(bpm=source.bpm, key=vocal.keys[0][1], bars=bars,
                  notes=[[str(t), str(d), p] for t, p, d in merged], chords=chords)
    converted, _ = compile_events(events)
    target = parse_abc(converted)
    if target.voices["Ins"].notes != merged or target.voices["Vocal"].notes:
        raise ValueError("Voice transfer changed the intended note events")
    if target.voices["Ins"].bars != ins.bars or target.bpm != source.bpm:
        raise ValueError("Voice transfer changed meter, timing or tempo")
    for note in vocal.notes:
        if note not in target.voices["Ins"].notes:
            raise ValueError("A vocal note was not preserved exactly")

    def harmony(chord_list):
        result = []
        for event in chord_list:
            if not result or result[-1][1] != event[1]:
                result.append(event)
        return result

    if keep_chords and harmony(target.voices["Vocal"].chords) != harmony(vocal.chords):
        raise ValueError("Voice transfer changed harmony")
    check = dict(vocal_notes_before=len(vocal.notes), vocal_notes_after=0,
                 original_ins_notes=len(ins.notes), unaltered_ins_notes=unchanged,
                 output_ins_notes=len(merged), vocal_pitch_onset_duration_preserved=True,
                 meter_and_tempo_preserved=True,
                 chords="preserved" if keep_chords else "removed for melody cover",
                 overlap_policy=overlap, affected_ins_notes=affected,
                 nominal_seconds=float(ins.time * 60 / source.bpm))
    return converted, check


# ═══════════════════════════════════════════════════════════════════════
#  节点专用辅助（官方器乐链路的请求级校验 + 人类可读报告）
# ═══════════════════════════════════════════════════════════════════════

def validate_instrumental(text: str) -> Score:
    """官方 instrumental 工作流的谱面规则：Vocal 必须全为休止、Ins 必须有音、网格够细。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("ABC must be nonempty text; let the model write or repair the score first")
    score = parse_abc(text)
    if score.voices["Vocal"].notes:
        raise ValueError("Vocal contains sounding notes; move the intended lead to Ins and replace Vocal notes with rests")
    if not score.voices["Ins"].notes:
        raise ValueError("Ins has no sounding notes")
    for _, _, (_, d) in score.voices["Ins"].bars:
        if score.unit.denominator % (4 * d):
            raise ValueError("L is too coarse for the four-subbeat grid; scale ALL durations with a finer L")
    previous = None
    for line in text.splitlines():
        if line.startswith("% "):
            label = line[2:]
            if label not in SECTIONS or label == previous:
                raise ValueError("Use native section labels, without consecutive duplicate section comments")
            previous = label
    for index in score.music_lines:
        line = text.splitlines()[index]
        if re.search(r"Z[234]?\|Z[234]?(?:\||$)", line):
            raise ValueError("Compress adjacent full-bar rests to Z2/Z3/Z4 inside each group")
        for bar in line[:-1].split("|"):
            if re.fullmatch(r"(?:z\d*)+", bar):
                raise ValueError("Use Z for an unannotated full-bar rest")
            for match in TOKEN.finditer(bar):
                if match.group("duration") == "1":
                    raise ValueError("Omit explicit duration 1 in the native notation")
    return score


def section_labels(text: str) -> list:
    """按出现顺序取出所有 `% section` 注释标签（去重保留顺序）。"""
    labels = []
    for line in text.splitlines():
        if line.startswith("% "):
            label = line[2:]
            if not labels or labels[-1] != label:
                labels.append(label)
    return labels


def lyric_tags(text: str) -> str:
    """把谱面的 `% verse` 注释转成歌词用的段落标签骨架 `[Verse]`。"""
    labels = section_labels(text)
    if not labels:
        return ""
    return "\n\n".join("[" + name.title() + "]" for name in labels) + "\n"


def mode_suggestion(text: str) -> tuple:
    """按官方规则推断 cot。

    官方两条路径的强度不同：
      · 通用路径（run_yue2 / score_check）：melody 模式**不接受**和弦记号（硬错误）；
        full 模式配无和弦谱面是允许的（等于让模型补配和声）。
      · 器乐路径（instrumental.validate_request）：硬性要求「有和弦→full、无和弦→melody」。
    所以含和弦时是「必须 full」，无和弦时是「建议 melody」。
    """
    score = parse_abc(text)
    if score.voices["Vocal"].chords:
        return "full", "谱面含和弦记号：melody 模式不接受和弦记号，必须用 mode=full"
    return "melody", "谱面无和弦记号：建议 mode=melody（伴奏自由发挥）；若要模型补配和声也可用 full"


def diff_lines(before: str, after: str, names=VOICES, allow_tempo_change: bool = False) -> list:
    """人工编辑后的差异清单（官方要求「显式审阅差异」，而不是看 ✅/❌ 结论）。"""
    result = compare(parse_abc(before), parse_abc(after), names, allow_tempo_change)
    return result["differences"] or ["（事件完全一致：音高 / 起音 / 时长 / 拍号 / 速度均未变）"]


def format_fraction(value) -> str:
    if isinstance(value, Fraction):
        return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    return str(value)


def _chord_line(score: Score, limit: int = 40) -> str:
    chords = score.voices["Vocal"].chords
    if not chords:
        return "（无和弦记号）"
    parts = [f'{symbol}@{format_fraction(when)}' for when, symbol in chords]
    text = "  ".join(parts[:limit])
    if len(parts) > limit:
        text += f" …（共 {len(parts)} 个）"
    return text


def summary_text(text: str) -> str:
    """把结构报告渲染成中文可读文本（不含模式建议与免责声明，由节点负责编排）。"""
    score = parse_abc(text)
    lines = [
        "✅ 结构校验通过（原生有界方言）",
        f"BPM: {score.bpm}    网格 L: 1/{score.unit.denominator}    "
        f"总时值: {format_fraction(score.voices['Vocal'].time)} 个四分音符 ≈ "
        f"{float(score.voices['Vocal'].time * 60 / score.bpm):.1f} 秒",
    ]
    for name in VOICES:
        voice = score.voices[name]
        lines.append(f"声部 {name}: 发声音符 {len(voice.notes)}    小节 {len(voice.bars)}")
    pitches = [p for voice in VOICES for _, p, _ in score.voices[voice].notes]
    if pitches:
        lines.append(f"音域: MIDI {min(pitches)}–{max(pitches)}")
    lines.append("和弦: " + _chord_line(score))
    labels = section_labels(text)
    if labels:
        lines.append("段落: " + " → ".join(labels)
                     + f"    （对应歌词标签 {' '.join('[' + n.title() + ']' for n in labels)}）")
    else:
        lines.append("段落: 无（谱面没有 % section 标记）")
    if score.voices["Vocal"].notes:
        lines.append(f"⚠️ Vocal 有 {len(score.voices['Vocal'].notes)} 个发声音符："
                     f"直接渲染会被人声唱/哼出来。做纯音乐请用「人声移到器乐轨」"
                     f"（Vocal 必须无发声音符，这是官方纯音乐链路的强制验收项）")
    if score.voices["Vocal"].notes and score.voices["Ins"].notes:
        lines.append("（Vocal 与 Ins 同时有音符：原生谱面允许；「人声移到器乐轨」时人声优先）")
    return "\n".join(lines)


def sha_line(text: str) -> str:
    return f"SHA256: {hashlib.sha256(text.encode()).hexdigest()[:16]}"


# ═══════════════════════════════════════════════════════════════════════
#  机械规范化（严格限定在官方 abc-repair.md「常见修复」里可判定的项）
#    去 BOM / Markdown 围栏 / 弯引号 / 行尾空白与首尾空行；
#    M:C → M:4/4；Q:81 → Q:1/4=81（非四分音符速度先换算）；
#    K:B minor → K:Bm、K:B major → K:B。
#  语义性修复（展开反复、量化三连音、补休止…）一律不猜，交给人工。
# ═══════════════════════════════════════════════════════════════════════

FENCE_LINE = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*$")
SMART_CHARS = (("\ufeff", ""), ("\u2018", "'"), ("\u2019", "'"),
               ("\u201c", '"'), ("\u201d", '"'), ("\u00a0", " "),
               ("\u3000", " "), ("\u2013", "-"), ("\u2014", "-"))
TEMPO_PLAIN = re.compile(r"^([1-9][0-9]*)$")
TEMPO_FRACTION = re.compile(r"^([1-9][0-9]*)/([1-9][0-9]*)=([1-9][0-9]*)$")
KEY_WORD = re.compile(r"^([A-G](?:bb|##|b|#)?)\s+(minor|min|major|maj)$", re.IGNORECASE)


def _normalize_tempo(value: str) -> str:
    """Q:81 → Q:1/4=81；Q:3/8=60 这类先换算成四分音符速度，换算不整则原样保留。"""
    plain = TEMPO_PLAIN.fullmatch(value)
    if plain:
        return f"1/4={plain.group(1)}"
    if value.startswith("1/4="):
        return value
    match = TEMPO_FRACTION.fullmatch(value)
    if match:
        numerator, denominator, count = (int(x) for x in match.groups())
        quarters = count * 4 * numerator / denominator
        if quarters == int(quarters) and quarters > 0:
            return f"1/4={int(quarters)}"
    return value


def _normalize_key(value: str) -> str:
    """K:B minor → K:Bm；K:B major/maj → K:B。"""
    match = KEY_WORD.fullmatch(value.strip())
    if not match:
        return value.strip()
    root, mode = match.group(1), match.group(2).lower()
    return root + ("m" if mode in ("minor", "min") else "")


def normalize_abc_text(text: str) -> tuple:
    """返回 (规范化后的文本, 改动说明列表)。不做语义性修复。"""
    changes = []
    working = text

    for src, dst in SMART_CHARS:
        if src in working:
            working = working.replace(src, dst)
            label = {"\ufeff": "去 BOM", "\u2018": "弯引号→直引号", "\u2019": "弯引号→直引号",
                     "\u201c": "弯引号→直引号", "\u201d": "弯引号→直引号",
                     "\u00a0": "不间断空格→空格", "\u3000": "全角空格→空格",
                     "\u2013": "en-dash→连字符", "\u2014": "em-dash→连字符"}[src]
            if label not in changes:
                changes.append(label)

    lines = working.splitlines()
    if lines and FENCE_LINE.match(lines[0]):
        lines = lines[1:]
        changes.append("去 Markdown 代码围栏")
    if lines and FENCE_LINE.match(lines[-1]):
        lines = lines[:-1]

    stripped = [line.rstrip() for line in lines]
    while stripped and not stripped[0].strip():
        stripped.pop(0)
    while stripped and not stripped[-1].strip():
        stripped.pop()
    if stripped != lines and "清理行尾空白与首尾空行" not in changes:
        changes.append("清理行尾空白与首尾空行")

    for index, line in enumerate(stripped[:12]):
        if line.strip() in ("M:C", "M:c", "M:C|"):
            stripped[index] = "M:4/4"
            changes.append(f"{line.strip()} → M:4/4")
        elif line.startswith("Q:"):
            new = _normalize_tempo(line[2:].strip())
            if new != line[2:].strip():
                stripped[index] = "Q:" + new
                changes.append(f"Q:{line[2:].strip()} → Q:{new}")
        elif line.startswith("K:"):
            new = _normalize_key(line[2:])
            if new != line[2:]:
                stripped[index] = "K:" + new
                changes.append(f"K:{line[2:]} → K:{new}")

    return "\n".join(stripped) + "\n", changes


def compare_text(before: str, after: str, names=VOICES, allow_tempo_change: bool = False) -> str:
    """把 compare() 结果渲染成中文可读文本。"""
    result = compare(parse_abc(before), parse_abc(after), names, allow_tempo_change)
    head = "✅ 事件一致（符号层音高/起音/时长/拍号未变）" if result["match"] else "❌ 事件已改变"
    lines = [head, f"比对声部: {', '.join(result['compared_voices'])}",
             f"允许变速: {'是' if result['tempo_change_allowed'] else '否'}"]
    lines += [f"· {item}" for item in result["differences"]]
    lines.append("说明: 只证明符号层事件关系，不代表音频一致，也不代表和声未被改动")
    return "\n".join(lines)
