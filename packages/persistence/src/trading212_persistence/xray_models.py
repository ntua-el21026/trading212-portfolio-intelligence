"""Single registry for the normalized Portfolio X-ray persistence model."""

from .xray_catalog_models import XRAY_CATALOG_MODELS
from .xray_lifecycle_models import XRAY_LIFECYCLE_MODELS
from .xray_run_models import XRAY_RUN_MODELS

XRAY_MODELS = (*XRAY_CATALOG_MODELS, *XRAY_LIFECYCLE_MODELS, *XRAY_RUN_MODELS)
