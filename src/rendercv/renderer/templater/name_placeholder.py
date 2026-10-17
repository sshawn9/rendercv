import re
from collections.abc import Callable
from typing import Any

import markdown
from markdown import inlinepatterns


class _SourceLinkProcessor(inlinepatterns.LinkInlineProcessor):
    """Read link spans without decoding or rewriting their destination/title."""

    def unescape(self, text: str) -> str:
        return text


def _clean_delimiters(
    text: str,
    processor: Any,
    wrap: Callable[[str, str], str],
) -> str:
    """Read source spans from the delimiter API absent in Markdown 3.10 types."""
    regions: list[tuple[int, int, int, int]] = []
    add_region = processor.add_region

    def record(delimiter: object, a: int, b: int, c: int, d: int, size: int) -> None:
        add_region(delimiter, a, b, c, d, size)
        regions.append((a, b, c, d))

    # This processor belongs to a fresh, local Markdown instance. Capture before
    # its normal cache management clears completed regions, then restore it.
    processor.add_region = record
    try:
        pos = 0
        while (match := processor.getCompiledRegExp().search(text, pos)) is not None:
            _, _, end = processor.handleMatch(match, text)
            pos = end if end is not None else match.end()
    finally:
        processor.add_region = add_region
        processor.reset()
    regions.sort()
    cursor = 0

    def replace(start: int, end: int) -> str:
        nonlocal cursor
        pos = start
        parts: list[str] = []
        while cursor < len(regions) and regions[cursor][0] < end:
            a, b, c, d = regions[cursor]
            cursor += 1
            parts.extend((text[pos:a], wrap(text[a:b], replace(b, c))))
            pos = d
        parts.append(text[pos:end])
        return "".join(parts)

    return replace(0, len(text))


