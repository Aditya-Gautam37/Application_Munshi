"""Flask Blueprints — one per domain, registered onto the existing `app`
object in app.py (`app.register_blueprint(...)`), not built via an app
factory. See app.py's comment at the registration call for why: constructing
Flask itself inside this package would change the app's import_name, which
Flask uses to resolve the default templates/ and static/ folders — that's a
risk not worth taking for what the API layer actually needs (route grouping),
so Flask app construction stays exactly where it already works, in app.py.
"""
