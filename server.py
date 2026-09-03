from mcp.server.mcpserver import MCPServer

from client.fastapi_client import FastAPIClient
from tools.session import register_session_tools
from tools.link import register_link_tools
from tools.geocode import register_geocode_tools

# ============================================================
# Configuração
# ============================================================

FASTAPI_URL = "http://features-link-v2:8080"
MCP_HOST = "0.0.0.0"
MCP_PORT = 8010


# ============================================================
# MCP Server
# ============================================================

mcp = MCPServer(
    name="PlanApp",
    version="1.0.0",
)


# ============================================================
# Cliente FastAPI
# ============================================================

client = FastAPIClient(
    base_url=FASTAPI_URL,
    timeout=120,
)


# ============================================================
# Registro das ferramentas
# ============================================================

register_session_tools(
    mcp,
    client,
)

register_link_tools(
    mcp,
    client,
)

register_geocode_tools(
    mcp
)

# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=MCP_HOST,
        port=MCP_PORT,
    )

