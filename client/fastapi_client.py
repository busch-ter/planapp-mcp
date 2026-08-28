import requests


class FastAPIClient:
    """
    Cliente HTTP para comunicação com o backend FastAPI do PlanApp.

    O usuário é registrado uma vez através de register().
    O user_id e o token retornados pelo backend são mantidos
    na instância e reutilizados nas chamadas seguintes.
    """

    def __init__(
        self,
        base_url="http://localhost:8080",
        timeout=120,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.user_id = None
        self.token = None

    # ========================================================
    # Registro
    # ========================================================

    def register(self, user_id):
        """
        Registra o usuário no backend do PlanApp.

        Endpoint:
            POST /register?user_id=<user_id>

        O backend retorna:
            user_id
            token

        Esses valores ficam armazenados na instância.
        """

        response = requests.post(
            f"{self.base_url}/register",
            params={
                "user_id": user_id,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        if "user_id" not in data:
            raise RuntimeError(
                f"Resposta de /register sem user_id: {data}"
            )

        if "token" not in data:
            raise RuntimeError(
                f"Resposta de /register sem token: {data}"
            )

        self.user_id = data["user_id"]
        self.token = data["token"]

        return data

    # ========================================================
    # HTTP interno
    # ========================================================

    def _request(
        self,
        route,
        method="get",
        params=None,
        body=None,
    ):
        """
        Executa uma chamada autenticada ao backend.

        Depois do register(), a URL segue o padrão:

            /{user_id}/{route}

        e o token é enviado através de:

            X-Token: <token>
        """

        if not self.user_id or not self.token:
            raise RuntimeError(
                "Usuário não registrado. "
                "Execute register(user_id) primeiro."
            )

        url = (
            f"{self.base_url}/"
            f"{self.user_id}/"
            f"{route.lstrip('/')}"
        )

        headers = {
            "X-Token": self.token,
        }

        method = method.lower()

        if method == "post":

            response = requests.post(
                url,
                params=params,
                headers=headers,
                json=body,
                timeout=self.timeout,
            )

        elif method == "get":

            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )

        else:
            raise ValueError(
                f"Método HTTP não suportado: {method}"
            )

        response.raise_for_status()

        return response.json()

    # ========================================================
    # PlanApp - set_link
    # ========================================================

    def set_link(
        self,
        tx_lat,
        tx_lon,
        rx_lat,
        rx_lon,
        tx_ha=7,
        rx_ha=7,
        freq_mhz=900,
        tx_ha_abs=None,
        rx_ha_abs=None,
        on_rooftop=False,
    ):
        """
        Define o enlace ativo no runtime do PlanApp.
        """

        params = {
            "tx_lat": tx_lat,
            "tx_lon": tx_lon,
            "rx_lat": rx_lat,
            "rx_lon": rx_lon,
            "tx_ha": tx_ha,
            "rx_ha": rx_ha,
            "freq_mhz": freq_mhz,
            "on_rooftop": on_rooftop,
        }

        if tx_ha_abs is not None:
            params["tx_ha_abs"] = tx_ha_abs

        if rx_ha_abs is not None:
            params["rx_ha_abs"] = rx_ha_abs

        return self._request(
            "set_link",
            method="post",
            params=params,
        )

    # ========================================================
    # PlanApp - prepare_profiles
    # ========================================================

    def prepare_profiles(self):
        """
        Prepara os perfis necessários para a análise do enlace.
        """

        return self._request(
            "prepare_profiles",
            method="post",
        )

    # ========================================================
    # PlanApp - link_features
    # ========================================================

    def link_features(self):
        """
        Executa a avaliação do enlace e retorna os
        link_features calculados pelo PlanApp.
        """

        return self._request(
            "link_features",
            method="get",
        )
