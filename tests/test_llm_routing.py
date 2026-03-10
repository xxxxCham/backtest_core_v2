from agents.llm_router import build_phase1_topology, build_single_host_topology


def test_phase1_topology_routes_builder_and_control_roles():
    topology = build_phase1_topology(
        primary_host="http://127.0.0.1:11434",
        control_host="http://127.0.0.1:22434",
        primary_gpu_target="GPU-2",
        control_gpu_target="GPU-1",
        trace_only=True,
    )

    proposal_route = topology.resolve_builder_phase_route("proposal")
    analysis_route = topology.resolve_builder_phase_route("analysis")
    critic_route = topology.resolve_role_route("critic")

    assert proposal_route.ollama_host == "http://127.0.0.1:11434"
    assert proposal_route.gpu_target == "GPU-2"
    assert analysis_route.ollama_host == "http://127.0.0.1:22434"
    assert analysis_route.gpu_target == "GPU-1"
    assert critic_route.ollama_host == "http://127.0.0.1:22434"


def test_single_host_topology_collapses_all_routes_on_primary_endpoint():
    topology = build_single_host_topology(
        primary_host="127.0.0.1:11434",
        primary_gpu_target="GPU-2",
        trace_only=True,
    )

    validator_route = topology.resolve_role_route("validator")
    analysis_route = topology.resolve_builder_phase_route("analysis")

    assert validator_route.ollama_host == "http://127.0.0.1:11434"
    assert validator_route.gpu_target == "GPU-2"
    assert analysis_route.ollama_host == "http://127.0.0.1:11434"
    assert topology.to_dict()["profile"] == "single_host"
