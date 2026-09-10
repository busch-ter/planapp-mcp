import base64
from dataclasses import dataclass

import requests


@dataclass
class APIResult:
    """
    Resultado de uma chamada à API do PlanApp.

    kind:
        "json"
        "image"
        "text"
        "bytes"
        "http_error"
        "request_error"
        "error"

    data:
        Conteúdo retornado pelo backend.
    """

    kind: str
    data: object
    response: requests.Response | None = None

    def __repr__(self):
        return f"APIResult(kind={self.kind!r})"


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
        timeout=None,
    ):
        """
        Executa uma chamada autenticada ao backend.

        O retorno pode ser JSON, imagem, texto ou bytes.
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
        timeout = timeout or self.timeout

        try:

            if method == "post":

                response = requests.post(
                    url,
                    params=params,
                    headers=headers,
                    json=body,
                    timeout=timeout,
                )

            elif method == "get":

                response = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )

            else:
                raise ValueError(
                    f"Método HTTP não suportado: {method}"
                )

            response.raise_for_status()

            return self._parse_response(response)

        except requests.HTTPError as e:

            response = getattr(e, "response", None)

            return APIResult(
                kind="http_error",
                data=str(e),
                response=response,
            )

        except requests.RequestException as e:

            return APIResult(
                kind="request_error",
                data=str(e),
                response=None,
            )

        except Exception as e:

            return APIResult(
                kind="error",
                data=str(e),
                response=None,
            )

    # ========================================================
    # Parsing da resposta
    # ========================================================

    def _parse_response(self, response):
        """
        Interpreta a resposta HTTP do backend.

        Suporta:

        - application/json
        - image/*
        - text/*
        - bytes
        """

        content_type = (
            response.headers.get("content-type") or ""
        ).lower()

        # ----------------------------------------------------
        # JSON
        # ----------------------------------------------------

        if "application/json" in content_type:

            try:
                data = response.json()
            except ValueError:
                return APIResult(
                    kind="bytes",
                    data=response.content,
                    response=response,
                )

            return self._parse_json_payload(
                data,
                response,
            )

        # ----------------------------------------------------
        # Imagem HTTP direta
        # ----------------------------------------------------

        if content_type.startswith("image/"):

            return APIResult(
                kind="image",
                data=response.content,
                response=response,
            )

        # ----------------------------------------------------
        # Texto
        # ----------------------------------------------------

        if "text/" in content_type:

            return APIResult(
                kind="text",
                data=response.text,
                response=response,
            )

        # ----------------------------------------------------
        # Qualquer outro conteúdo
        # ----------------------------------------------------

        return APIResult(
            kind="bytes",
            data=response.content,
            response=response,
        )

    # ========================================================
    # Parsing de payload JSON
    # ========================================================

    def _parse_json_payload(
        self,
        data,
        response,
    ):
        """
        Interpreta respostas JSON no formato utilizado pelo
        backend do PlanApp.

        Exemplo:

            {
                "status": "ok",
                "kind": "image",
                "data": "<base64>"
            }
        """

        # JSON simples que não seja dict
        if not isinstance(data, dict):

            return APIResult(
                kind="json",
                data=data,
                response=response,
            )

        status = str(
            data.get("status", "")
        ).lower()

        kind = data.get("kind")
        payload = data.get("data")

        # ----------------------------------------------------
        # Imagem codificada em Base64
        # ----------------------------------------------------

        if kind == "image" and status == "ok":

            try:

                image_bytes = base64.b64decode(
                    payload
                )

                return APIResult(
                    kind="image",
                    data=image_bytes,
                    response=response,
                )

            except Exception as e:

                return APIResult(
                    kind="error",
                    data=f"Erro ao decodificar imagem Base64: {e}",
                    response=response,
                )

        # ----------------------------------------------------
        # Texto
        # ----------------------------------------------------

        if kind == "text":

            return APIResult(
                kind="text",
                data={
                    "status": status,
                    "data": payload,
                },
                response=response,
            )

        # ----------------------------------------------------
        # JSON normal
        # ----------------------------------------------------

        return APIResult(
            kind="json",
            data=data,
            response=response,
        )

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

    # ========================================================
    # PlanApp - link_area
    # ========================================================

    def link_area(self, ds_string):
        """
        Retorna a representação visual da área do enlace.

        ds_string:
            COVER
            DTM
            DSM
        """

        return self._request(
            "link_area",
            params={
                "ds_string": ds_string,
            },
            method="get",
        )

    # ========================================================
    # PlanApp - link_profile
    # ========================================================

    def link_profile(
        self,
        v_h=0,
        **kwargs,
    ):
        """
        Retorna a representação visual do perfil do enlace.

        v_h:
            Offset horizontal do plano Fresnel.

        kwargs:
            Opções adicionais, como figsize e dpi.
        """

        return self._request(
            "link_profile",
            params={
                "v_h": v_h,
            },
            body={
                "options": kwargs,
            },
            method="post",
        )

    # ========================================================
    # PlanApp - lulc_fresnel
    # ========================================================

    def lulc_fresnel(
        self,
        **kwargs,
    ):
        """
        Retorna a visualização LULC/Fresnel do enlace.
        """

        return self._request(
            "lulc_fresnel",
            body={
                "options": kwargs,
            },
            method="post",
        )

    # ========================================================
    # PlanApp - bldg_prepare
    # ========================================================

    def bldg_prepare(self):
        """
        Prepara as informações de edificações para a análise
        do enlace.
        """

        return self._request(
            "prepare_bldg",
            method="get",
            timeout=120,
        )

    # ========================================================
    # PlanApp - bldg_fresnel
    # ========================================================

    def bldg_fresnel(
        self,
        **kwargs,
    ):
        """
        Retorna a visualização de edificações no plano Fresnel.
        """

        options = dict(kwargs)
        options["base64"] = True

        return self._request(
            "bldg_fresnel",
            body={
                "options": options,
            },
            method="post",
        )

    # ========================================================
    # PlanApp - bldg_profile
    # ========================================================

    def bldg_profile(
        self,
        filtered=False,
        **kwargs,
    ):
        """
        Retorna o perfil do enlace com informações de
        edificações.
        """

        options = dict(kwargs)
        options["base64"] = True

        return self._request(
            "bldg_profile",
            params={
                "filtered": filtered,
            },
            body={
                "options": options,
            },
            method="post",
        )

    # ========================================================
    # Visualizações completas do enlace
    # ========================================================

    def generate_link_visualizations(self):
        """
        Executa as visualizações padrão de um enlace.

        A sequência é determinística e não depende do LLM.

        Retorna um dicionário contendo os resultados visuais
        de cada etapa.
        """

        results = {}

        # ----------------------------------------------------
        # Área do enlace
        # ----------------------------------------------------

        results["dtm"] = self.link_area("DTM")
        results["dsm"] = self.link_area("DSM")
        results["cover"] = self.link_area("COVER")

        # ----------------------------------------------------
        # Perfil do enlace
        # ----------------------------------------------------

        results["link_profile"] = self.link_profile()

        # ----------------------------------------------------
        # LULC / Fresnel
        # ----------------------------------------------------

        results["lulc_fresnel"] = self.lulc_fresnel()

        # ----------------------------------------------------
        # Edificações
        # ----------------------------------------------------

        results["bldg_prepare"] = self.bldg_prepare()
        results["bldg_fresnel"] = self.bldg_fresnel()
        results["bldg_profile"] = self.bldg_profile()

        return results
