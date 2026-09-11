from mcp.server.mcpserver import MCPServer

from client.fastapi_client import FastAPIClient
from tools.session import register_session_tools
from tools.link import register_link_tools
from tools.geocode import register_geocode_tools
from tools.visualization import register_visualization_tools


# ============================================================
# CONFIGURAÇÃO
# ============================================================

FASTAPI_URL = "http://features-link-v2:8080"

MCP_HOST = "0.0.0.0"
MCP_PORT = 8010


# ============================================================
# SERVIDOR MCP
# ============================================================

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

# Sessão / autenticação
register_session_tools(
    mcp,
    client,
)

# Avaliação do enlace
register_link_tools(
    mcp,
    client,
)

# Geocodificação
register_geocode_tools(
    mcp,
    client,
)

# Visualizações do enlace
register_visualization_tools(
    mcp,
    client,
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