from mcp.server.mcpserver import MCPServer

from client.fastapi_client import FastAPIClient
from tools.session import register_session_tools
from tools.link import register_link_tools
from tools.geocode import register_geocode_tools
from tools.visualization import register_visualization_tools
from tools.planner import register_planner_tools


# ============================================================
# CONFIGURAÇÃO
# ============================================================

FASTAPI_URL = "http://features-link-v2:8080"

MCP_HOST = "0.0.0.0"
MCP_PORT = 8010


# ============================================================
# SERVIDOR MCP
# ============================================================


# FIX_FEATURES_JSON_JOVYAN
# Corrige proprietário e permissões após cada gravação do cache de features.
import os as _features_os
import cisei_planning_sdk.project as _features_project

for _features_cls in vars(_features_project).values():
    if isinstance(_features_cls, type) and callable(getattr(_features_cls, "save_features", None)):
        _features_original = _features_cls.save_features
        if not getattr(_features_original, "_jovyan_permissions_fix", False):
            def _features_save_as_jovyan(self, document, _original=_features_original):
                _path = _original(self, document)
                _features_os.chown(_path, 1000, 100)
                _features_os.chmod(_path, 0o664)
                return _path
            _features_save_as_jovyan._jovyan_permissions_fix = True
            _features_cls.save_features = _features_save_as_jovyan
        break
else:
    raise RuntimeError("Não foi encontrada a classe SDK com save_features().")

mcp = MCPServer(
    name="PlanApp",
    version="1.0.0",
)


# ============================================================
# CLIENTE FASTAPI
# ============================================================

client = FastAPIClient(
    base_url=FASTAPI_URL,
    timeout=120,
)


# ============================================================
# REGISTRO DAS FERRAMENTAS MCP
# ============================================================

# ------------------------------------------------------------
# Sessão / autenticação
# ------------------------------------------------------------
register_session_tools(
    mcp,
    client,
)


# ------------------------------------------------------------
# Avaliação do enlace
# ------------------------------------------------------------
register_link_tools(
    mcp,
    client,
)


# ------------------------------------------------------------
# Geocodificação
# ------------------------------------------------------------
register_geocode_tools(
    mcp,
    client,
)


# ------------------------------------------------------------
# Visualizações do enlace
# ------------------------------------------------------------
register_visualization_tools(
    mcp,
    client,
)


# ------------------------------------------------------------
# Planejamento
#
# Os planner tools utilizam o PlannerClient / Planning SDK
# e não dependem do FastAPIClient acima.
# ------------------------------------------------------------
register_planner_tools(
    mcp,
)


# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=MCP_HOST,
        port=MCP_PORT,
    )