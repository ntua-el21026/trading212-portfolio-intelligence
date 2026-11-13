"""Decode immutable native custody source tags in the aggregation proof guard.

Revision ID: 20261113_0034
Revises: 20260915_0030

Revisions 0031--0033 are reserved for unintegrated historical handoffs. This
forward repair follows the actual applied head; future handoff integration must
be authored against the then-current ledger. No source record is rewritten.
"""

from alembic import op

revision = "20261113_0034"
down_revision = "20260915_0030"
branch_labels = None
depends_on = None

# Frozen previous definition permits an empty disposable-schema downgrade only.
_PREVIOUS_GUARD = r"""
CREATE FUNCTION aggregate_native_proof_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE original source_records; body jsonb; proof jsonb; witness jsonb; a jsonb; b jsonb; left_row aggregate_transfer_evidence; right_row aggregate_transfer_evidence; fee aggregate_transfer_evidence;
 expected numeric; denominator numeric; fee_id uuid; leg record; ambiguous bigint;
BEGIN
 body:=convert_from(NEW.payload,'UTF8')::jsonb;
 IF TG_TABLE_NAME='aggregate_transfer_evidence' THEN
  SELECT * INTO original FROM source_records WHERE id=NEW.source_record_id AND broker_account_id=NEW.account_id;
  witness:=body->'transfer'; proof:=original.sanitized_payload->'custodyTransfer';
  IF witness IS NOT NULL AND witness<>'null'::jsonb THEN
   IF original.provider<>'synthetic' OR original.schema_version<>'synthetic-custody-v1:historical_transactions'
    OR original.sanitized_payload->>'type'<>'TRANSFER' OR proof IS NULL
    OR body->>'kind' IS DISTINCT FROM 'transfer'
    OR (body->>'occurred_at')::timestamptz IS DISTINCT FROM (original.sanitized_payload->>'dateTime')::timestamptz
    OR NEW.amount IS DISTINCT FROM (original.sanitized_payload->>'amount')::numeric
    OR NEW.currency IS DISTINCT FROM original.sanitized_payload->>'currency'
    OR (witness->>'counterparty_account_id')::uuid IS DISTINCT FROM (proof->>'counterpartyAccountId')::uuid
    OR witness->>'transfer_reference' IS DISTINCT FROM proof->>'transferReference'
    OR (witness->>'principal')::numeric IS DISTINCT FROM (proof->>'principal')::numeric
    OR witness->>'currency' IS DISTINCT FROM proof->>'currency'
    OR (witness->>'fx_rate')::numeric IS DISTINCT FROM (proof->>'fxRate')::numeric
    OR witness->>'fx_base_currency' IS DISTINCT FROM proof->>'fxBaseCurrency'
    OR witness->>'fx_quote_currency' IS DISTINCT FROM proof->>'fxQuoteCurrency'
    OR witness->>'fee_record_key' IS DISTINCT FROM proof->>'feeRecordKey'
    OR (witness->>'fee_amount')::numeric IS DISTINCT FROM (proof->>'feeAmount')::numeric
    OR witness->>'fee_currency' IS DISTINCT FROM proof->>'feeCurrency' THEN
    RAISE EXCEPTION 'aggregate native transfer witness was substituted' USING ERRCODE='23514'; END IF;
   fee_id:=(witness->>'fee_record_id')::uuid;
   IF fee_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM source_records WHERE id=fee_id AND broker_account_id=NEW.account_id
    AND provider_record_id=proof->>'feeRecordKey') THEN RAISE EXCEPTION 'aggregate fee source differs' USING ERRCODE='23514'; END IF;
  ELSIF original.provider='synthetic' AND original.schema_version='synthetic-custody-v1:historical_transactions' AND proof IS NOT NULL AND proof<>'null'::jsonb THEN
   RAISE EXCEPTION 'aggregate native proof was silently omitted' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO left_row FROM aggregate_transfer_evidence WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id AND source_record_id=NEW.outgoing_record_id AND selected;
 SELECT * INTO right_row FROM aggregate_transfer_evidence WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id AND source_record_id=NEW.incoming_record_id AND selected;
 a:=convert_from(left_row.payload,'UTF8')::jsonb->'transfer'; b:=convert_from(right_row.payload,'UTF8')::jsonb->'transfer';
 IF left_row.id IS NULL OR right_row.id IS NULL OR a IS NULL OR a='null'::jsonb OR b IS NULL OR b='null'::jsonb
  OR (a->>'counterparty_account_id')::uuid IS DISTINCT FROM right_row.account_id OR (b->>'counterparty_account_id')::uuid IS DISTINCT FROM left_row.account_id
  OR a->>'transfer_reference' IS DISTINCT FROM b->>'transfer_reference' OR body->>'transfer_reference' IS DISTINCT FROM a->>'transfer_reference'
  OR ROW(left_row.account_id,right_row.account_id,left_row.amount,right_row.amount,left_row.currency,right_row.currency) IS DISTINCT FROM
   ROW(NEW.outgoing_account_id,NEW.incoming_account_id,NEW.outgoing_principal,NEW.incoming_principal,NEW.outgoing_currency,NEW.incoming_currency)
  OR (body->>'outgoing_record_id')::uuid IS DISTINCT FROM NEW.outgoing_record_id OR (body->>'incoming_record_id')::uuid IS DISTINCT FROM NEW.incoming_record_id
  OR (body->>'outgoing_account_id')::uuid IS DISTINCT FROM NEW.outgoing_account_id OR (body->>'incoming_account_id')::uuid IS DISTINCT FROM NEW.incoming_account_id
  OR (body->>'outgoing_principal')::numeric IS DISTINCT FROM NEW.outgoing_principal OR (body->>'incoming_principal')::numeric IS DISTINCT FROM NEW.incoming_principal
  OR body->>'outgoing_currency' IS DISTINCT FROM NEW.outgoing_currency OR body->>'incoming_currency' IS DISTINCT FROM NEW.incoming_currency
  OR (body->>'fx_rate')::numeric IS DISTINCT FROM NEW.fx_rate THEN
  RAISE EXCEPTION 'aggregate mutual transfer proof differs' USING ERRCODE='23514'; END IF;
 IF NEW.outgoing_currency=NEW.incoming_currency THEN
  IF NEW.outgoing_principal+NEW.incoming_principal<>0 OR NEW.fx_rate IS NOT NULL THEN RAISE EXCEPTION 'aggregate same currency principal differs' USING ERRCODE='23514'; END IF;
 ELSE
  IF a->>'fx_rate' IS DISTINCT FROM b->>'fx_rate' OR a->>'fx_base_currency' IS DISTINCT FROM b->>'fx_base_currency'
   OR a->>'fx_quote_currency' IS DISTINCT FROM b->>'fx_quote_currency' OR (a->>'fx_rate')::numeric IS DISTINCT FROM NEW.fx_rate
   OR body->>'fx_base_currency' IS DISTINCT FROM a->>'fx_base_currency' OR body->>'fx_quote_currency' IS DISTINCT FROM a->>'fx_quote_currency'
   OR NEW.fx_rate IS NULL OR NEW.fx_rate<=0 OR (a->>'fx_base_currency') NOT IN (NEW.outgoing_currency,NEW.incoming_currency)
   OR (a->>'fx_quote_currency') NOT IN (NEW.outgoing_currency,NEW.incoming_currency) OR a->>'fx_base_currency'=a->>'fx_quote_currency' THEN
   RAISE EXCEPTION 'aggregate transfer FX witness differs' USING ERRCODE='23514'; END IF;
  expected:=CASE WHEN a->>'fx_base_currency'=NEW.outgoing_currency THEN aggregate_q18_ratio(-NEW.outgoing_principal*NEW.fx_rate,1) ELSE aggregate_q18_ratio(NEW.incoming_principal*NEW.fx_rate,1) END;
  IF expected<>(CASE WHEN a->>'fx_base_currency'=NEW.outgoing_currency THEN NEW.incoming_principal ELSE -NEW.outgoing_principal END) THEN RAISE EXCEPTION 'aggregate transfer FX principal differs' USING ERRCODE='23514'; END IF;
  FOR leg IN SELECT * FROM (VALUES(left_row.account_id,a,0),(right_row.account_id,b,1)) v(account_id,proof,ordinal) LOOP
   fee_id:=(leg.proof->>'fee_record_id')::uuid;
   SELECT * INTO fee FROM aggregate_transfer_evidence WHERE owner_id=NEW.owner_id AND run_id=NEW.run_id AND source_record_id=fee_id AND selected;
   IF fee.id IS NULL OR fee.account_id<>leg.account_id OR fee.amount IS DISTINCT FROM (leg.proof->>'fee_amount')::numeric
    OR fee.currency IS DISTINCT FROM leg.proof->>'fee_currency' OR convert_from(fee.payload,'UTF8')::jsonb->>'kind'<>'fee'
    OR (body->'fee_record_ids'->>leg.ordinal)::uuid IS DISTINCT FROM fee.source_record_id THEN RAISE EXCEPTION 'aggregate original fee proof differs' USING ERRCODE='23514'; END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
"""

