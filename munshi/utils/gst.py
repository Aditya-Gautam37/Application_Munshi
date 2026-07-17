"""GST reference data and pure GST math — relocated verbatim from app.py.

`compute_gst_split` sits here (not in a services/ module) for now because
nothing outside app.py consumes it yet in Phase 0 — it's a pure function with
zero DB/Flask dependency, same as the rest of this module. It's a natural
candidate to grow into services/gst_service.py once billing_service.py is
introduced (Phase 8, Bills domain); moving it there is a relocation, not a
behavior change, so it isn't done preemptively here.
"""
import re


GST_STATE_NAMES = {
    '01': 'JAMMU & KASHMIR', '02': 'HIMACHAL PRADESH', '03': 'PUNJAB',
    '04': 'CHANDIGARH', '05': 'UTTARAKHAND', '06': 'HARYANA',
    '07': 'DELHI', '08': 'RAJASTHAN', '09': 'UTTAR PRADESH',
    '10': 'BIHAR', '11': 'SIKKIM', '12': 'ARUNACHAL PRADESH',
    '13': 'NAGALAND', '14': 'MANIPUR', '15': 'MIZORAM',
    '16': 'TRIPURA', '17': 'MEGHALAYA', '18': 'ASSAM',
    '19': 'WEST BENGAL', '20': 'JHARKHAND', '21': 'ODISHA',
    '22': 'CHHATTISGARH', '23': 'MADHYA PRADESH', '24': 'GUJARAT',
    '25': 'DAMAN & DIU', '26': 'DADRA & NAGAR HAVELI', '27': 'MAHARASHTRA',
    '28': 'ANDHRA PRADESH (OLD)', '29': 'KARNATAKA', '30': 'GOA',
    '31': 'LAKSHADWEEP', '32': 'KERALA', '33': 'TAMIL NADU',
    '34': 'PUDUCHERRY', '35': 'ANDAMAN & NICOBAR', '36': 'TELANGANA',
    '37': 'ANDHRA PRADESH', '38': 'LADAKH', '97': 'OTHER TERRITORY',
}


def validate_gstin(gstin):
    """Returns (is_valid, normalized_or_none, error_msg).
       GSTIN format: 15 chars = 2 (state) + 10 (PAN) + 1 (entity) + 1 ('Z') + 1 (checksum).
       We validate the structural pattern but skip the checksum digit (rarely typed wrong)."""
    if not gstin:
        return False, None, 'GSTIN is empty'
    g = gstin.strip().upper()
    if len(g) != 15:
        return False, None, f'GSTIN must be 15 characters (got {len(g)})'
    if not re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[0-9A-Z]{1}Z[0-9A-Z]{1}$', g):
        return False, None, 'GSTIN format is invalid (expected: 09AFFFS7446N1Z6 pattern)'
    return True, g, ''


def compute_gst_split(taxable_value, gst_pct, supplier_state, place_of_supply, reverse_charge):
    """Return a dict with the tax line items.
       Rule: same state → CGST + SGST (gst_pct split equally);
             different states → IGST (full gst_pct).
       Reverse-charge bills carry 0 tax (recipient pays via RCM).
       All amounts are rounded to whole rupees — freight invoices don't carry paise."""
    tv = round(float(taxable_value or 0))    # taxable value itself is rounded too
    out = {'igst_pct': 0, 'cgst_pct': 0, 'sgst_pct': 0,
           'igst_amount': 0, 'cgst_amount': 0, 'sgst_amount': 0,
           'total_tax': 0, 'grand_total': tv}
    if reverse_charge:
        return out
    pct = float(gst_pct or 0)
    if pct <= 0:
        return out
    same_state = (supplier_state or '').strip() == (place_of_supply or '').strip()
    if same_state:
        half = round(tv * pct / 200)         # CGST = SGST = half of gst_pct, rounded
        out['cgst_pct'] = pct / 2
        out['sgst_pct'] = pct / 2
        out['cgst_amount'] = half
        out['sgst_amount'] = half
        out['total_tax'] = half * 2
    else:
        amt = round(tv * pct / 100)
        out['igst_pct'] = pct
        out['igst_amount'] = amt
        out['total_tax'] = amt
    out['grand_total'] = tv + out['total_tax']
    return out
