from client.fastapi_client import FastAPIClient


def register_visualization_tools(mcp, client: FastAPIClient):

    # ========================================================
    # Área do enlace
    # ========================================================

    @mcp.tool()
    def link_area(ds_string: str) -> object:
        """
        Retorna a visualização da área do enlace.

        ds_string:
            DTM
            DSM
            COVER
        """

        return client.link_area(ds_string)

    # ========================================================
    # Perfil do enlace
    # ========================================================

    @mcp.tool()
    def link_profile(
        v_h: float = 0,
    ) -> object:
        """
        Retorna o perfil do enlace.
        """

        return client.link_profile(v_h=v_h)

    # ========================================================
    # LULC / Fresnel
    # ========================================================

    @mcp.tool()
    def lulc_fresnel() -> object:
        """
        Retorna a visualização LULC/Fresnel.
        """

        return client.lulc_fresnel()

    # ========================================================
    # Preparação das edificações
    # ========================================================

    @mcp.tool()
    def bldg_prepare() -> object:
        """
        Prepara os dados de edificações para as visualizações.
        """

        return client.bldg_prepare()

    # ========================================================
    # Edificações / Fresnel
    # ========================================================

    @mcp.tool()
    def bldg_fresnel() -> object:
        """
        Retorna a visualização de edificações no plano Fresnel.
        """

        return client.bldg_fresnel()

    # ========================================================
    # Edificações / Perfil
    # ========================================================

    @mcp.tool()
    def bldg_profile(
        filtered: bool = False,
    ) -> object:
        """
        Retorna o perfil do enlace com informações de edificações.
        """

        return client.bldg_profile(filtered=filtered)