def remove_name_placeholder(template: str) -> str:
    """Remove NAME from inline Markdown while retaining unrelated source text.

    Use the renderer's Markdown rules for nested emphasis and complete links.
    Protect parsed fragments before removing adjacent separators, so a link
    destination or literal code cannot become ordinary template text.
    """
    if "NAME" not in template:
        return template

    prefix = "\0"
    while prefix in template:
        prefix += "\0"
    missing = f"{prefix}missing{prefix}"
    name = rf"(?:(?<!\w)NAME(?!\w)|{re.escape(missing)})(?:['’]s(?!\w))?"
    fragments: dict[str, str] = {}
    parser = markdown.Markdown()
    escaped_chars = parser.ESCAPED_CHARS
    links = _SourceLinkProcessor(
        f"(?:{inlinepatterns.IMAGE_LINK_RE}|{inlinepatterns.LINK_RE})"
    )

    def protect(text: str, *, word_boundary: bool = False) -> str:
        key = f"{prefix}{len(fragments)}{prefix}"
        if word_boundary:
            key = f"x{key}x"
        fragments[key] = text
        return key

    def clean_text(text: str, *, unwrap: bool = True) -> str:
        if not re.search(name, text):
            return text
        wrapped_name = rf"\(\s*{name}\s*\)|\[\s*{name}\s*\]|\{{\s*{name}\s*\}}"
        while unwrap and (unwrapped := re.sub(wrapped_name, missing, text)) != text:
            text = unwrapped
        separator = r"[ \t]*(?:--+|[-–—|,:;/·•])[ \t]*"
        # Keep one separator in A -- NAME -- B, and never guess connector words.
        text = re.sub(name + separator, "", text)
        text = re.sub(separator + name, "", text)
        text = re.sub(name + r"[ \t]+", "", text)
        text = re.sub(r"[ \t]+" + name, "", text)
        text = re.sub(name, "", text)
        return text if text.strip() else ""

    def wrap(marker: str, content: str) -> str:
        content = clean_text(content)
        return (
            protect(marker + content + marker, word_boundary=marker.startswith("_"))
            if content
            else missing
        )

    def clean_inline(text: str, limits: tuple[int, int] = (0, 0)) -> str:
        # Follow Markdown's precedence: code, escapes, links, then emphasis.
        backticks = parser.inlinePatterns["backtick"]
        pos = 0
        while (match := backticks.getCompiledRegExp().search(text, pos)) is not None:
            node, start, end = backticks.handleMatch(match, text)
            if start is None or end is None:
                pos = match.end()
                continue
            source = text[start:end]
            if isinstance(node, str):  # Escaped backslashes before a code delimiter.
                replacement = protect(source)
            else:
                # Read source spans rather than version-specific regex groups.
                find_spans = getattr(backticks, "find_code_spans", None)
                if find_spans is not None:
                    content_start, content_end = find_spans(start, text)
                else:
                    size = len(source) - len(source.rstrip("`"))
                    content_start, content_end = start + size, end - size
                original = text[content_start:content_end]
                content = clean_text(original, unwrap=False)
                if content == original:
                    replacement = protect(source)
                elif content:
                    replacement = protect(
                        text[start:content_start] + content + text[content_end:end]
                    )
                else:
                    replacement = missing
            text = text[:start] + replacement + text[end:]
            pos = start + len(replacement)
        text = re.sub(
            inlinepatterns.ESCAPE_RE,
            lambda m: (
                protect(m[0], word_boundary=m[1] == "_")
                if m[1] in escaped_chars
                else m[0]
            ),
            text,
            flags=re.DOTALL,
        )
        pos = 0
        while (match := links.getCompiledRegExp().search(text, pos)) is not None:
            label, label_end, handled = links.getText(text, match.end())
            if handled:
                _, _, end, handled = links.getLink(text, label_end)
            if not handled:
                pos = match.end()
                continue
            is_image = match[0].startswith("!")
            original_label = label
            label = clean_text(label, unwrap=False) if is_image else clean_inline(label)
            replacement = (
                protect(match[0] + label + "]" + text[label_end:end])
                if label or not original_label or is_image
                else missing
            )
            text = text[: match.start()] + replacement + text[end:]
            pos = match.start() + len(replacement)

        emphasis = parser.inlinePatterns["em_strong"]
        if hasattr(emphasis, "add_region"):
            return clean_text(_clean_delimiters(text, emphasis, wrap))

        # Markdown 3.10 exposes ordered emphasis patterns instead of spans.
        text = re.sub(inlinepatterns.NOT_STRONG_RE, lambda m: protect(m[0]), text)
        for kind, processor in enumerate(
            (inlinepatterns.AsteriskProcessor, inlinepatterns.UnderscoreProcessor)
        ):
            pos = 0
            while pos < len(text):
                for index in range(limits[kind], len(processor.PATTERNS)):
                    item = processor.PATTERNS[index]
                    match = item.pattern.match(text, pos)
                    if match is None:
                        continue
                    next_limits = list(limits)
                    next_limits[kind] = index + 1
                    child_limits = (next_limits[0], next_limits[1])
                    first = clean_inline(match[2], child_limits)
                    if item.builder == "single":
                        replacement = wrap(match[1], first)
                    else:
                        second = clean_inline(match[3], child_limits)
                        outer_tag, inner_tag = item.tags.split(",")
                        outer = match[1] * (2 if outer_tag == "strong" else 1)
                        inner = match[1] * (2 if inner_tag == "strong" else 1)
                        content = (
                            wrap(inner, first) + second
                            if item.builder == "double"
                            else first + wrap(inner, second)
                        )
                        replacement = wrap(outer, content)
                    text = text[:pos] + replacement + text[match.end() :]
                    pos += len(replacement)
                    break
                else:
                    pos += 1
        return clean_text(text)

    # Identify whole words before Markdown can consume an internal underscore.
    # Keep formatting delimiters separate: __NAME__ still contains a removable
    # NAME, while MONTH_NAME and NAME_SUFFIX are indivisible template tokens.
    protected_template = re.sub(
        r"[^\W_]+(?:_[^\W_]+)*",
        lambda match: (
            protect(match[0], word_boundary=True)
            if "NAME" in match[0] and match[0] != "NAME"
            else match[0]
        ),
        template,
    )
    if "NAME" not in protected_template:
        return template
    result = clean_inline(protected_template)
    # Outer fragments can reference earlier inner fragments. Restore outside in.
    for key, value in reversed(fragments.items()):
        result = result.replace(key, value)
    return result
