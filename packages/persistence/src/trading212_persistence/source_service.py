"""Canonical owner-authorized market source persistence and benchmark commands."""

from .source_benchmarks import SourceBenchmarks
from .source_ingestion import SourceIngestion
from .source_reads import SourceReads


class PostgresSourceService(SourceIngestion, SourceReads, SourceBenchmarks):
    """Compose fixed typed operations over a single transactional PostgreSQL store."""
