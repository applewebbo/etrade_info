from django.apps import apps as django_apps

import app as _app_module  # noqa: F401 - configures Django via nanodjango

# nanodjango skips import_models(), leaving models_module=None.
# Django's migrate --run-syncdb skips apps with models_module=None,
# so the app_lot table would never be created in tests.
# Setting it here makes syncdb pick up the Lot model.
django_apps.get_app_config("app").models_module = _app_module
