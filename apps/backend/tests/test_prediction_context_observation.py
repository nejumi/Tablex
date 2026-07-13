from tabular_harness.api.routes import registered_prediction_input_profile
from tabular_harness.services.prediction_operations import prediction_input_contract_observation


def test_prediction_input_contract_observation_reports_partial_relational_input() -> None:
    observation = prediction_input_contract_observation(
        pipeline_metadata={
            "pipeline_manifest": {
                "input_contract": {
                    "required_tables": [
                        {"name": "application", "role": "primary"},
                        {"name": "POS_CASH_balance", "role": "supporting"},
                        {"name": "optional_lookup", "role": "supporting", "optional": True},
                    ]
                }
            }
        },
        execution_payload={
            "input_artifact_ids_by_table": {
                "application": "artifact_primary",
                "pos_cash_balance": "artifact_history",
            }
        },
    )

    assert observation["provided_tables"] == ["application", "pos_cash_balance"]
    assert observation["missing_required_tables"] == []
    assert observation["has_partial_relational_input"] is False


def test_prediction_input_contract_observation_never_hides_missing_tables() -> None:
    observation = prediction_input_contract_observation(
        pipeline_metadata={
            "pipeline_manifest": {
                "input_contract": {
                    "required_tables": [
                        {"name": "application", "role": "primary"},
                        {"name": "bureau", "role": "supporting"},
                    ]
                }
            }
        },
        execution_payload={"input_artifact_ids_by_table": {"application": "artifact_primary"}},
    )

    assert observation["missing_required_tables"] == ["bureau"]
    assert observation["has_partial_relational_input"] is True
    assert observation["interpretation_owner"] == "main_codex_session"


def test_registered_prediction_input_profile_reuses_persisted_facts() -> None:
    profile = registered_prediction_input_profile(
        {
            "row_count": 12,
            "validation_report": {
                "row_count": 10,
                "key_checks": [{"columns": ["id"], "null_row_count": 0}],
                "dtype_checks": [{"name": "id", "observed_dtype": "int_like"}],
            },
        }
    )

    assert profile["row_count"] == 10
    assert profile["key_checks"][0]["columns"] == ["id"]
    assert profile["dtype_checks"][0]["observed_dtype"] == "int_like"
