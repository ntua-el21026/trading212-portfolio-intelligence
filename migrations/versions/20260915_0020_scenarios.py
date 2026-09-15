"""Owned scenario definitions, sealed evidence and shared premium publication guards.

Revision ID: 20260915_0020
Revises: 20260915_0019

Frozen SQL is intentionally self-contained. Runtime integration and retention consumers
must land with this migration; this schema alone does not implement a scenario command.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0020"
down_revision = "20260915_0019"
branch_labels = None
depends_on = None

_TABLES = (
    "scenario_sensitivity_sets",
    "scenario_definitions",
    "scenario_sensitivity_evidence",
    "scenario_sensitivity_versions",
    "scenario_definition_versions",
    "scenario_sensitivity_evidence_payloads",
    "scenario_sensitivity_observations",
    "scenario_sensitivity_retention",
    "scenario_sensitivity_version_payloads",
    "scenario_exclusions",
    "scenario_sensitivity_evidence_links",
    "scenario_sensitivity_memberships",
    "scenario_sensitivity_observation_payloads",
    "scenario_shocks",
    "scenario_runs",
    "scenario_results",
    "scenario_run_payloads",
    "scenario_run_sensitivity_evidence",
    "scenario_run_sensitivity_versions",
    "scenario_components",
    "scenario_run_sensitivity_observations",
    "scenario_applied_sensitivities",
    "scenario_run_sensitivity_memberships",
)

_DDL = (
    r"""CREATE TABLE scenario_sensitivity_sets (
	provider_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_sets PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_sets_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_sets_owner_id_market_data_providers FOREIGN KEY(owner_id, provider_id) REFERENCES market_data_providers (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_set_provider UNIQUE (owner_id, provider_id, id),
	CONSTRAINT fk_scenario_sensitivity_sets_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_definitions (
	name VARCHAR(120) NOT NULL,
	revision INTEGER NOT NULL,
	archived BOOLEAN NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_definitions PRIMARY KEY (id),
	CONSTRAINT uq_scenario_definitions_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT ck_scenario_definitions_revision_bound CHECK (revision BETWEEN 1 AND 512),
	CONSTRAINT ck_scenario_definitions_name_bound CHECK (char_length(name) BETWEEN 1 AND 120),
	CONSTRAINT fk_scenario_definitions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_definitions_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_scenario_definitions_owner_account_created ON scenario_definitions (owner_id, account_id, created_at, id)",
    r"""CREATE TABLE scenario_sensitivity_evidence (
	provider_id UUID NOT NULL,
	license_version_id UUID NOT NULL,
	source_record_id UUID NOT NULL,
	content_digest VARCHAR(64) NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_evidence PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_evidence_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_evidence_owner_id_provider_lice_d13f FOREIGN KEY(owner_id, provider_id, license_version_id) REFERENCES provider_license_versions (owner_id, provider_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_scenario_sensitivity_evidence_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT uq_scenario_sensitivity_evidence_digest UNIQUE (owner_id, id, content_digest),
	CONSTRAINT fk_scenario_sensitivity_evidence_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_sensitivity_versions (
	source_set_id UUID NOT NULL,
	provider_id UUID NOT NULL,
	license_version_id UUID NOT NULL,
	content_digest VARCHAR(64) NOT NULL,
	driver_id UUID NOT NULL,
	driver_definition_version_id UUID NOT NULL,
	driver_definition_digest VARCHAR(64) NOT NULL,
	revision INTEGER NOT NULL,
	observation_count INTEGER NOT NULL,
	membership_count INTEGER NOT NULL,
	evidence_count INTEGER NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	sealed BOOLEAN NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_versions PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_versions_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_versions_owner_id_provider_lice_2af6 FOREIGN KEY(owner_id, provider_id, license_version_id) REFERENCES provider_license_versions (owner_id, provider_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_sensitivity_versions_owner_id_scenario_sens_e429 FOREIGN KEY(owner_id, provider_id, source_set_id) REFERENCES scenario_sensitivity_sets (owner_id, provider_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_versions_source_set_id UNIQUE (source_set_id, revision),
	CONSTRAINT uq_scenario_sensitivity_version_digest UNIQUE (owner_id, id, content_digest),
	CONSTRAINT ck_scenario_sensitivity_versions_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_sensitivity_versions_driver_digest_format CHECK (driver_definition_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_sensitivity_versions_identity_bounds CHECK (revision >= 1 AND expires_at > created_at),
	CONSTRAINT ck_scenario_sensitivity_versions_source_count_bound CHECK (observation_count >= 0 AND membership_count >= 0 AND evidence_count >= 0 AND observation_count + membership_count + evidence_count <= 100000),
	CONSTRAINT fk_scenario_sensitivity_versions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_scenario_sensitivity_expiry ON scenario_sensitivity_versions (expires_at, id)",
    r"""CREATE TABLE scenario_definition_versions (
	definition_id UUID NOT NULL,
	version_number INTEGER NOT NULL,
	predecessor_id UUID,
	name VARCHAR(120) NOT NULL,
	description VARCHAR(1024) NOT NULL,
	mode VARCHAR(20) NOT NULL,
	method_version VARCHAR(40) NOT NULL,
	content_digest VARCHAR(64) NOT NULL,
	shock_count INTEGER NOT NULL,
	exclusion_count INTEGER NOT NULL,
	sealed BOOLEAN NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_definition_versions PRIMARY KEY (id),
	CONSTRAINT uq_scenario_definition_versions_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_definitions_definition_id FOREIGN KEY(owner_id, account_id, definition_id) REFERENCES scenario_definitions (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_version_definition_identity UNIQUE (owner_id, account_id, definition_id, id),
	CONSTRAINT uq_scenario_version_content_identity UNIQUE (owner_id, account_id, id, content_digest),
	CONSTRAINT uq_scenario_definition_versions_definition_id UNIQUE (definition_id, version_number),
	CONSTRAINT fk_scenario_version_predecessor FOREIGN KEY(owner_id, account_id, definition_id, predecessor_id) REFERENCES scenario_definition_versions (owner_id, account_id, definition_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_scenario_definition_versions_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_definition_versions_version_order CHECK (version_number BETWEEN 1 AND 512 AND (version_number=1)=(predecessor_id IS NULL)),
	CONSTRAINT ck_scenario_definition_versions_method_allowed CHECK (mode IN ('first_order','compounded') AND method_version='1.0.0'),
	CONSTRAINT ck_scenario_definition_versions_text_bound CHECK (char_length(name) BETWEEN 1 AND 120 AND char_length(description)<=1024),
	CONSTRAINT ck_scenario_definition_versions_count_bound CHECK (shock_count BETWEEN 0 AND 128 AND exclusion_count BETWEEN 0 AND 128),
	CONSTRAINT fk_scenario_definition_versions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_definition_versions_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_scenario_versions_definition_number ON scenario_definition_versions (definition_id, version_number, id)",
    r"""CREATE TABLE scenario_sensitivity_evidence_payloads (
	evidence_id UUID NOT NULL,
	effective_at TIMESTAMP WITH TIME ZONE NOT NULL,
	first_known_at TIMESTAMP WITH TIME ZONE NOT NULL,
	adapter_id VARCHAR(120) NOT NULL,
	adapter_version VARCHAR(120) NOT NULL,
	transformation VARCHAR(40) NOT NULL,
	canonical_payload BYTEA NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_evidence_payloads PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_evidence_payloads_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_evidence_payloads_owner_id_scen_b131 FOREIGN KEY(owner_id, evidence_id) REFERENCES scenario_sensitivity_evidence (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_evidence_payloads_evidence_id UNIQUE (evidence_id),
	CONSTRAINT ck_scenario_sensitivity_evidence_payloads_transform_allowed CHECK (transformation IN ('identity_local_simple_return_v1','unsupported')),
	CONSTRAINT ck_scenario_sensitivity_evidence_payloads_adapter_bounds CHECK (char_length(adapter_id) BETWEEN 1 AND 120 AND char_length(adapter_version) BETWEEN 1 AND 120),
	CONSTRAINT ck_scenario_sensitivity_evidence_payloads_payload_bound CHECK (octet_length(canonical_payload) BETWEEN 1 AND 33554432),
	CONSTRAINT fk_scenario_sensitivity_evidence_payloads_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_sensitivity_observations (
	version_id UUID NOT NULL,
	provider_id UUID NOT NULL,
	license_version_id UUID NOT NULL,
	content_digest VARCHAR(64) NOT NULL,
	driver_id UUID NOT NULL,
	driver_definition_version_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_observations PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_observations_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_observations_owner_id_provider__9077 FOREIGN KEY(owner_id, provider_id, license_version_id) REFERENCES provider_license_versions (owner_id, provider_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_sensitivity_observations_owner_id_scenario__ecb2 FOREIGN KEY(owner_id, version_id) REFERENCES scenario_sensitivity_versions (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_observation_version UNIQUE (owner_id, version_id, id),
	CONSTRAINT uq_scenario_sensitivity_observation_digest UNIQUE (owner_id, id, content_digest),
	CONSTRAINT ck_scenario_sensitivity_observations_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT fk_scenario_sensitivity_observations_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_scenario_observations_version ON scenario_sensitivity_observations (version_id, id)",
    r"""CREATE TABLE scenario_sensitivity_retention (
	version_id UUID NOT NULL,
	reason VARCHAR(30) NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_retention PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_retention_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_retention_owner_id_scenario_sen_d8ad FOREIGN KEY(owner_id, version_id) REFERENCES scenario_sensitivity_versions (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_retention_version_id UNIQUE (version_id),
	CONSTRAINT ck_scenario_sensitivity_retention_reason_allowed CHECK (reason IN ('source_restricted','source_expired','owner_erasure')),
	CONSTRAINT ck_scenario_sensitivity_retention_completion_order CHECK (completed_at IS NULL OR completed_at >= created_at),
	CONSTRAINT fk_scenario_sensitivity_retention_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_scenario_sensitivity_retention_pending ON scenario_sensitivity_retention (completed_at, owner_id, id)",
    r"""CREATE TABLE scenario_sensitivity_version_payloads (
	version_id UUID NOT NULL,
	driver_kind VARCHAR(10) NOT NULL,
	shock_unit VARCHAR(30) NOT NULL,
	equivalence_kind VARCHAR(10) NOT NULL,
	equivalence_rate_id UUID,
	equivalence_factor_id UUID,
	equivalence_currency VARCHAR(3),
	equivalence_selector_kind VARCHAR(20),
	equivalence_instrument_id UUID,
	equivalence_entity_id UUID,
	equivalence_taxonomy_id UUID,
	equivalence_taxonomy_version VARCHAR(120),
	equivalence_bucket_key VARCHAR(120),
	equivalence_reason VARCHAR(60),
	effective_at TIMESTAMP WITH TIME ZONE NOT NULL,
	first_known_at TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_until TIMESTAMP WITH TIME ZONE,
	revision INTEGER NOT NULL,
	adapter_id VARCHAR(120) NOT NULL,
	adapter_version VARCHAR(120) NOT NULL,
	availability VARCHAR(20) NOT NULL,
	quality VARCHAR(20) NOT NULL,
	canonical_payload BYTEA NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_version_payloads PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_version_payloads_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_version_payloads_owner_id_scena_b2e1 FOREIGN KEY(owner_id, version_id) REFERENCES scenario_sensitivity_versions (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_version_payloads_version_id UNIQUE (version_id),
	CONSTRAINT fk_scenario_sensitivity_version_payloads_owner_id_econo_a487 FOREIGN KEY(owner_id, equivalence_entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_sensitivity_version_payloads_owner_id_xray__8121 FOREIGN KEY(owner_id, equivalence_taxonomy_id) REFERENCES xray_taxonomies (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_scenario_sensitivity_version_payloads_validity_order CHECK (valid_until IS NULL OR valid_until > valid_from),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_revision_positive CHECK (revision >= 1),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_driver_units CHECK (driver_kind IN ('rate','factor') AND shock_unit = CASE driver_kind WHEN 'rate' THEN 'absolute_rate_change' ELSE 'simple_factor_return' END),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_equivalence_identity CHECK ((equivalence_kind='rate' AND equivalence_rate_id IS NOT NULL AND equivalence_factor_id IS NULL AND equivalence_currency IS NOT NULL AND equivalence_selector_kind IS NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AND equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND equivalence_bucket_key IS NULL AND equivalence_reason IS NULL) OR (equivalence_kind='factor' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS NOT NULL AND equivalence_currency IS NULL AND equivalence_selector_kind IS NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AND equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND equivalence_bucket_key IS NULL AND equivalence_reason IS NULL) OR (equivalence_kind='fx' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS NULL AND equivalence_currency IS NOT NULL AND equivalence_selector_kind IS NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AND equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND equivalence_bucket_key IS NULL AND equivalence_reason IS NULL) OR (equivalence_kind='unknown' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS NULL AND equivalence_currency IS NULL AND equivalence_selector_kind IS NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AND equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND equivalence_bucket_key IS NULL AND equivalence_reason IS NOT NULL) OR (equivalence_kind='price' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS NULL AND equivalence_currency IS NULL AND equivalence_selector_kind IS NOT NULL AND equivalence_instrument_id IS NOT NULL AND equivalence_entity_id IS NULL AND equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND equivalence_bucket_key IS NULL AND equivalence_reason IS NULL AND equivalence_selector_kind='instrument') OR (equivalence_kind='price' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS NULL AND equivalence_currency IS NULL AND equivalence_selector_kind IS NOT NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NOT NULL AND equivalence_taxonomy_id IS NULL AND equivalence_taxonomy_version IS NULL AND equivalence_bucket_key IS NULL AND equivalence_reason IS NULL AND equivalence_selector_kind='entity') OR (equivalence_kind='price' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS NULL AND equivalence_currency IS NULL AND equivalence_selector_kind IS NOT NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AND equivalence_taxonomy_id IS NOT NULL AND equivalence_taxonomy_version IS NOT NULL AND equivalence_bucket_key IS NOT NULL AND equivalence_reason IS NULL AND equivalence_selector_kind='sector') OR (equivalence_kind='price' AND equivalence_rate_id IS NULL AND equivalence_factor_id IS NULL AND equivalence_currency IS NULL AND equivalence_selector_kind IS NOT NULL AND equivalence_instrument_id IS NULL AND equivalence_entity_id IS NULL AND equivalence_taxonomy_id IS NOT NULL AND equivalence_taxonomy_version IS NOT NULL AND equivalence_bucket_key IS NOT NULL AND equivalence_reason IS NULL AND equivalence_selector_kind='region')),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_eq_reason_allowed CHECK (equivalence_reason IS NULL OR equivalence_reason IN ('missing_value','missing_identity','ambiguous_identity','missing_classification','ambiguous_classification','incompatible_taxonomy','missing_economic_currency','unsupported_economic_currency','uncertain_exclusion','uncertain_price_priority','missing_sensitivity','ambiguous_sensitivity','unsupported_sensitivity','incompatible_sensitivity_currency','unknown_driver_equivalence','missing_replay_mapping','missing_replay_source','fx_decomposition_unavailable','historical_holdings_unavailable','incompatible_basis','uncertain_money','zero_denominator')),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_eq_currency_format CHECK (equivalence_currency IS NULL OR equivalence_currency ~ '^[A-Z]{3}$'),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_availability_allowed CHECK (availability IN ('available','partial','unavailable','failed')),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_quality_allowed CHECK (quality IN ('fresh','stale','partial','estimated','unreconciled','failed')),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_adapter_bounds CHECK (char_length(adapter_id) BETWEEN 1 AND 120 AND char_length(adapter_version) BETWEEN 1 AND 120),
	CONSTRAINT ck_scenario_sensitivity_version_payloads_payload_bound CHECK (octet_length(canonical_payload) BETWEEN 1 AND 33554432),
	CONSTRAINT fk_scenario_sensitivity_version_payloads_equivalence_in_6921 FOREIGN KEY(equivalence_instrument_id) REFERENCES instruments (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_sensitivity_version_payloads_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_exclusions (
	selector_kind VARCHAR(20) NOT NULL,
	version_id UUID NOT NULL,
	rule_key VARCHAR(80) NOT NULL,
	instrument_id UUID,
	entity_id UUID,
	taxonomy_id UUID,
	taxonomy_version VARCHAR(120),
	bucket_key VARCHAR(120),
	currency VARCHAR(3),
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_exclusions PRIMARY KEY (id),
	CONSTRAINT uq_scenario_exclusions_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_definition_versions_version_id FOREIGN KEY(owner_id, account_id, version_id) REFERENCES scenario_definition_versions (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_exclusions_owner_id_economic_entities FOREIGN KEY(owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_exclusions_owner_id_xray_taxonomies FOREIGN KEY(owner_id, taxonomy_id) REFERENCES xray_taxonomies (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_exclusions_version_id UNIQUE (version_id, rule_key),
	CONSTRAINT ck_scenario_exclusions_rule_key_format CHECK (rule_key ~ '^exclusion:[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_exclusions_selector_identity CHECK ((selector_kind='instrument' AND instrument_id IS NOT NULL AND entity_id IS NULL AND taxonomy_id IS NULL AND taxonomy_version IS NULL AND bucket_key IS NULL AND currency IS NULL) OR (selector_kind='entity' AND instrument_id IS NULL AND entity_id IS NOT NULL AND taxonomy_id IS NULL AND taxonomy_version IS NULL AND bucket_key IS NULL AND currency IS NULL) OR (selector_kind='sector' AND instrument_id IS NULL AND entity_id IS NULL AND taxonomy_id IS NOT NULL AND taxonomy_version IS NOT NULL AND bucket_key IS NOT NULL AND currency IS NULL) OR (selector_kind='region' AND instrument_id IS NULL AND entity_id IS NULL AND taxonomy_id IS NOT NULL AND taxonomy_version IS NOT NULL AND bucket_key IS NOT NULL AND currency IS NULL) OR (selector_kind='economic_currency' AND instrument_id IS NULL AND entity_id IS NULL AND taxonomy_id IS NULL AND taxonomy_version IS NULL AND bucket_key IS NULL AND currency IS NOT NULL)),
	CONSTRAINT ck_scenario_exclusions_currency_format CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
	CONSTRAINT uq_scenario_exclusion_selector UNIQUE NULLS NOT DISTINCT (version_id, selector_kind, instrument_id, entity_id, taxonomy_id, taxonomy_version, bucket_key, currency),
	CONSTRAINT fk_scenario_exclusions_instrument_id_instruments FOREIGN KEY(instrument_id) REFERENCES instruments (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_exclusions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_exclusions_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_sensitivity_evidence_links (
	version_id UUID NOT NULL,
	observation_id UUID,
	evidence_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_evidence_links PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_evidence_links_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_evidence_links_owner_id_scenari_36fb FOREIGN KEY(owner_id, version_id) REFERENCES scenario_sensitivity_versions (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_sensitivity_evidence_links_owner_id_scenari_2eda FOREIGN KEY(owner_id, evidence_id) REFERENCES scenario_sensitivity_evidence (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_sensitivity_evidence_links_owner_id_scenari_cddf FOREIGN KEY(owner_id, version_id, observation_id) REFERENCES scenario_sensitivity_observations (owner_id, version_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_evidence_links_version_id UNIQUE NULLS NOT DISTINCT (version_id, observation_id, evidence_id),
	CONSTRAINT fk_scenario_sensitivity_evidence_links_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_scenario_evidence_links_evidence ON scenario_sensitivity_evidence_links (evidence_id, version_id)",
    r"""CREATE TABLE scenario_sensitivity_memberships (
	version_id UUID NOT NULL,
	version_digest VARCHAR(64) NOT NULL,
	observation_id UUID NOT NULL,
	observation_digest VARCHAR(64) NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_memberships PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_memberships_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_memberships_owner_id_scenario_s_efb7 FOREIGN KEY(owner_id, version_id, version_digest) REFERENCES scenario_sensitivity_versions (owner_id, id, content_digest) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_membership_observation_version FOREIGN KEY(owner_id, version_id, observation_id) REFERENCES scenario_sensitivity_observations (owner_id, version_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_membership_observation_digest FOREIGN KEY(owner_id, observation_id, observation_digest) REFERENCES scenario_sensitivity_observations (owner_id, id, content_digest) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_memberships_version_id UNIQUE (version_id, observation_id),
	CONSTRAINT fk_scenario_sensitivity_memberships_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_sensitivity_observation_payloads (
	observation_id UUID NOT NULL,
	subject_kind VARCHAR(12) NOT NULL,
	instrument_id UUID,
	entity_id UUID,
	coefficient NUMERIC(38, 18),
	shock_unit VARCHAR(30) NOT NULL,
	response_unit VARCHAR(30) NOT NULL,
	response_basis VARCHAR(30) NOT NULL,
	response_currency VARCHAR(3),
	effective_at TIMESTAMP WITH TIME ZONE NOT NULL,
	first_known_at TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_from TIMESTAMP WITH TIME ZONE NOT NULL,
	valid_until TIMESTAMP WITH TIME ZONE,
	revision INTEGER NOT NULL,
	state VARCHAR(20) NOT NULL,
	quality VARCHAR(20) NOT NULL,
	confidence NUMERIC(38, 18),
	reason VARCHAR(60),
	canonical_payload BYTEA NOT NULL,
	owner_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_sensitivity_observation_payloads PRIMARY KEY (id),
	CONSTRAINT uq_scenario_sensitivity_observation_payloads_owner_id UNIQUE (owner_id, id),
	CONSTRAINT fk_scenario_sensitivity_observation_payloads_owner_id_s_5e9f FOREIGN KEY(owner_id, observation_id) REFERENCES scenario_sensitivity_observations (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_sensitivity_observation_payloads_owner_id_e_a94f FOREIGN KEY(owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_sensitivity_observation_payloads_observation_id UNIQUE (observation_id),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_validity_order CHECK (valid_until IS NULL OR valid_until > valid_from),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_revision_positive CHECK (revision >= 1),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_subject_identity CHECK ((subject_kind='instrument' AND instrument_id IS NOT NULL AND entity_id IS NULL) OR (subject_kind='entity' AND entity_id IS NOT NULL AND instrument_id IS NULL)),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_state_allowed CHECK (state IN ('available','missing','unsupported','disputed')),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_coeff_availability CHECK ((state='available') = (coefficient IS NOT NULL) AND (coefficient IS NULL) = (reason IS NOT NULL) AND (state<>'available' OR (response_basis='local_economic_value' AND response_currency IS NOT NULL))),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_coefficient_finite CHECK (coefficient IS NULL OR (coefficient > '-Infinity'::numeric AND coefficient < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_confidence_finite CHECK (confidence IS NULL OR (confidence > '-Infinity'::numeric AND confidence < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_reason_allowed CHECK (reason IS NULL OR reason IN ('missing_value','missing_identity','ambiguous_identity','missing_classification','ambiguous_classification','incompatible_taxonomy','missing_economic_currency','unsupported_economic_currency','uncertain_exclusion','uncertain_price_priority','missing_sensitivity','ambiguous_sensitivity','unsupported_sensitivity','incompatible_sensitivity_currency','unknown_driver_equivalence','missing_replay_mapping','missing_replay_source','fx_decomposition_unavailable','historical_holdings_unavailable','incompatible_basis','uncertain_money','zero_denominator')),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_coefficient_bound CHECK (coefficient IS NULL OR coefficient BETWEEN -100 AND 100),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_confidence_bound CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_units_allowed CHECK (shock_unit IN ('absolute_rate_change','simple_factor_return') AND response_unit='local_value_simple_return'),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_response_basis CHECK (response_basis IN ('local_economic_value','fx_inclusive','unknown') AND (response_currency IS NULL OR response_currency ~ '^[A-Z]{3}$')),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_quality_allowed CHECK (quality IN ('fresh','stale','partial','estimated','unreconciled','failed')),
	CONSTRAINT ck_scenario_sensitivity_observation_payloads_payload_bound CHECK (octet_length(canonical_payload) BETWEEN 1 AND 33554432),
	CONSTRAINT fk_scenario_sensitivity_observation_payloads_instrument_2f5d FOREIGN KEY(instrument_id) REFERENCES instruments (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_sensitivity_observation_payloads_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_shocks (
	version_id UUID NOT NULL,
	rule_key VARCHAR(80) NOT NULL,
	kind VARCHAR(10) NOT NULL,
	size NUMERIC(38, 18) NOT NULL,
	shock_currency VARCHAR(3),
	source_version_id UUID,
	source_version_digest VARCHAR(64),
	driver_id UUID,
	driver_definition_version_id UUID,
	selector_kind VARCHAR(20),
	instrument_id UUID,
	entity_id UUID,
	taxonomy_id UUID,
	taxonomy_version VARCHAR(120),
	bucket_key VARCHAR(120),
	currency VARCHAR(3),
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_shocks PRIMARY KEY (id),
	CONSTRAINT uq_scenario_shocks_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_definition_versions_version_id FOREIGN KEY(owner_id, account_id, version_id) REFERENCES scenario_definition_versions (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_shocks_owner_id_economic_entities FOREIGN KEY(owner_id, entity_id) REFERENCES economic_entities (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_shocks_owner_id_xray_taxonomies FOREIGN KEY(owner_id, taxonomy_id) REFERENCES xray_taxonomies (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_shocks_owner_id_scenario_sensitivity_versions FOREIGN KEY(owner_id, source_version_id, source_version_digest) REFERENCES scenario_sensitivity_versions (owner_id, id, content_digest) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_shocks_version_id UNIQUE (version_id, rule_key),
	CONSTRAINT ck_scenario_shocks_rule_key_format CHECK (rule_key ~ '^shock:[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_shocks_selector_identity CHECK ((selector_kind='instrument' AND instrument_id IS NOT NULL AND entity_id IS NULL AND taxonomy_id IS NULL AND taxonomy_version IS NULL AND bucket_key IS NULL AND currency IS NULL) OR (selector_kind='entity' AND instrument_id IS NULL AND entity_id IS NOT NULL AND taxonomy_id IS NULL AND taxonomy_version IS NULL AND bucket_key IS NULL AND currency IS NULL) OR (selector_kind='sector' AND instrument_id IS NULL AND entity_id IS NULL AND taxonomy_id IS NOT NULL AND taxonomy_version IS NOT NULL AND bucket_key IS NOT NULL AND currency IS NULL) OR (selector_kind='region' AND instrument_id IS NULL AND entity_id IS NULL AND taxonomy_id IS NOT NULL AND taxonomy_version IS NOT NULL AND bucket_key IS NOT NULL AND currency IS NULL) OR (selector_kind IS NULL AND instrument_id IS NULL AND entity_id IS NULL AND taxonomy_id IS NULL AND taxonomy_version IS NULL AND bucket_key IS NULL AND currency IS NULL)),
	CONSTRAINT ck_scenario_shocks_size_finite CHECK (size IS NULL OR (size > '-Infinity'::numeric AND size < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_shocks_shock_identity CHECK ((kind='price' AND selector_kind IS NOT NULL AND shock_currency IS NULL AND source_version_id IS NULL AND source_version_digest IS NULL AND driver_id IS NULL AND driver_definition_version_id IS NULL) OR (kind='fx' AND selector_kind IS NULL AND shock_currency IS NOT NULL AND source_version_id IS NULL AND source_version_digest IS NULL AND driver_id IS NULL AND driver_definition_version_id IS NULL) OR (kind IN ('rate','factor') AND selector_kind IS NULL AND shock_currency IS NULL AND source_version_id IS NOT NULL AND source_version_digest IS NOT NULL AND driver_id IS NOT NULL AND driver_definition_version_id IS NOT NULL)),
	CONSTRAINT ck_scenario_shocks_size_bound CHECK (size >= -1 AND size <= CASE WHEN kind IN ('price','fx') THEN 5 ELSE 1 END),
	CONSTRAINT ck_scenario_shocks_currency_format CHECK (shock_currency IS NULL OR shock_currency ~ '^[A-Z]{3}$'),
	CONSTRAINT uq_scenario_shock_selector UNIQUE NULLS NOT DISTINCT (version_id, kind, selector_kind, instrument_id, entity_id, taxonomy_id, taxonomy_version, bucket_key, currency, shock_currency, driver_id),
	CONSTRAINT fk_scenario_shocks_instrument_id_instruments FOREIGN KEY(instrument_id) REFERENCES instruments (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_shocks_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_shocks_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_scenario_shocks_source_version ON scenario_shocks (source_version_id, version_id)",
    "CREATE UNIQUE INDEX uq_scenario_shock_driver ON scenario_shocks (version_id, driver_id) WHERE driver_id IS NOT NULL",
    r"""CREATE TABLE scenario_runs (
	definition_version_id UUID NOT NULL,
	definition_digest VARCHAR(64) NOT NULL,
	portfolio_snapshot_id UUID NOT NULL,
	portfolio_snapshot_digest VARCHAR(64) NOT NULL,
	xray_run_id UUID NOT NULL,
	xray_input_id UUID NOT NULL,
	xray_input_digest VARCHAR(64) NOT NULL,
	xray_result_digest VARCHAR(64) NOT NULL,
	reporting_currency VARCHAR(3) NOT NULL,
	source_cutoff_at TIMESTAMP WITH TIME ZONE NOT NULL,
	historical_input_id UUID,
	historical_input_digest VARCHAR(64),
	replay_start_date DATE,
	replay_end_date DATE,
	market_knowledge_cutoff_at TIMESTAMP WITH TIME ZONE,
	holdings_basis VARCHAR(20),
	knowledge_basis VARCHAR(20),
	sensitivity_version_count INTEGER NOT NULL,
	sensitivity_observation_count INTEGER NOT NULL,
	sensitivity_membership_count INTEGER NOT NULL,
	sensitivity_evidence_count INTEGER NOT NULL,
	sealed BOOLEAN NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_runs PRIMARY KEY (id),
	CONSTRAINT uq_scenario_runs_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_premium_runs_id FOREIGN KEY(owner_id, account_id, id) REFERENCES premium_runs (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_definition_digest FOREIGN KEY(owner_id, account_id, definition_version_id, definition_digest) REFERENCES scenario_definition_versions (owner_id, account_id, id, content_digest) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_runs_owner_id_xray_runs FOREIGN KEY(owner_id, xray_run_id) REFERENCES xray_runs (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_runs_owner_id_xray_input_snapshots FOREIGN KEY(owner_id, xray_input_id) REFERENCES xray_input_snapshots (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_runs_owner_id_historical_input_snapshots FOREIGN KEY(owner_id, historical_input_id) REFERENCES historical_input_snapshots (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT ck_scenario_runs_definition_digest_format CHECK (definition_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_runs_portfolio_snapshot_digest_format CHECK (portfolio_snapshot_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_runs_xray_input_digest_format CHECK (xray_input_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_runs_xray_result_digest_format CHECK (xray_result_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_runs_history_digest_format CHECK (historical_input_digest IS NULL OR historical_input_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_runs_currency_format CHECK (reporting_currency ~ '^[A-Z]{3}$'),
	CONSTRAINT ck_scenario_runs_replay_identity CHECK ((historical_input_id IS NULL AND historical_input_digest IS NULL AND replay_start_date IS NULL AND replay_end_date IS NULL AND market_knowledge_cutoff_at IS NULL AND holdings_basis IS NULL AND knowledge_basis IS NULL) OR (historical_input_id IS NOT NULL AND historical_input_digest IS NOT NULL AND replay_start_date IS NOT NULL AND replay_end_date IS NOT NULL AND replay_start_date < replay_end_date AND market_knowledge_cutoff_at IS NOT NULL AND holdings_basis IN ('current_holdings','historical_holdings') AND knowledge_basis IN ('point_in_time','retrospective'))),
	CONSTRAINT ck_scenario_runs_source_count_bound CHECK (sensitivity_version_count BETWEEN 0 AND 128 AND sensitivity_observation_count >= 0 AND sensitivity_membership_count >= 0 AND sensitivity_evidence_count >= 0 AND sensitivity_observation_count+sensitivity_membership_count+sensitivity_evidence_count <= 100000),
	CONSTRAINT ck_scenario_runs_replay_basis_present CHECK (historical_input_id IS NULL OR (holdings_basis IS NOT NULL AND knowledge_basis IS NOT NULL)),
	CONSTRAINT fk_scenario_runs_portfolio_snapshot_id_portfolio_snapshots FOREIGN KEY(portfolio_snapshot_id) REFERENCES portfolio_snapshots (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_runs_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_runs_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    "CREATE INDEX ix_scenario_runs_historical ON scenario_runs (historical_input_id, id)",
    "CREATE INDEX ix_scenario_runs_xray ON scenario_runs (xray_run_id, id)",
    r"""CREATE TABLE scenario_results (
	run_id UUID NOT NULL,
	content_digest VARCHAR(64) NOT NULL,
	canonical_result BYTEA NOT NULL,
	component_count INTEGER NOT NULL,
	sensitivity_source_row_count INTEGER NOT NULL,
	applied_use_count INTEGER NOT NULL,
	sealed BOOLEAN NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_results PRIMARY KEY (id),
	CONSTRAINT uq_scenario_results_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_runs_run_id FOREIGN KEY(owner_id, account_id, run_id) REFERENCES scenario_runs (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_results_run_id UNIQUE (run_id),
	CONSTRAINT ck_scenario_results_content_digest_format CHECK (content_digest ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_results_payload_bound CHECK (octet_length(canonical_result)<=33554432),
	CONSTRAINT ck_scenario_results_count_bound CHECK (component_count BETWEEN 0 AND 10000 AND sensitivity_source_row_count >= 0 AND applied_use_count >= 0 AND sensitivity_source_row_count+applied_use_count <= 100000),
	CONSTRAINT fk_scenario_results_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_results_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_run_payloads (
	run_id UUID NOT NULL,
	canonical_input BYTEA NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_run_payloads PRIMARY KEY (id),
	CONSTRAINT uq_scenario_run_payloads_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_runs_run_id FOREIGN KEY(owner_id, account_id, run_id) REFERENCES scenario_runs (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_run_payloads_run_id UNIQUE (run_id),
	CONSTRAINT ck_scenario_run_payloads_payload_bound CHECK (octet_length(canonical_input) BETWEEN 1 AND 33554432),
	CONSTRAINT fk_scenario_run_payloads_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_payloads_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_run_sensitivity_evidence (
	run_id UUID NOT NULL,
	evidence_id UUID NOT NULL,
	content_digest VARCHAR(64) NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_run_sensitivity_evidence PRIMARY KEY (id),
	CONSTRAINT uq_scenario_run_sensitivity_evidence_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_runs_run_id FOREIGN KEY(owner_id, account_id, run_id) REFERENCES scenario_runs (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_sensitivity_evidence_owner_id_scenario__745a FOREIGN KEY(owner_id, evidence_id, content_digest) REFERENCES scenario_sensitivity_evidence (owner_id, id, content_digest) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_run_sensitivity_evidence_run_id UNIQUE (run_id, evidence_id),
	CONSTRAINT fk_scenario_run_sensitivity_evidence_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_sensitivity_evidence_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_run_sensitivity_versions (
	run_id UUID NOT NULL,
	version_id UUID NOT NULL,
	content_digest VARCHAR(64) NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_run_sensitivity_versions PRIMARY KEY (id),
	CONSTRAINT uq_scenario_run_sensitivity_versions_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_runs_run_id FOREIGN KEY(owner_id, account_id, run_id) REFERENCES scenario_runs (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_sensitivity_versions_owner_id_scenario__e929 FOREIGN KEY(owner_id, version_id, content_digest) REFERENCES scenario_sensitivity_versions (owner_id, id, content_digest) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_run_sensitivity_versions_run_id UNIQUE (run_id, version_id),
	CONSTRAINT uq_scenario_run_source_version UNIQUE (owner_id, account_id, run_id, version_id),
	CONSTRAINT fk_scenario_run_sensitivity_versions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_sensitivity_versions_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_components (
	result_id UUID NOT NULL,
	path_key VARCHAR(1024) NOT NULL,
	root_key VARCHAR(1024) NOT NULL,
	root_kind VARCHAR(10) NOT NULL,
	position_id UUID,
	snapshot_cash_id UUID,
	root_instrument_id UUID,
	partition VARCHAR(20) NOT NULL,
	money_basis VARCHAR(30) NOT NULL,
	currency VARCHAR(3) NOT NULL,
	pre_value NUMERIC(38, 18),
	post_value NUMERIC(38, 18),
	impact NUMERIC(38, 18),
	rounding_residual NUMERIC(38, 18),
	quality VARCHAR(20) NOT NULL,
	reason VARCHAR(60),
	applied_use_count INTEGER NOT NULL,
	canonical_component BYTEA NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_components PRIMARY KEY (id),
	CONSTRAINT uq_scenario_components_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_results_result_id FOREIGN KEY(owner_id, account_id, result_id) REFERENCES scenario_results (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_components_result_id UNIQUE (result_id, path_key),
	CONSTRAINT ck_scenario_components_path_bounds CHECK (char_length(path_key) BETWEEN 1 AND 1024 AND char_length(root_key) BETWEEN 1 AND 1024),
	CONSTRAINT ck_scenario_components_root_identity CHECK ((root_kind='position' AND position_id IS NOT NULL AND snapshot_cash_id IS NULL AND root_instrument_id IS NOT NULL) OR (root_kind='cash' AND position_id IS NULL AND snapshot_cash_id IS NOT NULL AND root_instrument_id IS NULL)),
	CONSTRAINT uq_scenario_component_result_identity UNIQUE (owner_id, account_id, result_id, id),
	CONSTRAINT ck_scenario_components_coverage_allowed CHECK (partition IN ('covered','uncovered','excluded') AND money_basis IN ('resolved','zero_pre_value','provably_zero_effect','unavailable')),
	CONSTRAINT ck_scenario_components_currency_format CHECK (currency ~ '^[A-Z]{3}$'),
	CONSTRAINT ck_scenario_components_quality_allowed CHECK (quality IN ('fresh','stale','partial','estimated','unreconciled','failed')),
	CONSTRAINT ck_scenario_components_monetary_availability CHECK ((post_value IS NULL)=(reason IS NOT NULL) AND (post_value IS NULL)=(impact IS NULL)),
	CONSTRAINT ck_scenario_components_pre_value_finite CHECK (pre_value IS NULL OR (pre_value > '-Infinity'::numeric AND pre_value < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_components_post_value_finite CHECK (post_value IS NULL OR (post_value > '-Infinity'::numeric AND post_value < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_components_impact_finite CHECK (impact IS NULL OR (impact > '-Infinity'::numeric AND impact < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_components_rounding_residual_finite CHECK (rounding_residual IS NULL OR (rounding_residual > '-Infinity'::numeric AND rounding_residual < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_components_reason_allowed CHECK (reason IS NULL OR reason IN ('missing_value','missing_identity','ambiguous_identity','missing_classification','ambiguous_classification','incompatible_taxonomy','missing_economic_currency','unsupported_economic_currency','uncertain_exclusion','uncertain_price_priority','missing_sensitivity','ambiguous_sensitivity','unsupported_sensitivity','incompatible_sensitivity_currency','unknown_driver_equivalence','missing_replay_mapping','missing_replay_source','fx_decomposition_unavailable','historical_holdings_unavailable','incompatible_basis','uncertain_money','zero_denominator')),
	CONSTRAINT ck_scenario_components_payload_bound CHECK (octet_length(canonical_component) BETWEEN 1 AND 33554432),
	CONSTRAINT ck_scenario_components_use_count_bound CHECK (applied_use_count BETWEEN 0 AND 128),
	CONSTRAINT fk_scenario_components_position_id_snapshot_positions FOREIGN KEY(position_id) REFERENCES snapshot_positions (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_components_snapshot_cash_id_snapshot_cash FOREIGN KEY(snapshot_cash_id) REFERENCES snapshot_cash (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_components_root_instrument_id_instruments FOREIGN KEY(root_instrument_id) REFERENCES instruments (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_components_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_components_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_run_sensitivity_observations (
	run_id UUID NOT NULL,
	version_id UUID NOT NULL,
	observation_id UUID NOT NULL,
	content_digest VARCHAR(64) NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_run_sensitivity_observations PRIMARY KEY (id),
	CONSTRAINT uq_scenario_run_sensitivity_observations_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_runs_run_id FOREIGN KEY(owner_id, account_id, run_id) REFERENCES scenario_runs (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_observation_version FOREIGN KEY(owner_id, account_id, run_id, version_id) REFERENCES scenario_run_sensitivity_versions (owner_id, account_id, run_id, version_id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_capture_observation_version FOREIGN KEY(owner_id, version_id, observation_id) REFERENCES scenario_sensitivity_observations (owner_id, version_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_capture_observation_digest FOREIGN KEY(owner_id, observation_id, content_digest) REFERENCES scenario_sensitivity_observations (owner_id, id, content_digest) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_run_sensitivity_observations_run_id UNIQUE (run_id, observation_id),
	CONSTRAINT uq_scenario_run_source_observation UNIQUE (owner_id, account_id, run_id, version_id, observation_id),
	CONSTRAINT fk_scenario_run_sensitivity_observations_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_sensitivity_observations_account_id_bro_bc7a FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_applied_sensitivities (
	result_id UUID NOT NULL,
	component_id UUID NOT NULL,
	rule_key VARCHAR(80) NOT NULL,
	version_id UUID NOT NULL,
	driver_id UUID NOT NULL,
	driver_definition_version_id UUID NOT NULL,
	candidate_observation_ids UUID[] NOT NULL,
	observation_id UUID,
	coefficient NUMERIC(38, 18),
	shock_size NUMERIC(38, 18) NOT NULL,
	effect_ratio NUMERIC(38, 18),
	effect_reason VARCHAR(60),
	effect_quality VARCHAR(20) NOT NULL,
	reason VARCHAR(60),
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_applied_sensitivities PRIMARY KEY (id),
	CONSTRAINT uq_scenario_applied_sensitivities_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_results_result_id FOREIGN KEY(owner_id, account_id, result_id) REFERENCES scenario_results (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_applied_component FOREIGN KEY(owner_id, account_id, result_id, component_id) REFERENCES scenario_components (owner_id, account_id, result_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_applied_sensitivities_owner_id_scenario_sen_457c FOREIGN KEY(owner_id, version_id) REFERENCES scenario_sensitivity_versions (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_applied_sensitivities_owner_id_scenario_sen_9684 FOREIGN KEY(owner_id, observation_id) REFERENCES scenario_sensitivity_observations (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_applied_sensitivities_component_id UNIQUE (component_id, rule_key),
	CONSTRAINT ck_scenario_applied_sensitivities_rule_key_format CHECK (rule_key ~ '^shock:[0-9a-f]{64}$'),
	CONSTRAINT ck_scenario_applied_sensitivities_candidates_bound CHECK (cardinality(candidate_observation_ids)<=100000 AND array_position(candidate_observation_ids,NULL) IS NULL),
	CONSTRAINT ck_scenario_applied_sensitivities_coefficient_finite CHECK (coefficient IS NULL OR (coefficient > '-Infinity'::numeric AND coefficient < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_applied_sensitivities_shock_size_finite CHECK (shock_size IS NULL OR (shock_size > '-Infinity'::numeric AND shock_size < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_applied_sensitivities_effect_ratio_finite CHECK (effect_ratio IS NULL OR (effect_ratio > '-Infinity'::numeric AND effect_ratio < 'Infinity'::numeric)),
	CONSTRAINT ck_scenario_applied_sensitivities_reason_allowed CHECK (reason IS NULL OR reason IN ('missing_value','missing_identity','ambiguous_identity','missing_classification','ambiguous_classification','incompatible_taxonomy','missing_economic_currency','unsupported_economic_currency','uncertain_exclusion','uncertain_price_priority','missing_sensitivity','ambiguous_sensitivity','unsupported_sensitivity','incompatible_sensitivity_currency','unknown_driver_equivalence','missing_replay_mapping','missing_replay_source','fx_decomposition_unavailable','historical_holdings_unavailable','incompatible_basis','uncertain_money','zero_denominator')),
	CONSTRAINT ck_scenario_applied_sensitivities_coefficient_bound CHECK (coefficient IS NULL OR coefficient BETWEEN -100 AND 100),
	CONSTRAINT ck_scenario_applied_sensitivities_shock_bound CHECK (shock_size BETWEEN -1 AND 1),
	CONSTRAINT ck_scenario_applied_sensitivities_availability CHECK ((reason IS NOT NULL OR (observation_id IS NOT NULL AND coefficient IS NOT NULL)) AND (effect_ratio IS NULL)=(effect_reason IS NOT NULL)),
	CONSTRAINT ck_scenario_applied_sensitivities_coeff_observation_required CHECK (coefficient IS NULL OR observation_id IS NOT NULL),
	CONSTRAINT ck_scenario_applied_sensitivities_effect_reason_allowed CHECK (effect_reason IS NULL OR effect_reason IN ('missing_value','missing_identity','ambiguous_identity','missing_classification','ambiguous_classification','incompatible_taxonomy','missing_economic_currency','unsupported_economic_currency','uncertain_exclusion','uncertain_price_priority','missing_sensitivity','ambiguous_sensitivity','unsupported_sensitivity','incompatible_sensitivity_currency','unknown_driver_equivalence','missing_replay_mapping','missing_replay_source','fx_decomposition_unavailable','historical_holdings_unavailable','incompatible_basis','uncertain_money','zero_denominator')),
	CONSTRAINT ck_scenario_applied_sensitivities_effect_quality_allowed CHECK (effect_quality IN ('fresh','stale','partial','estimated','unreconciled','failed')),
	CONSTRAINT fk_scenario_applied_sensitivities_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_applied_sensitivities_account_id_broker_accounts FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
    r"""CREATE TABLE scenario_run_sensitivity_memberships (
	run_id UUID NOT NULL,
	version_id UUID NOT NULL,
	observation_id UUID NOT NULL,
	membership_id UUID NOT NULL,
	owner_id UUID NOT NULL,
	account_id UUID NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_scenario_run_sensitivity_memberships PRIMARY KEY (id),
	CONSTRAINT uq_scenario_run_sensitivity_memberships_owner_id UNIQUE (owner_id, account_id, id),
	CONSTRAINT fk_premium_scenario_runs_run_id FOREIGN KEY(owner_id, account_id, run_id) REFERENCES scenario_runs (owner_id, account_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_sensitivity_memberships_owner_id_scenar_29b6 FOREIGN KEY(owner_id, membership_id) REFERENCES scenario_sensitivity_memberships (owner_id, id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_membership_observation FOREIGN KEY(owner_id, account_id, run_id, version_id, observation_id) REFERENCES scenario_run_sensitivity_observations (owner_id, account_id, run_id, version_id, observation_id) ON DELETE RESTRICT,
	CONSTRAINT uq_scenario_capture_membership UNIQUE (run_id, membership_id),
	CONSTRAINT uq_scenario_capture_membership_observation UNIQUE (run_id, version_id, observation_id),
	CONSTRAINT fk_scenario_run_sensitivity_memberships_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id) ON DELETE RESTRICT,
	CONSTRAINT fk_scenario_run_sensitivity_memberships_account_id_brok_b836 FOREIGN KEY(account_id) REFERENCES broker_accounts (id) ON DELETE RESTRICT
)""",
)

_PREVIOUS_COMMAND_CHECKS = {
    "command_allowed": "command IN ('reports.generate.v1','reports.generate.v2','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1')",
    "parent_kind": "(command IN ('reports.generate.v1','reports.generate.v2') AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL)",
}

_COMMAND_CHECKS = {
    "command_allowed": "command IN ('reports.generate.v1','reports.generate.v2','exports.generate.v1','risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1')",
    "parent_kind": "(command IN ('reports.generate.v1','reports.generate.v2') AND report_job_id IS NOT NULL AND export_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command='exports.generate.v1' AND export_job_id IS NOT NULL AND report_job_id IS NULL AND premium_resource_id IS NULL AND premium_actor_id IS NULL AND premium_correlation_id IS NULL) OR (command IN ('risk.definition.create.v1','risk.version.create.v1','risk.run.create.v1','risk.run.cancel.v1','scenario.definition.create.v1','scenario.version.create.v1','scenario.run.create.v1','scenario.run.cancel.v1') AND report_job_id IS NULL AND export_job_id IS NULL AND premium_resource_id IS NOT NULL AND premium_actor_id IS NOT NULL AND premium_correlation_id IS NOT NULL)",
}

_PREVIOUS_SHARED_GUARDS = r"""
CREATE OR REPLACE FUNCTION premium_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; pinned boolean; version integer; family text; snapshot uuid; cutoff timestamptz;
BEGIN
 IF TG_TABLE_NAME='application_command_identities' THEN
  IF NEW.command NOT LIKE 'risk.%' THEN RETURN NEW; END IF;
 END IF;
 SELECT c.owner_id INTO actual FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=NEW.account_id;
 IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium account scope mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT owner_id INTO actual FROM principals WHERE id=NEW.actor_principal_id;
  IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium principal scope mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT premium_resource_id INTO actual FROM application_command_identities WHERE id=NEW.command_id AND command='risk.run.create.v1' AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF actual IS DISTINCT FROM NEW.id THEN RAISE EXCEPTION 'Premium run command mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='risk_definition_versions' AND TG_OP='INSERT' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND OR (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)>=512 THEN RAISE EXCEPTION 'Premium version capacity unavailable' USING ERRCODE='23514'; END IF;
  SELECT revision INTO version FROM risk_definitions WHERE id=NEW.definition_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF version IS DISTINCT FROM NEW.version_number THEN RAISE EXCEPTION 'Risk aggregate revision mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.predecessor_id IS NOT NULL THEN
   SELECT version_number INTO version FROM risk_definition_versions WHERE id=NEW.predecessor_id AND definition_id=NEW.definition_id;
   IF version IS DISTINCT FROM NEW.version_number-1 THEN RAISE EXCEPTION 'Risk predecessor mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_runs' THEN
  SELECT kind INTO family FROM premium_runs WHERE id=NEW.id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF family IS DISTINCT FROM 'risk' THEN RAISE EXCEPTION 'Risk run family mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id, sealed INTO actual,pinned FROM historical_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.historical_input_id AND input_digest=NEW.historical_input_digest;
  IF actual IS DISTINCT FROM NEW.account_id OR NOT coalesce(pinned,false) THEN RAISE EXCEPTION 'Risk history binding mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id INTO actual FROM portfolio_snapshots WHERE id=NEW.portfolio_snapshot_id;
  IF actual IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Risk snapshot binding mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.xray_run_id IS NOT NULL THEN
   SELECT i.account_id,i.snapshot_id,i.source_cutoff_at INTO actual,snapshot,cutoff FROM xray_runs r JOIN xray_input_snapshots i ON i.id=r.input_id WHERE r.id=NEW.xray_run_id AND r.owner_id=NEW.owner_id AND r.sealed_at IS NOT NULL AND i.sealed_at IS NOT NULL;
   IF actual IS DISTINCT FROM NEW.account_id OR snapshot IS DISTINCT FROM NEW.portfolio_snapshot_id OR cutoff IS DISTINCT FROM NEW.source_cutoff_at THEN RAISE EXCEPTION 'Risk X-ray binding mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_run_assets' THEN
  SELECT instrument_id INTO actual FROM market_source_series WHERE id=NEW.source_series_id AND owner_id=NEW.owner_id;
  IF actual IS DISTINCT FROM NEW.instrument_id THEN RAISE EXCEPTION 'Risk asset source mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_dispatch_outbox' THEN
  SELECT r.kind INTO family FROM premium_jobs j JOIN premium_runs r ON r.id=j.run_id WHERE j.id=NEW.job_id;
  IF NEW.task_name IS DISTINCT FROM (CASE family WHEN 'risk' THEN 'risk.calculate.v1' WHEN 'scenario' THEN 'scenarios.calculate.v1' WHEN 'projection' THEN 'projections.calculate.v1' END) THEN RAISE EXCEPTION 'Premium task identity mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_jobs' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Premium capacity reservation missing' USING ERRCODE='23514'; END IF;
  IF NEW.state IN ('queued','running') AND (SELECT count(*) FROM premium_jobs WHERE owner_id=NEW.owner_id AND id<>NEW.id AND state IN ('queued','running')) >= 2 THEN RAISE EXCEPTION 'Premium owner active capacity exceeded' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; run uuid; allowed boolean;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 body:=to_jsonb(OLD);
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='risk_definitions' THEN
  IF NEW.revision=OLD.revision+1 AND NEW.updated_at>=OLD.updated_at AND (to_jsonb(NEW)-ARRAY['revision','name','archived','updated_at'])=(body-ARRAY['revision','name','archived','updated_at']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_jobs' THEN
  IF (to_jsonb(NEW)-ARRAY['state','consumer_attempts','lease_token','lease_expires_at','heartbeat_at','deadline_at','consumer_id','failure_code','completed_at'])=(body-ARRAY['state','consumer_attempts','lease_token','lease_expires_at','heartbeat_at','deadline_at','consumer_id','failure_code','completed_at']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_dispatch_outbox' THEN
  IF (to_jsonb(NEW)-ARRAY['state','publication_attempts','available_at','claim_token','claim_expires_at','dispatcher_id','published_at','failure_code'])=(body-ARRAY['state','publication_attempts','available_at','claim_token','claim_expires_at','dispatcher_id','published_at','failure_code']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_retention_events' THEN
  IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL AND (to_jsonb(NEW)-'completed_at')=(body-'completed_at') THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('risk_runs','risk_results') AND TG_OP='UPDATE' THEN
  IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(body-'sealed') THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_runs' AND TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['reserved_bytes','retained_bytes'])=(body-ARRAY['reserved_bytes','retained_bytes']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('risk_run_assets','risk_results','risk_series','risk_intervals','risk_matrix_cells','risk_metrics','risk_components') THEN
  IF TG_TABLE_NAME IN ('risk_run_assets','risk_results') THEN run:=(body->>'run_id')::uuid;
  ELSE SELECT run_id INTO run FROM risk_results WHERE id=(body->>'result_id')::uuid; END IF;
  SELECT EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=OLD.owner_id AND account_id=OLD.account_id AND run_id=run) INTO allowed;
  IF allowed AND TG_OP='DELETE' AND TG_TABLE_NAME<>'risk_results' THEN RETURN OLD; END IF;
  IF allowed AND TG_OP='UPDATE' AND TG_TABLE_NAME='risk_results' THEN
   IF NEW.canonical_result='\x'::bytea AND (to_jsonb(NEW)-'canonical_result')=(body-'canonical_result') THEN RETURN NEW; END IF;
  END IF;
 END IF;
 RAISE EXCEPTION 'Published premium content is immutable' USING ERRCODE='23514';
END $$;

CREATE OR REPLACE FUNCTION premium_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned boolean;
BEGIN
 IF TG_TABLE_NAME='risk_run_assets' THEN SELECT sealed INTO pinned FROM risk_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.run_id FOR UPDATE;
 ELSE SELECT sealed INTO pinned FROM risk_results WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.result_id FOR UPDATE; END IF;
 IF coalesce(pinned,true) THEN RAISE EXCEPTION 'Premium parent is already sealed' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_definition_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE aggregate risk_definitions; version risk_definition_versions;
BEGIN
 SELECT * INTO aggregate FROM risk_definitions WHERE id=NEW.id;
 SELECT * INTO version FROM risk_definition_versions WHERE definition_id=NEW.id ORDER BY version_number DESC LIMIT 1;
 IF version.id IS NULL OR aggregate.revision IS DISTINCT FROM version.version_number OR aggregate.name IS DISTINCT FROM version.name THEN RAISE EXCEPTION 'Risk definition publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_command_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; account uuid;
BEGIN
 IF NEW.command NOT LIKE 'risk.%' THEN RETURN NEW; END IF;
 IF NEW.command='risk.definition.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definitions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='risk.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definition_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('risk.run.create.v1','risk.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='risk'; END IF;
 IF actual IS DISTINCT FROM NEW.owner_id OR account IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Premium command target mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_run_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned boolean; jobs integer;
BEGIN
 IF NEW.kind<>'risk' THEN RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
 SELECT sealed INTO pinned FROM risk_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.id;
 SELECT count(*) INTO jobs FROM premium_jobs j JOIN premium_dispatch_outbox o ON o.job_id=j.id AND o.owner_id=j.owner_id AND o.account_id=j.account_id WHERE j.run_id=NEW.id;
 IF NOT coalesce(pinned,false) OR jobs<>1 THEN RAISE EXCEPTION 'Premium request publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_result_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current risk_results; state text;
BEGIN
 SELECT * INTO current FROM risk_results WHERE id=NEW.id;
 SELECT j.state INTO state FROM premium_jobs j WHERE j.run_id=NEW.run_id AND j.owner_id=NEW.owner_id AND j.account_id=NEW.account_id;
 IF NOT current.sealed OR octet_length(current.canonical_result)=0 OR state IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'Premium result publication incomplete' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM risk_series WHERE result_id=NEW.id)<>current.series_count OR
    (SELECT count(*) FROM risk_intervals WHERE result_id=NEW.id)<>current.interval_count OR
    (SELECT count(*) FROM risk_matrix_cells WHERE result_id=NEW.id)<>current.matrix_cell_count OR
    (SELECT count(*) FROM risk_metrics WHERE result_id=NEW.id)<>current.metric_count OR
    (SELECT count(*) FROM risk_components WHERE result_id=NEW.id)<>current.component_count THEN RAISE EXCEPTION 'Premium normalized publication incomplete' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM risk_series s WHERE s.result_id=NEW.id AND s.interval_count<>(SELECT count(*) FROM risk_intervals i WHERE i.series_id=s.id)) THEN RAISE EXCEPTION 'Premium series publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

_SHARED_GUARDS = r"""
CREATE OR REPLACE FUNCTION premium_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; pinned boolean; version integer; family text; snapshot uuid; cutoff timestamptz;
BEGIN
 IF TG_TABLE_NAME='application_command_identities' THEN
  IF NEW.command NOT LIKE 'risk.%' AND NEW.command NOT LIKE 'scenario.%' THEN RETURN NEW; END IF;
 END IF;
 SELECT c.owner_id INTO actual FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=NEW.account_id;
 IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium account scope mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT owner_id INTO actual FROM principals WHERE id=NEW.actor_principal_id;
  IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Premium principal scope mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_runs' THEN
  SELECT premium_resource_id INTO actual FROM application_command_identities WHERE id=NEW.command_id AND command=CASE NEW.kind WHEN 'risk' THEN 'risk.run.create.v1' WHEN 'scenario' THEN 'scenario.run.create.v1' END AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF actual IS DISTINCT FROM NEW.id THEN RAISE EXCEPTION 'Premium run command mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='risk_definition_versions' AND TG_OP='INSERT' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND OR (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)+(SELECT count(*) FROM scenario_definition_versions WHERE owner_id=NEW.owner_id)>=512 THEN RAISE EXCEPTION 'Premium version capacity unavailable' USING ERRCODE='23514'; END IF;
  SELECT revision INTO version FROM risk_definitions WHERE id=NEW.definition_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF version IS DISTINCT FROM NEW.version_number THEN RAISE EXCEPTION 'Risk aggregate revision mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.predecessor_id IS NOT NULL THEN
   SELECT version_number INTO version FROM risk_definition_versions WHERE id=NEW.predecessor_id AND definition_id=NEW.definition_id;
   IF version IS DISTINCT FROM NEW.version_number-1 THEN RAISE EXCEPTION 'Risk predecessor mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_runs' THEN
  SELECT kind INTO family FROM premium_runs WHERE id=NEW.id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF family IS DISTINCT FROM 'risk' THEN RAISE EXCEPTION 'Risk run family mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id, sealed INTO actual,pinned FROM historical_input_snapshots WHERE owner_id=NEW.owner_id AND id=NEW.historical_input_id AND input_digest=NEW.historical_input_digest;
  IF actual IS DISTINCT FROM NEW.account_id OR NOT coalesce(pinned,false) THEN RAISE EXCEPTION 'Risk history binding mismatch' USING ERRCODE='23514'; END IF;
  SELECT broker_account_id INTO actual FROM portfolio_snapshots WHERE id=NEW.portfolio_snapshot_id;
  IF actual IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Risk snapshot binding mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.xray_run_id IS NOT NULL THEN
   SELECT i.account_id,i.snapshot_id,i.source_cutoff_at INTO actual,snapshot,cutoff FROM xray_runs r JOIN xray_input_snapshots i ON i.id=r.input_id WHERE r.id=NEW.xray_run_id AND r.owner_id=NEW.owner_id AND r.sealed_at IS NOT NULL AND i.sealed_at IS NOT NULL;
   IF actual IS DISTINCT FROM NEW.account_id OR snapshot IS DISTINCT FROM NEW.portfolio_snapshot_id OR cutoff IS DISTINCT FROM NEW.source_cutoff_at THEN RAISE EXCEPTION 'Risk X-ray binding mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='risk_run_assets' THEN
  SELECT instrument_id INTO actual FROM market_source_series WHERE id=NEW.source_series_id AND owner_id=NEW.owner_id;
  IF actual IS DISTINCT FROM NEW.instrument_id THEN RAISE EXCEPTION 'Risk asset source mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_dispatch_outbox' THEN
  SELECT r.kind INTO family FROM premium_jobs j JOIN premium_runs r ON r.id=j.run_id WHERE j.id=NEW.job_id;
  IF NEW.task_name IS DISTINCT FROM (CASE family WHEN 'risk' THEN 'risk.calculate.v1' WHEN 'scenario' THEN 'scenarios.calculate.v1' WHEN 'projection' THEN 'projections.calculate.v1' END) THEN RAISE EXCEPTION 'Premium task identity mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_jobs' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Premium capacity reservation missing' USING ERRCODE='23514'; END IF;
  IF NEW.state IN ('queued','running') AND (SELECT count(*) FROM premium_jobs WHERE owner_id=NEW.owner_id AND id<>NEW.id AND state IN ('queued','running')) >= 2 THEN RAISE EXCEPTION 'Premium owner active capacity exceeded' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; run uuid; allowed boolean;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 body:=to_jsonb(OLD);
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='risk_definitions' THEN
  IF NEW.revision=OLD.revision+1 AND NEW.updated_at>=OLD.updated_at AND (to_jsonb(NEW)-ARRAY['revision','name','archived','updated_at'])=(body-ARRAY['revision','name','archived','updated_at']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_jobs' THEN
  IF (to_jsonb(NEW)-ARRAY['state','consumer_attempts','lease_token','lease_expires_at','heartbeat_at','deadline_at','consumer_id','failure_code','completed_at'])=(body-ARRAY['state','consumer_attempts','lease_token','lease_expires_at','heartbeat_at','deadline_at','consumer_id','failure_code','completed_at']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_dispatch_outbox' THEN
  IF (to_jsonb(NEW)-ARRAY['state','publication_attempts','available_at','claim_token','claim_expires_at','dispatcher_id','published_at','failure_code'])=(body-ARRAY['state','publication_attempts','available_at','claim_token','claim_expires_at','dispatcher_id','published_at','failure_code']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='premium_retention_events' THEN
  IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL AND (to_jsonb(NEW)-'completed_at')=(body-'completed_at') THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('risk_runs','risk_results') AND TG_OP='UPDATE' THEN
  IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(body-'sealed') THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME='premium_runs' AND TG_OP='UPDATE' THEN
  IF (to_jsonb(NEW)-ARRAY['reserved_bytes','retained_bytes'])=(body-ARRAY['reserved_bytes','retained_bytes']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('risk_run_assets','risk_results','risk_series','risk_intervals','risk_matrix_cells','risk_metrics','risk_components') THEN
  IF TG_TABLE_NAME IN ('risk_run_assets','risk_results') THEN run:=(body->>'run_id')::uuid;
  ELSE SELECT run_id INTO run FROM risk_results WHERE id=(body->>'result_id')::uuid; END IF;
  SELECT EXISTS(SELECT 1 FROM premium_retention_events WHERE owner_id=OLD.owner_id AND account_id=OLD.account_id AND run_id=run) INTO allowed;
  IF allowed AND TG_OP='DELETE' AND TG_TABLE_NAME<>'risk_results' THEN RETURN OLD; END IF;
  IF allowed AND TG_OP='UPDATE' AND TG_TABLE_NAME='risk_results' THEN
   IF NEW.canonical_result='\x'::bytea AND (to_jsonb(NEW)-'canonical_result')=(body-'canonical_result') THEN RETURN NEW; END IF;
  END IF;
 END IF;
 RAISE EXCEPTION 'Published premium content is immutable' USING ERRCODE='23514';
END $$;

CREATE OR REPLACE FUNCTION premium_child_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned boolean;
BEGIN
 IF TG_TABLE_NAME='risk_run_assets' THEN SELECT sealed INTO pinned FROM risk_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.run_id FOR UPDATE;
 ELSE SELECT sealed INTO pinned FROM risk_results WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.result_id FOR UPDATE; END IF;
 IF coalesce(pinned,true) THEN RAISE EXCEPTION 'Premium parent is already sealed' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_definition_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE aggregate risk_definitions; version risk_definition_versions;
BEGIN
 SELECT * INTO aggregate FROM risk_definitions WHERE id=NEW.id;
 SELECT * INTO version FROM risk_definition_versions WHERE definition_id=NEW.id ORDER BY version_number DESC LIMIT 1;
 IF version.id IS NULL OR aggregate.revision IS DISTINCT FROM version.version_number OR aggregate.name IS DISTINCT FROM version.name THEN RAISE EXCEPTION 'Risk definition publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_command_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; account uuid;
BEGIN
 IF NEW.command NOT LIKE 'risk.%' AND NEW.command NOT LIKE 'scenario.%' THEN RETURN NEW; END IF;
 IF NEW.command='risk.definition.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definitions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='risk.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM risk_definition_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('risk.run.create.v1','risk.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='risk';
 ELSIF NEW.command='scenario.definition.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM scenario_definitions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command='scenario.version.create.v1' THEN SELECT owner_id,account_id INTO actual,account FROM scenario_definition_versions WHERE id=NEW.premium_resource_id;
 ELSIF NEW.command IN ('scenario.run.create.v1','scenario.run.cancel.v1') THEN SELECT owner_id,account_id INTO actual,account FROM premium_runs WHERE id=NEW.premium_resource_id AND kind='scenario'; END IF;
 IF actual IS DISTINCT FROM NEW.owner_id OR account IS DISTINCT FROM NEW.account_id THEN RAISE EXCEPTION 'Premium command target mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_run_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE pinned boolean; jobs integer;
BEGIN
 IF NEW.kind NOT IN ('risk','scenario') THEN RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
 IF NEW.kind='risk' THEN SELECT sealed INTO pinned FROM risk_runs WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id AND id=NEW.id;
 ELSE pinned:=scenario_capture_complete(NEW.id); END IF;
 SELECT count(*) INTO jobs FROM premium_jobs j JOIN premium_dispatch_outbox o ON o.job_id=j.id AND o.owner_id=j.owner_id AND o.account_id=j.account_id WHERE j.run_id=NEW.id;
 IF NOT coalesce(pinned,false) OR jobs<>1 THEN RAISE EXCEPTION 'Premium request publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION premium_result_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM premium_risk_result_complete_check(NEW.id,NEW.run_id,NEW.owner_id,NEW.account_id);
 RETURN NEW;
END $$;
"""

_PREVIOUS_LICENSE_GUARD = r"""CREATE OR REPLACE FUNCTION premium_run_license_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE pinned boolean;
      BEGIN
        IF TG_OP <> 'INSERT' THEN
          RAISE EXCEPTION 'Premium license lineage is immutable' USING ERRCODE='23514';
        END IF;
        SELECT sealed INTO pinned FROM risk_runs
          WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        IF pinned IS DISTINCT FROM false OR
          (SELECT count(*) FROM premium_run_licenses WHERE run_id=NEW.run_id)>=8192 THEN
          RAISE EXCEPTION 'Premium license lineage is sealed or over capacity' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$;"""

_LICENSE_GUARD = r"""CREATE OR REPLACE FUNCTION premium_run_license_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE pinned boolean; family text;
      BEGIN
        IF TG_OP <> 'INSERT' THEN
          RAISE EXCEPTION 'Premium license lineage is immutable' USING ERRCODE='23514';
        END IF;
        SELECT kind INTO family FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
        IF family='risk' THEN SELECT sealed INTO pinned FROM risk_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        ELSIF family='scenario' THEN SELECT sealed INTO pinned FROM scenario_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
        ELSE RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
        IF pinned IS DISTINCT FROM false OR
          (SELECT count(*) FROM premium_run_licenses WHERE run_id=NEW.run_id)>=8192 THEN
          RAISE EXCEPTION 'Premium license lineage is sealed or over capacity' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
      END $$;"""

_SCENARIO_GUARDS = r"""CREATE FUNCTION scenario_run_has_payload(p_run uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM scenario_run_payloads WHERE run_id=p_run)
 OR EXISTS(SELECT 1 FROM scenario_results WHERE run_id=p_run AND octet_length(canonical_result)>0)
 OR EXISTS(SELECT 1 FROM scenario_components c JOIN scenario_results r ON r.id=c.result_id WHERE r.run_id=p_run)
 OR EXISTS(SELECT 1 FROM scenario_applied_sensitivities a JOIN scenario_results r ON r.id=a.result_id WHERE r.run_id=p_run)
$$;

CREATE FUNCTION scenario_source_copy_pending(p_version uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v
 WHERE v.version_id=p_version AND scenario_run_has_payload(v.run_id))
$$;

CREATE FUNCTION scenario_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; v uuid; o uuid; e uuid; pinned boolean; version scenario_sensitivity_versions;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 IF TG_OP='INSERT' THEN body:=to_jsonb(NEW); ELSE body:=to_jsonb(OLD); END IF;
 -- Normal cleanup prelocks the owner before DELETE. Direct SQL must not wait
 -- for that owner while already holding the physical target payload tuple.
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('scenario_sensitivity_version_payloads','scenario_sensitivity_observation_payloads','scenario_sensitivity_evidence_payloads') THEN
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sources:'||(body->>'owner_id'),0)) THEN
   RAISE EXCEPTION 'Sensitivity source purge owner is busy' USING ERRCODE='55P03';
  END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_sensitivity_versions' THEN v:=(body->>'id')::uuid;
 ELSIF TG_TABLE_NAME='scenario_sensitivity_observation_payloads' THEN
  SELECT version_id INTO v FROM scenario_sensitivity_observations WHERE id=(body->>'observation_id')::uuid AND owner_id=(body->>'owner_id')::uuid;
 ELSIF TG_TABLE_NAME NOT IN ('scenario_sensitivity_sets','scenario_sensitivity_evidence','scenario_sensitivity_evidence_payloads') THEN v:=(body->>'version_id')::uuid; END IF;
 IF TG_TABLE_NAME IN ('scenario_sensitivity_evidence_links','scenario_sensitivity_evidence_payloads') THEN
  e:=(body->>'evidence_id')::uuid;
  PERFORM id FROM scenario_sensitivity_evidence WHERE id=e AND owner_id=(body->>'owner_id')::uuid FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Sensitivity evidence identity unavailable' USING ERRCODE='23514'; END IF;
 END IF;
 IF v IS NOT NULL THEN SELECT * INTO version FROM scenario_sensitivity_versions WHERE id=v AND owner_id=(body->>'owner_id')::uuid FOR UPDATE; END IF;
 IF TG_OP='INSERT' THEN
  IF TG_TABLE_NAME='scenario_sensitivity_versions' THEN
   IF NEW.sealed THEN RAISE EXCEPTION 'Sensitivity source must begin unsealed' USING ERRCODE='23514'; END IF;
  ELSIF TG_TABLE_NAME='scenario_sensitivity_retention' THEN
   IF version.id IS NULL OR NOT version.sealed OR NEW.completed_at IS NOT NULL THEN RAISE EXCEPTION 'Sensitivity retention binding invalid' USING ERRCODE='23514'; END IF;
  ELSIF v IS NOT NULL AND (version.id IS NULL OR version.sealed OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=v)) THEN
   RAISE EXCEPTION 'Sensitivity source is sealed or restricted' USING ERRCODE='23514';
  END IF;
  IF TG_TABLE_NAME IN ('scenario_sensitivity_versions','scenario_sensitivity_observations','scenario_sensitivity_evidence') THEN
   IF NOT EXISTS(SELECT 1 FROM provider_license_versions WHERE owner_id=NEW.owner_id AND provider_id=NEW.provider_id AND id=NEW.license_version_id AND store_permission='allowed' AND retention_days IS NOT NULL) THEN RAISE EXCEPTION 'Sensitivity storage license unavailable' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_evidence_links' THEN
   IF NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads WHERE evidence_id=e AND owner_id=NEW.owner_id) THEN RAISE EXCEPTION 'Sensitivity evidence payload unavailable' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_version_payloads' THEN
   IF NEW.revision IS DISTINCT FROM version.revision THEN RAISE EXCEPTION 'Sensitivity revision mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_observation_payloads' THEN
   IF NOT EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads p WHERE p.version_id=v AND p.shock_unit=NEW.shock_unit) THEN RAISE EXCEPTION 'Sensitivity observation units mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_observations' THEN
   IF (NEW.driver_id IS DISTINCT FROM version.driver_id OR NEW.driver_definition_version_id IS DISTINCT FROM version.driver_definition_version_id) THEN RAISE EXCEPTION 'Sensitivity observation driver mismatch' USING ERRCODE='23514'; END IF;
  END IF;
  IF TG_TABLE_NAME='scenario_sensitivity_evidence_payloads' THEN
   IF EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links l JOIN scenario_sensitivity_versions s ON s.id=l.version_id WHERE l.evidence_id=NEW.evidence_id AND (s.sealed OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=s.id))) THEN RAISE EXCEPTION 'Published evidence payload is immutable' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_versions' THEN
  IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(body-'sealed') THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_sensitivity_retention' THEN
  IF OLD.completed_at IS NULL AND NEW.completed_at IS NOT NULL AND (to_jsonb(NEW)-'completed_at')=(body-'completed_at') THEN
   IF scenario_source_copy_pending(v) OR EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads WHERE version_id=v) OR EXISTS(SELECT 1 FROM scenario_sensitivity_observation_payloads p JOIN scenario_sensitivity_observations o ON o.id=p.observation_id WHERE o.version_id=v) OR EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads p JOIN scenario_sensitivity_evidence_links l ON l.evidence_id=p.evidence_id WHERE l.version_id=v) THEN RAISE EXCEPTION 'Sensitivity source copies remain' USING ERRCODE='23514'; END IF;
   RETURN NEW;
  END IF;
 END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME IN ('scenario_sensitivity_version_payloads','scenario_sensitivity_observation_payloads') THEN
  IF EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=v) AND NOT scenario_source_copy_pending(v) THEN RETURN OLD; END IF;
 END IF;
 IF TG_OP='DELETE' AND TG_TABLE_NAME='scenario_sensitivity_evidence_payloads' THEN
  -- A shared evidence payload cannot be removed while any published version still needs it.
  PERFORM s.id FROM scenario_sensitivity_versions s JOIN scenario_sensitivity_evidence_links l ON l.version_id=s.id WHERE l.evidence_id=OLD.evidence_id ORDER BY s.id FOR UPDATE OF s;
  IF EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links WHERE evidence_id=OLD.evidence_id) AND NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links l WHERE l.evidence_id=OLD.evidence_id AND (NOT EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=l.version_id) OR scenario_source_copy_pending(l.version_id))) THEN RETURN OLD; END IF;
 END IF;
 RAISE EXCEPTION 'Sensitivity source identity or published payload is immutable' USING ERRCODE='23514';
END $$;

CREATE FUNCTION scenario_source_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current scenario_sensitivity_versions; payload_bytes bigint;
BEGIN
 SELECT * INTO current FROM scenario_sensitivity_versions WHERE id=NEW.id;
 IF NOT current.sealed OR (SELECT count(*) FROM scenario_sensitivity_version_payloads WHERE version_id=current.id)<>1 OR (SELECT count(*) FROM scenario_sensitivity_observations WHERE version_id=current.id)<>current.observation_count OR (SELECT count(*) FROM scenario_sensitivity_observation_payloads p JOIN scenario_sensitivity_observations o ON o.id=p.observation_id WHERE o.version_id=current.id)<>current.observation_count OR (SELECT count(*) FROM scenario_sensitivity_memberships WHERE version_id=current.id)<>current.membership_count OR (SELECT count(DISTINCT evidence_id) FROM scenario_sensitivity_evidence_links WHERE version_id=current.id)<>current.evidence_count OR (SELECT count(DISTINCT p.evidence_id) FROM scenario_sensitivity_evidence_payloads p JOIN scenario_sensitivity_evidence_links l ON l.evidence_id=p.evidence_id WHERE l.version_id=current.id)<>current.evidence_count THEN RAISE EXCEPTION 'Sensitivity source publication incomplete' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM scenario_sensitivity_observations o WHERE o.version_id=current.id AND NOT EXISTS(SELECT 1 FROM scenario_sensitivity_memberships m WHERE m.version_id=current.id AND m.observation_id=o.id)) THEN RAISE EXCEPTION 'Sensitivity membership proof missing' USING ERRCODE='23514'; END IF;
 SELECT coalesce(sum(bytes),0) INTO payload_bytes FROM (
  SELECT octet_length(p.canonical_payload)+pg_column_size(ROW(p.id,p.owner_id,p.created_at,p.version_id,p.driver_kind,p.shock_unit,p.equivalence_kind,p.equivalence_rate_id,p.equivalence_factor_id,p.equivalence_currency,p.equivalence_selector_kind,p.equivalence_instrument_id,p.equivalence_entity_id,p.equivalence_taxonomy_id,p.equivalence_taxonomy_version,p.equivalence_bucket_key,p.equivalence_reason,p.effective_at,p.first_known_at,p.valid_from,p.valid_until,p.revision,p.adapter_id,p.adapter_version,p.availability,p.quality))::bigint bytes FROM scenario_sensitivity_version_payloads p WHERE version_id=current.id
  UNION ALL SELECT pg_column_size(current)
  UNION ALL SELECT pg_column_size(o) FROM scenario_sensitivity_observations o WHERE version_id=current.id
  UNION ALL SELECT pg_column_size(m) FROM scenario_sensitivity_memberships m WHERE version_id=current.id
  UNION ALL SELECT pg_column_size(l) FROM scenario_sensitivity_evidence_links l WHERE version_id=current.id
  UNION ALL SELECT pg_column_size(e) FROM scenario_sensitivity_evidence e WHERE EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links l WHERE l.evidence_id=e.id AND l.version_id=current.id)
  UNION ALL SELECT octet_length(p.canonical_payload)+pg_column_size(ROW(p.id,p.owner_id,p.created_at,p.observation_id,p.subject_kind,p.instrument_id,p.entity_id,p.coefficient,p.shock_unit,p.response_unit,p.response_basis,p.response_currency,p.effective_at,p.first_known_at,p.valid_from,p.valid_until,p.revision,p.state,p.quality,p.confidence,p.reason)) FROM scenario_sensitivity_observation_payloads p JOIN scenario_sensitivity_observations o ON o.id=p.observation_id WHERE o.version_id=current.id
  UNION ALL SELECT octet_length(p.canonical_payload)+pg_column_size(ROW(p.id,p.owner_id,p.created_at,p.evidence_id,p.effective_at,p.first_known_at,p.adapter_id,p.adapter_version,p.transformation)) FROM scenario_sensitivity_evidence_payloads p WHERE EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links l WHERE l.evidence_id=p.evidence_id AND l.version_id=current.id)
 ) physical;
 IF (SELECT count(DISTINCT license_version_id) FROM (
  SELECT current.license_version_id
  UNION ALL SELECT license_version_id FROM scenario_sensitivity_observations WHERE version_id=current.id
  UNION ALL SELECT e.license_version_id FROM scenario_sensitivity_evidence e JOIN scenario_sensitivity_evidence_links l ON l.evidence_id=e.id WHERE l.version_id=current.id
 ) licenses)>8192 THEN RAISE EXCEPTION 'Sensitivity source license capacity exceeded' USING ERRCODE='23514'; END IF;
 IF payload_bytes>33554432 THEN RAISE EXCEPTION 'Sensitivity source byte capacity exceeded' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION scenario_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actual uuid; pinned boolean; n integer; family text; v scenario_sensitivity_versions; run scenario_runs; x record;
BEGIN
 SELECT c.owner_id INTO actual FROM broker_accounts a JOIN broker_connections c ON c.id=a.connection_id WHERE a.id=NEW.account_id;
 IF actual IS DISTINCT FROM NEW.owner_id THEN RAISE EXCEPTION 'Scenario account scope mismatch' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='scenario_definition_versions' THEN
  PERFORM owner_id FROM premium_owner_capacity WHERE owner_id=NEW.owner_id FOR UPDATE;
  IF NOT FOUND OR (SELECT count(*) FROM risk_definition_versions WHERE owner_id=NEW.owner_id)+(SELECT count(*) FROM scenario_definition_versions WHERE owner_id=NEW.owner_id)>=512 THEN RAISE EXCEPTION 'Premium version capacity unavailable' USING ERRCODE='23514'; END IF;
  SELECT revision INTO n FROM scenario_definitions WHERE id=NEW.definition_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF n IS DISTINCT FROM NEW.version_number OR NEW.sealed THEN RAISE EXCEPTION 'Scenario revision publication invalid' USING ERRCODE='23514'; END IF;
  IF NEW.predecessor_id IS NOT NULL THEN
   SELECT version_number INTO n FROM scenario_definition_versions WHERE id=NEW.predecessor_id AND definition_id=NEW.definition_id;
   IF n IS DISTINCT FROM NEW.version_number-1 THEN RAISE EXCEPTION 'Scenario predecessor mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME IN ('scenario_shocks','scenario_exclusions') THEN
  SELECT sealed INTO pinned FROM scenario_definition_versions WHERE id=NEW.version_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF pinned IS DISTINCT FROM false THEN RAISE EXCEPTION 'Scenario definition is already sealed' USING ERRCODE='23514'; END IF;
  IF TG_TABLE_NAME='scenario_shocks' THEN
   IF NEW.source_version_id IS NOT NULL THEN
    SELECT * INTO v FROM scenario_sensitivity_versions WHERE id=NEW.source_version_id AND owner_id=NEW.owner_id;
    IF NOT coalesce(v.sealed,false) OR NEW.driver_id IS DISTINCT FROM v.driver_id OR NEW.driver_definition_version_id IS DISTINCT FROM v.driver_definition_version_id THEN RAISE EXCEPTION 'Scenario shock source driver mismatch' USING ERRCODE='23514'; END IF;
   END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_runs' THEN
  SELECT kind INTO family FROM premium_runs WHERE id=NEW.id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF EXISTS(SELECT 1 FROM premium_retention_events WHERE run_id=NEW.id) THEN RAISE EXCEPTION 'Scenario capture is restricted' USING ERRCODE='23514'; END IF;
  IF family IS DISTINCT FROM 'scenario' OR NEW.sealed THEN RAISE EXCEPTION 'Scenario run family or seal mismatch' USING ERRCODE='23514'; END IF;
  SELECT sealed INTO pinned FROM scenario_definition_versions WHERE id=NEW.definition_version_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id;
  IF NOT coalesce(pinned,false) THEN RAISE EXCEPTION 'Scenario version is not sealed' USING ERRCODE='23514'; END IF;
  PERFORM id FROM xray_input_snapshots WHERE id=NEW.xray_input_id AND owner_id=NEW.owner_id FOR SHARE;
  PERFORM id FROM xray_runs WHERE id=NEW.xray_run_id AND owner_id=NEW.owner_id FOR SHARE;
  SELECT i.account_id,i.snapshot_id,i.source_cutoff_at,i.reporting_currency,i.input_digest,r.content_digest INTO x FROM xray_runs r JOIN xray_input_snapshots i ON i.id=r.input_id AND i.owner_id=r.owner_id WHERE r.id=NEW.xray_run_id AND r.owner_id=NEW.owner_id AND i.id=NEW.xray_input_id AND r.sealed_at IS NOT NULL AND i.sealed_at IS NOT NULL AND octet_length(i.canonical_input)>0 AND octet_length(r.canonical_exact_state)>0 AND NOT EXISTS(SELECT 1 FROM xray_retention_events WHERE input_id=i.id AND owner_id=NEW.owner_id);
  IF x.account_id IS DISTINCT FROM NEW.account_id OR x.snapshot_id IS DISTINCT FROM NEW.portfolio_snapshot_id OR x.source_cutoff_at IS DISTINCT FROM NEW.source_cutoff_at OR x.reporting_currency IS DISTINCT FROM NEW.reporting_currency OR x.input_digest IS DISTINCT FROM NEW.xray_input_digest OR x.content_digest IS DISTINCT FROM NEW.xray_result_digest THEN RAISE EXCEPTION 'Scenario X-ray binding mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.historical_input_id IS NOT NULL THEN
   PERFORM id FROM historical_input_snapshots WHERE id=NEW.historical_input_id AND owner_id=NEW.owner_id FOR SHARE;
   SELECT broker_account_id,sealed INTO actual,pinned FROM historical_input_snapshots WHERE id=NEW.historical_input_id AND owner_id=NEW.owner_id AND input_digest=NEW.historical_input_digest AND octet_length(canonical_input)>0 AND NOT EXISTS(SELECT 1 FROM historical_retention_events WHERE input_id=NEW.historical_input_id AND owner_id=NEW.owner_id);
   IF actual IS DISTINCT FROM NEW.account_id OR NOT coalesce(pinned,false) OR EXISTS(SELECT 1 FROM scenario_shocks WHERE version_id=NEW.definition_version_id) THEN RAISE EXCEPTION 'Scenario replay binding mismatch' USING ERRCODE='23514'; END IF;
  END IF;
 END IF;
 IF TG_TABLE_NAME IN ('scenario_run_payloads','scenario_run_sensitivity_versions','scenario_run_sensitivity_observations','scenario_run_sensitivity_memberships','scenario_run_sensitivity_evidence') THEN
  SELECT * INTO run FROM scenario_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF run.sealed IS DISTINCT FROM false THEN RAISE EXCEPTION 'Scenario capture is already sealed' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_run_sensitivity_versions' THEN
  SELECT * INTO v FROM scenario_sensitivity_versions WHERE id=NEW.version_id AND owner_id=NEW.owner_id FOR UPDATE;
  IF NOT coalesce(v.sealed,false) OR v.expires_at<=statement_timestamp() OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention WHERE version_id=v.id) OR NOT EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads WHERE version_id=v.id) THEN RAISE EXCEPTION 'Scenario sensitivity source unavailable' USING ERRCODE='23514'; END IF;
  IF (SELECT count(*) FROM scenario_run_sensitivity_versions WHERE run_id=NEW.run_id)>=128 THEN RAISE EXCEPTION 'Scenario sensitivity version capacity exceeded' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_run_sensitivity_memberships' THEN
  IF NOT EXISTS(SELECT 1 FROM scenario_sensitivity_memberships m WHERE m.id=NEW.membership_id AND m.owner_id=NEW.owner_id AND m.version_id=NEW.version_id AND m.observation_id=NEW.observation_id) THEN RAISE EXCEPTION 'Scenario sensitivity membership mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_results' THEN
  PERFORM id FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF NEW.sealed OR EXISTS(SELECT 1 FROM premium_retention_events WHERE run_id=NEW.run_id) THEN RAISE EXCEPTION 'Scenario result publication is restricted' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('scenario_components','scenario_applied_sensitivities') THEN
  SELECT sealed INTO pinned FROM scenario_results WHERE id=NEW.result_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF pinned IS DISTINCT FROM false THEN RAISE EXCEPTION 'Scenario result is already sealed' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_components' THEN
  SELECT s.* INTO run FROM scenario_runs s JOIN scenario_results r ON r.run_id=s.id WHERE r.id=NEW.result_id AND r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id;
  IF NEW.root_kind='position' AND NOT EXISTS(SELECT 1 FROM snapshot_positions p JOIN listings l ON l.id=p.listing_id WHERE p.id=NEW.position_id AND p.snapshot_id=run.portfolio_snapshot_id AND l.instrument_id=NEW.root_instrument_id) THEN RAISE EXCEPTION 'Scenario component position binding mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.root_kind='cash' AND NOT EXISTS(SELECT 1 FROM snapshot_cash c WHERE c.id=NEW.snapshot_cash_id AND c.snapshot_id=run.portfolio_snapshot_id) THEN RAISE EXCEPTION 'Scenario component cash binding mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 IF TG_TABLE_NAME='scenario_applied_sensitivities' THEN
  SELECT s.* INTO run FROM scenario_runs s JOIN scenario_results r ON r.run_id=s.id WHERE r.id=NEW.result_id AND r.owner_id=NEW.owner_id AND r.account_id=NEW.account_id;
  IF NOT EXISTS(SELECT 1 FROM scenario_shocks s WHERE s.version_id=run.definition_version_id AND s.rule_key=NEW.rule_key AND s.source_version_id=NEW.version_id AND s.driver_id=NEW.driver_id AND s.driver_definition_version_id=NEW.driver_definition_version_id AND s.size=NEW.shock_size) THEN RAISE EXCEPTION 'Scenario applied assumption mismatch' USING ERRCODE='23514'; END IF;
  IF EXISTS(SELECT 1 FROM unnest(NEW.candidate_observation_ids) candidate WHERE NOT EXISTS(SELECT 1 FROM scenario_run_sensitivity_observations o WHERE o.run_id=run.id AND o.version_id=NEW.version_id AND o.observation_id=candidate)) OR cardinality(NEW.candidate_observation_ids)<>(SELECT count(DISTINCT id) FROM unnest(NEW.candidate_observation_ids) id) THEN RAISE EXCEPTION 'Scenario applied candidate membership mismatch' USING ERRCODE='23514'; END IF;
  IF NEW.observation_id IS NOT NULL AND (NOT NEW.observation_id=ANY(NEW.candidate_observation_ids) OR NOT EXISTS(SELECT 1 FROM scenario_sensitivity_observations o JOIN scenario_sensitivity_observation_payloads p ON p.observation_id=o.id WHERE o.id=NEW.observation_id AND o.version_id=NEW.version_id AND o.owner_id=NEW.owner_id AND o.driver_id=NEW.driver_id AND o.driver_definition_version_id=NEW.driver_definition_version_id AND p.coefficient IS NOT DISTINCT FROM NEW.coefficient)) THEN RAISE EXCEPTION 'Scenario applied coefficient mismatch' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION scenario_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb; run uuid;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 body:=to_jsonb(OLD);
 IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_definitions' THEN
  IF NEW.revision=OLD.revision+1 AND NEW.updated_at>=OLD.updated_at AND (to_jsonb(NEW)-ARRAY['revision','name','archived','updated_at'])=(body-ARRAY['revision','name','archived','updated_at']) THEN RETURN NEW; END IF;
 END IF;
 IF TG_OP='UPDATE' AND TG_TABLE_NAME IN ('scenario_definition_versions','scenario_runs','scenario_results') THEN
  IF NOT OLD.sealed AND NEW.sealed AND (to_jsonb(NEW)-'sealed')=(body-'sealed') THEN RETURN NEW; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('scenario_run_payloads','scenario_results') THEN run:=(body->>'run_id')::uuid;
 ELSIF TG_TABLE_NAME IN ('scenario_components','scenario_applied_sensitivities') THEN SELECT run_id INTO run FROM scenario_results WHERE id=(body->>'result_id')::uuid; END IF;
 IF run IS NOT NULL AND EXISTS(SELECT 1 FROM premium_retention_events WHERE run_id=run AND owner_id=OLD.owner_id AND account_id=OLD.account_id) THEN
  IF TG_OP='DELETE' AND TG_TABLE_NAME<>'scenario_results' THEN RETURN OLD; END IF;
  IF TG_OP='UPDATE' AND TG_TABLE_NAME='scenario_results' THEN
   IF NEW.canonical_result='\x'::bytea AND (to_jsonb(NEW)-'canonical_result')=(body-'canonical_result') THEN RETURN NEW; END IF;
  END IF;
 END IF;
 RAISE EXCEPTION 'Published scenario content is immutable' USING ERRCODE='23514';
END $$;

CREATE FUNCTION scenario_definition_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE aggregate scenario_definitions; version scenario_definition_versions; identity uuid;
BEGIN
 IF TG_TABLE_NAME='scenario_definitions' THEN identity:=NEW.id; ELSE identity:=NEW.definition_id; END IF;
 SELECT * INTO aggregate FROM scenario_definitions WHERE id=identity;
 SELECT * INTO version FROM scenario_definition_versions WHERE definition_id=identity ORDER BY version_number DESC LIMIT 1;
 IF version.id IS NULL OR NOT version.sealed OR aggregate.revision IS DISTINCT FROM version.version_number OR aggregate.name IS DISTINCT FROM version.name THEN RAISE EXCEPTION 'Scenario definition publication incomplete' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='scenario_definition_versions' THEN SELECT * INTO version FROM scenario_definition_versions WHERE id=NEW.id; END IF;
 IF NOT version.sealed OR version.shock_count<>(SELECT count(*) FROM scenario_shocks WHERE version_id=version.id) OR version.exclusion_count<>(SELECT count(*) FROM scenario_exclusions WHERE version_id=version.id) THEN RAISE EXCEPTION 'Scenario assumption publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION scenario_capture_complete(p_run uuid) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE current scenario_runs; source_count integer;
BEGIN
 SELECT * INTO current FROM scenario_runs WHERE id=p_run;
 IF current.id IS NULL OR NOT current.sealed OR (SELECT count(*) FROM scenario_run_payloads WHERE run_id=p_run)<>1 THEN RETURN false; END IF;
 IF current.sensitivity_version_count<>(SELECT count(*) FROM scenario_run_sensitivity_versions WHERE run_id=p_run) OR current.sensitivity_observation_count<>(SELECT count(*) FROM scenario_run_sensitivity_observations WHERE run_id=p_run) OR current.sensitivity_membership_count<>(SELECT count(*) FROM scenario_run_sensitivity_memberships WHERE run_id=p_run) OR current.sensitivity_evidence_count<>(SELECT count(*) FROM scenario_run_sensitivity_evidence WHERE run_id=p_run) THEN RETURN false; END IF;
 -- Full retained versions, including unavailable observations and non-winning evidence.
 IF EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v JOIN scenario_sensitivity_observations o ON o.version_id=v.version_id WHERE v.run_id=p_run AND NOT EXISTS(SELECT 1 FROM scenario_run_sensitivity_observations c WHERE c.run_id=p_run AND c.observation_id=o.id)) OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v JOIN scenario_sensitivity_memberships m ON m.version_id=v.version_id WHERE v.run_id=p_run AND NOT EXISTS(SELECT 1 FROM scenario_run_sensitivity_memberships c WHERE c.run_id=p_run AND c.membership_id=m.id)) OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v JOIN scenario_sensitivity_evidence_links l ON l.version_id=v.version_id WHERE v.run_id=p_run AND NOT EXISTS(SELECT 1 FROM scenario_run_sensitivity_evidence c WHERE c.run_id=p_run AND c.evidence_id=l.evidence_id)) THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM scenario_run_sensitivity_evidence e WHERE e.run_id=p_run AND NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links l JOIN scenario_run_sensitivity_versions v ON v.version_id=l.version_id AND v.run_id=p_run WHERE l.evidence_id=e.evidence_id)) THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v WHERE v.run_id=p_run AND NOT EXISTS(SELECT 1 FROM scenario_shocks s WHERE s.version_id=current.definition_version_id AND s.source_version_id=v.version_id)) THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM scenario_shocks s WHERE s.version_id=current.definition_version_id AND s.source_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions v WHERE v.run_id=p_run AND v.version_id=s.source_version_id)) THEN RETURN false; END IF;
 IF EXISTS(
  WITH RECURSIVE history AS (
   SELECT d.id,d.license_version_id,d.registered_evidence_id FROM historical_dependencies d WHERE d.owner_id=current.owner_id AND d.input_id=current.historical_input_id
   UNION SELECT d.id,d.license_version_id,d.registered_evidence_id FROM history h JOIN historical_dependencies d ON d.owner_id=current.owner_id AND d.evidence_id=h.registered_evidence_id
  ), required AS (
   SELECT s.license_version_id FROM scenario_run_sensitivity_versions v JOIN scenario_sensitivity_versions s ON s.id=v.version_id WHERE v.run_id=p_run
   UNION SELECT s.license_version_id FROM scenario_run_sensitivity_observations v JOIN scenario_sensitivity_observations s ON s.id=v.observation_id WHERE v.run_id=p_run
   UNION SELECT s.license_version_id FROM scenario_run_sensitivity_evidence v JOIN scenario_sensitivity_evidence s ON s.id=v.evidence_id WHERE v.run_id=p_run
   UNION SELECT license_version_id FROM xray_input_dependencies WHERE input_id=current.xray_input_id AND owner_id=current.owner_id AND license_version_id IS NOT NULL
   UNION SELECT license_version_id FROM history WHERE license_version_id IS NOT NULL
  ) SELECT 1 FROM required r WHERE NOT EXISTS(SELECT 1 FROM premium_run_licenses l WHERE l.run_id=p_run AND l.license_version_id=r.license_version_id)
 ) THEN RETURN false; END IF;
 RETURN true;
END $$;

CREATE FUNCTION scenario_result_complete_check(p_result uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE current scenario_results; run scenario_runs; state text;
BEGIN
 SELECT * INTO current FROM scenario_results WHERE id=p_result;
 SELECT * INTO run FROM scenario_runs WHERE id=current.run_id;
 SELECT j.state INTO state FROM premium_jobs j WHERE j.run_id=current.run_id AND j.owner_id=current.owner_id AND j.account_id=current.account_id;
 IF current.id IS NULL OR NOT current.sealed OR octet_length(current.canonical_result)=0 OR state IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'Scenario result publication incomplete' USING ERRCODE='23514'; END IF;
 IF current.sensitivity_source_row_count IS DISTINCT FROM run.sensitivity_observation_count+run.sensitivity_membership_count+run.sensitivity_evidence_count OR current.component_count<>(SELECT count(*) FROM scenario_components WHERE result_id=current.id) OR current.applied_use_count<>(SELECT count(*) FROM scenario_applied_sensitivities WHERE result_id=current.id) OR EXISTS(SELECT 1 FROM scenario_components c WHERE c.result_id=current.id AND c.applied_use_count<>(SELECT count(*) FROM scenario_applied_sensitivities a WHERE a.component_id=c.id)) THEN RAISE EXCEPTION 'Scenario normalized result publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN;
END $$;

CREATE FUNCTION scenario_result_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM scenario_result_complete_check(NEW.id);
 RETURN NEW;
END $$;

CREATE FUNCTION scenario_retention_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run uuid; input uuid; root uuid; body jsonb;
BEGIN
 IF TG_OP='INSERT' THEN
  PERFORM id FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id FOR UPDATE;
  IF NEW.completed_at IS NOT NULL AND EXISTS(SELECT 1 FROM premium_runs WHERE id=NEW.run_id AND owner_id=NEW.owner_id AND account_id=NEW.account_id AND kind='scenario') THEN RAISE EXCEPTION 'Scenario retention cannot begin completed' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 body:=to_jsonb(OLD);
 IF TG_TABLE_NAME='premium_retention_events' THEN
  IF NEW.completed_at IS NULL THEN RETURN NEW; END IF;
  run:=OLD.run_id;
 ELSIF TG_TABLE_NAME='premium_runs' THEN
  IF NEW.kind<>'scenario' OR NEW.retained_bytes<>0 OR OLD.retained_bytes=0 THEN RETURN NEW; END IF;
  run:=OLD.id;
 END IF;
 IF run IS NOT NULL AND scenario_run_has_payload(run) THEN RAISE EXCEPTION 'Scenario retained copies remain' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='xray_input_snapshots' THEN input:=OLD.id;
 ELSIF TG_TABLE_NAME='xray_runs' THEN root:=OLD.id;
 ELSIF TG_TABLE_NAME='historical_input_snapshots' THEN input:=OLD.id;
 END IF;
 IF TG_TABLE_NAME IN ('xray_input_snapshots','xray_runs') AND EXISTS(SELECT 1 FROM scenario_runs s WHERE (s.xray_input_id=input OR s.xray_run_id=root) AND scenario_run_has_payload(s.id)) THEN RAISE EXCEPTION 'Scenario X-ray copies require cleanup first' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='historical_input_snapshots' AND EXISTS(SELECT 1 FROM scenario_runs s WHERE s.historical_input_id=input AND scenario_run_has_payload(s.id)) THEN RAISE EXCEPTION 'Scenario historical copies require cleanup first' USING ERRCODE='23514'; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION scenario_storage_bytes(p_run uuid) RETURNS bigint LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN scenario_run_has_payload(p_run) THEN coalesce(sum(bytes),0)::bigint ELSE 0::bigint END FROM (
  SELECT octet_length(canonical_input)::bigint bytes FROM scenario_run_payloads WHERE run_id=p_run
  UNION ALL SELECT octet_length(canonical_result) FROM scenario_results WHERE run_id=p_run
  UNION ALL SELECT octet_length(c.canonical_component)+pg_column_size(ROW(c.id,c.owner_id,c.account_id,c.result_id,c.path_key,c.root_key,c.root_kind,c.position_id,c.snapshot_cash_id,c.root_instrument_id,c.partition,c.money_basis,c.currency,c.pre_value,c.post_value,c.impact,c.rounding_residual,c.quality,c.reason,c.applied_use_count,c.created_at)) FROM scenario_components c JOIN scenario_results r ON r.id=c.result_id WHERE r.run_id=p_run
  UNION ALL SELECT pg_column_size(a) FROM scenario_applied_sensitivities a JOIN scenario_results r ON r.id=a.result_id WHERE r.run_id=p_run
  UNION ALL SELECT pg_column_size(v) FROM scenario_run_sensitivity_versions v WHERE run_id=p_run
  UNION ALL SELECT pg_column_size(v) FROM scenario_run_sensitivity_observations v WHERE run_id=p_run
  UNION ALL SELECT pg_column_size(v) FROM scenario_run_sensitivity_memberships v WHERE run_id=p_run
  UNION ALL SELECT pg_column_size(v) FROM scenario_run_sensitivity_evidence v WHERE run_id=p_run
 ) stored
$$;

CREATE FUNCTION scenario_capacity_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE run uuid; bytes bigint; root premium_runs;
BEGIN
 IF TG_TABLE_NAME='premium_runs' THEN run:=NEW.id; ELSE run:=NEW.run_id; END IF;
 SELECT * INTO root FROM premium_runs WHERE id=run;
 IF root.kind<>'scenario' THEN RETURN NEW; END IF;
 bytes:=scenario_storage_bytes(run);
 IF bytes>33554432 OR root.reserved_bytes+root.retained_bytes>33554432 OR bytes>root.reserved_bytes+root.retained_bytes THEN RAISE EXCEPTION 'Scenario retained byte capacity exceeded' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION scenario_evidence_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads WHERE evidence_id=NEW.id) OR NOT EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links WHERE evidence_id=NEW.id) THEN RAISE EXCEPTION 'Sensitivity evidence publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;


CREATE FUNCTION scenario_parent_retention_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='xray_retention_events' THEN
  PERFORM id FROM xray_input_snapshots WHERE id=NEW.input_id AND owner_id=NEW.owner_id FOR UPDATE;
 ELSE
  PERFORM id FROM historical_input_snapshots WHERE id=NEW.input_id AND owner_id=NEW.owner_id FOR UPDATE;
 END IF;
 RETURN NEW;
END $$;


CREATE FUNCTION premium_risk_result_complete_check(p_result uuid, p_run uuid, p_owner uuid, p_account uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE current risk_results; state text;
BEGIN
 SELECT * INTO current FROM risk_results WHERE id=p_result;
 SELECT j.state INTO state FROM premium_jobs j WHERE j.run_id=p_run AND j.owner_id=p_owner AND j.account_id=p_account;
 IF current.id IS NULL OR NOT current.sealed OR octet_length(current.canonical_result)=0 OR state IS DISTINCT FROM 'succeeded' THEN RAISE EXCEPTION 'Premium result publication incomplete' USING ERRCODE='23514'; END IF;
 IF (SELECT count(*) FROM risk_series WHERE result_id=p_result)<>current.series_count OR
    (SELECT count(*) FROM risk_intervals WHERE result_id=p_result)<>current.interval_count OR
    (SELECT count(*) FROM risk_matrix_cells WHERE result_id=p_result)<>current.matrix_cell_count OR
    (SELECT count(*) FROM risk_metrics WHERE result_id=p_result)<>current.metric_count OR
    (SELECT count(*) FROM risk_components WHERE result_id=p_result)<>current.component_count THEN RAISE EXCEPTION 'Premium normalized publication incomplete' USING ERRCODE='23514'; END IF;
 IF EXISTS(SELECT 1 FROM risk_series s WHERE s.result_id=p_result AND s.interval_count<>(SELECT count(*) FROM risk_intervals i WHERE i.series_id=s.id)) THEN RAISE EXCEPTION 'Premium series publication incomplete' USING ERRCODE='23514'; END IF;
 RETURN;
END $$;

CREATE FUNCTION premium_job_success_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE job premium_jobs; family text; result uuid;
BEGIN
 SELECT * INTO job FROM premium_jobs WHERE id=NEW.id;
 IF job.state IS DISTINCT FROM 'succeeded' THEN RETURN NEW; END IF;
 SELECT kind INTO family FROM premium_runs WHERE id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
 IF family='risk' THEN
  SELECT id INTO result FROM risk_results WHERE run_id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
  PERFORM premium_risk_result_complete_check(result,job.run_id,job.owner_id,job.account_id);
 ELSIF family='scenario' THEN
  SELECT id INTO result FROM scenario_results WHERE run_id=job.run_id AND owner_id=job.owner_id AND account_id=job.account_id;
  PERFORM scenario_result_complete_check(result);
 ELSE RAISE EXCEPTION 'Premium handler is not implemented' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""

_TRIGGERS = (
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_sets FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_versions FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_version_payloads FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_observations FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_observation_payloads FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_memberships FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_evidence FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_evidence_payloads FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_evidence_links FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_source_guard BEFORE INSERT OR UPDATE OR DELETE ON scenario_sensitivity_retention FOR EACH ROW EXECUTE FUNCTION scenario_source_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_definitions FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_definitions FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_definition_versions FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_definition_versions FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_shocks FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_shocks FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_exclusions FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_exclusions FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_runs FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_runs FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_run_payloads FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_run_payloads FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_run_sensitivity_versions FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_run_sensitivity_versions FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_run_sensitivity_observations FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_run_sensitivity_observations FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_run_sensitivity_memberships FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_run_sensitivity_memberships FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_run_sensitivity_evidence FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_run_sensitivity_evidence FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_results FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_results FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_components FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_components FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE TRIGGER scenario_scope_guard BEFORE INSERT ON scenario_applied_sensitivities FOR EACH ROW EXECUTE FUNCTION scenario_scope_guard()",
    "CREATE TRIGGER scenario_immutable_guard BEFORE UPDATE OR DELETE ON scenario_applied_sensitivities FOR EACH ROW EXECUTE FUNCTION scenario_immutable_guard()",
    "CREATE CONSTRAINT TRIGGER scenario_source_complete AFTER INSERT ON scenario_sensitivity_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION scenario_source_complete()",
    "CREATE CONSTRAINT TRIGGER scenario_evidence_complete AFTER INSERT ON scenario_sensitivity_evidence DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION scenario_evidence_complete()",
    "CREATE CONSTRAINT TRIGGER scenario_definition_complete AFTER INSERT OR UPDATE ON scenario_definitions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION scenario_definition_complete()",
    "CREATE CONSTRAINT TRIGGER scenario_definition_complete AFTER INSERT ON scenario_definition_versions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION scenario_definition_complete()",
    "CREATE CONSTRAINT TRIGGER scenario_result_complete AFTER INSERT ON scenario_results DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION scenario_result_complete()",
    "CREATE CONSTRAINT TRIGGER scenario_capacity_complete AFTER INSERT ON scenario_results DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION scenario_capacity_complete()",
    "CREATE CONSTRAINT TRIGGER scenario_capacity_complete AFTER INSERT ON scenario_run_payloads DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION scenario_capacity_complete()",
    "CREATE CONSTRAINT TRIGGER scenario_capacity_complete AFTER INSERT OR UPDATE ON premium_runs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION scenario_capacity_complete()",
    "CREATE CONSTRAINT TRIGGER premium_job_success_complete AFTER INSERT OR UPDATE ON premium_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION premium_job_success_complete()",
    "CREATE TRIGGER scenario_retention_copy_guard BEFORE INSERT OR UPDATE OR DELETE ON premium_retention_events FOR EACH ROW EXECUTE FUNCTION scenario_retention_copy_guard()",
    "CREATE TRIGGER scenario_retention_copy_guard BEFORE UPDATE OR DELETE ON premium_runs FOR EACH ROW EXECUTE FUNCTION scenario_retention_copy_guard()",
    "CREATE TRIGGER scenario_retention_copy_guard BEFORE UPDATE OR DELETE ON xray_input_snapshots FOR EACH ROW EXECUTE FUNCTION scenario_retention_copy_guard()",
    "CREATE TRIGGER scenario_retention_copy_guard BEFORE UPDATE OR DELETE ON xray_runs FOR EACH ROW EXECUTE FUNCTION scenario_retention_copy_guard()",
    "CREATE TRIGGER scenario_retention_copy_guard BEFORE UPDATE OR DELETE ON historical_input_snapshots FOR EACH ROW EXECUTE FUNCTION scenario_retention_copy_guard()",
    "CREATE TRIGGER scenario_parent_retention_lock BEFORE INSERT ON xray_retention_events FOR EACH ROW EXECUTE FUNCTION scenario_parent_retention_lock()",
    "CREATE TRIGGER scenario_parent_retention_lock BEFORE INSERT ON historical_retention_events FOR EACH ROW EXECUTE FUNCTION scenario_parent_retention_lock()",
)

_EXTERNAL_TRIGGERS = (
    ("premium_runs", "scenario_capacity_complete"),
    ("premium_jobs", "premium_job_success_complete"),
    ("premium_retention_events", "scenario_retention_copy_guard"),
    ("premium_runs", "scenario_retention_copy_guard"),
    ("xray_input_snapshots", "scenario_retention_copy_guard"),
    ("xray_runs", "scenario_retention_copy_guard"),
    ("historical_input_snapshots", "scenario_retention_copy_guard"),
    ("xray_retention_events", "scenario_parent_retention_lock"),
    ("historical_retention_events", "scenario_parent_retention_lock"),
)

_FUNCTIONS = (
    "premium_job_success_complete()",
    "premium_risk_result_complete_check(uuid, uuid, uuid, uuid)",
    "scenario_parent_retention_lock()",
    "scenario_evidence_complete()",
    "scenario_capacity_complete()",
    "scenario_storage_bytes(uuid)",
    "scenario_retention_copy_guard()",
    "scenario_result_complete()",
    "scenario_result_complete_check(uuid)",
    "scenario_capture_complete(uuid)",
    "scenario_definition_complete()",
    "scenario_immutable_guard()",
    "scenario_scope_guard()",
    "scenario_source_complete()",
    "scenario_source_guard()",
    "scenario_source_copy_pending(uuid)",
    "scenario_run_has_payload(uuid)",
)


_PREVIOUS_COLLECTION_CHECKS = {
    "account_scope_match": "((resource IN "
    "('risk_definitions','risk_versions','risk_runs','intelligence_quality_sources','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','premium_reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') "
    "AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND "
    "broker_account_id IS NULL) OR resource IN "
    "('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
    "resource_allowed": "resource IN "
    "('risk_definitions','risk_versions','risk_runs','intelligence_quality_sources','activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations')",
    "resource_sort_match": "(resource IN "
    "('intelligence_quality_sources','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') "
    "AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND "
    "sort_specification = 'occurred_at_desc_id_desc') OR (resource = "
    "'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource "
    "= 'instruments' AND sort_specification = "
    "'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR "
    "(resource = 'positions_market_value' AND sort_specification = "
    "'market_value_desc_ticker_asc_listing_id_asc') OR (resource = "
    "'positions_weight' AND sort_specification = "
    "'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = "
    "'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') "
    "OR (resource = 'portfolios_name' AND sort_specification = "
    "'name_asc_id_asc') OR (resource = 'portfolios_updated' AND "
    "sort_specification = 'updated_at_desc_id_desc') OR (resource = "
    "'target_versions' AND sort_specification = 'version_number_desc_id_desc') "
    "OR (resource = 'target_events' AND sort_specification = "
    "'created_at_desc_id_desc') OR (resource = 'target_nodes' AND "
    "sort_specification = 'depth_first_order_key') OR (resource = "
    "'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') "
    "OR (resource = 'contribution_plans' AND sort_specification = "
    "'created_at_desc_id_desc') OR (resource IN "
    "('plan_lines','actual_target_rows','plan_revisions') AND "
    "sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' "
    "AND sort_specification = 'source_key_asc_id_asc') OR (resource = "
    "'benchmark_source_status' AND sort_specification = "
    "'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND "
    "sort_specification = 'base_quote_provider_asc') OR (resource = "
    "'price_observations' AND sort_specification = 'ordinal_asc') OR (resource "
    "= 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource "
    "= 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR "
    "(resource = 'benchmark_defs_name' AND sort_specification = "
    "'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND "
    "sort_specification = 'created_at_desc_id_desc') OR (resource = "
    "'benchmark_versions' AND sort_specification = "
    "'version_number_desc_id_desc') OR (resource IN "
    "('reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') "
    "AND sort_specification = 'created_at_desc_id_desc') OR (resource IN "
    "('risk_definitions','risk_runs') AND "
    "sort_specification='created_at_desc_id_desc') OR "
    "(resource='risk_versions' AND "
    "sort_specification='version_number_desc_id_desc')",
}

_COLLECTION_CHECKS = {
    "account_scope_match": "((resource IN "
    "('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','intelligence_quality_sources','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations','reports','premium_reports','exports','activity','dividends','positions_market_value','positions_weight','positions_ticker','contribution_plans','plan_lines','actual_target_rows','plan_revisions','historical_performance','historical_cash_flows','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities') "
    "AND broker_account_id IS NOT NULL) OR (resource = 'instruments' AND "
    "broker_account_id IS NULL) OR resource IN "
    "('portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','composite_benchmark_points','constituent_holdings'))",
    "resource_allowed": "resource IN "
    "('risk_definitions','risk_versions','risk_runs','scenario_definitions','scenario_versions','scenario_runs','intelligence_quality_sources','activity','dividends','instruments','positions_market_value','positions_weight','positions_ticker','portfolios_name','portfolios_updated','target_versions','target_events','target_nodes','contribution_plans','plan_lines','actual_target_rows','plan_revisions','market_source_status','benchmark_source_status','fx_source_status','price_observations','fx_observations','benchmark_observations','benchmark_defs_name','benchmark_defs_created','benchmark_versions','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings','reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations')",
    "resource_sort_match": "(resource IN "
    "('intelligence_quality_sources','historical_performance','historical_cash_flows','composite_benchmark_points','xray_exposures','xray_paths','xray_held_funds','xray_pairs','xray_common_entities','constituent_holdings') "
    "AND sort_specification = 'ordinal_asc') OR (resource = 'activity' AND "
    "sort_specification = 'occurred_at_desc_id_desc') OR (resource = "
    "'dividends' AND sort_specification = 'paid_on_desc_id_desc') OR (resource "
    "= 'instruments' AND sort_specification = "
    "'provider_asc_environment_asc_ticker_asc_name_asc_listing_id_asc') OR "
    "(resource = 'positions_market_value' AND sort_specification = "
    "'market_value_desc_ticker_asc_listing_id_asc') OR (resource = "
    "'positions_weight' AND sort_specification = "
    "'direct_weight_desc_ticker_asc_listing_id_asc') OR (resource = "
    "'positions_ticker' AND sort_specification = 'ticker_asc_listing_id_asc') "
    "OR (resource = 'portfolios_name' AND sort_specification = "
    "'name_asc_id_asc') OR (resource = 'portfolios_updated' AND "
    "sort_specification = 'updated_at_desc_id_desc') OR (resource = "
    "'target_versions' AND sort_specification = 'version_number_desc_id_desc') "
    "OR (resource = 'target_events' AND sort_specification = "
    "'created_at_desc_id_desc') OR (resource = 'target_nodes' AND "
    "sort_specification = 'depth_first_order_key') OR (resource = "
    "'plan_revisions' AND sort_specification = 'revision_number_desc_id_desc') "
    "OR (resource = 'contribution_plans' AND sort_specification = "
    "'created_at_desc_id_desc') OR (resource IN "
    "('plan_lines','actual_target_rows','plan_revisions') AND "
    "sort_specification = 'ordinal_asc') OR (resource = 'market_source_status' "
    "AND sort_specification = 'source_key_asc_id_asc') OR (resource = "
    "'benchmark_source_status' AND sort_specification = "
    "'source_key_asc_id_asc') OR (resource = 'fx_source_status' AND "
    "sort_specification = 'base_quote_provider_asc') OR (resource = "
    "'price_observations' AND sort_specification = 'ordinal_asc') OR (resource "
    "= 'fx_observations' AND sort_specification = 'ordinal_asc') OR (resource "
    "= 'benchmark_observations' AND sort_specification = 'ordinal_asc') OR "
    "(resource = 'benchmark_defs_name' AND sort_specification = "
    "'name_asc_id_asc') OR (resource = 'benchmark_defs_created' AND "
    "sort_specification = 'created_at_desc_id_desc') OR (resource = "
    "'benchmark_versions' AND sort_specification = "
    "'version_number_desc_id_desc') OR (resource IN "
    "('reports','premium_reports','exports','alert_rules','alert_versions','alert_events','alert_evaluations','notification_destinations') "
    "AND sort_specification = 'created_at_desc_id_desc') OR (resource IN "
    "('risk_definitions','risk_runs','scenario_definitions','scenario_runs') "
    "AND sort_specification='created_at_desc_id_desc') OR (resource IN "
    "('risk_versions','scenario_versions') AND "
    "sort_specification='version_number_desc_id_desc')",
}


def _collection_checks(checks: dict[str, str]) -> None:
    for name, sql in checks.items():
        constraint = op.f("ck_collection_query_snapshots_" + name)
        op.drop_constraint(constraint, "collection_query_snapshots", type_="check")
        op.create_check_constraint(constraint, "collection_query_snapshots", sql)


def _command_checks(checks: dict[str, str]) -> None:
    for name, sql in checks.items():
        op.drop_constraint(
            op.f("ck_application_command_identities_" + name),
            "application_command_identities",
            type_="check",
        )
        op.create_check_constraint(
            op.f("ck_application_command_identities_" + name), "application_command_identities", sql
        )


def upgrade() -> None:
    for sql in _DDL:
        op.execute(sa.text(sql))
    _command_checks(_COMMAND_CHECKS)
    _collection_checks(_COLLECTION_CHECKS)
    op.execute(sa.text(_SCENARIO_GUARDS))
    op.execute(sa.text(_SHARED_GUARDS))
    op.execute(sa.text(_LICENSE_GUARD))
    for sql in _TRIGGERS:
        op.execute(sa.text(sql))


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS(SELECT 1 FROM collection_query_snapshots WHERE resource IN ('scenario_definitions','scenario_versions','scenario_runs')) THEN RAISE EXCEPTION 'Scenario collection metadata prevents downgrade' USING ERRCODE='23514'; END IF; END $$"
        )
    )
    # Permanent user assumptions and source identity audit records are not discarded.
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS(SELECT 1 FROM scenario_sensitivity_sets) OR EXISTS(SELECT 1 FROM scenario_definitions) OR EXISTS(SELECT 1 FROM scenario_sensitivity_evidence) OR EXISTS(SELECT 1 FROM scenario_sensitivity_versions) OR EXISTS(SELECT 1 FROM scenario_definition_versions) OR EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_payloads) OR EXISTS(SELECT 1 FROM scenario_sensitivity_observations) OR EXISTS(SELECT 1 FROM scenario_sensitivity_retention) OR EXISTS(SELECT 1 FROM scenario_sensitivity_version_payloads) OR EXISTS(SELECT 1 FROM scenario_exclusions) OR EXISTS(SELECT 1 FROM scenario_sensitivity_evidence_links) OR EXISTS(SELECT 1 FROM scenario_sensitivity_memberships) OR EXISTS(SELECT 1 FROM scenario_sensitivity_observation_payloads) OR EXISTS(SELECT 1 FROM scenario_shocks) OR EXISTS(SELECT 1 FROM scenario_runs) OR EXISTS(SELECT 1 FROM scenario_results) OR EXISTS(SELECT 1 FROM scenario_run_payloads) OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_evidence) OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_versions) OR EXISTS(SELECT 1 FROM scenario_components) OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_observations) OR EXISTS(SELECT 1 FROM scenario_applied_sensitivities) OR EXISTS(SELECT 1 FROM scenario_run_sensitivity_memberships) THEN RAISE EXCEPTION 'Scenario metadata prevents downgrade' USING ERRCODE='23514'; END IF; END $$"
        )
    )
    for table, trigger in _EXTERNAL_TRIGGERS:
        op.execute(sa.text("DROP TRIGGER " + trigger + " ON " + table))
    op.execute(sa.text(_PREVIOUS_SHARED_GUARDS))
    op.execute(sa.text(_PREVIOUS_LICENSE_GUARD))
    _command_checks(_PREVIOUS_COMMAND_CHECKS)
    _collection_checks(_PREVIOUS_COLLECTION_CHECKS)
    for table in reversed(_TABLES):
        op.drop_table(table)
    for function in _FUNCTIONS:
        op.execute(sa.text("DROP FUNCTION " + function))