_DECODERS = r"""
CREATE FUNCTION aggregate_native_source_decimal(p_value jsonb) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE raw text;
BEGIN
 IF p_value IS NULL OR p_value='null'::jsonb THEN RETURN NULL; END IF;
 IF jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'aggregate native source decimal encoding invalid' USING ERRCODE='23514'; END IF;
 IF p_value-'$decimal'<>'{}'::jsonb OR jsonb_typeof(p_value->'$decimal') IS DISTINCT FROM 'string' THEN
  RAISE EXCEPTION 'aggregate native source decimal encoding invalid' USING ERRCODE='23514'; END IF;
 raw:=p_value->>'$decimal';
 -- The canonical source encoder uses format(Decimal, 'f'), never aliases.
 IF raw !~ '^-?(0|[1-9][0-9]*)([.][0-9]+)?$' THEN
  RAISE EXCEPTION 'aggregate native source decimal encoding invalid' USING ERRCODE='23514'; END IF;
 RETURN raw::numeric;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
 RAISE EXCEPTION 'aggregate native source decimal encoding invalid' USING ERRCODE='23514';
END $$;
CREATE FUNCTION aggregate_native_source_instant(p_value jsonb) RETURNS timestamptz
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE raw text;
BEGIN
 IF p_value IS NULL OR p_value='null'::jsonb THEN RETURN NULL; END IF;
 IF jsonb_typeof(p_value) IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'aggregate native source instant encoding invalid' USING ERRCODE='23514'; END IF;
 IF p_value-'$datetime'<>'{}'::jsonb OR jsonb_typeof(p_value->'$datetime') IS DISTINCT FROM 'string' THEN
  RAISE EXCEPTION 'aggregate native source instant encoding invalid' USING ERRCODE='23514'; END IF;
 raw:=p_value->>'$datetime';
 -- PostgresIngestionStore._json_value emits aware UTC datetime.isoformat().
 IF raw !~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]{6})?[+]00:00$'
 OR raw ~ '[.]000000[+]00:00$' THEN
  RAISE EXCEPTION 'aggregate native source instant encoding invalid' USING ERRCODE='23514'; END IF;
 RETURN raw::timestamptz;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN
 RAISE EXCEPTION 'aggregate native source instant encoding invalid' USING ERRCODE='23514';
END $$;
"""

