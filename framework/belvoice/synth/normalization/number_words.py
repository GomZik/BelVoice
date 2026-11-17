"""Context-free Belarusian cardinal integers; no dates, units or inflection."""

import re

_UNITS = ('нуль', 'адзін', 'два', 'тры', 'чатыры', 'пяць', 'шэсць', 'сем', 'восем', 'дзевяць')
_TEENS = ('дзесяць', 'адзінаццаць', 'дванаццаць', 'трынаццаць', 'чатырнаццаць',
          'пятнаццаць', 'шаснаццаць', 'сямнаццаць', 'васямнаццаць', 'дзевятнаццаць')
_TENS = ('', '', 'дваццаць', 'трыццаць', 'сорак', 'пяцьдзясят', 'шэсцьдзясят',
         'семдзесят', 'восемдзесят', 'дзевяноста')
_HUNDREDS = ('', 'сто', 'дзвесце', 'трыста', 'чатырыста', 'пяцьсот', 'шэсцьсот',
             'семсот', 'восемсот', 'дзевяцьсот')
_SCALES = (
    (), ('тысяча', 'тысячы', 'тысяч'), ('мільён', 'мільёны', 'мільёнаў'),
    ('мільярд', 'мільярды', 'мільярдаў'), ('трыльён', 'трыльёны', 'трыльёнаў'),
    ('квадрыльён', 'квадрыльёны', 'квадрыльёнаў'),
)
# Only correctly grouped triples join into one number. Never cross newlines,
# swallow a partial digit run, or treat a comma/period as a grouping separator.
_NUMBER = re.compile(r'[-−]?(?:[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3}(?![0-9]))+|[0-9]+)')
_GROUP_SPACE = re.compile(r'[ \u00a0\u202f]')


def integer_words(digits: str) -> str:
    """ASCII digits only. Leading zeros and >18 digits stay digit-by-digit."""
    if not digits or re.fullmatch(r'[0-9]+', digits) is None:
        raise ValueError('Expected ASCII digits')
    if len(digits) > 18 or (len(digits) > 1 and digits[0] == '0'):
        return ' '.join(_UNITS[int(char)] for char in digits)
    if digits == '0':
        return _UNITS[0]
    chunks = []
    while digits:
        chunks.append(int(digits[-3:]))
        digits = digits[:-3]
    words = []
    for scale in range(len(chunks) - 1, -1, -1):
        value = chunks[scale]
        if value == 0:
            continue
        if value >= 100:
            words.append(_HUNDREDS[value // 100])
        remainder = value % 100
        if 10 <= remainder < 20:
            words.append(_TEENS[remainder - 10])
        else:
            if remainder >= 20:
                words.append(_TENS[remainder // 10])
            unit = remainder % 10
            if unit:
                words.append(('адна' if unit == 1 else 'дзве') if scale == 1 and unit <= 2 else _UNITS[unit])
        if scale:
            ending = 2 if 11 <= remainder <= 14 else 0 if value % 10 == 1 else 1 if 2 <= value % 10 <= 4 else 2
            words.append(_SCALES[scale][ending])
    return ' '.join(words)


def normalize_numbers(text: str) -> str:
    def replace(match):
        token = match.group()
        sign = token[0] if token[0] in '-−' else ''
        digits = _GROUP_SPACE.sub('', token[len(sign):])
        previous = text[match.start() - 1] if match.start() else ''
        # A hyphen inside a word/range is not guessed to be a unary minus.
        attached = bool(previous and (previous.isalnum() or previous == '_'))
        prefix = sign if sign and attached else ' мінус ' if sign else ''
        return prefix + ' ' + integer_words(digits) + ' '

    return _NUMBER.sub(replace, text)
