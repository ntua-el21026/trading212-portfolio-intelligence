"""Normalized bounded research provenance and owner revision storage.

This migration has no provider registration or financial calculation entrypoint.
Capability authorization is supplied only by the private typed runtime port.
"""

from alembic import op
from sqlalchemy import text

revision = "20260915_0024"
down_revision = "20260915_0023"
branch_labels = None
depends_on = None

_DDL = (
    r"""CREATE TABLE research_owner_capacity (
    owner_id UUID NOT NULL,
    retained_bytes BIGINT NOT NULL,
    source_revisions INTEGER NOT NULL,
    event_revisions INTEGER NOT NULL,
    item_headers INTEGER NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_research_owner_capacity PRIMARY KEY (owner_id),
    CONSTRAINT fk_research_owner_capacity_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT ck_research_owner_capacity_bytes_bound CHECK (retained_bytes BETWEEN 0 AND 268435456),
    CONSTRAINT ck_research_owner_capacity_revisions_bound CHECK (source_revisions>=0 AND event_revisions>=0 AND source_revisions+event_revisions<=10000),
    CONSTRAINT ck_research_owner_capacity_items_bound CHECK (item_headers BETWEEN 0 AND 10000)
)""",
    r"""CREATE TABLE research_account_states (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    revision BIGINT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_research_account_states PRIMARY KEY (id),
    CONSTRAINT fk_research_account_states_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_account_states_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_account_states_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_account_states_1 UNIQUE (owner_id, account_id),
    CONSTRAINT ck_research_account_states_revision_bound CHECK (revision BETWEEN 1 AND 9223372036854775807)
)""",
    r"""CREATE TABLE research_source_origins (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    entity_id UUID NOT NULL,
    capability VARCHAR(30) NOT NULL,
    facts_digest VARCHAR(64) NOT NULL,
    original_retained_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_research_source_origins PRIMARY KEY (id),
    CONSTRAINT fk_research_source_origins_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_source_origins_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_source_origins_0 UNIQUE (owner_id, id),
    CONSTRAINT uq_research_source_origins_1 UNIQUE (owner_id, entity_id, capability, facts_digest),
    CONSTRAINT ck_research_source_origins_capability_allowed CHECK (capability IN ('news','company_overview')),
    CONSTRAINT ck_research_source_origins_expiry_order CHECK (expires_at>original_retained_at AND expires_at<=original_retained_at+interval '30 days'),
    CONSTRAINT ck_research_source_origins_facts_digest_format CHECK (facts_digest ~ '^[0-9a-f]{64}$')
)""",
    r"""CREATE TABLE research_sources (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    entity_id UUID NOT NULL,
    capability VARCHAR(30) NOT NULL,
    provider VARCHAR(30) NOT NULL,
    CONSTRAINT pk_research_sources PRIMARY KEY (id),
    CONSTRAINT fk_research_sources_provider_id FOREIGN KEY (owner_id, provider_id) REFERENCES market_data_providers (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_sources_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_sources_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_sources_0 UNIQUE (owner_id, id),
    CONSTRAINT ck_research_sources_provider_allowed CHECK (provider='alpha_vantage'),
    CONSTRAINT ck_research_sources_capability_allowed CHECK (capability IN ('news','company_overview'))
)""",
    r"""CREATE TABLE research_source_versions (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    source_id UUID NOT NULL,
    origin_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    entity_id UUID NOT NULL,
    license_version_id UUID NOT NULL,
    capability VARCHAR(30) NOT NULL,
    adapter_version VARCHAR(128) NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    facts_digest VARCHAR(64) NOT NULL,
    content_digest VARCHAR(64) NOT NULL,
    capability_grant_id UUID NOT NULL,
    capability_grant_digest VARCHAR(64) NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    first_known_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_cutoff_at TIMESTAMP WITH TIME ZONE NOT NULL,
    retained_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    effective_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    synthetic BOOLEAN NOT NULL,
    sealed BOOLEAN NOT NULL,
    CONSTRAINT pk_research_source_versions PRIMARY KEY (id),
    CONSTRAINT fk_research_source_versions_source_id FOREIGN KEY (owner_id, source_id) REFERENCES research_sources (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_source_versions_origin_id FOREIGN KEY (owner_id, origin_id) REFERENCES research_source_origins (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_source_versions_provider_id FOREIGN KEY (owner_id, provider_id) REFERENCES market_data_providers (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_source_versions_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_source_versions_license_version_id FOREIGN KEY (owner_id, license_version_id) REFERENCES provider_license_versions (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_source_versions_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_source_versions_0 UNIQUE (owner_id, id),
    CONSTRAINT ck_research_source_versions_capability_allowed CHECK (capability IN ('news','company_overview')),
    CONSTRAINT ck_research_source_versions_effective_expiry CHECK (retained_at<effective_expires_at AND effective_expires_at<=expires_at),
    CONSTRAINT ck_research_source_versions_time_order CHECK (observed_at<=first_known_at AND first_known_at<=source_cutoff_at AND source_cutoff_at<=retained_at AND retained_at<expires_at AND expires_at<=retained_at+interval '30 days'),
    CONSTRAINT ck_research_source_versions_request_digest_format CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_source_versions_facts_digest_format CHECK (facts_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_source_versions_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_source_versions_capability_grant_digest_format CHECK (capability_grant_digest ~ '^[0-9a-f]{64}$')
)""",
    "CREATE INDEX ix_research_source_versions_0 ON research_source_versions (owner_id, origin_id, id)",
    "CREATE INDEX ix_research_source_versions_1 ON research_source_versions (owner_id, effective_expires_at, id)",
    r"""CREATE TABLE research_source_payloads (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    version_id UUID NOT NULL,
    canonical_source BYTEA NOT NULL,
    canonical_facts BYTEA NOT NULL,
    kind VARCHAR(30) NOT NULL,
    publisher TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    company_name TEXT,
    description TEXT,
    published_at TIMESTAMP WITH TIME ZONE,
    publication_reason VARCHAR(50),
    CONSTRAINT pk_research_source_payloads PRIMARY KEY (id),
    CONSTRAINT fk_research_source_payloads_version_id FOREIGN KEY (owner_id, version_id) REFERENCES research_source_versions (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_source_payloads_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_source_payloads_0 UNIQUE (owner_id, id),
    CONSTRAINT uq_research_source_payloads_1 UNIQUE (version_id),
    CONSTRAINT ck_research_source_payloads_payload_bound CHECK (octet_length(canonical_source) BETWEEN 1 AND 16384 AND octet_length(canonical_facts) BETWEEN 1 AND 16384),
    CONSTRAINT ck_research_source_payloads_facts_shape CHECK ((kind='news' AND title IS NOT NULL AND summary IS NOT NULL AND published_at IS NOT NULL AND company_name IS NULL AND description IS NULL AND publication_reason IS NULL) OR (kind='company_overview' AND company_name IS NOT NULL AND description IS NOT NULL AND published_at IS NULL AND title IS NULL AND summary IS NULL AND publication_reason='provider_publication_unavailable')),
    CONSTRAINT ck_research_source_payloads_text_bound CHECK (char_length(publisher) BETWEEN 1 AND 4096 AND (title IS NULL OR char_length(title) BETWEEN 1 AND 4096) AND (summary IS NULL OR char_length(summary)<=4096) AND (company_name IS NULL OR char_length(company_name) BETWEEN 1 AND 4096) AND (description IS NULL OR char_length(description)<=4096))
)""",
    r"""CREATE TABLE research_citations (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    source_version_id UUID NOT NULL,
    source_version_digest VARCHAR(64) NOT NULL,
    entity_id UUID NOT NULL,
    provider_event_key VARCHAR(128) NOT NULL,
    facts_digest VARCHAR(64) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    content_digest VARCHAR(64) NOT NULL,
    CONSTRAINT pk_research_citations PRIMARY KEY (id),
    CONSTRAINT fk_research_citations_source_version_id FOREIGN KEY (owner_id, source_version_id) REFERENCES research_source_versions (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_citations_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_citations_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_citations_0 UNIQUE (owner_id, id),
    CONSTRAINT uq_research_citations_1 UNIQUE (source_version_id, provider_event_key),
    CONSTRAINT ck_research_citations_source_version_digest_format CHECK (source_version_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_citations_facts_digest_format CHECK (facts_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_citations_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$')
)""",
    r"""CREATE TABLE research_events (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    entity_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    provider_event_key VARCHAR(128) NOT NULL,
    kind VARCHAR(30) NOT NULL,
    revision INTEGER NOT NULL,
    head_digest VARCHAR(64) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_research_events PRIMARY KEY (id),
    CONSTRAINT fk_research_events_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_events_provider_id FOREIGN KEY (owner_id, provider_id) REFERENCES market_data_providers (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_events_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_events_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_events_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_events_1 UNIQUE (owner_id, account_id, provider_id, provider_event_key),
    CONSTRAINT ck_research_events_revision_bound CHECK (revision BETWEEN 1 AND 512),
    CONSTRAINT ck_research_events_kind_allowed CHECK (kind IN ('news','company_overview')),
    CONSTRAINT ck_research_events_head_digest_format CHECK (head_digest ~ '^[0-9a-f]{64}$')
)""",
    "CREATE INDEX ix_research_events_0 ON research_events (owner_id, account_id, entity_id, id)",
    r"""CREATE TABLE research_event_revisions (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    event_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    previous_revision_id UUID,
    entity_id UUID NOT NULL,
    content_digest VARCHAR(64) NOT NULL,
    facts_digest VARCHAR(64) NOT NULL,
    semantic_digest VARCHAR(64) NOT NULL,
    material_digest VARCHAR(64) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    visible_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    citation_count INTEGER NOT NULL,
    sealed BOOLEAN NOT NULL,
    CONSTRAINT pk_research_event_revisions PRIMARY KEY (id),
    CONSTRAINT fk_research_event_revisions_event_id FOREIGN KEY (owner_id, account_id, event_id) REFERENCES research_events (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_revisions_previous_revision_id FOREIGN KEY (owner_id, account_id, previous_revision_id) REFERENCES research_event_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_revisions_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_revisions_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_revisions_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_event_revisions_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_event_revisions_1 UNIQUE (event_id, revision),
    CONSTRAINT ck_research_event_revisions_revision_bound CHECK (revision BETWEEN 1 AND 512 AND ((revision=1)=(previous_revision_id IS NULL))),
    CONSTRAINT ck_research_event_revisions_citation_bound CHECK (citation_count BETWEEN 1 AND 64),
    CONSTRAINT ck_research_event_revisions_expiry_order CHECK (expires_at>created_at),
    CONSTRAINT ck_research_event_revisions_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_event_revisions_facts_digest_format CHECK (facts_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_event_revisions_semantic_digest_format CHECK (semantic_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_event_revisions_material_digest_format CHECK (material_digest ~ '^[0-9a-f]{64}$')
)""",
    "CREATE INDEX ix_research_event_revisions_0 ON research_event_revisions (owner_id, account_id, semantic_digest, id)",
    "CREATE INDEX ix_research_latest_visible ON research_event_revisions (owner_id, account_id, event_id, revision DESC)",
    r"""CREATE TABLE research_event_payloads (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    canonical_event BYTEA NOT NULL,
    CONSTRAINT pk_research_event_payloads PRIMARY KEY (id),
    CONSTRAINT fk_research_event_payloads_revision_id FOREIGN KEY (owner_id, account_id, revision_id) REFERENCES research_event_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_payloads_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_payloads_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_event_payloads_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_event_payloads_1 UNIQUE (revision_id),
    CONSTRAINT ck_research_event_payloads_payload_bound CHECK (octet_length(canonical_event) BETWEEN 1 AND 16384)
)""",
    r"""CREATE TABLE research_event_citations (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    citation_id UUID NOT NULL,
    source_version_id UUID NOT NULL,
    copy_pending BOOLEAN DEFAULT 'true' NOT NULL,
    ordinal INTEGER NOT NULL,
    CONSTRAINT fk_research_event_citations_source FOREIGN KEY (owner_id, source_version_id) REFERENCES research_source_versions (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT pk_research_event_citations PRIMARY KEY (id),
    CONSTRAINT fk_research_event_citations_revision_id FOREIGN KEY (owner_id, account_id, revision_id) REFERENCES research_event_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_citations_citation_id FOREIGN KEY (owner_id, citation_id) REFERENCES research_citations (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_citations_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_citations_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_event_citations_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_event_citations_1 UNIQUE (revision_id, citation_id),
    CONSTRAINT uq_research_event_citations_2 UNIQUE (revision_id, ordinal),
    CONSTRAINT ck_research_event_citations_ordinal_bound CHECK (ordinal BETWEEN 0 AND 63)
)""",
    "CREATE INDEX ix_research_pending_event_source ON research_event_citations (owner_id, source_version_id, copy_pending, revision_id, id)",
    "CREATE INDEX ix_research_source_payload_owner ON research_source_payloads (owner_id, id)",
    "CREATE INDEX ix_research_event_payload_owner ON research_event_payloads (owner_id, id)",
    r"""CREATE TABLE research_event_aliases (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    event_id UUID NOT NULL,
    provider_id UUID NOT NULL,
    provider_event_key VARCHAR(128) NOT NULL,
    CONSTRAINT pk_research_event_aliases PRIMARY KEY (id),
    CONSTRAINT fk_research_event_aliases_event_id FOREIGN KEY (owner_id, account_id, event_id) REFERENCES research_events (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_aliases_provider_id FOREIGN KEY (owner_id, provider_id) REFERENCES market_data_providers (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_aliases_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_event_aliases_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_event_aliases_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_event_aliases_1 UNIQUE (owner_id, account_id, provider_id, provider_event_key)
)""",
    r"""CREATE TABLE research_publication_witnesses (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    event_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    incoming_revision_id UUID NOT NULL,
    incoming_event_id UUID NOT NULL,
    incoming_revision INTEGER NOT NULL,
    incoming_previous_revision_id UUID,
    incoming_created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    incoming_provider_id UUID NOT NULL,
    incoming_provider_event_key VARCHAR(128) NOT NULL,
    incoming_facts_digest VARCHAR(64) NOT NULL,
    incoming_digest VARCHAR(64) NOT NULL,
    action VARCHAR(30) NOT NULL,
    citation_count INTEGER NOT NULL,
    actor_id UUID NOT NULL,
    sealed BOOLEAN NOT NULL,
    CONSTRAINT pk_research_publication_witnesses PRIMARY KEY (id),
    CONSTRAINT fk_research_publication_witnesses_event_id FOREIGN KEY (owner_id, account_id, event_id) REFERENCES research_events (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_publication_witnesses_revision_id FOREIGN KEY (owner_id, account_id, revision_id) REFERENCES research_event_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_publication_witnesses_actor_id FOREIGN KEY (owner_id, actor_id) REFERENCES principals (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_publication_witnesses_incoming_provider_id FOREIGN KEY (owner_id, incoming_provider_id) REFERENCES market_data_providers (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_publication_witnesses_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_publication_witnesses_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_publication_witnesses_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_publication_witnesses_1 UNIQUE (owner_id, account_id, incoming_digest),
    CONSTRAINT ck_research_publication_witnesses_incoming_order CHECK (incoming_revision BETWEEN 1 AND 512 AND ((incoming_revision=1)=(incoming_previous_revision_id IS NULL))),
    CONSTRAINT ck_research_publication_witnesses_action_allowed CHECK (action IN ('new_event','exact_replay','retrieval_only','material_revision','semantic_alias')),
    CONSTRAINT ck_research_publication_witnesses_citation_bound CHECK (citation_count BETWEEN 1 AND 64),
    CONSTRAINT ck_research_publication_witnesses_incoming_facts_digest_format CHECK (incoming_facts_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_publication_witnesses_incoming_digest_format CHECK (incoming_digest ~ '^[0-9a-f]{64}$')
)""",
    r"""CREATE TABLE research_witness_citations (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    witness_id UUID NOT NULL,
    citation_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    CONSTRAINT pk_research_witness_citations PRIMARY KEY (id),
    CONSTRAINT fk_research_witness_citations_witness_id FOREIGN KEY (owner_id, account_id, witness_id) REFERENCES research_publication_witnesses (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_witness_citations_citation_id FOREIGN KEY (owner_id, citation_id) REFERENCES research_citations (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_witness_citations_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_witness_citations_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_witness_citations_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_witness_citations_1 UNIQUE (witness_id, citation_id),
    CONSTRAINT uq_research_witness_citations_2 UNIQUE (witness_id, ordinal),
    CONSTRAINT ck_research_witness_citations_ordinal_bound CHECK (ordinal BETWEEN 0 AND 63)
)""",
    r"""CREATE TABLE research_alias_promotions (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    alias_id UUID NOT NULL,
    event_id UUID NOT NULL,
    witness_id UUID NOT NULL,
    CONSTRAINT pk_research_alias_promotions PRIMARY KEY (id),
    CONSTRAINT fk_research_alias_promotions_alias_id FOREIGN KEY (owner_id, account_id, alias_id) REFERENCES research_event_aliases (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_alias_promotions_event_id FOREIGN KEY (owner_id, account_id, event_id) REFERENCES research_events (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_alias_promotions_witness_id FOREIGN KEY (owner_id, account_id, witness_id) REFERENCES research_publication_witnesses (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_alias_promotions_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_alias_promotions_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_alias_promotions_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_alias_promotions_1 UNIQUE (alias_id),
    CONSTRAINT uq_research_alias_promotions_2 UNIQUE (event_id),
    CONSTRAINT uq_research_alias_promotions_3 UNIQUE (witness_id)
)""",
    r"""CREATE TABLE research_items (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    revision_digest VARCHAR(64) NOT NULL,
    entity_id UUID NOT NULL,
    xray_run_id UUID NOT NULL,
    xray_input_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    xray_input_digest VARCHAR(64) NOT NULL,
    xray_result_digest VARCHAR(64) NOT NULL,
    xray_pin_digest VARCHAR(64) NOT NULL,
    source_cutoff_at TIMESTAMP WITH TIME ZONE NOT NULL,
    selection_digest VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_research_items PRIMARY KEY (id),
    CONSTRAINT fk_research_items_revision_id FOREIGN KEY (owner_id, account_id, revision_id) REFERENCES research_event_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_items_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_items_xray_run_id FOREIGN KEY (owner_id, xray_run_id) REFERENCES xray_runs (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_items_xray_input_id FOREIGN KEY (owner_id, xray_input_id) REFERENCES xray_input_snapshots (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_items_snapshot_id FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_items_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_items_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_items_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_items_1 UNIQUE (owner_id, account_id, selection_digest),
    CONSTRAINT ck_research_items_expiry_order CHECK (expires_at>created_at),
    CONSTRAINT ck_research_items_revision_digest_format CHECK (revision_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_items_xray_input_digest_format CHECK (xray_input_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_items_xray_result_digest_format CHECK (xray_result_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_items_xray_pin_digest_format CHECK (xray_pin_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_items_selection_digest_format CHECK (selection_digest ~ '^[0-9a-f]{64}$')
)""",
    "CREATE INDEX ix_research_items_0 ON research_items (owner_id, account_id, expires_at, id)",
    r"""CREATE TABLE research_notes (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    entity_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    head_digest VARCHAR(64) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_research_notes PRIMARY KEY (id),
    CONSTRAINT fk_research_notes_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_notes_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_notes_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_notes_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT ck_research_notes_revision_bound CHECK (revision BETWEEN 1 AND 512),
    CONSTRAINT ck_research_notes_head_digest_format CHECK (head_digest ~ '^[0-9a-f]{64}$')
)""",
    "CREATE INDEX ix_research_notes_0 ON research_notes (owner_id, account_id, created_at, id)",
    r"""CREATE TABLE research_note_revisions (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    note_id UUID NOT NULL,
    revision INTEGER NOT NULL,
    previous_revision_id UUID,
    entity_id UUID NOT NULL,
    actor_id UUID NOT NULL,
    content_digest VARCHAR(64) NOT NULL,
    citation_count INTEGER NOT NULL,
    sealed BOOLEAN NOT NULL,
    CONSTRAINT pk_research_note_revisions PRIMARY KEY (id),
    CONSTRAINT fk_research_note_revisions_note_id FOREIGN KEY (owner_id, account_id, note_id) REFERENCES research_notes (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_revisions_previous_revision_id FOREIGN KEY (owner_id, account_id, previous_revision_id) REFERENCES research_note_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_revisions_entity_id FOREIGN KEY (owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_revisions_actor_id FOREIGN KEY (owner_id, actor_id) REFERENCES principals (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_revisions_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_revisions_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_note_revisions_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_note_revisions_1 UNIQUE (note_id, revision),
    CONSTRAINT ck_research_note_revisions_revision_bound CHECK (revision BETWEEN 1 AND 512 AND ((revision=1)=(previous_revision_id IS NULL))),
    CONSTRAINT ck_research_note_revisions_citation_bound CHECK (citation_count BETWEEN 0 AND 64),
    CONSTRAINT ck_research_note_revisions_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$')
)""",
    "CREATE INDEX ix_research_note_version_page ON research_note_revisions (owner_id, account_id, note_id, revision DESC, id DESC)",
    r"""CREATE TABLE research_note_payloads (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    canonical_note BYTEA NOT NULL,
    title TEXT NOT NULL,
    note TEXT NOT NULL,
    thesis TEXT NOT NULL,
    risks TEXT NOT NULL,
    catalysts TEXT NOT NULL,
    break_conditions TEXT NOT NULL,
    CONSTRAINT pk_research_note_payloads PRIMARY KEY (id),
    CONSTRAINT fk_research_note_payloads_revision_id FOREIGN KEY (owner_id, account_id, revision_id) REFERENCES research_note_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_payloads_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_payloads_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_note_payloads_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_note_payloads_1 UNIQUE (revision_id),
    CONSTRAINT ck_research_note_payloads_payload_bound CHECK (octet_length(canonical_note) BETWEEN 1 AND 131072),
    CONSTRAINT ck_research_note_payloads_text_bound CHECK (char_length(title) BETWEEN 1 AND 4096 AND char_length(note)<=4096 AND char_length(thesis)<=4096 AND char_length(risks)<=4096 AND char_length(catalysts)<=4096 AND char_length(break_conditions)<=4096)
)""",
    "CREATE INDEX ix_research_note_payload_owner ON research_note_payloads (owner_id, id)",
    r"""CREATE TABLE research_note_citations (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    citation_id UUID NOT NULL,
    source_version_id UUID NOT NULL,
    source_version_digest VARCHAR(64) NOT NULL,
    citation_digest VARCHAR(64) NOT NULL,
    ordinal INTEGER NOT NULL,
    CONSTRAINT pk_research_note_citations PRIMARY KEY (id),
    CONSTRAINT fk_research_note_citations_revision_id FOREIGN KEY (owner_id, account_id, revision_id) REFERENCES research_note_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_citations_citation_id FOREIGN KEY (owner_id, citation_id) REFERENCES research_citations (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_citations_source_version_id FOREIGN KEY (owner_id, source_version_id) REFERENCES research_source_versions (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_citations_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_note_citations_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_note_citations_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_note_citations_1 UNIQUE (revision_id, citation_id),
    CONSTRAINT uq_research_note_citations_2 UNIQUE (revision_id, ordinal),
    CONSTRAINT ck_research_note_citations_ordinal_bound CHECK (ordinal BETWEEN 0 AND 63),
    CONSTRAINT ck_research_note_citations_source_version_digest_format CHECK (source_version_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_note_citations_citation_digest_format CHECK (citation_digest ~ '^[0-9a-f]{64}$')
)""",
    r"""CREATE TABLE research_review_acknowledgments (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    event_id UUID NOT NULL,
    revision_id UUID NOT NULL,
    revision_digest VARCHAR(64) NOT NULL,
    actor_id UUID NOT NULL,
    reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    content_digest VARCHAR(64) NOT NULL,
    CONSTRAINT pk_research_review_acknowledgments PRIMARY KEY (id),
    CONSTRAINT fk_research_review_acknowledgments_event_id FOREIGN KEY (owner_id, account_id, event_id) REFERENCES research_events (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_review_acknowledgments_revision_id FOREIGN KEY (owner_id, account_id, revision_id) REFERENCES research_event_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_review_acknowledgments_actor_id FOREIGN KEY (owner_id, actor_id) REFERENCES principals (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_review_acknowledgments_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_review_acknowledgments_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_review_acknowledgments_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_review_acknowledgments_1 UNIQUE (owner_id, account_id, event_id, revision_id, actor_id),
    CONSTRAINT ck_research_review_acknowledgments_revision_digest_format CHECK (revision_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_research_review_acknowledgments_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$')
)""",
    "CREATE INDEX ix_research_revision_review ON research_review_acknowledgments (owner_id, account_id, revision_id, reviewed_at DESC, id DESC)",
    r"""CREATE TABLE research_command_results (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    account_id UUID NOT NULL,
    command_id UUID NOT NULL,
    note_revision_id UUID,
    review_id UUID,
    CONSTRAINT pk_research_command_results PRIMARY KEY (id),
    CONSTRAINT fk_research_command_results_command_id FOREIGN KEY (owner_id, account_id, command_id) REFERENCES application_command_identities (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_command_results_note_revision_id FOREIGN KEY (owner_id, account_id, note_revision_id) REFERENCES research_note_revisions (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_command_results_review_id FOREIGN KEY (owner_id, account_id, review_id) REFERENCES research_review_acknowledgments (owner_id, account_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_command_results_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_command_results_account_id_broker_accounts FOREIGN KEY (account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_command_results_0 UNIQUE (owner_id, account_id, id),
    CONSTRAINT uq_research_command_results_1 UNIQUE (command_id),
    CONSTRAINT ck_research_command_results_result_xor CHECK (num_nonnulls(note_revision_id,review_id)=1)
)""",
    r"""CREATE TABLE research_source_retention (
    id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    owner_id UUID NOT NULL,
    source_version_id UUID NOT NULL,
    reason VARCHAR(30) NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_research_source_retention PRIMARY KEY (id),
    CONSTRAINT fk_research_source_retention_source_version_id FOREIGN KEY (owner_id, source_version_id) REFERENCES research_source_versions (owner_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_research_source_retention_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT uq_research_source_retention_0 UNIQUE (owner_id, id),
    CONSTRAINT uq_research_source_retention_1 UNIQUE (source_version_id),
    CONSTRAINT ck_research_source_retention_reason_allowed CHECK (reason IN ('source_expired','source_restricted','owner_erasure')),
    CONSTRAINT ck_research_source_retention_completion_order CHECK (completed_at IS NULL OR completed_at>=created_at)
)""",
    "CREATE INDEX ix_research_source_retention_0 ON research_source_retention (owner_id, completed_at, id)",
    r"""CREATE TABLE research_owner_erasure (
    owner_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_research_owner_erasure PRIMARY KEY (owner_id),
    CONSTRAINT fk_research_owner_erasure_owner_id_owners FOREIGN KEY (owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
    CONSTRAINT ck_research_owner_erasure_completion_order CHECK (completed_at IS NULL OR completed_at>=created_at)
)""",
    r"""CREATE TABLE research_retention_cursor (
      key VARCHAR(50) NOT NULL, scope_owner_id UUID, last_owner_id UUID, last_version_id UUID, updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
      CONSTRAINT pk_research_retention_cursor PRIMARY KEY(key),
      CONSTRAINT fk_research_retention_cursor_scope_owner_id_owners FOREIGN KEY(scope_owner_id) REFERENCES owners(id) ON DELETE RESTRICT,
      CONSTRAINT ck_research_retention_cursor_singleton CHECK((key='research' AND scope_owner_id IS NULL) OR (scope_owner_id IS NOT NULL AND key='research:'||scope_owner_id::text)),
      CONSTRAINT ck_research_retention_cursor_owner_scope CHECK(scope_owner_id IS NULL OR last_owner_id IS NULL OR scope_owner_id=last_owner_id),
      CONSTRAINT ck_research_retention_cursor_cursor_pair CHECK((last_owner_id IS NULL)=(last_version_id IS NULL)),
      CONSTRAINT fk_research_cursor_source FOREIGN KEY(last_owner_id,last_version_id) REFERENCES research_source_versions(owner_id,id) ON DELETE RESTRICT
    )""",
    "ALTER TABLE application_command_identities DROP CONSTRAINT ck_application_command_identities_command_allowed",
    "ALTER TABLE application_command_identities ADD CONSTRAINT ck_application_command_identities_command_allowed CHECK (command IN ('reports.generate.v1','reports.generate.v2','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1','projection.assumption.create.v1','projection.assumption.version.create.v1','projection.goal.create.v1','projection.goal.version.create.v1','projection.run.create.v1','projection.run.cancel.v1','research.note.create.v1','research.note.version.create.v1','research.event.review.v1'))",
    "ALTER TABLE application_command_identities DROP CONSTRAINT ck_application_command_identities_parent_kind",
    "ALTER TABLE application_command_identities ADD CONSTRAINT ck_application_command_identities_parent_kind CHECK ((command IN ('reports.generate.v1','reports.generate.v2') AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1','projection.assumption.create.v1','projection.assumption.version.create.v1','projection.goal.create.v1','projection.goal.version.create.v1','projection.run.create.v1','projection.run.cancel.v1','research.note.create.v1','research.note.version.create.v1','research.event.review.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL))",
    "ALTER TABLE collection_query_snapshots DROP CONSTRAINT ck_collection_query_snapshots_resource_allowed",
    "ALTER TABLE collection_query_snapshots ADD CONSTRAINT ck_collection_query_snapshots_resource_allowed CHECK (resource IN ('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','assumption_sets','assumption_versions','goals','goal_versions','projection_runs','intelligence_quality_sources','activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','research_items','research_notes','research_note_versions'))",
    "ALTER TABLE collection_query_snapshots DROP CONSTRAINT ck_collection_query_snapshots_resource_sort_match",
    "ALTER TABLE collection_query_snapshots ADD CONSTRAINT ck_collection_query_snapshots_resource_sort_match CHECK (((resource IN ('intelligence_quality_sources','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('risk_definitions','risk_runs','scenario_definitions','scenario_runs','assumption_sets','goals','projection_runs') AND sort_specification='created_at_desc_id_desc') OR (resource IN ('risk_versions','scenario_versions','assumption_versions','goal_versions') AND sort_specification='version_number_desc_id_desc')) OR (resource='research_items' AND sort_specification='ordinal_asc') OR (resource='research_notes' AND sort_specification='created_at_desc_id_desc') OR (resource='research_note_versions' AND sort_specification='version_number_desc_id_desc'))",
    "ALTER TABLE collection_query_snapshots DROP CONSTRAINT ck_collection_query_snapshots_account_scope_match",
    "ALTER TABLE collection_query_snapshots ADD CONSTRAINT ck_collection_query_snapshots_account_scope_match CHECK ((((resource IN ('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','assumption_sets','assumption_versions','goals','goal_versions','projection_runs','intelligence_quality_sources','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','premium_reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))) OR (resource IN ('research_items','research_notes','research_note_versions') AND broker_account_id IS NOT NULL))",
    r"""CREATE FUNCTION research_owner_lock(owner UUID) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('premium:'||owner::text,0));
  PERFORM pg_advisory_xact_lock(hashtextextended('research:'||owner::text,0));
END $$;""",
    r"""CREATE FUNCTION research_admission_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE n BIGINT;
BEGIN
  PERFORM research_owner_lock(NEW.owner_id);
  IF EXISTS(SELECT 1 FROM research_owner_erasure WHERE owner_id=NEW.owner_id) THEN
    RAISE EXCEPTION 'research authority unavailable' USING ERRCODE='23514';
  END IF;
  INSERT INTO premium_owner_capacity(owner_id,reserved_bytes,retained_bytes,active_jobs,definition_versions,updated_at)
    VALUES(NEW.owner_id,0,0,0,0,statement_timestamp()) ON CONFLICT(owner_id) DO NOTHING;
  INSERT INTO research_owner_capacity(owner_id,retained_bytes,source_revisions,event_revisions,item_headers,updated_at)
    VALUES(NEW.owner_id,0,0,0,0,statement_timestamp()) ON CONFLICT(owner_id) DO NOTHING;
  IF TG_TABLE_NAME IN ('research_source_versions','research_event_revisions','research_publication_witnesses') THEN
    SELECT (SELECT count(*) FROM research_source_versions WHERE owner_id=NEW.owner_id)
      +(SELECT count(*) FROM research_event_revisions WHERE owner_id=NEW.owner_id)
      +(SELECT count(*) FROM research_publication_witnesses WHERE owner_id=NEW.owner_id) INTO n;
    IF n>=10000 THEN RAISE EXCEPTION 'research revision capacity exceeded' USING ERRCODE='23514'; END IF;
    IF TG_TABLE_NAME='research_source_versions' THEN
      UPDATE research_owner_capacity SET source_revisions=source_revisions+1,updated_at=statement_timestamp() WHERE owner_id=NEW.owner_id;
    ELSE
      UPDATE research_owner_capacity SET event_revisions=event_revisions+1,updated_at=statement_timestamp() WHERE owner_id=NEW.owner_id;
    END IF;
  ELSIF TG_TABLE_NAME='research_items' THEN
    IF (SELECT count(*) FROM research_items WHERE owner_id=NEW.owner_id)>=10000 THEN
      RAISE EXCEPTION 'research item capacity exceeded' USING ERRCODE='23514';
    END IF;
    UPDATE research_owner_capacity SET item_headers=item_headers+1,updated_at=statement_timestamp() WHERE owner_id=NEW.owner_id;
  END IF;
  RETURN NEW;
END $$;""",
    r"""CREATE FUNCTION research_note_capacity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE n BIGINT;
BEGIN
  PERFORM research_owner_lock(NEW.owner_id);
  SELECT (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)
    +(SELECT count(*) FROM scenario_definition_versions WHERE owner_id=NEW.owner_id)
    +(SELECT count(*) FROM assumption_versions WHERE owner_id=NEW.owner_id)
    +(SELECT count(*) FROM goal_versions WHERE owner_id=NEW.owner_id)
    +(SELECT count(*) FROM research_note_revisions WHERE owner_id=NEW.owner_id) INTO n;
  IF n>=512 THEN RAISE EXCEPTION 'shared definition capacity exceeded' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='research_note_revisions' THEN
    INSERT INTO premium_owner_capacity(owner_id,reserved_bytes,retained_bytes,active_jobs,definition_versions,updated_at)
      VALUES(NEW.owner_id,0,0,0,0,statement_timestamp()) ON CONFLICT(owner_id) DO NOTHING;
    UPDATE premium_owner_capacity SET definition_versions=definition_versions+1,updated_at=statement_timestamp() WHERE owner_id=NEW.owner_id;
  END IF;
  RETURN NEW;
END $$;""",
    r"""CREATE FUNCTION research_payload_charge() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner UUID; delta BIGINT;
BEGIN
  IF TG_OP='DELETE' THEN owner:=OLD.owner_id; ELSE owner:=NEW.owner_id; END IF;
  PERFORM research_owner_lock(owner);
  IF TG_TABLE_NAME='research_source_payloads' THEN
    IF TG_OP='DELETE' THEN
      delta:=-(octet_length(OLD.canonical_source)+octet_length(OLD.canonical_facts)+octet_length(OLD.publisher)
        +coalesce(octet_length(OLD.title),0)+coalesce(octet_length(OLD.summary),0)+coalesce(octet_length(OLD.company_name),0)+coalesce(octet_length(OLD.description),0)+octet_length(OLD.kind)+coalesce(octet_length(OLD.publication_reason),0)+(CASE WHEN OLD.published_at IS NULL THEN 0 ELSE 8 END));
    ELSE
      delta:=octet_length(NEW.canonical_source)+octet_length(NEW.canonical_facts)+octet_length(NEW.publisher)
        +coalesce(octet_length(NEW.title),0)+coalesce(octet_length(NEW.summary),0)+coalesce(octet_length(NEW.company_name),0)+coalesce(octet_length(NEW.description),0)+octet_length(NEW.kind)+coalesce(octet_length(NEW.publication_reason),0)+(CASE WHEN NEW.published_at IS NULL THEN 0 ELSE 8 END);
    END IF;
  ELSIF TG_TABLE_NAME='research_event_payloads' THEN
    IF TG_OP='DELETE' THEN delta:=-octet_length(OLD.canonical_event); ELSE delta:=octet_length(NEW.canonical_event); END IF;
  ELSIF TG_TABLE_NAME='research_note_payloads' THEN
    IF TG_OP='DELETE' THEN
      delta:=-(octet_length(OLD.canonical_note)+octet_length(OLD.title)+octet_length(OLD.note)+octet_length(OLD.thesis)
        +octet_length(OLD.risks)+octet_length(OLD.catalysts)+octet_length(OLD.break_conditions));
    ELSE
      delta:=octet_length(NEW.canonical_note)+octet_length(NEW.title)+octet_length(NEW.note)+octet_length(NEW.thesis)
        +octet_length(NEW.risks)+octet_length(NEW.catalysts)+octet_length(NEW.break_conditions);
    END IF;
  ELSE RAISE EXCEPTION 'unknown research payload'; END IF;
  UPDATE research_owner_capacity SET retained_bytes=retained_bytes+delta,updated_at=statement_timestamp() WHERE owner_id=owner;
  IF NOT FOUND THEN RAISE EXCEPTION 'research capacity missing'; END IF;
  UPDATE premium_owner_capacity SET retained_bytes=retained_bytes+delta,updated_at=statement_timestamp() WHERE owner_id=owner;
  IF NOT FOUND THEN RAISE EXCEPTION 'shared research capacity missing'; END IF;
  RETURN NULL;
END $$;""",
    r"""CREATE FUNCTION research_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent RECORD; other RECORD; source_row RECORD;
BEGIN
  IF TG_ARGV[0]='account' THEN
    IF NOT EXISTS(SELECT 1 FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id
      WHERE a.id=NEW.account_id AND c.owner_id=NEW.owner_id) THEN
      RAISE EXCEPTION 'research account scope differs' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_TABLE_NAME='research_source_versions' THEN
    SELECT * INTO parent FROM research_sources WHERE id=NEW.source_id AND owner_id=NEW.owner_id FOR SHARE;
    IF NOT FOUND OR (parent.provider_id,parent.entity_id,parent.capability) IS DISTINCT FROM (NEW.provider_id,NEW.entity_id,NEW.capability) THEN
      RAISE EXCEPTION 'research source identity differs' USING ERRCODE='23514'; END IF;
    SELECT * INTO parent FROM research_source_origins WHERE id=NEW.origin_id AND owner_id=NEW.owner_id FOR SHARE;
    IF NOT FOUND OR (parent.entity_id,parent.capability,parent.facts_digest) IS DISTINCT FROM (NEW.entity_id,NEW.capability,NEW.facts_digest)
      OR parent.original_retained_at>NEW.retained_at OR NEW.effective_expires_at>parent.expires_at THEN
      RAISE EXCEPTION 'research original lifetime differs' USING ERRCODE='23514'; END IF;
    SELECT * INTO other FROM provider_license_versions WHERE owner_id=NEW.owner_id AND id=NEW.license_version_id AND provider_id=NEW.provider_id;
    IF NOT FOUND OR other.store_permission<>'allowed' OR other.display_permission<>'allowed'
      OR other.retention_days IS NULL OR other.effective_at>NEW.first_known_at
      OR NEW.effective_expires_at>parent.original_retained_at+make_interval(days=>least(30,other.retention_days)) THEN
      RAISE EXCEPTION 'research pinned license differs' USING ERRCODE='23514'; END IF;
    SELECT * INTO other FROM provider_license_versions WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id
      AND effective_at<=statement_timestamp() ORDER BY effective_at DESC,version_number DESC,id DESC LIMIT 1;
    IF NOT FOUND OR other.store_permission<>'allowed' OR other.display_permission<>'allowed' OR other.retention_days IS NULL
      OR NEW.effective_expires_at>parent.original_retained_at+make_interval(days=>least(30,other.retention_days)) THEN
      RAISE EXCEPTION 'research current license differs' USING ERRCODE='23514'; END IF;
    IF NEW.sealed THEN RAISE EXCEPTION 'research source must seal after its payload' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_source_payloads' THEN
    SELECT * INTO parent FROM research_source_versions WHERE owner_id=NEW.owner_id AND id=NEW.version_id FOR SHARE;
    IF NOT FOUND OR parent.sealed OR parent.capability<>NEW.kind OR parent.effective_expires_at<=statement_timestamp()
      OR EXISTS(SELECT 1 FROM research_source_retention WHERE source_version_id=parent.id) THEN
      RAISE EXCEPTION 'research payload parent unavailable' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_citations' THEN
    SELECT * INTO parent FROM research_source_versions WHERE owner_id=NEW.owner_id AND id=NEW.source_version_id FOR SHARE;
    IF NOT FOUND OR NOT parent.sealed OR parent.effective_expires_at<=statement_timestamp()
      OR (NEW.source_version_digest,NEW.entity_id,NEW.facts_digest) IS DISTINCT FROM (parent.content_digest,parent.entity_id,parent.facts_digest)
      OR EXISTS(SELECT 1 FROM research_source_retention WHERE source_version_id=parent.id)
      OR NOT EXISTS(SELECT 1 FROM research_source_payloads p WHERE p.version_id=parent.id AND p.published_at IS NOT DISTINCT FROM NEW.published_at) THEN
      RAISE EXCEPTION 'research citation source differs' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_event_revisions' THEN
    SELECT * INTO parent FROM research_events WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.event_id FOR SHARE;
    IF NOT FOUND OR parent.entity_id<>NEW.entity_id OR NEW.sealed THEN RAISE EXCEPTION 'research event identity differs' USING ERRCODE='23514'; END IF;
    IF NEW.revision>1 THEN
      SELECT * INTO other FROM research_event_revisions WHERE id=NEW.previous_revision_id AND event_id=NEW.event_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
      IF NOT FOUND OR NOT other.sealed OR NEW.revision<>other.revision+1 OR NEW.created_at<other.created_at OR NEW.material_digest=other.material_digest THEN
        RAISE EXCEPTION 'research material predecessor differs' USING ERRCODE='23514'; END IF;
    END IF;
  ELSIF TG_TABLE_NAME IN ('research_event_payloads','research_event_citations') THEN
    SELECT * INTO parent FROM research_event_revisions WHERE id=NEW.revision_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR SHARE;
    IF NOT FOUND OR parent.sealed THEN RAISE EXCEPTION 'research event is immutable' USING ERRCODE='23514'; END IF;
    IF TG_TABLE_NAME='research_event_citations' THEN
      SELECT * INTO other FROM research_citations WHERE id=NEW.citation_id AND owner_id=NEW.owner_id;
      IF NOT FOUND OR other.entity_id<>parent.entity_id OR other.facts_digest<>parent.facts_digest OR other.published_at IS DISTINCT FROM parent.published_at THEN
        RAISE EXCEPTION 'research event citation differs' USING ERRCODE='23514'; END IF;
      IF NEW.copy_pending IS DISTINCT FROM true OR (NEW.source_version_id IS NOT NULL AND NEW.source_version_id<>other.source_version_id) THEN
        RAISE EXCEPTION 'research pending source identity differs' USING ERRCODE='23514'; END IF;
      NEW.source_version_id:=other.source_version_id;
      SELECT * INTO source_row FROM research_source_versions WHERE id=other.source_version_id AND owner_id=NEW.owner_id FOR SHARE;
      IF NOT FOUND OR NOT source_row.sealed OR source_row.effective_expires_at<=NEW.created_at
        OR EXISTS(SELECT 1 FROM research_source_retention WHERE source_version_id=source_row.id)
        OR NOT EXISTS(SELECT 1 FROM research_source_payloads WHERE version_id=source_row.id) THEN
        RAISE EXCEPTION 'research event source is no longer retained' USING ERRCODE='23514'; END IF;
    END IF;
  ELSIF TG_TABLE_NAME='research_publication_witnesses' THEN
    SELECT * INTO parent FROM research_event_revisions WHERE id=NEW.revision_id AND event_id=NEW.event_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
    IF NOT FOUND OR NOT parent.sealed OR NEW.sealed OR parent.facts_digest<>NEW.incoming_facts_digest THEN
      RAISE EXCEPTION 'research witness identity differs' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_witness_citations' THEN
    SELECT * INTO parent FROM research_publication_witnesses WHERE id=NEW.witness_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR SHARE;
    IF NOT FOUND OR parent.sealed THEN RAISE EXCEPTION 'research witness is immutable' USING ERRCODE='23514'; END IF;
    SELECT c.* INTO other FROM research_citations c JOIN research_events e ON e.id=parent.event_id
      WHERE c.id=NEW.citation_id AND c.owner_id=NEW.owner_id AND c.entity_id=e.entity_id AND c.facts_digest=parent.incoming_facts_digest;
    IF NOT FOUND THEN RAISE EXCEPTION 'research witness citation differs' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_alias_promotions' THEN
    SELECT a.* INTO parent FROM research_event_aliases a WHERE a.id=NEW.alias_id AND a.owner_id=NEW.owner_id AND a.account_id=NEW.account_id;
    SELECT e.* INTO other FROM research_events e JOIN research_publication_witnesses w ON w.event_id=e.id
      WHERE e.id=NEW.event_id AND e.owner_id=NEW.owner_id AND e.account_id=NEW.account_id AND w.id=NEW.witness_id AND w.sealed
        AND (e.provider_id,e.provider_event_key)=(parent.provider_id,parent.provider_event_key);
    IF NOT FOUND OR NEW.event_id=parent.event_id THEN RAISE EXCEPTION 'research alias promotion differs' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_items' THEN
    SELECT * INTO parent FROM research_event_revisions WHERE id=NEW.revision_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR SHARE;
    IF NOT FOUND OR NOT parent.sealed OR parent.content_digest<>NEW.revision_digest OR parent.entity_id<>NEW.entity_id
      OR parent.visible_at>NEW.source_cutoff_at OR NEW.expires_at>parent.expires_at THEN
      RAISE EXCEPTION 'research item revision differs' USING ERRCODE='23514'; END IF;
    SELECT * INTO parent FROM xray_input_snapshots WHERE id=NEW.xray_input_id AND owner_id=NEW.owner_id FOR SHARE;
    IF NOT FOUND OR parent.account_id<>NEW.account_id OR parent.snapshot_id<>NEW.snapshot_id OR parent.input_digest<>NEW.xray_input_digest
      OR parent.sealed_at IS NULL OR octet_length(parent.canonical_input)=0 THEN
      RAISE EXCEPTION 'research Xray input differs' USING ERRCODE='23514'; END IF;
    SELECT * INTO parent FROM xray_runs WHERE id=NEW.xray_run_id AND owner_id=NEW.owner_id FOR SHARE;
    IF NOT FOUND OR parent.input_id<>NEW.xray_input_id OR parent.content_digest<>NEW.xray_result_digest OR parent.sealed_at IS NULL
      OR (octet_length(parent.canonical_summary)=0 OR octet_length(parent.canonical_reconciliation)=0 OR octet_length(parent.canonical_exact_state)=0)
      OR EXISTS(SELECT 1 FROM xray_retention_events WHERE input_id=NEW.xray_input_id) THEN
      RAISE EXCEPTION 'research Xray result differs' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_note_revisions' THEN
    SELECT * INTO parent FROM research_notes WHERE id=NEW.note_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR SHARE;
    IF NOT FOUND OR parent.entity_id<>NEW.entity_id OR NEW.sealed THEN RAISE EXCEPTION 'research note identity differs' USING ERRCODE='23514'; END IF;
    IF NEW.revision>1 THEN
      SELECT * INTO other FROM research_note_revisions WHERE id=NEW.previous_revision_id AND note_id=NEW.note_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
      IF NOT FOUND OR NOT other.sealed OR NEW.revision<>other.revision+1 OR NEW.created_at<other.created_at THEN
        RAISE EXCEPTION 'research note predecessor differs' USING ERRCODE='23514'; END IF;
    END IF;
  ELSIF TG_TABLE_NAME IN ('research_note_payloads','research_note_citations') THEN
    SELECT * INTO parent FROM research_note_revisions WHERE id=NEW.revision_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR SHARE;
    IF NOT FOUND OR parent.sealed THEN RAISE EXCEPTION 'research note is immutable' USING ERRCODE='23514'; END IF;
    IF TG_TABLE_NAME='research_note_citations' THEN
      SELECT c.* INTO other FROM research_citations c WHERE c.id=NEW.citation_id AND c.owner_id=NEW.owner_id;
      IF NOT FOUND OR (other.source_version_id,other.source_version_digest,other.content_digest) IS DISTINCT FROM (NEW.source_version_id,NEW.source_version_digest,NEW.citation_digest) THEN
        RAISE EXCEPTION 'research note citation differs' USING ERRCODE='23514'; END IF;
    END IF;
  ELSIF TG_TABLE_NAME='research_review_acknowledgments' THEN
    SELECT * INTO parent FROM research_event_revisions WHERE id=NEW.revision_id AND event_id=NEW.event_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
    IF NOT FOUND OR NOT parent.sealed OR parent.content_digest<>NEW.revision_digest OR NEW.reviewed_at<parent.created_at THEN
      RAISE EXCEPTION 'research reviewed revision differs' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_command_results' THEN
    SELECT * INTO parent FROM application_command_identities WHERE id=NEW.command_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'research command identity missing' USING ERRCODE='23514'; END IF;
    IF NEW.note_revision_id IS NOT NULL THEN
      IF parent.command NOT IN ('research.note.create.v1','research.note.version.create.v1') OR parent.premium_resource_id<>NEW.note_revision_id THEN
        RAISE EXCEPTION 'research note command differs' USING ERRCODE='23514'; END IF;
    ELSE
      IF parent.command<>'research.event.review.v1' OR parent.premium_resource_id<>NEW.review_id THEN
        RAISE EXCEPTION 'research review command differs' USING ERRCODE='23514'; END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;""",
    r"""CREATE FUNCTION research_complete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE row RECORD; actual BIGINT; last_ordinal INTEGER;
BEGIN
  IF TG_TABLE_NAME='research_source_versions' THEN
    SELECT * INTO row FROM research_source_versions WHERE id=NEW.id;
    IF NOT row.sealed OR (SELECT count(*) FROM research_source_payloads WHERE version_id=row.id)<>1 THEN
      RAISE EXCEPTION 'research source publication incomplete' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_citations' THEN
    IF NOT EXISTS(SELECT 1 FROM research_witness_citations WHERE citation_id=NEW.id) THEN
      RAISE EXCEPTION 'research citation receipt missing' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_event_aliases' THEN
    IF NOT EXISTS(SELECT 1 FROM research_publication_witnesses WHERE event_id=NEW.event_id AND owner_id=NEW.owner_id
      AND account_id=NEW.account_id AND incoming_provider_id=NEW.provider_id AND incoming_provider_event_key=NEW.provider_event_key AND sealed) THEN
      RAISE EXCEPTION 'research alias receipt missing' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_event_revisions' THEN
    SELECT * INTO row FROM research_event_revisions WHERE id=NEW.id;
    SELECT count(*),max(ordinal) INTO actual,last_ordinal FROM research_event_citations WHERE revision_id=row.id;
    IF NOT EXISTS(SELECT 1 FROM research_events WHERE id=row.event_id AND revision>=row.revision) THEN
      RAISE EXCEPTION 'research event head did not advance' USING ERRCODE='23514'; END IF;
    IF NOT row.sealed OR (SELECT count(*) FROM research_event_payloads WHERE revision_id=row.id)<>1
      OR actual<>row.citation_count OR last_ordinal<>row.citation_count-1 THEN
      RAISE EXCEPTION 'research event publication incomplete' USING ERRCODE='23514'; END IF;
    IF (SELECT min(v.effective_expires_at) FROM research_event_citations m JOIN research_citations c ON c.id=m.citation_id
        JOIN research_source_versions v ON v.id=c.source_version_id WHERE m.revision_id=row.id) IS DISTINCT FROM row.expires_at
      OR (SELECT max(v.first_known_at) FROM research_event_citations m JOIN research_citations c ON c.id=m.citation_id
        JOIN research_source_versions v ON v.id=c.source_version_id WHERE m.revision_id=row.id) IS DISTINCT FROM row.visible_at THEN
      RAISE EXCEPTION 'research event provenance clock differs' USING ERRCODE='23514'; END IF;
    IF NOT EXISTS(SELECT 1 FROM research_event_citations m JOIN research_citations c ON c.id=m.citation_id
      JOIN research_source_versions v ON v.id=c.source_version_id JOIN research_events e ON e.id=row.event_id
      WHERE m.revision_id=row.id AND c.provider_event_key=e.provider_event_key AND v.provider_id=e.provider_id) THEN
      RAISE EXCEPTION 'research primary citation missing' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_publication_witnesses' THEN
    SELECT * INTO row FROM research_publication_witnesses WHERE id=NEW.id;
    SELECT count(*),max(ordinal) INTO actual,last_ordinal FROM research_witness_citations WHERE witness_id=row.id;
    IF NOT row.sealed OR actual<>row.citation_count OR last_ordinal<>row.citation_count-1 THEN
      RAISE EXCEPTION 'research receipt incomplete' USING ERRCODE='23514'; END IF;
    IF NOT EXISTS(SELECT 1 FROM research_witness_citations m JOIN research_citations c ON c.id=m.citation_id
      JOIN research_source_versions v ON v.id=c.source_version_id WHERE m.witness_id=row.id
        AND c.provider_event_key=row.incoming_provider_event_key AND v.provider_id=row.incoming_provider_id) THEN
      RAISE EXCEPTION 'research original primary citation missing' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_note_revisions' THEN
    SELECT * INTO row FROM research_note_revisions WHERE id=NEW.id;
    SELECT count(*),max(ordinal) INTO actual,last_ordinal FROM research_note_citations WHERE revision_id=row.id;
    IF NOT EXISTS(SELECT 1 FROM research_notes WHERE id=row.note_id AND revision>=row.revision) THEN
      RAISE EXCEPTION 'research note head did not advance' USING ERRCODE='23514'; END IF;
    IF NOT row.sealed OR (SELECT count(*) FROM research_note_payloads WHERE revision_id=row.id)<>1
      OR actual<>row.citation_count OR (actual>0 AND last_ordinal<>row.citation_count-1) THEN
      RAISE EXCEPTION 'research note publication incomplete' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_events' THEN
    SELECT * INTO row FROM research_events WHERE id=NEW.id;
    IF NOT EXISTS(SELECT 1 FROM research_event_revisions r WHERE r.event_id=row.id AND r.revision=row.revision AND r.content_digest=row.head_digest AND r.sealed)
      OR row.revision<>(SELECT max(revision) FROM research_event_revisions WHERE event_id=row.id) THEN
      RAISE EXCEPTION 'research event head incomplete' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_notes' THEN
    SELECT * INTO row FROM research_notes WHERE id=NEW.id;
    IF NOT EXISTS(SELECT 1 FROM research_note_revisions r WHERE r.note_id=row.id AND r.revision=row.revision AND r.content_digest=row.head_digest AND r.sealed)
      OR row.revision<>(SELECT max(revision) FROM research_note_revisions WHERE note_id=row.id) THEN
      RAISE EXCEPTION 'research note head incomplete' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='application_command_identities' THEN
    IF NEW.command IN ('research.note.create.v1','research.note.version.create.v1','research.event.review.v1') THEN
      IF (SELECT count(*) FROM research_command_results WHERE command_id=NEW.id)<>1 THEN
        RAISE EXCEPTION 'research command publication incomplete' USING ERRCODE='23514'; END IF;
    END IF;
  END IF;
  RETURN NULL;
END $$;""",
    r"""CREATE FUNCTION research_retention_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner UUID; source UUID; deleting BOOLEAN:=TG_OP='DELETE'; row RECORD;
BEGIN
  IF deleting THEN owner:=OLD.owner_id; ELSE owner:=NEW.owner_id; END IF;
  -- DELETE already holds its target tuple. Never wait for an owner lock from here.
  IF NOT pg_try_advisory_xact_lock(hashtextextended('premium:'||owner::text,0))
    OR NOT pg_try_advisory_xact_lock(hashtextextended('research:'||owner::text,0)) THEN
    RAISE EXCEPTION 'research owner is busy' USING ERRCODE='55P03'; END IF;
  IF TG_TABLE_NAME='research_source_retention' THEN
    IF deleting THEN RAISE EXCEPTION 'research retention identity is immutable' USING ERRCODE='23514'; END IF;
    SELECT * INTO row FROM research_source_versions WHERE owner_id=owner AND id=NEW.source_version_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'research retention parent missing' USING ERRCODE='23514'; END IF;
    IF TG_OP='UPDATE' THEN
      IF OLD.completed_at IS NOT NULL OR (to_jsonb(NEW)-'completed_at') IS DISTINCT FROM (to_jsonb(OLD)-'completed_at') THEN
        RAISE EXCEPTION 'research retention identity is immutable' USING ERRCODE='23514'; END IF;
    END IF;
    IF NEW.completed_at IS NOT NULL THEN
      IF EXISTS(SELECT 1 FROM research_source_payloads WHERE version_id=NEW.source_version_id)
        OR EXISTS(SELECT 1 FROM research_event_citations WHERE owner_id=owner AND source_version_id=NEW.source_version_id AND copy_pending) THEN
        RAISE EXCEPTION 'research retained copies remain' USING ERRCODE='23514'; END IF;
    END IF;
    RETURN NEW;
  ELSIF TG_TABLE_NAME='research_owner_erasure' THEN
    IF deleting THEN RAISE EXCEPTION 'research erasure identity is immutable' USING ERRCODE='23514'; END IF;
    IF TG_OP='UPDATE' THEN
      IF OLD.completed_at IS NOT NULL OR (to_jsonb(NEW)-'completed_at') IS DISTINCT FROM (to_jsonb(OLD)-'completed_at') THEN
        RAISE EXCEPTION 'research erasure identity is immutable' USING ERRCODE='23514'; END IF;
    END IF;
    IF NEW.completed_at IS NOT NULL AND (EXISTS(SELECT 1 FROM research_source_payloads WHERE owner_id=owner)
      OR EXISTS(SELECT 1 FROM research_event_payloads WHERE owner_id=owner) OR EXISTS(SELECT 1 FROM research_note_payloads WHERE owner_id=owner)) THEN
      RAISE EXCEPTION 'research owner payload remains' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  ELSIF TG_TABLE_NAME='research_event_payloads' THEN
    IF NOT EXISTS(SELECT 1 FROM research_owner_erasure WHERE owner_id=owner)
      AND NOT EXISTS(SELECT 1 FROM research_event_citations m JOIN research_citations c ON c.id=m.citation_id
        JOIN research_source_retention r ON r.source_version_id=c.source_version_id WHERE m.revision_id=OLD.revision_id) THEN
      RAISE EXCEPTION 'research event retention marker missing' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_source_payloads' THEN
    source:=OLD.version_id;
    IF NOT EXISTS(SELECT 1 FROM research_source_retention WHERE source_version_id=source AND owner_id=owner)
      OR EXISTS(SELECT 1 FROM research_event_citations WHERE owner_id=owner AND source_version_id=source AND copy_pending) THEN
      RAISE EXCEPTION 'research source copy order differs' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='research_note_payloads' THEN
    IF NOT EXISTS(SELECT 1 FROM research_owner_erasure WHERE owner_id=owner) THEN
      RAISE EXCEPTION 'research owner erasure marker missing' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN OLD;
END $$;""",
    r"""CREATE FUNCTION research_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'research identity is immutable' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='research_account_states' THEN
    IF NEW.revision<>OLD.revision+1 OR NEW.updated_at<OLD.updated_at OR (to_jsonb(NEW)-ARRAY['revision','updated_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['revision','updated_at']) THEN
      RAISE EXCEPTION 'research head transition differs' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='research_source_versions' THEN
    IF OLD.sealed OR NOT NEW.sealed OR (to_jsonb(NEW)-'sealed') IS DISTINCT FROM (to_jsonb(OLD)-'sealed') THEN
      RAISE EXCEPTION 'research sealed identity is immutable' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='research_events' THEN
    IF NEW.revision<>OLD.revision+1 OR NEW.updated_at<OLD.updated_at OR (to_jsonb(NEW)-ARRAY['revision','updated_at','head_digest']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['revision','updated_at','head_digest']) THEN
      RAISE EXCEPTION 'research head transition differs' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='research_event_revisions' THEN
    IF OLD.sealed OR NOT NEW.sealed OR (to_jsonb(NEW)-'sealed') IS DISTINCT FROM (to_jsonb(OLD)-'sealed') THEN
      RAISE EXCEPTION 'research sealed identity is immutable' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='research_publication_witnesses' THEN
    IF OLD.sealed OR NOT NEW.sealed OR (to_jsonb(NEW)-'sealed') IS DISTINCT FROM (to_jsonb(OLD)-'sealed') THEN
      RAISE EXCEPTION 'research sealed identity is immutable' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='research_notes' THEN
    IF NEW.revision<>OLD.revision+1 OR NEW.updated_at<OLD.updated_at OR (to_jsonb(NEW)-ARRAY['revision','updated_at','head_digest']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['revision','updated_at','head_digest']) THEN
      RAISE EXCEPTION 'research head transition differs' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME='research_note_revisions' THEN
    IF OLD.sealed OR NOT NEW.sealed OR (to_jsonb(NEW)-'sealed') IS DISTINCT FROM (to_jsonb(OLD)-'sealed') THEN
      RAISE EXCEPTION 'research sealed identity is immutable' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'research identity is immutable' USING ERRCODE='23514';
END $$;""",
    r"""CREATE FUNCTION research_event_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='research_event_payloads' THEN
    -- AFTER DELETE: all <=64 normalized source witnesses lose their copy together.
    UPDATE research_event_citations SET copy_pending=false
      WHERE owner_id=OLD.owner_id AND account_id=OLD.account_id
        AND revision_id=OLD.revision_id AND copy_pending;
    RETURN NULL;
  END IF;
  IF TG_OP<>'UPDATE' OR pg_trigger_depth()<2 OR NOT OLD.copy_pending OR NEW.copy_pending
    OR (to_jsonb(NEW)-'copy_pending') IS DISTINCT FROM (to_jsonb(OLD)-'copy_pending')
    OR EXISTS(SELECT 1 FROM research_event_payloads WHERE revision_id=OLD.revision_id) THEN
    RAISE EXCEPTION 'research pending copy identity is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;""",
    "CREATE TRIGGER research_event_copy_guard AFTER DELETE ON research_event_payloads FOR EACH ROW EXECUTE FUNCTION research_event_copy_guard()",
    "CREATE TRIGGER research_event_copy_guard BEFORE UPDATE ON research_event_citations FOR EACH ROW EXECUTE FUNCTION research_event_copy_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_account_states FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_account_states FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_source_origins FOR EACH ROW EXECUTE FUNCTION research_scope_guard('source')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_source_origins FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_sources FOR EACH ROW EXECUTE FUNCTION research_scope_guard('source')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_sources FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_source_versions FOR EACH ROW EXECUTE FUNCTION research_scope_guard('source')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_source_versions FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_admission_guard BEFORE INSERT ON research_source_versions FOR EACH ROW EXECUTE FUNCTION research_admission_guard()",
    "CREATE CONSTRAINT TRIGGER research_complete_guard AFTER INSERT ON research_source_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_source_payloads FOR EACH ROW EXECUTE FUNCTION research_scope_guard('source')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE ON research_source_payloads FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_retention_guard BEFORE DELETE ON research_source_payloads FOR EACH ROW EXECUTE FUNCTION research_retention_guard()",
    "CREATE TRIGGER research_payload_charge AFTER INSERT OR DELETE ON research_source_payloads FOR EACH ROW EXECUTE FUNCTION research_payload_charge()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_citations FOR EACH ROW EXECUTE FUNCTION research_scope_guard('source')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_citations FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE CONSTRAINT TRIGGER research_complete_guard AFTER INSERT ON research_citations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_events FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_events FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE CONSTRAINT TRIGGER research_complete_guard AFTER INSERT OR UPDATE ON research_events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_event_revisions FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_event_revisions FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_admission_guard BEFORE INSERT ON research_event_revisions FOR EACH ROW EXECUTE FUNCTION research_admission_guard()",
    "CREATE CONSTRAINT TRIGGER research_complete_guard AFTER INSERT ON research_event_revisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_event_payloads FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE ON research_event_payloads FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_retention_guard BEFORE DELETE ON research_event_payloads FOR EACH ROW EXECUTE FUNCTION research_retention_guard()",
    "CREATE TRIGGER research_payload_charge AFTER INSERT OR DELETE ON research_event_payloads FOR EACH ROW EXECUTE FUNCTION research_payload_charge()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_event_citations FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE DELETE ON research_event_citations FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_event_aliases FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_event_aliases FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE CONSTRAINT TRIGGER research_complete_guard AFTER INSERT ON research_event_aliases DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_publication_witnesses FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_publication_witnesses FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_admission_guard BEFORE INSERT ON research_publication_witnesses FOR EACH ROW EXECUTE FUNCTION research_admission_guard()",
    "CREATE CONSTRAINT TRIGGER research_complete_guard AFTER INSERT ON research_publication_witnesses DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_witness_citations FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_witness_citations FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_alias_promotions FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_alias_promotions FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_items FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_items FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_admission_guard BEFORE INSERT ON research_items FOR EACH ROW EXECUTE FUNCTION research_admission_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_notes FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_notes FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE CONSTRAINT TRIGGER research_complete_guard AFTER INSERT OR UPDATE ON research_notes DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_note_revisions FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_note_revisions FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_admission_guard BEFORE INSERT ON research_note_revisions FOR EACH ROW EXECUTE FUNCTION research_admission_guard()",
    "CREATE CONSTRAINT TRIGGER research_complete_guard AFTER INSERT ON research_note_revisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_note_payloads FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE ON research_note_payloads FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_retention_guard BEFORE DELETE ON research_note_payloads FOR EACH ROW EXECUTE FUNCTION research_retention_guard()",
    "CREATE TRIGGER research_payload_charge AFTER INSERT OR DELETE ON research_note_payloads FOR EACH ROW EXECUTE FUNCTION research_payload_charge()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_note_citations FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_note_citations FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_review_acknowledgments FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_review_acknowledgments FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_scope_guard BEFORE INSERT ON research_command_results FOR EACH ROW EXECUTE FUNCTION research_scope_guard('account')",
    "CREATE TRIGGER research_immutable_guard BEFORE UPDATE OR DELETE ON research_command_results FOR EACH ROW EXECUTE FUNCTION research_immutable_guard()",
    "CREATE TRIGGER research_retention_guard BEFORE INSERT OR UPDATE OR DELETE ON research_source_retention FOR EACH ROW EXECUTE FUNCTION research_retention_guard()",
    "CREATE TRIGGER research_retention_guard BEFORE INSERT OR UPDATE OR DELETE ON research_owner_erasure FOR EACH ROW EXECUTE FUNCTION research_retention_guard()",
    "CREATE TRIGGER research_note_capacity_guard BEFORE INSERT ON risk_definition_versions FOR EACH ROW EXECUTE FUNCTION research_note_capacity_guard()",
    "CREATE TRIGGER research_note_capacity_guard BEFORE INSERT ON scenario_definition_versions FOR EACH ROW EXECUTE FUNCTION research_note_capacity_guard()",
    "CREATE TRIGGER research_note_capacity_guard BEFORE INSERT ON assumption_versions FOR EACH ROW EXECUTE FUNCTION research_note_capacity_guard()",
    "CREATE TRIGGER research_note_capacity_guard BEFORE INSERT ON goal_versions FOR EACH ROW EXECUTE FUNCTION research_note_capacity_guard()",
    "CREATE TRIGGER research_note_capacity_guard BEFORE INSERT ON research_note_revisions FOR EACH ROW EXECUTE FUNCTION research_note_capacity_guard()",
    "CREATE CONSTRAINT TRIGGER research_command_complete_guard AFTER INSERT ON application_command_identities DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION research_complete_guard()",
)


