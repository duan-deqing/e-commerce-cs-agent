from __future__ import annotations

import re

PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
IDCARD_RE = re.compile(r"(?<!\d)(\d{3})\d{11}(\d{3}[0-9Xx])(?!\d)")
BANK_RE = re.compile(r"(?<!\d)(\d{4})\d{8,12}(\d{4})(?!\d)")
EMAIL_RE = re.compile(r"([\w.+-])([\w.+-]*)(@[\w.-]+\.[A-Za-z]{2,})")
# 详细门牌：路/街/号 后的数字与室
ADDR_RE = re.compile(r"([一-龥]{2,}(?:路|街|道|巷))\d+\s*号(?:\d+\s*栋)?(?:\d+\s*单元)?(?:\d+\s*室)?")


def mask_phone(text: str) -> str:
    return PHONE_RE.sub(lambda m: f"{m.group(1)}****{m.group(3)}", text)


def mask_idcard(text: str) -> str:
    return IDCARD_RE.sub(lambda m: f"{m.group(1)}***********{m.group(2)}", text)


def mask_bank(text: str) -> str:
    return BANK_RE.sub(lambda m: f"**** **** **** {m.group(2)}", text)


def mask_email(text: str) -> str:
    def _rep(m: re.Match) -> str:
        local = m.group(1) + "***"
        return f"{local}{m.group(3)}"

    return EMAIL_RE.sub(_rep, text)


def mask_address(text: str) -> str:
    return ADDR_RE.sub(lambda m: f"{m.group(1)}（详细地址已脱敏）", text)


def mask_sensitive(text: str) -> str:
    if not text:
        return text
    out = text
    out = mask_phone(out)
    out = mask_idcard(out)
    out = mask_bank(out)
    out = mask_email(out)
    out = mask_address(out)
    return out


def contains_sensitive(text: str) -> bool:
    if not text:
        return False
    return bool(
        PHONE_RE.search(text)
        or IDCARD_RE.search(text)
        or BANK_RE.search(text)
        or EMAIL_RE.search(text)
    )
