"""Pure, dependency-light helpers: display formatting, GST reference data/math,
and i18n. No Flask app or DB dependency except utils.i18n.t(), which is
inherently request-scoped (reads the session language).
"""
