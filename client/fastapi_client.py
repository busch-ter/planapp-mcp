import requests


class FastAPIClient:
    """
    Cliente HTTP para o backend FastAPI do PlanApp.

    O register() é executado uma única vez por sessão.
    Depois disso, user_id e token são reutilizados nas
    chamadas ao backend.
    """

    def __init__(self, base_url="http://localhost:8080", timeout=120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.user_id = None
        self.token = None

    # ---------------------------------------------------------
    # Session
    # ---------------------------------------------------------

    def register(self, user_id):
        """
        Registra o usuário no backend e cria/recupera a sessão.

        Retorna o user_id e token fornecidos pelo PlanApp.
        """

        response = requests.post(
            f"{self.base_url}/register",
            params={"user_id": user_id},
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        if "user_id" not in data:
            raise RuntimeError(
                f"Resposta de /register não contém user_id: {data}"
            )

        if "token" not in data:
            raise RuntimeError(
                f"Resposta de /register não contém token: {data}"
            )

        self.user_id = data["user_id"]
        self.token = data["token"]

        return data

    # ---------------------------------------------------------
    # Internal HTTP
    # ---------------------------------------------------------

    def _request(
        self,
        route,
        method="get",
        params=None,
        body=None,
    ):
        """
        Executa uma chamada autenticada ao backend.

        As chamadas, após register(), são feitas como:

            /{user_id}/{route}

        com:

            X-Token: <token>
        """

        if not self.user_id or not self.token:
            raise RuntimeError(
                "Cliente não registrado. Execute register(user_id) primeiro."
            )

        url = f"{self.base_url}/{self.user_id}/{route.lstrip('/')}"

        headers = {
            "X-Token": self.token
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
            raise ValueError(f"Método HTTP não suportado: {method}")

        response.raise_for_status()

        return response.json()

    # ---------------------------------------------------------
    # PlanApp operations
    # ---------------------------------------------------------

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

    def prepare_profiles(self):
        """
        Prepara DTM, DSM, LULC e demais informações necessárias
        para avaliação do enlace.
        """

        return self._request(
            "prepare_profiles",
            method="post",
        )

    def link_features(self):
        """
        Executa a avaliação do enlace e retorna os link_features.
        """

        return self._request(
            "link_features",
            method="get",
        )
