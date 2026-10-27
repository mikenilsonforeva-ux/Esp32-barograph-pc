"""Единицы давления. В базе всегда хранятся мм рт. ст."""

_MMHG_PER_HPA = 0.750061683

# unit -> (множитель из мм рт. ст., знаков после запятой, подпись)
PRESSURE_UNITS = {
    "mmHg": (1.0, 2, "мм рт. ст."),
    "hPa": (1.0 / _MMHG_PER_HPA, 2, "гПа"),
    "kPa": (0.1 / _MMHG_PER_HPA, 3, "кПа"),
}


def _spec(unit):
    return PRESSURE_UNITS.get(unit, PRESSURE_UNITS["mmHg"])


def convert_pressure(mmhg, unit="mmHg"):
    if mmhg is None:
        return None
    factor, digits, _ = _spec(unit)
    return round(mmhg * factor, digits)


def pressure_label(unit="mmHg") -> str:
    return _spec(unit)[2]


def pressure_digits(unit="mmHg") -> int:
    return _spec(unit)[1]
