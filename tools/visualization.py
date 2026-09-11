import base64

from client.fastapi_client import FastAPIClient


def _serialize_result(result):
    """
    Converte APIResult para um payload JSON seguro para o MCP.
    """

    if result is None:
        return {
            "status": "ERROR",
            "error": "Resultado vazio.",
        }

    kind = getattr(result, "kind", None)
    data = getattr(result, "data", None)

    # --------------------------------------------------------
    # Imagem
    # --------------------------------------------------------

    if kind == "image":

        if isinstance(data, bytes):

            return {
                "status": "OK",
                "kind": "image",
                "encoding": "base64",
                "mime_type": "image/png",
                "data": base64.b64encode(data).decode("ascii"),
            }

        return {
            "status": "ERROR",
            "kind": "image",
            "error": "Dados da imagem não são bytes.",
        }

    # --------------------------------------------------------
    # JSON / dados estruturados
    # --------------------------------------------------------

    if kind == "json":

        return {
            "status": "OK",
            "kind": "json",
            "data": data,
        }

    # --------------------------------------------------------
    # Texto
    # --------------------------------------------------------

    if kind == "text":

        return {
            "status": "OK",
            "kind": "text",
            "data": data,
        }

    # --------------------------------------------------------
    # Bytes genéricos
    # --------------------------------------------------------

    if kind == "bytes":

        if isinstance(data, bytes):

            return {
                "status": "OK",
                "kind": "bytes",
                "encoding": "base64",
                "data": base64.b64encode(data).decode("ascii"),
            }

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    return {
        "status": "OK",
        "kind": str(kind),
        "data": data,
    }


def register_visualization_tools(mcp, client: FastAPIClient):

    # ========================================================
    # Área do enlace
    # ========================================================

    @mcp.tool()
    def link_area(ds_string: str) -> dict:
        """
        Retorna a visualização da área do enlace.

        ds_string:
            DTM
            DSM
            COVER
        """

        result = client.link_area(ds_string)

        return _serialize_result(result)

    # ========================================================
    # Perfil do enlace
    # ========================================================

    @mcp.tool()
    def link_profile(v_h: float = 0) -> dict:
        """
        Retorna o perfil do enlace.
        """

        result = client.link_profile(v_h=v_h)

        return _serialize_result(result)

    # ========================================================
    # LULC / Fresnel
    # ========================================================

    @mcp.tool()
    def lulc_fresnel() -> dict:
        """
        Retorna a visualização LULC/Fresnel.
        """

        result = client.lulc_fresnel()

        return _serialize_result(result)

    # ========================================================
    # Preparação das edificações
    # ========================================================

    @mcp.tool()
    def bldg_prepare() -> dict:
        """
        Prepara os dados de edificações para as visualizações.
        """

        result = client.bldg_prepare()

        return _serialize_result(result)

    # ========================================================
    # Edificações / Fresnel
    # ========================================================

    @mcp.tool()
    def bldg_fresnel() -> dict:
        """
        Retorna a visualização de edificações no plano Fresnel.
        """

        result = client.bldg_fresnel()

        return _serialize_result(result)

    # ========================================================
    # Edificações / Perfil
    # ========================================================

    @mcp.tool()
    def bldg_profile(
        filtered: bool = False,
    ) -> dict:
        """
        Retorna o perfil do enlace com informações de edificações.
        """

        result = client.bldg_profile(
            filtered=filtered
        )

        return _serialize_result(result)