# Only decode the five canonical source-side tagged scalars. Every identity,
# mutual-counterparty, principal, FX and fee comparison remains in place.
_REPLACEMENTS = (
    (
        "(original.sanitized_payload->>'dateTime')::timestamptz",
        "aggregate_native_source_instant(original.sanitized_payload->'dateTime')",
    ),
    (
        "(original.sanitized_payload->>'amount')::numeric",
        "aggregate_native_source_decimal(original.sanitized_payload->'amount')",
    ),
    (
        "(proof->>'principal')::numeric",
        "aggregate_native_source_decimal(proof->'principal')",
    ),
    (
        "(proof->>'fxRate')::numeric",
        "aggregate_native_source_decimal(proof->'fxRate')",
    ),
    (
        "(proof->>'feeAmount')::numeric",
        "aggregate_native_source_decimal(proof->'feeAmount')",
    ),
)


def _guard(*, repaired: bool) -> str:
    sql = _PREVIOUS_GUARD.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    if repaired:
        for previous, current in _REPLACEMENTS:
            if sql.count(previous) != 1:
                raise RuntimeError("Frozen aggregate native guard replacement differs")
            sql = sql.replace(previous, current, 1)
    return sql


def upgrade() -> None:
    op.execute(_DECODERS)
    op.execute(_guard(repaired=True))


def downgrade() -> None:
    # Rolling a populated database back to the broken proof decoder would make
    # retained native evidence unusable. Operational rollback remains forward-only.
    op.execute(
        "DO $$ BEGIN IF EXISTS(SELECT 1 FROM aggregate_selections) "
        "OR EXISTS(SELECT 1 FROM aggregate_owner_erasure) THEN "
        "RAISE EXCEPTION 'aggregate source decoding rollback requires empty aggregate identities' "
        "USING ERRCODE='23514'; END IF; END $$"
    )
    op.execute(_guard(repaired=False))
    op.execute("DROP FUNCTION aggregate_native_source_instant(jsonb)")
    op.execute("DROP FUNCTION aggregate_native_source_decimal(jsonb)")
