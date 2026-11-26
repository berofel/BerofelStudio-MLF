"""Conservative PT-BR normalization for speech synthesis.

Only the text sent to the TTS backend is expanded. The caller's source text,
caption text and reference transcript remain unchanged. Every replacement
records its half-open source span so downstream tools can retain provenance.

This is a deterministic text front-end, not a phonemizer or a claim that the
Qwen tokenizer accepts IPA. Ambiguous numbers, URLs, phone numbers and codes
are intentionally left alone.
"""
from __future__ import annotations

from dataclasses import dataclass
import calendar
import re

NORMALIZER_VERSION = 3


@dataclass(frozen=True)
class TextReplacement:
    source_start: int
    source_end: int
    original: str
    spoken: str
    rule: str


@dataclass(frozen=True)
class NormalizedSpeechText:
    original: str
    spoken: str
    replacements: tuple[TextReplacement, ...]
    version: int = NORMALIZER_VERSION


_ONES = ("zero", "um", "dois", "três", "quatro", "cinco", "seis",
         "sete", "oito", "nove")
_TEENS = ("dez", "onze", "doze", "treze", "quatorze", "quinze",
          "dezesseis", "dezessete", "dezoito", "dezenove")
_TENS = ("", "", "vinte", "trinta", "quarenta", "cinquenta",
         "sessenta", "setenta", "oitenta", "noventa")
_HUNDREDS = ("", "cento", "duzentos", "trezentos", "quatrocentos",
             "quinhentos", "seiscentos", "setecentos", "oitocentos",
             "novecentos")
_MONTHS = ("janeiro", "fevereiro", "março", "abril", "maio", "junho",
           "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
_ORDINALS_M = ("primeiro", "segundo", "terceiro", "quarto", "quinto",
               "sexto", "sétimo", "oitavo", "nono", "décimo")
_ORDINALS_F = ("primeira", "segunda", "terceira", "quarta", "quinta",
               "sexta", "sétima", "oitava", "nona", "décima")


def _under_thousand(value: int) -> str:
    if value < 10:
        return _ONES[value]
    if value < 20:
        return _TEENS[value - 10]
    if value < 100:
        tens, ones = divmod(value, 10)
        return _TENS[tens] + (f" e {_ONES[ones]}" if ones else "")
    if value == 100:
        return "cem"
    hundreds, rest = divmod(value, 100)
    return _HUNDREDS[hundreds] + (f" e {_under_thousand(rest)}" if rest else "")


def _integer(value: int) -> str:
    if value < 0:
        return "menos " + _integer(-value)
    if value < 1000:
        return _under_thousand(value)
    if value < 1_000_000:
        thousands, rest = divmod(value, 1000)
        prefix = "mil" if thousands == 1 else f"{_under_thousand(thousands)} mil"
        connector = " e " if rest and (rest < 100 or rest % 100 == 0) else " "
        return prefix + (connector + _under_thousand(rest) if rest else "")
    if value < 1_000_000_000:
        millions, rest = divmod(value, 1_000_000)
        prefix = "um milhão" if millions == 1 else f"{_integer(millions)} milhões"
        if not rest:
            return prefix
        connector = " e " if rest < 100 or rest % 1000 == 0 else " "
        return prefix + connector + _integer(rest)
    # Large numeric codes are likely identifiers; the caller leaves them intact.
    raise ValueError("Número fora do limite de normalização verbal.")


def _digits(value: str) -> str:
    return " ".join(_ONES[int(char)] for char in value)


def _amount(raw: str) -> str:
    value = raw.replace(".", "").replace(",", ".")
    whole, dot, fraction = value.partition(".")
    integer = int(whole)
    result = _integer(integer)
    if dot and fraction:
        # Decimal precision is spoken digit-by-digit to avoid altering scale.
        result += " vírgula " + _digits(fraction)
    return result


def _currency(match: re.Match[str]) -> str:
    raw = match.group("amount")
    normalized = raw.replace(".", "").replace(",", ".")
    whole, dot, fraction = normalized.partition(".")
    reais = int(whole)
    text = _integer(reais) + (" real" if reais == 1 else " reais")
    if dot and fraction:
        cents = int((fraction + "00")[:2])
        if cents:
            text += " e " + _integer(cents) + (" centavo" if cents == 1 else " centavos")
    return text


def _date(match: re.Match[str]) -> str:
    day, month, year = (int(match.group(key)) for key in ("day", "month", "year"))
    if not 1 <= day <= 31 or not 1 <= month <= 12:
        return match.group(0)
    # Validate against the actual month when the year has four digits. For a
    # two-digit year the century is unknown; permit Feb 29 without guessing it.
    days_in_month = (29 if month == 2 and len(match.group("year")) == 2
                     else calendar.monthrange(year, month)[1])
    if day > days_in_month:
        return match.group(0)
    # A two-digit year stays a year value; do not guess which century it means.
    day_text = "primeiro" if day == 1 else _integer(day)
    year_text = _integer(year)
    return f"{day_text} de {_MONTHS[month - 1]} de {year_text}"


def _time(match: re.Match[str]) -> str:
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or "0")
    if hour > 23 or minute > 59:
        return match.group(0)
    if hour == 0 and minute == 0:
        return "meia-noite"
    if hour == 12 and minute == 0:
        return "meio-dia"
    if hour == 0 and minute == 30:
        return "meia-noite e meia"
    if hour == 12 and minute == 30:
        return "meio-dia e meia"
    hour_text = ("meio-dia" if hour == 12 else
                 "uma" if hour == 1 else _integer(hour))
    if hour not in (0, 12) and hour % 10 == 2:
        hour_text = hour_text.removesuffix("dois") + "duas"
    hour_unit = "hora" if hour == 1 else "horas"
    minute_unit = "minuto" if minute == 1 else "minutos"
    return (f"{hour_text} {hour_unit}" if minute == 0 else
            f"{hour_text} {hour_unit} e {_integer(minute)} {minute_unit}")


