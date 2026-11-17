import concurrent.futures
import json
import time

import requests

from .config import ANOS, BRUTOS, DATA_FINAL, PONTOS


def baixar_arquivo(job):
    (url, destino) = job
    if destino.exists():
        return
    parcial = destino.with_suffix(destino.suffix + ".part")
    for tentativa in range(4):
        try:
            with requests.get(url, timeout=(20, 60), stream=True) as resposta:
                resposta.raise_for_status()
                with parcial.open("wb") as arquivo:
                    for bloco in resposta.iter_content(1024 * 1024):
                        arquivo.write(bloco)
            parcial.replace(destino)
            return
        except requests.RequestException:
            if tentativa == 3:
                raise
            time.sleep(2**tentativa)


def baixar_originais(brutos=BRUTOS):
    brutos.mkdir(parents=True, exist_ok=True)
    catalogos = {
        "interrupcoes": (
            "https://dadosabertos.aneel.gov.br",
            "interrupcoes-de-energia-eletrica-nas-redes-de-distribuicao",
        ),
        "ocorrencias": (
            "https://dadosabertos.aneel.gov.br",
            "ocorrencias-emergenciais-nas-redes-de-distribuicao",
        ),
        "ons": ("https://dados.ons.org.br", "curva-carga"),
    }
    jobs = []
    for nome, (host, identificador) in catalogos.items():
        caminho = brutos / f"{nome}_catalogo.json"
        if caminho.exists():
            catalogo = json.loads(caminho.read_text())
        else:
            resposta = requests.get(
                host + "/api/3/action/package_show",
                params={"id": identificador},
                timeout=60,
            )
            resposta.raise_for_status()
            catalogo = resposta.json()
            caminho.write_text(json.dumps(catalogo, ensure_ascii=False, indent=2))
        for recurso in catalogo["result"]["resources"]:
            url = recurso["url"]
            ano_selecionado = any((str(ano) in url for ano in ANOS))
            dados = ano_selecionado and url.endswith(
                ".csv" if nome == "ons" else ".parquet"
            )
            dicionario = url.endswith(".pdf") and (
                nome == "ons"
                or any((ano in recurso["name"] for ano in ["2025", "2026"]))
            )
            if dados or dicionario:
                prefixo = "_novo_" if dicionario and "2026" in recurso["name"] else "_"
                jobs.append((url, brutos / (nome + prefixo + url.split("/")[-1])))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(baixar_arquivo, jobs))
    for nome, (lat, lon) in PONTOS.items():
        caminho = brutos / f"clima_{nome}_2026.json"
        if caminho.exists():
            continue
        parametros = dict(
            latitude=lat,
            longitude=lon,
            start_date="2022-01-01",
            end_date=DATA_FINAL,
            daily="temperature_2m_mean,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max",
            timezone="America/Sao_Paulo",
            models="era5",
            wind_speed_unit="kmh",
        )
        resposta = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params=parametros,
            timeout=120,
        )
        resposta.raise_for_status()
        dados = resposta.json()
        dados["_request_url"] = resposta.url
        parcial = caminho.with_suffix(".json.part")
        parcial.write_text(json.dumps(dados, ensure_ascii=False, indent=2))
        parcial.replace(caminho)
        time.sleep(1)
    print("Originais disponíveis.")
