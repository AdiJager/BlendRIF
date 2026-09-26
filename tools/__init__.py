"""Diagnostic tools - not imported by the addon at runtime.

Anything in this package is opt-in: `avp_rif_importer/__init__.py` never
imports from here, so adding or changing modules in tools/ has no effect
on the installed addon's startup cost or behaviour.
"""