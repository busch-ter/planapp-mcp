import os

from cisei_planning_sdk import PlanningClient, PlanningProject


print("=== CREATE CLIENT ===")

client = PlanningClient(
    "http://network-service:8080",
    workspace="/workspace/cisei_workspace",
    user_id=os.environ["PLANAPP_USER_ID"],
    timeout=900,
)

print("connected:", client.token is not None)


print("\n=== OPEN PROJECT ===")

project = PlanningProject(
    "/workspace/cisei_workspace/projects/curitiba_lte"
)

session = client.open_project(
    project,
    planner="cell",
)

print("scenario_id:", session.scenario_id)
print("planner:", session.planner)
print("ok:", session.ok)
print("summary:", session.summary)


print("\n=== BUILD CANDIDATE EDGES ===")

candidates = session.build_candidate_edges()

print(
    "candidate_edges:",
    len(candidates.get("candidate_edges", [])),
)


print("\n=== COMPUTE METRICS ===")

metrics = session.compute_metrics(
    geo_base_url="http://planning-service:8080",
    geo_user_prefix="planning-sdk",
    geo_pool_size=1,
    geo_timeout=120.0,
    include_features=False,
)

print(
    "metrics result type:",
    type(metrics).__name__,
)

if isinstance(metrics, dict):
    print(
        "metrics result keys:",
        list(metrics.keys()),
    )


print("\n=== METRICS SUMMARY ===")

if isinstance(metrics, dict):
    counts = metrics.get("counts")
    metric_list = metrics.get("metrics")

    print(
        "counts:",
        type(counts).__name__,
        f"({len(counts)})" if isinstance(counts, dict) else "",
    )

    print(
        "metrics:",
        type(metric_list).__name__,
        f"({len(metric_list)})"
        if isinstance(metric_list, list)
        else "",
    )


print("\n=== SESSION METRICS ===")

print(
    "metrics present:",
    session.metrics is not None,
)


print("\n=== B5 SUCCESS ===")


print("\n=== SOLVE ===")

solution = session.solve()

print(
    "solution result type:",
    type(solution).__name__,
)

if isinstance(solution, dict):
    print(
        "solution result keys:",
        list(solution.keys()),
    )


print("\n=== SESSION SOLUTION ===")

print(
    "solution present:",
    session.solution is not None,
)

if isinstance(session.solution, dict):
    print(
        "session solution keys:",
        list(session.solution.keys()),
    )


print("\n=== B6 SUCCESS ===")

print("\n=== SOLUTION SUMMARY ===")

if isinstance(solution, dict):
    counts = solution.get("counts", {})
    planned_nodes = solution.get("planned_nodes", [])
    planned_edges = solution.get("planned_edges", [])

    print("counts:", counts)

    print(
        "planned_nodes:",
        type(planned_nodes).__name__,
        len(planned_nodes)
        if isinstance(planned_nodes, list)
        else "",
    )

    print(
        "planned_edges:",
        type(planned_edges).__name__,
        len(planned_edges)
        if isinstance(planned_edges, list)
        else "",
    )
    
print("\n=== EVALUATE ===")

evaluation = session.evaluate(
    rank_threshold=10,
    primary_tech="lte",
)

print(
    "evaluation result type:",
    type(evaluation).__name__,
)

if isinstance(evaluation, dict):
    print(
        "evaluation result keys:",
        list(evaluation.keys()),
    )

print("\n=== SESSION EVALUATION ===")

print(
    "evaluation present:",
    session.evaluation is not None,
)

if isinstance(session.evaluation, dict):
    print(
        "session evaluation keys:",
        list(session.evaluation.keys()),
    )

print("\n=== B7 SUCCESS ===")

print("\n=== EXPORT RESULT ===")

result = session.export_result(
    include_features=False,
    rank_threshold=10,
    primary_tech="lte",
)

print(
    "export result type:",
    type(result).__name__,
)

if isinstance(result, dict):
    print(
        "export result keys:",
        list(result.keys()),
    )

print("\n=== SESSION RESULT ===")

print(
    "result present:",
    session.result is not None,
)

if isinstance(session.result, dict):
    print(
        "session result keys:",
        list(session.result.keys()),
    )

print("\n=== B8 SUCCESS ===")
