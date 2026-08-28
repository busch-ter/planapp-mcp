from client.fastapi_client import FastAPIClient


def register_session_tools(mcp, client: FastAPIClient):
    """
    Registra no MCP as ferramentas relacionadas à sessão
    do usuário no PlanApp.
    """

    @mcp.tool()
    def register(user_id: str) -> dict:
        """
        Registra um usuário no PlanApp.

        Deve ser executado uma vez no início da sessão.
        O user_id e o token ficam armazenados no FastAPIClient
        utilizado pelo servidor MCP.

        Depois do registro, as demais ferramentas podem utilizar
        automaticamente a sessão autenticada.
        """

        return client.register(user_id)

