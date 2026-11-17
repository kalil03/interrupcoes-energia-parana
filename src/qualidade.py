from datetime import datetime, timezone
import hashlib
import json
import platform

import holidays
import pandas as pd
import pyarrow.parquet as pq

from .config import BRUTOS, CNPJ, DATA_FINAL, PONTOS, PROCESSADOS


def significado_coluna(c):
    if c == "data":
        return ("data civil local", "data")
    if c == "n_registros_interrupcao":
        return (
            "Registros ANEEL após duplicatas exatas; não são necessariamente defeitos físicos independentes",
            "registros",
        )
    if c == "n_ids_interrupcao":
        return (
            "Identificadores distintos ano/ordem até 2025 e ano/CodInterrupcao em 2026, por dia de início",
            "identificadores",
        )
    if c == "n_nao_programadas":
        return ("Registros classificados como Não Programada na fonte", "registros")
    if c == "n_duracoes_validas":
        return ("Registros com duração não nula e não negativa", "registros")
    if c == "duracao_media_h":
        return ("Média das durações válidas de eventos iniciados no dia", "h")
    if c == "uc_eventos_soma":
        return (
            "Soma de UCs afetadas por registro, com possíveis repetições de UC",
            "UC-eventos",
        )
    if c == "uc_horas_soma":
        return (
            "Soma de UC-eventos multiplicados pela duração; atribuída ao início; não é DEC oficial",
            "UC-eventos h",
        )
    if c == "n_registros_ocorrencia":
        return (
            "Registros de atendimento/ocorrência emergencial; não equivalem à contagem de interrupções",
            "registros",
        )
    if c == "n_numeros_ocorrencia":
        return (
            "Números de ocorrência distintos por dia de abertura",
            "identificadores",
        )
    if c == "ons_sul_horas_validas":
        return (
            "Número de valores horários válidos de carga do subsistema Sul",
            "horas",
        )
    if c == "ons_dia_completo":
        return (
            "24 valores horários válidos no dia; ausente quando não há data na fonte",
            "booleano",
        )
    if c.startswith("ons_sul_carga_"):
        return (
            "Carga do subsistema Sul, agregada de CSV horário; não corresponde à demanda exclusiva do PR",
            "MWmed",
        )
    if c == "clima_pontos_completos":
        return (
            "Menor contagem de pontos válidos entre as variáveis meteorológicas",
            "pontos de 5",
        )
    if c.startswith("clima_"):
        unit = (
            "°C"
            if "temperature" in c
            else "km/h" if "wind" in c or "rajada" in c else "mm/dia"
        )
        return (
            (
                "Média simples dos cinco pontos ERA5"
                if c.startswith("clima_media")
                else "Máximo espacial entre os cinco pontos ERA5"
            ),
            unit,
        )
    if c == "feriado_nome":
        return (
            "Nome retornado por holidays BR/PR; nulo significa sem feriado no calendário",
            "texto",
        )
    if c == "feriado_br_pr":
        return (
            "Data presente no calendário holidays BR/PR; não inclui regra própria para pontos facultativos",
            "booleano",
        )
    if c == "dia_semana":
        return ("Segunda=0 a domingo=6", "código")
    if c == "fim_semana":
        return ("Sábado ou domingo", "booleano")
    if c.startswith("sem_registro_"):
        return (
            "Não há registro da fonte neste dia; não se presume contagem zero",
            "booleano",
        )
    if c == "aneel_esquema_2026":
        return (
            "Regime do esquema ANEEL 2026; indica mudança de campos/identificadores",
            "booleano",
        )
    if c == "ons_pos_mmgd_20230429":
        return (
            "Marca de sensibilidade documental; não é correção numérica da carga",
            "booleano",
        )
    raise ValueError(c)


def dicionario_colunas(base):
    return pd.DataFrame.from_dict(
        {
            coluna: {
                "descricao": significado_coluna(coluna)[0],
                "tipo": str(base[coluna].dtype),
                "unidade": significado_coluna(coluna)[1],
                "nulos": int(base[coluna].isna().sum()),
            }
            for coluna in base
        },
        orient="index",
    )


