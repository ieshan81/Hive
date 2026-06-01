from _alpha_factory_verify_common import seed_backtest, session_with_config

from app.services.autonomous_alpha_factory_service import AutonomousAlphaFactoryService
from app.services.hive_brain_graph_service import HiveBrainGraphService


def main() -> None:
    session, cfg = session_with_config()
    svc = AutonomousAlphaFactoryService(session, cfg)
    seed_backtest(session)
    svc.run_candidate_promotion_cycle(operator="verify")
    svc.run_memory_consolidation_cycle(operator="verify")
    graph = HiveBrainGraphService(session, cfg).build(show_raw=False, graph_mode="research")
    assert graph["status"] == "ok", graph
    assert graph["meta"]["hidden_raw_memories"] >= 0, graph["meta"]
    assert any(n.get("memory_type") in ("validated_alpha_candidate", "alpha_candidate_unproven", "rejected_alpha_candidate") for n in graph["nodes"]), graph["nodes"]
    print("verify_hive_graph_uses_consolidated_memory: PASS")
    print({"visible_nodes": graph["meta"]["visible_nodes"], "hidden_raw": graph["meta"]["hidden_raw_memories"]})


if __name__ == "__main__":
    main()
