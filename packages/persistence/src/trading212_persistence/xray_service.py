"""PostgreSQL Portfolio X-ray service over authorized immutable source inputs."""

from .xray_exposure_reads import XrayExposureReads
from .xray_overlap_reads import XrayOverlapReads
from .xray_source_reads import XraySourceReads


class PostgresXrayService(XrayExposureReads, XrayOverlapReads, XraySourceReads):
    """Expose the four bounded read operations and internal typed enrichment ingestion."""