def upgrade() -> None:
    for statement in _DDL:
        op.execute(text(statement))


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM research_source_versions) OR EXISTS(SELECT 1 FROM research_note_revisions) OR EXISTS(SELECT 1 FROM research_items) THEN RAISE EXCEPTION 'research records prevent downgrade'; END IF; END $$"
    )
    op.execute("DROP TRIGGER research_note_capacity_guard ON risk_definition_versions")
    op.execute("DROP TRIGGER research_note_capacity_guard ON scenario_definition_versions")
    op.execute("DROP TRIGGER research_note_capacity_guard ON assumption_versions")
    op.execute("DROP TRIGGER research_note_capacity_guard ON goal_versions")
    op.execute("DROP TRIGGER research_command_complete_guard ON application_command_identities")
    op.execute("DROP TABLE research_retention_cursor")
    op.execute("DROP TABLE research_owner_erasure")
    op.execute("DROP TABLE research_source_retention")
    op.execute("DROP TABLE research_command_results")
    op.execute("DROP TABLE research_review_acknowledgments")
    op.execute("DROP TABLE research_note_citations")
    op.execute("DROP TABLE research_note_payloads")
    op.execute("DROP TABLE research_note_revisions")
    op.execute("DROP TABLE research_notes")
    op.execute("DROP TABLE research_items")
    op.execute("DROP TABLE research_alias_promotions")
    op.execute("DROP TABLE research_witness_citations")
    op.execute("DROP TABLE research_publication_witnesses")
    op.execute("DROP TABLE research_event_aliases")
    op.execute("DROP TABLE research_event_citations")
    op.execute("DROP TABLE research_event_payloads")
    op.execute("DROP TABLE research_event_revisions")
    op.execute("DROP TABLE research_events")
    op.execute("DROP TABLE research_citations")
    op.execute("DROP TABLE research_source_payloads")
    op.execute("DROP TABLE research_source_versions")
    op.execute("DROP TABLE research_sources")
    op.execute("DROP TABLE research_source_origins")
    op.execute("DROP TABLE research_account_states")
    op.execute("DROP TABLE research_owner_capacity")
    op.execute("DROP FUNCTION research_immutable_guard()")
    op.execute("DROP FUNCTION research_complete_guard()")
    op.execute("DROP FUNCTION research_event_copy_guard()")
    op.execute("DROP FUNCTION research_retention_guard()")
    op.execute("DROP FUNCTION research_payload_charge()")
    op.execute("DROP FUNCTION research_scope_guard()")
    op.execute("DROP FUNCTION research_note_capacity_guard()")
    op.execute("DROP FUNCTION research_admission_guard()")
    op.execute("DROP FUNCTION research_owner_lock(UUID)")
    op.execute(
        "ALTER TABLE application_command_identities DROP CONSTRAINT ck_application_command_identities_command_allowed"
    )
    op.execute(
        "ALTER TABLE application_command_identities ADD CONSTRAINT ck_application_command_identities_command_allowed CHECK (command IN ('reports.generate.v1','reports.generate.v2','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1','projection.assumption.create.v1','projection.assumption.version.create.v1','projection.goal.create.v1','projection.goal.version.create.v1','projection.run.create.v1','projection.run.cancel.v1'))"
    )
    op.execute(
        "ALTER TABLE application_command_identities DROP CONSTRAINT ck_application_command_identities_parent_kind"
    )
    op.execute(
        "ALTER TABLE application_command_identities ADD CONSTRAINT ck_application_command_identities_parent_kind CHECK ((command IN ('reports.generate.v1','reports.generate.v2') AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1','projection.assumption.create.v1','projection.assumption.version.create.v1','projection.goal.create.v1','projection.goal.version.create.v1','projection.run.create.v1','projection.run.cancel.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL))"
    )
    op.execute(
        "ALTER TABLE collection_query_snapshots DROP CONSTRAINT ck_collection_query_snapshots_resource_allowed"
    )
    op.execute(
        "ALTER TABLE collection_query_snapshots ADD CONSTRAINT ck_collection_query_snapshots_resource_allowed CHECK (resource IN ('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','assumption_sets','assumption_versions','goals','goal_versions','projection_runs','intelligence_quality_sources','activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations'))"
    )
    op.execute(
        "ALTER TABLE collection_query_snapshots DROP CONSTRAINT ck_collection_query_snapshots_resource_sort_match"
    )
    op.execute(
        "ALTER TABLE collection_query_snapshots ADD CONSTRAINT ck_collection_query_snapshots_resource_sort_match CHECK ((resource IN ('intelligence_quality_sources','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND sort_specification = 'occurred_at_desc_id_desc') OR (resource = 'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource = 'instruments' AND sort_specification = 'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR (resource = 'positions_market_value' AND sort_specification = 'market_value_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_weight' AND sort_specification = 'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = 'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') OR (resource = 'portfolios_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'portfolios_updated' AND sort_specification = 'updated_at_desc_id_desc') OR (resource = 'target_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource = 'target_events' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'target_nodes' AND sort_specification = 'depth_first_order_key') OR (resource = 'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') OR (resource = 'contribution_plans' AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('plan_lines','actual_target_rows','plan_revisions') AND sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'benchmark_source_status' AND sort_specification = 'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND sort_specification = 'base_quote_provider_asc') OR (resource = 'price_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR (resource = 'benchmark_defs_name' AND sort_specification = 'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND sort_specification = 'created_at_desc_id_desc') OR (resource = 'benchmark_versions' AND sort_specification = 'version_number_desc_id_desc') OR (resource IN ('reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') AND sort_specification = 'created_at_desc_id_desc') OR (resource IN ('risk_definitions','risk_runs','scenario_definitions','scenario_runs','assumption_sets','goals','projection_runs') AND sort_specification='created_at_desc_id_desc') OR (resource IN ('risk_versions','scenario_versions','assumption_versions','goal_versions') AND sort_specification='version_number_desc_id_desc'))"
    )
    op.execute(
        "ALTER TABLE collection_query_snapshots DROP CONSTRAINT ck_collection_query_snapshots_account_scope_match"
    )
    op.execute(
        "ALTER TABLE collection_query_snapshots ADD CONSTRAINT ck_collection_query_snapshots_account_scope_match CHECK (((resource IN ('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','assumption_sets','assumption_versions','goals','goal_versions','projection_runs','intelligence_quality_sources','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','premium_reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND broker_account_id IS NULL) OR resource IN ('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings')))"
    )