def registrar_manifesto(brutos=BRUTOS, processados=PROCESSADOS):
    arquivos = []
    for caminho in sorted(brutos.iterdir()):
        if not caminho.is_file() or caminho.suffix == ".part":
            continue
        digest = hashlib.sha256()
        with caminho.open("rb") as arquivo:
            for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
                digest.update(bloco)
        arquivos.append(
            {
                "arquivo": caminho.name,
                "bytes": caminho.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        )
    manifesto = {
        "processado_em_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "holidays": holidays.__version__,
        "arquivos": arquivos,
    }
    processados.mkdir(parents=True, exist_ok=True)
    (processados / "manifesto.json").write_text(json.dumps(manifesto, indent=2))
    return manifesto


def resumo_fontes(brutos=BRUTOS):
    linhas = []
    for fonte in ["interrupcoes", "ocorrencias", "ons"]:
        catalogo = json.loads((brutos / f"{fonte}_catalogo.json").read_text())["result"]
        linhas.append(
            {
                "fonte": fonte,
                "conjunto": catalogo["title"],
                "recursos_no_catalogo": len(catalogo["resources"]),
            }
        )
    return pd.DataFrame(linhas)


def comparar_esquemas(brutos=BRUTOS):
    linhas = []
    for fonte in ["interrupcoes", "ocorrencias"]:
        esquemas = {}
        for ano in [2025, 2026]:
            caminho = next(brutos.glob(f"{fonte}_*{ano}.parquet"))
            esquemas[ano] = {
                campo.name: str(campo.type)
                for campo in pq.ParquetFile(caminho).schema_arrow
            }
        for campo in sorted(esquemas[2025].keys() | esquemas[2026].keys()):
            antigo = esquemas[2025].get(campo)
            novo = esquemas[2026].get(campo)
            if antigo != novo:
                linhas.append(
                    {
                        "base": fonte,
                        "campo": campo,
                        "tipo_2025": antigo,
                        "tipo_2026": novo,
                    }
                )
    return pd.DataFrame(linhas)


def auditoria_aneel(qualidade):
    campos = [
        "linhas_copel_originais",
        "duplicados_exatos",
        "linhas_sem_duplicados",
        "linhas_chave_repetida",
    ]
    return pd.DataFrame(
        {
            fonte: {campo: qualidade[fonte][campo] for campo in campos}
            for fonte in ["interrupcoes", "ocorrencias"]
        }
    ).T


def valores_suspeitos(qualidade):
    campos = {
        "linhas_copel_originais",
        "duplicados_exatos",
        "linhas_sem_duplicados",
        "linhas_chave_repetida",
    }
    return pd.DataFrame(
        {
            fonte: {
                campo: valor
                for campo, valor in qualidade[fonte].items()
                if campo not in campos
            }
            for fonte in ["interrupcoes", "ocorrencias"]
        }
    ).T


def amostra_dados(nome, colunas, processados=PROCESSADOS):
    arquivo = pq.ParquetFile(processados / f"{nome}.parquet")
    return next(arquivo.iter_batches(batch_size=5, columns=colunas)).to_pandas()


def conferir_agregacoes(base, processados=PROCESSADOS):
    dia = base.loc[
        base.data.dt.year.eq(2026)
        & base.ons_dia_completo.eq(True)
        & base.clima_pontos_completos.eq(len(PONTOS)),
        "data",
    ].iloc[0]
    horario = pd.read_parquet(processados / "ons_sul_horario.parquet")
    carga = horario.loc[horario.data.eq(dia), "carga_mwmed"]
    clima = pd.read_parquet(processados / "clima_pontos.parquet")
    pontos = clima.loc[clima.data.eq(dia)]
    linha = base.loc[base.data.eq(dia)].iloc[0]
    tabela = pd.DataFrame(
        [
            ["Carga média Sul (MWmed)", carga.mean(), linha.ons_sul_carga_media_mwmed],
            [
                "Máximo horário Sul (MWmed)",
                carga.max(),
                linha.ons_sul_carga_max_horaria_mwmed,
            ],
            [
                "Temperatura média dos pontos (°C)",
                pontos.temperature_2m_mean.mean(),
                linha.clima_media_temperature_2m_mean,
            ],
        ],
        columns=["medida", "calculado_dos_dados", "base_integrada"],
    )
    assert len(carga) == 24 and len(pontos) == len(PONTOS)
    assert (tabela.calculado_dos_dados - tabela.base_integrada).abs().lt(1e-8).all()
    return tabela


def cobertura_fontes(base):
    medidas = {
        "Interrupções Copel": "n_ids_interrupcao",
        "Ocorrências Copel": "n_registros_ocorrencia",
        "Carga ONS Sul": "ons_sul_carga_media_mwmed",
        "Clima dos cinco pontos": "clima_media_temperature_2m_mean",
    }
    linhas = []
    for fonte, coluna in medidas.items():
        datas = base.loc[base[coluna].notna(), "data"]
        linhas.append(
            {
                "fonte": fonte,
                "primeiro_dia": datas.min().date(),
                "ultimo_dia": datas.max().date(),
                "dias_com_dado": len(datas),
                "dias_ausentes": int(base[coluna].isna().sum()),
            }
        )
    return pd.DataFrame(linhas)


def cobertura_mensal(base):
    mensal = (
        base.assign(mes=base.data.dt.strftime("%Y-%m"))
        .groupby("mes")
        .agg(
            dias_calendario=("data", "size"),
            dias_com_interrupcoes=("n_registros_interrupcao", "count"),
            dias_com_ocorrencias=("n_registros_ocorrencia", "count"),
            dias_com_ons=("ons_sul_carga_media_mwmed", "count"),
            dias_com_clima=("clima_media_temperature_2m_mean", "count"),
        )
    )
    mensal["ano_esquema_2026"] = mensal.index.str.startswith("2026")
    return mensal


def verificar_base(base, brutos=BRUTOS, processados=PROCESSADOS):
    datas = pd.date_range("2022-01-01", DATA_FINAL)
    assert len(base) == len(datas) and base.data.is_unique
    assert base.data.tolist() == list(datas)
    assert (
        base.loc[base.sem_registro_interrupcao, "n_registros_interrupcao"].isna().all()
    )
    assert base.loc[base.sem_registro_ocorrencia, "n_registros_ocorrencia"].isna().all()
    assert (
        base.loc[
            ~base.ons_dia_completo.astype("boolean").fillna(False),
            "ons_sul_carga_media_mwmed",
        ]
        .isna()
        .all()
    )
    interrupcoes = pd.read_parquet(
        processados / "interrupcoes_copel.parquet",
        columns=[
            "data",
            "NumCPFCNPJ",
            "duracao_h",
            "duracao_h_valida",
            "id_interrupcao",
        ],
    )
    assert interrupcoes.NumCPFCNPJ.eq(CNPJ).all()
    assert (
        interrupcoes.loc[interrupcoes.duracao_h.lt(0), "duracao_h_valida"].isna().all()
    )
    contagem = interrupcoes.groupby("data").size().rename("real").reset_index()
    conferencia = base.merge(contagem, on="data", how="left", validate="1:1")
    assert conferencia.n_registros_interrupcao.equals(
        conferencia.real.astype("float64")
    )
    assert (
        base.n_ids_interrupcao.dropna() <= base.n_registros_interrupcao.dropna()
    ).all()
    clima = pd.read_parquet(processados / "clima_pontos.parquet")
    assert not clima.duplicated(["data", "ponto"]).any() and len(clima) == len(
        PONTOS
    ) * len(base)
    assert (
        base.loc[
            base.clima_pontos_completos.ne(len(PONTOS)), "clima_max_precipitacao_mm"
        ]
        .isna()
        .all()
    )
    assert base.feriado_br_pr.dtype == bool
    assert base.loc[base.data.dt.strftime("%m-%d").eq("01-01"), "feriado_br_pr"].all()
    manifesto = json.loads((processados / "manifesto.json").read_text())
    assert all(
        (brutos / item["arquivo"]).stat().st_size == item["bytes"]
        for item in manifesto["arquivos"]
    )
    return "Verificações concluídas: datas, CNPJ, contagens, ausências, clima, feriados e manifesto."


def verificar_entregas(base, previsao, conjuntos, processados=PROCESSADOS):
    conferir_agregacoes(base, processados)
    datas_alvo = previsao.data_origem + pd.Timedelta(days=1)
    pd.testing.assert_series_equal(previsao.data_alvo, datas_alvo, check_names=False)
    pd.testing.assert_series_equal(previsao.data_origem, base.data, check_names=False)
    leituras = pd.read_parquet(
        processados / "ons_sul_horario.parquet", columns=["din_instante", "carga_mwmed"]
    )
    por_dia = leituras.groupby(leituras.din_instante.dt.normalize()).carga_mwmed
    maximos = por_dia.max().where(por_dia.count().eq(24))
    pd.testing.assert_series_equal(
        previsao.carga_max_sul_d1_mwmed, datas_alvo.map(maximos), check_names=False
    )

    chave = ["data", "conjunto"]
    eventos = pd.read_parquet(
        processados / "interrupcoes_copel.parquet",
        columns=[
            "data",
            "IdeConjuntoUnidadeConsumidora",
            "DscTipoInterrupcao",
            "id_interrupcao",
        ],
    ).rename(columns={"IdeConjuntoUnidadeConsumidora": "conjunto"})
    eventos = eventos.loc[eventos.conjunto.gt(0)]
    contagens = conjuntos.set_index(chave, verify_integrity=True).sort_index()
    pd.testing.assert_series_equal(
        contagens.registros_total, eventos.groupby(chave).size(), check_names=False
    )
    falhas = eventos.loc[eventos.DscTipoInterrupcao.eq("Não Programada")]
    ids = falhas.groupby(chave).id_interrupcao.nunique()
    pd.testing.assert_series_equal(
        contagens.interrupcoes_nao_programadas,
        ids.reindex(contagens.index, fill_value=0),
        check_names=False,
    )
