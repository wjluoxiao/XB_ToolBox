"""文件名前缀里的动态标记展开
=============================

ComfyUI 核心的保存节点（SaveImage / SaveVideo / SaveAudio ...）本身**不做**标记替换：
真正干活的是前端扩展 ``Comfy.SaveImageExtraOutput``——它给白名单里的节点挂上
``filename_prefix`` 的 ``serializeValue``，排队前把
  · ``%date:yyyy-MM-dd%``  → 执行时刻的日期
  · ``%节点名.控件名%``     → 该控件当前的値
展开成普通字符串。

自定义保存节点不在那个白名单里，前缀会原样送到服务端，于是
``output/视频/xxx/%date:yyyy-MM-dd%/`` 这种目录名在 Windows 上直接
``NotADirectoryError``（目录名无效）。

前端（js/xb_save_video.js）已经补上了同样的展开逻辑；这里再在服务端补一遍，
保证「用 API 直接提交」「前端版本较老」等情况下也不会生成非法目录名，
并且对已经被前端展开过的字符串是幂等的（没有 % 就原样返回）。
"""

from __future__ import annotations

import datetime as _dt
import re

# 与前端 formatDate 一致的标记集合：dd? MM? hh? mm? ss? yyy?y?
# 额外支持 H / HH（24 小时制），用户写 yyyy-MM-dd_HH-mm-ss 也能得到预期结果
_DATE_TOKEN_RE = re.compile(r"dd?|MM?|HH?|hh?|mm?|ss?|yyy?y?")
# 前缀里的任意 %...% 标记
_ANY_TOKEN_RE = re.compile(r"%([^%]+)%")
# Windows 单个路径段里不允许出现的字符（'/' 是分隔符，单独处理）
_INVALID_SEGMENT_CHARS = re.compile(r'[<>:"\\|?*\x00-\x1f\x7f]')


def format_date(fmt: str, when: _dt.datetime | None = None) -> str:
    """按前端 ``formatDate`` 的规则格式化日期（d / dd / M / MM / h / hh / m / mm / s / ss / yy / yyyy）。"""
    now = when or _dt.datetime.now()

    def repl(match: re.Match) -> str:
        token = match.group(0)
        if token == "yy":
            return str(now.year)[-2:]
        if token == "yyyy":
            return str(now.year)
        value = {
            "d": now.day,
            "M": now.month,
            "H": now.hour,
            "h": now.hour,
            "m": now.minute,
            "s": now.second,
        }.get(token[0])
        if value is None:
            return token
        return str(value).zfill(len(token))

    return _DATE_TOKEN_RE.sub(repl, fmt)


def _sanitize_segment(segment: str) -> str:
    segment = _INVALID_SEGMENT_CHARS.sub("_", segment)
    return segment.strip().rstrip(".")


def expand_tokens(prefix: str, when: _dt.datetime | None = None) -> str:
    """展开 ``%date:...%``，并把无法解析的标记去掉（避免变成非法目录名）。"""
    if not isinstance(prefix, str) or "%" not in prefix:
        return prefix

    def repl(match: re.Match) -> str:
        token = match.group(1)
        # 只有 date: 能在服务端解析；%节点名.控件名% 交给前端，
        # 残留到这里的（前端没展开 / 用 API 提交）直接丢掉，别当文件名用
        if not token.startswith("date:"):
            return ""
        return format_date(token[5:], when)

    return _ANY_TOKEN_RE.sub(repl, prefix)


def resolve_filename_prefix(prefix: str, when: _dt.datetime | None = None) -> str:
    """保存节点用：展开标记 + 清理 Windows 非法字符，返回可直接交给 get_save_image_path 的前缀。"""
    if not isinstance(prefix, str):
        return prefix
    expanded = expand_tokens(prefix, when)
    # 分段清理：'/' 是子目录分隔符，不能换成 '_'；被丢掉的标记留下的空段一并去掉
    segments = [_sanitize_segment(seg) for seg in expanded.split("/")]
    cleaned = "/".join(seg for seg in segments if seg)
    return cleaned or "ComfyUI"