_PATTERN = re.compile(
    r"(?<![\w/.])(?:"
    r"(?P<currency>R\$\s*(?P<amount>(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?))"
    r"|(?P<date>(?P<day>\d{1,2})/(?P<month>\d{1,2})/(?P<year>\d{2}(?:\d{2})?))"
    r"|(?P<time>(?P<hour>\d{1,2})h(?P<minute>\d{2})?)"
    r"|(?P<ordinal>(?P<ordinal_number>\d{1,3})(?P<ordinal_suffix>º|ª))"
    r"|(?P<unit>(?P<quantity>(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?)\s*"
    r"(?P<unit_name>km/h|GB|MB|TB|km|kg|mg|cm|mm|°C|%))"
    r"|(?P<decimal>\d{1,6},\d+)"
    r")(?![\w/])",
    re.IGNORECASE,
)

_UNIT_FORMS = {
    "gb": ("gigabyte", "gigabytes"), "mb": ("megabyte", "megabytes"),
    "tb": ("terabyte", "terabytes"), "km": ("quilômetro", "quilômetros"),
    "km/h": ("quilômetro por hora", "quilômetros por hora"),
    "kg": ("quilograma", "quilogramas"), "mg": ("miligrama", "miligramas"),
    "cm": ("centímetro", "centímetros"), "mm": ("milímetro", "milímetros"),
    "%": ("por cento", "por cento"), "°c": ("grau Celsius", "graus Celsius"),
}


def _replace(match: re.Match[str]) -> tuple[str, str] | None:
    if match.group("currency"):
        return _currency(match), "currency"
    if match.group("date"):
        result = _date(match)
        return (result, "date") if result != match.group(0) else None
    if match.group("time"):
        result = _time(match)
        return (result, "time") if result != match.group(0) else None
    if match.group("ordinal"):
        number = int(match.group("ordinal_number"))
        suffix = match.group("ordinal_suffix")
        forms = _ORDINALS_M if suffix == "º" else _ORDINALS_F
        if not 1 <= number <= len(forms):
            return None
        result = forms[number - 1]
        return result, "ordinal"
    if match.group("unit"):
        amount = _amount(match.group("quantity"))
        unit = match.group("unit_name").casefold()
        forms = _UNIT_FORMS[unit]
        normalized = match.group("quantity").replace(".", "").replace(",", ".")
        whole, _dot, fraction = normalized.partition(".")
        singular = int(whole) == 1 and not any(digit != "0" for digit in fraction)
        return f"{amount} {forms[0 if singular else 1]}", "unit"
    if match.group("decimal"):
        return _amount(match.group("decimal")), "decimal"
    return None


_ABBREVIATIONS = re.compile(r"(?<!\w)(Dr\.|Dra\.|Sr\.|Sra\.|Av\.|etc\.)", re.IGNORECASE)
_ABBREVIATION_SPOKEN = {
    "dr.": "doutor", "dra.": "doutora", "sr.": "senhor",
    "sra.": "senhora", "av.": "avenida", "etc.": "etcetera",
}
_ACRONYMS = re.compile(r"(?<!\w)(CPU|GPU|USB|SSD|IA)(?!\w)", re.IGNORECASE)
_ACRONYM_SPOKEN = {"cpu": "cê pê u", "gpu": "gê pê u", "usb": "u ésse bê",
                   "ssd": "ésse ésse dê", "ia": "i a"}


def normalize_pt_br(text: str) -> NormalizedSpeechText:
    """Expand unambiguous PT-BR numbers and common abbreviations for TTS.

    Invalid dates/times and numeric identifiers are preserved. The result is
    safe to compute repeatedly and therefore can be included in cache keys.
    """
    original = str(text or "")
    replacements: list[TextReplacement] = []
    occupied: list[tuple[int, int]] = []

    def collect(pattern: re.Pattern[str], transform, rule: str) -> None:
        for match in pattern.finditer(original):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            try:
                result = transform(match)
            except ValueError:
                # Very large values may be identifiers. Never turn an
                # unbounded token into an exception or destructive expansion.
                continue
            if result is None:
                continue
            spoken, specific_rule = result if isinstance(result, tuple) else (result, rule)
            if spoken == match.group(0):
                continue
            replacements.append(TextReplacement(match.start(), match.end(),
                match.group(0), spoken, specific_rule or rule))
            occupied.append((match.start(), match.end()))

    collect(_PATTERN, _replace, "number")
    collect(_ABBREVIATIONS,
            lambda m: (_ABBREVIATION_SPOKEN[m.group(0).casefold()], "abbreviation"),
            "abbreviation")
    collect(_ACRONYMS,
            lambda m: (_ACRONYM_SPOKEN[m.group(0).casefold()], "acronym"), "acronym")
    replacements.sort(key=lambda item: item.source_start)
    output: list[str] = []
    cursor = 0
    for item in replacements:
        output.extend((original[cursor:item.source_start], item.spoken))
        cursor = item.source_end
    output.append(original[cursor:])
    return NormalizedSpeechText(original, "".join(output), tuple(replacements))
