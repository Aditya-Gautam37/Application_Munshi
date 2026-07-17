"""Jinja display-formatting filters — relocated verbatim from app.py. Pure
functions, no Flask/DB dependency. app.py registers these as Jinja filters
(app.jinja_env.filters[...]); that registration stays in app.py since it's
tied to the Flask app object, not the formatting logic itself.
"""
import json
from datetime import datetime


def fmt_amount(v):
    try:
        f = float(v)
        return f'{f:,.2f}' if f else ''
    except Exception:
        return str(v) if v else ''


def fmt_date(v):
    """Convert YYYY-MM-DD → DD/MM/YY (Indian print format)."""
    if not v:
        return ''
    try:
        d = datetime.strptime(str(v)[:10], '%Y-%m-%d')
        return d.strftime('%d/%m/%y')
    except Exception:
        return str(v)


def from_json_filter(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def fmt_int(v):
    """Format a number as a rounded integer with Indian thousands separators.
       Empty / non-numeric / zero values render as empty string (so blank cells
       on the printed bill stay blank rather than showing '0')."""
    if v in (None, '', 0, '0'):
        return ''
    try:
        f = float(v)
        if abs(f) < 0.5:
            return ''
        return f'{round(f):,}'
    except (TypeError, ValueError):
        return str(v)


def fmt_int0(v):
    """Same as fmt_int but renders 0 (not blank) — for totals row that must show '0' on empty bills."""
    try:
        return f'{round(float(v or 0)):,}'
    except (TypeError, ValueError):
        return '0'


def amount_in_words_inr(amount):
    """Convert a rupee amount to words in Indian numbering (Lakh / Crore).
       Returns: 'Rupees One Lakh Forty Seven Thousand Nine Hundred Ninety Seven Only'."""
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        return 'Rupees Zero Only'
    if amt < 0:
        return 'Minus ' + amount_in_words_inr(-amt)

    rupees = int(amt)
    paise = round((amt - rupees) * 100)

    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy',
            'Eighty', 'Ninety']

    def two_digit(n):
        if n < 20:
            return ones[n]
        return (tens[n // 10] + (' ' + ones[n % 10] if n % 10 else '')).strip()

    def three_digit(n):
        # Returns up to 999 in words
        parts = []
        if n >= 100:
            parts.append(ones[n // 100] + ' Hundred')
            n %= 100
        if n:
            parts.append(two_digit(n))
        return ' '.join(parts)

    # Indian numbering: ones (0-999), thousand (1K-99K), lakh (1L-99L), crore (1Cr+)
    parts = []
    crore = rupees // 10000000
    rupees %= 10000000
    lakh = rupees // 100000
    rupees %= 100000
    thousand = rupees // 1000
    rupees %= 1000
    hundreds = rupees

    if crore:
        parts.append((two_digit(crore) if crore > 0 else '') + ' Crore')
    if lakh:
        parts.append(two_digit(lakh) + ' Lakh')
    if thousand:
        parts.append(two_digit(thousand) + ' Thousand')
    if hundreds:
        parts.append(three_digit(hundreds))

    out = 'Rupees ' + (' '.join(parts).strip() or 'Zero')
    if paise:
        out += ' and ' + two_digit(paise) + ' Paise'
    out += ' Only'
    return out
